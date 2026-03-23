import sys
from unittest.mock import MagicMock, patch

# Mock PyQt6 and pyqtconfig before any rataGUI imports
_qt_modules = ["PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "pyqtconfig"]
for mod_name in _qt_modules:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import multiprocessing
import threading
import time

import numpy as np
import pytest

from rataGUI.cameras.BaseCamera import BaseCamera


# --- Concrete test camera that records calls --------------------------------

class _MockCamera(BaseCamera):
    """Minimal concrete camera for testing the acquisition loop."""

    _init_should_fail = False
    _frames_to_produce = 5
    _frame_shape = (480, 640, 3)

    @staticmethod
    def getAvailableCameras():
        return [_MockCamera("test-cam")]

    def initializeCamera(self, prop_config, plugin_names=[]):
        if self._init_should_fail:
            return False
        self._running = True
        self.frames_acquired = 0
        return True

    def readCamera(self):
        if self.frames_acquired >= self._frames_to_produce:
            self._running = False
            return False, None
        self.frames_acquired += 1
        frame = np.full(self._frame_shape, self.frames_acquired, dtype=np.uint8)
        return True, frame

    def closeCamera(self):
        self._running = False
        return True


class TestCameraAcquisitionLoop:
    """Tests for rataGUI.camera_process.camera_acquisition_loop."""

    def _run_loop(self, camera_module_name="test_camera_process", camera_id="test-cam",
                  config_dict=None, plugin_names=None, num_slots=4,
                  frame_shape=(480, 640, 3), timeout=10):
        """Helper that runs camera_acquisition_loop in a thread and returns results."""
        from multiprocessing.shared_memory import SharedMemory
        from rataGUI.camera_process import camera_acquisition_loop

        if config_dict is None:
            config_dict = {}
        if plugin_names is None:
            plugin_names = []

        H, W, C = frame_shape
        shm_shape = (num_slots, H, W, C)
        shm_nbytes = int(np.prod(shm_shape))

        shm = SharedMemory(create=True, size=shm_nbytes)
        meta_queue = multiprocessing.Queue()
        control_queue = multiprocessing.Queue()
        ready_event = multiprocessing.Event()
        error_queue = multiprocessing.Queue()

        # Run in a thread (not process) for easier testing and mock access
        t = threading.Thread(
            target=camera_acquisition_loop,
            kwargs={
                "camera_module_name": camera_module_name,
                "camera_id": camera_id,
                "camera_config_dict": config_dict,
                "plugin_names": plugin_names,
                "shm_name": shm.name,
                "shm_shape": shm_shape,
                "meta_queue": meta_queue,
                "control_queue": control_queue,
                "ready_event": ready_event,
                "error_queue": error_queue,
            },
            daemon=True,
        )
        t.start()
        t.join(timeout=timeout)

        # Collect results
        results = []
        while not meta_queue.empty():
            results.append(meta_queue.get_nowait())

        errors = []
        while not error_queue.empty():
            errors.append(error_queue.get_nowait())

        frame_ring = np.ndarray(shm_shape, dtype=np.uint8, buffer=shm.buf)

        return {
            "results": results,
            "errors": errors,
            "ready": ready_event.is_set(),
            "shm": shm,
            "frame_ring": frame_ring,
            "control_queue": control_queue,
        }

    def _cleanup(self, data):
        try:
            data["shm"].close()
            data["shm"].unlink()
        except Exception:
            pass

    def test_acquisition_loop_reads_frames(self):
        """Mock camera returns 5 frames, verify they appear in metadata queue."""
        _MockCamera._frames_to_produce = 5
        _MockCamera._init_should_fail = False
        data = self._run_loop()
        try:
            assert data["ready"] is True
            assert len(data["results"]) == 5
            assert len(data["errors"]) == 0

            # Verify slot indices and metadata
            for slot_idx, metadata in data["results"]:
                assert isinstance(slot_idx, int)
                assert "Camera Name" in metadata
                assert "Timestamp" in metadata
                assert "Frame Index" in metadata
        finally:
            self._cleanup(data)

    def test_ready_event_on_success(self):
        """Verify ready_event is set after successful initialization."""
        _MockCamera._frames_to_produce = 1
        _MockCamera._init_should_fail = False
        data = self._run_loop()
        try:
            assert data["ready"] is True
        finally:
            self._cleanup(data)

    def test_ready_event_not_set_on_failure(self):
        """Verify ready_event is NOT set when initialization fails."""
        _MockCamera._init_should_fail = True
        data = self._run_loop()
        try:
            assert data["ready"] is False
            assert len(data["errors"]) > 0
            assert data["errors"][0][0] == "init_error"
        finally:
            _MockCamera._init_should_fail = False
            self._cleanup(data)

    def test_control_stop(self):
        """Send stop signal, verify process exits."""
        _MockCamera._frames_to_produce = 1000000  # would run forever
        _MockCamera._init_should_fail = False

        from multiprocessing.shared_memory import SharedMemory
        from rataGUI.camera_process import camera_acquisition_loop

        H, W, C = 480, 640, 3
        num_slots = 4
        shm_shape = (num_slots, H, W, C)
        shm = SharedMemory(create=True, size=int(np.prod(shm_shape)))
        meta_queue = multiprocessing.Queue()
        control_queue = multiprocessing.Queue()
        ready_event = multiprocessing.Event()
        error_queue = multiprocessing.Queue()

        t = threading.Thread(
            target=camera_acquisition_loop,
            kwargs={
                "camera_module_name": "test_camera_process",
                "camera_id": "test-cam",
                "camera_config_dict": {},
                "plugin_names": [],
                "shm_name": shm.name,
                "shm_shape": shm_shape,
                "meta_queue": meta_queue,
                "control_queue": control_queue,
                "ready_event": ready_event,
                "error_queue": error_queue,
            },
            daemon=True,
        )
        t.start()

        # Wait for ready
        assert ready_event.wait(timeout=5), "Camera did not initialize in time"

        # Let it run briefly then stop
        time.sleep(0.1)
        control_queue.put("stop")
        t.join(timeout=5)
        assert not t.is_alive(), "Thread should have exited after stop signal"

        try:
            shm.close()
            shm.unlink()
        except Exception:
            pass

    def test_frame_data_in_shared_memory(self):
        """Verify actual frame data is written to shared memory."""
        _MockCamera._frames_to_produce = 2
        _MockCamera._init_should_fail = False
        data = self._run_loop()
        try:
            assert len(data["results"]) == 2
            # The mock camera fills frames with frame_number (1, 2, ...)
            # Check that at least one slot has non-zero data
            frame_ring = data["frame_ring"]
            slot_idx_0 = data["results"][0][0]
            assert frame_ring[slot_idx_0].max() > 0
        finally:
            self._cleanup(data)

    def test_metadata_contains_timestamp(self):
        """Verify metadata includes a Timestamp field."""
        from datetime import datetime

        _MockCamera._frames_to_produce = 1
        _MockCamera._init_should_fail = False
        data = self._run_loop()
        try:
            assert len(data["results"]) == 1
            _, metadata = data["results"][0]
            assert isinstance(metadata["Timestamp"], datetime)
        finally:
            self._cleanup(data)


class TestBaseCameraCreateAndInitialize:
    """Tests for BaseCamera.create_and_initialize classmethod."""

    def test_creates_and_initializes(self):
        _MockCamera._init_should_fail = False
        camera = _MockCamera.create_and_initialize("test-cam", {}, [])
        assert camera._running is True
        assert camera.frames_acquired == 0
        assert camera.cameraID == "test-cam"

    def test_raises_on_init_failure(self):
        _MockCamera._init_should_fail = True
        try:
            with pytest.raises(IOError, match="failed to initialize"):
                _MockCamera.create_and_initialize("test-cam", {}, [])
        finally:
            _MockCamera._init_should_fail = False

    def test_config_dict_passed_correctly(self):
        _MockCamera._init_should_fail = False
        config_dict = {"Framerate": 60, "Gain": 10}
        camera = _MockCamera.create_and_initialize("test-cam", config_dict, ["VideoWriter"])
        assert camera._running is True
