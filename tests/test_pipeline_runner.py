"""Tests for PipelineRunner."""

import asyncio
import json
import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from rataGUI.headless.context import HeadlessConfigManager
from rataGUI.headless.runner import PipelineRunner


def _make_camera_cls(num_cameras=1, num_frames=3):
    """Create a mock camera class that produces a fixed number of frames."""

    class MockCamera:
        modules = {}
        DEFAULT_PROPS = {"File path": ""}

        def __init__(self, cam_id):
            self.cameraID = cam_id
            self.display_name = cam_id
            self._running = False
            self.frames_acquired = 0
            self._frame_limit = num_frames

        @staticmethod
        def getAvailableCameras():
            return [MockCamera(f"MockCam-{i+1}") for i in range(num_cameras)]

        def getDisplayName(self):
            return self.display_name or str(self.cameraID)

        def initializeCamera(self, config, plugin_names):
            return True

        def readCamera(self):
            if self.frames_acquired >= self._frame_limit:
                self._running = False
                return False, None
            self.frames_acquired += 1
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            return True, frame

        def closeCamera(self):
            self._running = False
            return True

        def getMetadata(self):
            return {"Frame Index": self.frames_acquired}

        @staticmethod
        def releaseResources():
            pass

    return MockCamera


def _make_plugin_cls(name="MockPlugin", blocking=False, independent=False):
    """Create a mock plugin class that counts processed frames."""
    from rataGUI.plugins.base_plugin import BasePlugin

    class _Plugin(BasePlugin):
        frames_processed = 0

        def __init__(self, cam_widget, config, queue_size=0):
            super().__init__(cam_widget, config, queue_size)
            self.blocking = blocking
            self.independent = independent
            _Plugin.frames_processed = 0

        def process(self, frame, metadata):
            _Plugin.frames_processed += 1
            return frame, metadata

    _Plugin.__name__ = name
    _Plugin.__qualname__ = name
    return _Plugin


class TestPipelineRunnerInit:

    def test_accepts_dict(self):
        config = {"Enabled Camera Modules": [], "Save Directory": "/tmp/test"}
        runner = PipelineRunner(config)
        assert runner._config["Save Directory"] == "/tmp/test"

    def test_accepts_json_path(self, tmp_path):
        config = {"Enabled Camera Modules": ["VideoReader"], "Save Directory": str(tmp_path)}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        runner = PipelineRunner(str(config_path))
        assert runner._config["Enabled Camera Modules"] == ["VideoReader"]

    def test_save_dir_override(self):
        runner = PipelineRunner({"Save Directory": "/old"}, save_dir="/new")
        assert runner._config["Save Directory"] == "/new"


class TestPipelineRunnerExcludesFrameDisplay:

    def test_excluded_plugins_set(self):
        assert "FrameDisplay" in PipelineRunner.EXCLUDED_PLUGINS


class TestPipelineRunnerLifecycle:

    @pytest.mark.asyncio
    async def test_single_camera_pipeline(self, tmp_path):
        """Run a pipeline with one mock camera and one mock plugin."""
        MockCamera = _make_camera_cls(num_cameras=1, num_frames=5)
        MockPlugin = _make_plugin_cls("MockPlugin")

        from rataGUI.cameras.BaseCamera import BaseCamera
        from rataGUI.plugins.base_plugin import BasePlugin

        # Register mock modules
        BaseCamera.modules["MockCamera"] = MockCamera
        BasePlugin.modules["MockPlugin"] = MockPlugin

        try:
            config = {
                "Enabled Camera Modules": ["MockCamera"],
                "Enabled Plugin Modules": ["MockPlugin"],
                "Enabled Trigger Modules": [],
                "Save Directory": str(tmp_path),
            }
            runner = PipelineRunner(config)
            await runner.run()

            assert MockPlugin.frames_processed == 5
        finally:
            BaseCamera.modules.pop("MockCamera", None)
            BasePlugin.modules.pop("MockPlugin", None)

    @pytest.mark.asyncio
    async def test_stop_terminates_pipeline(self, tmp_path):
        """Calling stop() causes the pipeline to exit."""
        MockCamera = _make_camera_cls(num_cameras=1, num_frames=999999)
        MockPlugin = _make_plugin_cls("MockPlugin2")

        from rataGUI.cameras.BaseCamera import BaseCamera
        from rataGUI.plugins.base_plugin import BasePlugin

        BaseCamera.modules["MockCamera2"] = MockCamera
        BasePlugin.modules["MockPlugin2"] = MockPlugin

        try:
            config = {
                "Enabled Camera Modules": ["MockCamera2"],
                "Enabled Plugin Modules": ["MockPlugin2"],
                "Enabled Trigger Modules": [],
                "Save Directory": str(tmp_path),
            }
            runner = PipelineRunner(config)

            async def stop_after_delay():
                await asyncio.sleep(0.3)
                runner.stop()

            await asyncio.gather(runner.run(), stop_after_delay())
            # Pipeline should have stopped — frames_processed may vary but should be > 0
            assert MockPlugin.frames_processed > 0
        finally:
            BaseCamera.modules.pop("MockCamera2", None)
            BasePlugin.modules.pop("MockPlugin2", None)

    @pytest.mark.asyncio
    async def test_no_cameras_exits_cleanly(self, tmp_path):
        """If no cameras are discovered, run() returns without error."""
        from rataGUI.cameras.BaseCamera import BaseCamera

        MockCamera = _make_camera_cls(num_cameras=0)
        BaseCamera.modules["EmptyCam"] = MockCamera

        try:
            config = {
                "Enabled Camera Modules": ["EmptyCam"],
                "Enabled Plugin Modules": [],
                "Enabled Trigger Modules": [],
                "Save Directory": str(tmp_path),
            }
            runner = PipelineRunner(config)
            await runner.run()  # Should not raise
        finally:
            BaseCamera.modules.pop("EmptyCam", None)

    @pytest.mark.asyncio
    async def test_independent_plugins_fan_out(self, tmp_path):
        """Independent plugins receive frames via fan-out."""
        MockCamera = _make_camera_cls(num_cameras=1, num_frames=3)

        PluginA = _make_plugin_cls("PluginA", independent=True)
        PluginB = _make_plugin_cls("PluginB", independent=True)

        from rataGUI.cameras.BaseCamera import BaseCamera
        from rataGUI.plugins.base_plugin import BasePlugin

        BaseCamera.modules["FanOutCam"] = MockCamera
        BasePlugin.modules["PluginA"] = PluginA
        BasePlugin.modules["PluginB"] = PluginB

        try:
            config = {
                "Enabled Camera Modules": ["FanOutCam"],
                "Enabled Plugin Modules": ["PluginA", "PluginB"],
                "Enabled Trigger Modules": [],
                "Save Directory": str(tmp_path),
            }
            runner = PipelineRunner(config)
            await runner.run()

            assert PluginA.frames_processed == 3
            assert PluginB.frames_processed == 3
        finally:
            BaseCamera.modules.pop("FanOutCam", None)
            BasePlugin.modules.pop("PluginA", None)
            BasePlugin.modules.pop("PluginB", None)
