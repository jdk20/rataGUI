"""Subprocess target for multi-process camera acquisition.

Each camera runs in its own process, reading frames into shared memory
and sending lightweight metadata through a multiprocessing.Queue.  This
eliminates GIL contention between cameras in multi-camera setups.

The main process creates the SharedMemory and spawns this function via
``multiprocessing.Process``.  All heavy imports (camera SDKs, numpy) are
deferred to inside the function body so that Windows ``spawn`` start
method works correctly.
"""

import logging
import multiprocessing

logger = logging.getLogger(__name__)


def camera_acquisition_loop(
    camera_module_name,   # e.g. "FLIRCamera" — key in BaseCamera.modules
    camera_id,            # Camera identifier string
    camera_config_dict,   # Plain dict (serializable) of camera settings
    plugin_names,         # List of plugin name strings
    shm_name,             # SharedMemory name for the frame ring buffer
    shm_shape,            # (num_slots, H, W, C)
    meta_queue,           # multiprocessing.Queue for (slot_idx, metadata_dict)
    control_queue,        # multiprocessing.Queue for control signals
    ready_event,          # multiprocessing.Event — set when camera initialized
    error_queue,          # multiprocessing.Queue for error reporting
    log_dir=None,         # Optional: directory path for file logging
):
    """Target function for camera acquisition subprocess.

    1. Sets up logging (console + optional file handler).
    2. Dynamically imports the camera class and creates an instance.
    3. Initialises the camera with the provided config dict.
    4. Loops: readCamera() → write frame into shared memory slot →
       put (slot_idx, metadata) into meta_queue.
    5. Responds to control signals: ``"stop"``, ``"pause"``, ``"resume"``.

    All parameters must be picklable (no Qt objects, no camera handles).
    """
    # -- Deferred imports (Windows spawn compatibility) ----------------------
    import numpy as np
    from multiprocessing.shared_memory import SharedMemory
    from datetime import datetime

    # -- Logging setup -------------------------------------------------------
    proc_logger = logging.getLogger(f"rataGUI.camera_process.{camera_module_name}")
    proc_logger.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    console.setFormatter(
        logging.Formatter("%(levelname)-8s %(module)-16s %(message)s")
    )
    proc_logger.addHandler(console)

    if log_dir is not None:
        import os
        os.makedirs(log_dir, exist_ok=True)
        file_name = f"camera_{camera_module_name}_{datetime.now().strftime('%Y_%m_%d-%H_%M_%S')}.log"
        fh = logging.FileHandler(os.path.join(log_dir, file_name))
        fh.setLevel(logging.INFO)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s.%(msecs)03d  %(levelname)-8s %(module)-16s %(message)s",
                "%Y-%m-%d,%H:%M:%S",
            )
        )
        proc_logger.addHandler(fh)

    proc_logger.info("Camera acquisition process starting for %s (ID: %s)",
                     camera_module_name, camera_id)

    # -- Attach shared memory ------------------------------------------------
    try:
        shm = SharedMemory(name=shm_name, create=False)
        frame_ring = np.ndarray(shm_shape, dtype=np.uint8, buffer=shm.buf)
    except Exception as err:
        proc_logger.exception("Failed to attach shared memory: %s", err)
        error_queue.put(("shm_error", repr(err)))
        return

    num_slots = shm_shape[0]
    write_pos = 0

    # -- Import and instantiate camera ---------------------------------------
    try:
        # Import camera modules to trigger __init_subclass__ registration
        import rataGUI.cameras  # noqa: F401
        from rataGUI.cameras.BaseCamera import BaseCamera

        if camera_module_name not in BaseCamera.modules:
            raise ImportError(
                f"Camera module '{camera_module_name}' not found in BaseCamera.modules. "
                f"Available: {list(BaseCamera.modules.keys())}"
            )

        CameraClass = BaseCamera.modules[camera_module_name]
        camera = CameraClass.create_and_initialize(
            camera_id, camera_config_dict, plugin_names
        )
        ready_event.set()
        proc_logger.info("Camera %s initialized successfully", camera_id)

    except Exception as err:
        proc_logger.exception("Camera initialization failed: %s", err)
        error_queue.put(("init_error", repr(err)))
        shm.close()
        return

    # -- Acquisition loop ----------------------------------------------------
    paused = False
    try:
        while camera._running:
            # Check for control signals (non-blocking)
            try:
                while not control_queue.empty():
                    signal = control_queue.get_nowait()
                    if signal == "stop":
                        proc_logger.info("Received stop signal")
                        camera._running = False
                        break
                    elif signal == "pause":
                        proc_logger.info("Received pause signal")
                        paused = True
                    elif signal == "resume":
                        proc_logger.info("Received resume signal")
                        paused = False
            except Exception:
                pass  # Queue empty or other transient error

            if not camera._running:
                break

            if paused:
                import time
                time.sleep(0.01)
                continue

            # Read frame from camera
            status, frame = camera.readCamera()

            if not status or frame is None:
                proc_logger.warning("Frame read failed on camera %s", camera_id)
                continue

            # Get metadata
            metadata = camera.getMetadata()
            metadata["Camera Name"] = camera.getDisplayName()
            metadata["Timestamp"] = datetime.now()

            # Write frame into shared memory ring slot
            slot_idx = write_pos % num_slots
            try:
                np.copyto(frame_ring[slot_idx], frame)
            except ValueError:
                # Frame shape doesn't match shared memory — report and skip
                proc_logger.error(
                    "Frame shape %s does not match shared memory slot shape %s",
                    frame.shape, frame_ring[slot_idx].shape,
                )
                continue

            # Send metadata + slot index to main process
            meta_queue.put((slot_idx, metadata))
            write_pos += 1

    except Exception as err:
        proc_logger.exception("Acquisition loop error: %s", err)
        error_queue.put(("acquisition_error", repr(err)))
    finally:
        proc_logger.info("Closing camera %s (frames acquired: %d)",
                         camera_id, camera.frames_acquired)
        try:
            camera.closeCamera()
        except Exception as err:
            proc_logger.exception("Error closing camera: %s", err)
        shm.close()
        proc_logger.info("Camera acquisition process exiting")
