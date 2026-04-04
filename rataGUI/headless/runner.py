"""Headless pipeline runner for rataGUI — no Qt dependency."""

from __future__ import annotations

import os
import json
import time
import asyncio
import logging
import multiprocessing
from importlib import import_module
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from multiprocessing.shared_memory import SharedMemory
from typing import Any

import numpy as np

from rataGUI import add_file_logger
from rataGUI.utils import slugify
from rataGUI.headless.context import HeadlessConfigManager, PipelineContext

logger = logging.getLogger(__name__)

# Shared bounded thread pool for camera I/O and blocking plugin execution.
thread_pool = ThreadPoolExecutor(max_workers=8)

# Exponential moving average decay factor for smoothing pipeline latency measurements.
# Higher values weight recent samples more heavily (0.8 = 80% new, 20% old).
EXP_AVG_DECAY = 0.8


class PipelineRunner:
    """Run rataGUI pipelines without Qt.

    Usage::

        runner = PipelineRunner("config.json")
        runner.start()          # blocks until stopped

        # or async:
        await runner.run()

        # or stop from another thread / signal handler:
        runner.stop()

    :param config: A dict matching ``launch_config.json`` schema, or a path
        to a JSON file.
    :param save_dir: Override the ``"Save Directory"`` from config.
    """

    EXCLUDED_PLUGINS = {"FrameDisplay"}

    def __init__(self, config: dict | str, save_dir: str | None = None) -> None:
        if isinstance(config, str):
            with open(config) as f:
                config = json.load(f)
        self._config = dict(config)

        if save_dir is not None:
            self._config["Save Directory"] = save_dir

        self._contexts = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Block until all pipelines complete or :meth:`stop` is called."""
        asyncio.run(self.run())

    def stop(self) -> None:
        """Signal all pipelines to stop.  Thread-safe."""
        for ctx in self._contexts:
            ctx.stop_camera_pipeline()

    async def run(self) -> None:
        """Initialise and run all camera pipelines concurrently."""
        self._load_modules()

        save_dir = self._config.get("Save Directory", "recordings")
        os.makedirs(save_dir, exist_ok=True)
        session_dir = os.path.join(
            save_dir, datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
        )

        log_dir = os.path.join(save_dir, "logs")
        add_file_logger(log_dir)

        from rataGUI.cameras.BaseCamera import BaseCamera
        from rataGUI.plugins.base_plugin import BasePlugin
        from rataGUI.triggers.base_trigger import BaseTrigger

        # Discover cameras
        camera_module_names = self._config.get("Enabled Camera Modules", [])
        cameras = []
        for name in camera_module_names:
            cam_cls = BaseCamera.modules.get(name)
            if cam_cls is None:
                logger.error("Camera module %s not found in registry", name)
                continue
            for cam in cam_cls.getAvailableCameras():
                cameras.append(cam)

        if not cameras:
            logger.error("No cameras discovered — nothing to do")
            return

        # Discover and initialise triggers
        triggers = []
        trigger_module_names = self._config.get("Enabled Trigger Modules", [])
        trigger_configs_dict = self._config.get("triggers", {})
        for name in trigger_module_names:
            trig_cls = BaseTrigger.modules.get(name)
            if trig_cls is None:
                logger.warning("Trigger module %s not found", name)
                continue
            for trig in trig_cls.getAvailableDevices():
                device_id = str(trig.deviceID)
                trig_config = HeadlessConfigManager()
                if hasattr(trig_cls, "DEFAULT_CONFIG"):
                    trig_config.set_defaults(trig_cls.DEFAULT_CONFIG)
                user_trig = trigger_configs_dict.get(device_id, {})
                if user_trig:
                    trig_config.set_many(user_trig)
                try:
                    success = trig.initialize(trig_config)
                    if not success:
                        raise IOError(f"Trigger {device_id} failed to initialize")
                    trig.initialized = True
                    triggers.append(trig)
                    logger.info("Trigger %s initialized", device_id)
                except Exception as err:
                    logger.exception(
                        "Failed to initialize trigger %s: %s", device_id, err
                    )

        # Resolve enabled plugins (excluding display-only plugins)
        plugin_module_names = [
            n
            for n in self._config.get("Enabled Plugin Modules", [])
            if n not in self.EXCLUDED_PLUGINS
        ]

        multiprocess = self._config.get("multiprocess", False)
        cam_overrides = self._config.get("cameras", {})
        plugin_overrides = self._config.get("plugins", {})

        # Build pipeline context per camera
        self._contexts = []
        for camera in cameras:
            display_name = camera.getDisplayName()
            cam_save_dir = os.path.join(session_dir, slugify(display_name))

            # Camera config
            cam_config = HeadlessConfigManager()
            cam_cls = type(camera)
            if hasattr(cam_cls, "DEFAULT_PROPS"):
                cam_config.set_defaults(cam_cls.DEFAULT_PROPS)
            user_cam = cam_overrides.get(display_name, {})
            if user_cam:
                cam_config.set_many(user_cam)

            ctx = PipelineContext(
                camera=camera,
                camera_config=cam_config,
                save_dir=cam_save_dir,
                triggers=triggers,
                session_dir=session_dir,
            )
            ctx.multiprocess = multiprocess

            # Instantiate plugins
            for pname in plugin_module_names:
                pcls = BasePlugin.modules.get(pname)
                if pcls is None:
                    logger.warning("Plugin module %s not found", pname)
                    continue
                pconfig = HeadlessConfigManager()
                if hasattr(pcls, "DEFAULT_CONFIG"):
                    pconfig.set_defaults(pcls.DEFAULT_CONFIG)
                user_plugin = plugin_overrides.get(pname, {})
                if user_plugin:
                    pconfig.set_many(user_plugin)
                if pcls.__name__ == "VideoWriter" and user_plugin:
                    from rataGUI.plugins.video_codec_rules import validate_config

                    codec = user_plugin.get("vcodec", pconfig.get("vcodec"))
                    validate_config(codec, user_plugin, strict=True)
                try:
                    ctx.plugins.append(pcls(ctx, pconfig))
                    ctx.plugin_names.append(pcls.__name__)
                except Exception as err:
                    config_dict = pconfig.as_dict()
                    config_dict["Error Message"] = repr(err)
                    ctx.failed_plugins[pcls.__name__] = config_dict
                    logger.exception(
                        "Plugin %s failed to init for camera %s: %s",
                        pcls.__name__,
                        display_name,
                        err,
                    )
                    logger.warning(
                        "Plugin %s failed to initialize and will not run. "
                        "If this is VideoWriter, video will NOT be saved! "
                        "Camera: %s",
                        pcls.__name__,
                        display_name,
                    )

            if not ctx.plugins:
                logger.warning("No plugins for camera %s — skipping", display_name)
                continue

            ctx.save_widget_data()
            self._contexts.append(ctx)

        if not self._contexts:
            logger.error("No pipelines to run")
            return

        logger.info("Starting %d pipeline(s)", len(self._contexts))
        await asyncio.gather(
            *[self._run_single_pipeline(ctx) for ctx in self._contexts]
        )
        logger.info("All pipelines finished")

        # Clean up triggers
        for trig in triggers:
            try:
                if trig.initialized:
                    trig.close()
            except Exception as err:
                logger.exception("Trigger %s failed to close: %s", trig.deviceID, err)

        # Release camera resources
        released = set()
        for ctx in self._contexts:
            cam_cls = type(ctx.camera)
            if cam_cls not in released:
                cam_cls.releaseResources()
                released.add(cam_cls)

    # ------------------------------------------------------------------
    # Module loading
    # ------------------------------------------------------------------

    def _load_modules(self) -> None:
        """Import camera/plugin/trigger modules to trigger __init_subclass__ registration."""
        for kind, key in [
            ("cameras", "Enabled Camera Modules"),
            ("plugins", "Enabled Plugin Modules"),
            ("triggers", "Enabled Trigger Modules"),
        ]:
            for name in self._config.get(key, []):
                try:
                    import_module(f"rataGUI.{kind}.{name}")
                except Exception as err:
                    logger.exception(
                        "Failed to import rataGUI.%s.%s: %s", kind, name, err
                    )

    # ------------------------------------------------------------------
    # Single-pipeline lifecycle
    # ------------------------------------------------------------------

    async def _run_single_pipeline(self, ctx: PipelineContext) -> None:
        """Run one camera's full pipeline lifecycle."""
        try:
            if ctx.multiprocess:
                await self._start_multiprocess_pipeline(ctx)
            else:
                await self._start_threaded_pipeline(ctx)
        finally:
            for plugin in ctx.plugins:
                try:
                    plugin.close()
                except Exception as err:
                    logger.exception(
                        "Plugin %s failed to close: %s", type(plugin).__name__, err
                    )
            ctx.clean_session_dir()

    async def _start_threaded_pipeline(self, ctx: PipelineContext) -> None:
        """Single-process pipeline using ThreadPoolExecutor."""
        try:
            success = ctx.camera.initializeCamera(ctx.camera_config, ctx.plugin_names)
            if not success:
                raise IOError(
                    f"Camera: {ctx.camera.getDisplayName()} failed to initialize"
                )
            ctx.camera._running = True
            ctx.camera.frames_acquired = 0
            logger.info("Started pipeline for camera: %s", ctx.camera.getDisplayName())
            await self._process_plugin_pipeline(ctx, multiprocess=False)
        except Exception as err:
            logger.exception(err)
            ctx.stop_camera_pipeline()

    async def _start_multiprocess_pipeline(self, ctx: PipelineContext) -> None:
        """Multi-process pipeline: camera in subprocess, plugins in main process."""
        from rataGUI.camera_process import camera_acquisition_loop

        default_h, default_w, default_c = 1080, 1920, 3
        # Number of ring buffer slots in shared memory for frame handoff
        # between the camera subprocess and the main process plugin pipeline.
        num_slots = 8
        shm_shape = (num_slots, default_h, default_w, default_c)
        shm_nbytes = int(np.prod(shm_shape))

        try:
            ctx._mp_shm = SharedMemory(create=True, size=shm_nbytes)
            ctx._mp_shm_frames = np.ndarray(
                shm_shape, dtype=np.uint8, buffer=ctx._mp_shm.buf
            )
            ctx._mp_meta_queue = multiprocessing.Queue()
            ctx._mp_control_queue = multiprocessing.Queue()
            ctx._mp_error_queue = multiprocessing.Queue()
            ready_event = multiprocessing.Event()

            camera_config_dict = ctx.camera_config.as_dict()

            ctx._mp_process = multiprocessing.Process(
                target=camera_acquisition_loop,
                kwargs={
                    "camera_module_name": ctx.camera_type,
                    "camera_id": ctx.camera.cameraID,
                    "camera_config_dict": camera_config_dict,
                    "plugin_names": ctx.plugin_names,
                    "shm_name": ctx._mp_shm.name,
                    "shm_shape": shm_shape,
                    "meta_queue": ctx._mp_meta_queue,
                    "control_queue": ctx._mp_control_queue,
                    "ready_event": ready_event,
                    "error_queue": ctx._mp_error_queue,
                    "log_dir": ctx.session_dir,
                },
                daemon=True,
            )
            ctx._mp_process.start()
            logger.info(
                "Started camera subprocess for %s (PID: %d)",
                ctx.camera.getDisplayName(),
                ctx._mp_process.pid,
            )

            if not ready_event.wait(timeout=30):
                if not ctx._mp_error_queue.empty():
                    err_type, err_msg = ctx._mp_error_queue.get_nowait()
                    raise IOError(f"Camera subprocess error ({err_type}): {err_msg}")
                raise IOError("Camera subprocess timed out during initialization")

            ctx.camera._running = True
            ctx.camera.frames_acquired = 0
            logger.info("Camera subprocess ready for %s", ctx.camera.getDisplayName())

            await self._process_plugin_pipeline(ctx, multiprocess=True)
        except Exception as err:
            logger.exception(err)
            ctx.stop_camera_pipeline()
        finally:
            self._cleanup_multiprocess(ctx)

    def _cleanup_multiprocess(self, ctx: PipelineContext) -> None:
        """Clean up multiprocess resources."""
        if ctx._mp_process is not None and ctx._mp_process.is_alive():
            try:
                ctx._mp_control_queue.put("stop")
                ctx._mp_process.join(timeout=10)
                if ctx._mp_process.is_alive():
                    logger.warning("Camera subprocess did not exit, terminating")
                    ctx._mp_process.terminate()
                    ctx._mp_process.join(timeout=5)
            except Exception as err:
                logger.exception("Error stopping camera subprocess: %s", err)

        if ctx._mp_shm is not None:
            try:
                ctx._mp_shm.close()
                ctx._mp_shm.unlink()
            except Exception:
                pass
            ctx._mp_shm = None

    # ------------------------------------------------------------------
    # Async pipeline methods (ported from CameraWidget)
    # ------------------------------------------------------------------

    async def _acquire_frames(self, ctx: PipelineContext) -> None:
        """Read frames from camera in thread pool and enqueue them."""
        t0 = time.time()
        try:
            loop = asyncio.get_running_loop()
            while ctx.camera._running:
                if ctx.active:
                    status, frame = await loop.run_in_executor(
                        thread_pool, ctx.camera.readCamera
                    )
                    metadata = ctx.camera.getMetadata()
                    metadata["Camera Name"] = ctx.camera.getDisplayName()
                    metadata["Timestamp"] = datetime.now()
                    metadata["Average Latency"] = ctx.avg_latency

                    if status:
                        target_queue = ctx._acquisition_queue or ctx.plugins[0].in_queue
                        await target_queue.put((frame, metadata))
                        await asyncio.sleep(0)
                    else:
                        raise IOError(
                            f"Frame not found on camera: {ctx.camera.getDisplayName()}"
                        )
                else:
                    await asyncio.sleep(0)
        except Exception as err:
            logger.exception(err)
            logger.error(
                "Exception acquiring frame from camera: %s ... stopping",
                ctx.camera.getDisplayName(),
            )
            ctx.stop_camera_pipeline()

        t1 = time.time()
        elapsed = t1 - t0
        if elapsed > 0:
            logger.debug("FPS: %s", ctx.camera.frames_acquired / elapsed)
        ctx.camera.closeCamera()

    def _read_from_mp_queue(self, ctx: PipelineContext) -> tuple[int, dict] | None:
        """Blocking read from multiprocessing metadata queue."""
        import queue as _queue

        while ctx.camera._running:
            try:
                return ctx._mp_meta_queue.get(timeout=0.1)
            except _queue.Empty:
                if not ctx._mp_error_queue.empty():
                    err_type, err_msg = ctx._mp_error_queue.get_nowait()
                    raise IOError(f"Camera subprocess error ({err_type}): {err_msg}")
                continue
        return None

    async def _acquire_frames_mp(self, ctx: PipelineContext) -> None:
        """Acquire frames from camera subprocess via shared memory."""
        t0 = time.time()
        try:
            loop = asyncio.get_running_loop()
            while ctx.camera._running:
                if ctx.active:
                    result = await loop.run_in_executor(
                        thread_pool, self._read_from_mp_queue, ctx
                    )
                    if result is None:
                        break

                    slot_idx, metadata = result
                    metadata["Average Latency"] = ctx.avg_latency
                    ctx.camera.frames_acquired += 1

                    frame = ctx._mp_shm_frames[slot_idx].copy()

                    target_queue = ctx._acquisition_queue or ctx.plugins[0].in_queue
                    await target_queue.put((frame, metadata))
                    await asyncio.sleep(0)
                else:
                    await asyncio.sleep(0)
        except Exception as err:
            logger.exception(err)
            logger.error(
                "Exception in multiprocess acquisition for camera: %s ... stopping",
                ctx.camera.getDisplayName(),
            )
            ctx.stop_camera_pipeline()

        t1 = time.time()
        elapsed = t1 - t0
        if elapsed > 0:
            logger.debug("FPS: %s", ctx.camera.frames_acquired / elapsed)

    async def _put_to_queue(
        self,
        target_queue: Any,
        item: Any,
        drop_policy: str = "block",
        ring_buffer: Any = None,
    ) -> None:
        """Put item to queue, respecting the drop policy."""
        if drop_policy == "drop_oldest" and target_queue.full():
            try:
                dropped = target_queue.get_nowait()
                if ring_buffer is not None and isinstance(dropped, int):
                    ring_buffer.release(dropped)
                target_queue.task_done()
            except asyncio.QueueEmpty:
                pass
        await target_queue.put(item)

    async def _plugin_process(
        self, ctx: PipelineContext, plugin: Any, ring_buffer: Any = None
    ) -> None:
        """Async execution loop for a single plugin."""
        loop = asyncio.get_running_loop()
        failures = 0
        while True:
            raw_item = await plugin.in_queue.get()

            if ring_buffer is not None and isinstance(raw_item, int):
                slot_idx = raw_item
                frame, metadata = ring_buffer.get_view(slot_idx)
                if plugin.blocking:
                    frame = frame.copy()
                    ring_buffer.release(slot_idx)
                    slot_idx = None
            else:
                slot_idx = None
                frame, metadata = raw_item

            try:
                if plugin.active:
                    if plugin.blocking:
                        result = await loop.run_in_executor(
                            thread_pool, plugin.process, frame, metadata
                        )
                    else:
                        result = plugin.process(frame, metadata)
                else:
                    result = (frame, metadata)

                if plugin.out_queue is not None:
                    await plugin.out_queue.put(result)
                elif not plugin.blocking:
                    delta_t = datetime.now() - metadata["Timestamp"]
                    ctx.avg_latency = (
                        delta_t.total_seconds() * 1000 * EXP_AVG_DECAY
                        + ctx.avg_latency * (1 - EXP_AVG_DECAY)
                    )
            except Exception as err:
                failures += 1
                logger.error(
                    "Plugin %s failure #%d: camera=%s, frame_index=%s, "
                    "frame_shape=%s, error=%s",
                    type(plugin).__name__,
                    failures,
                    ctx.camera.getDisplayName(),
                    metadata.get("Frame Index", "?") if metadata else "?",
                    frame.shape if frame is not None else None,
                    err,
                )
                logger.exception(err)
                if failures > 5:
                    logger.error(
                        "Plugin %s exceeded failure threshold (5), deactivating. "
                        "Camera: %s, total_frames_acquired: %d",
                        type(plugin).__name__,
                        ctx.camera.getDisplayName(),
                        ctx.camera.frames_acquired,
                    )
                    plugin.failed = True
                    plugin.active = False
                    logger.warning(
                        "Plugin %s has been deactivated due to repeated failures. "
                        "If this is VideoWriter, video is NOT being saved! "
                        "Camera: %s",
                        type(plugin).__name__,
                        ctx.camera.getDisplayName(),
                    )
                    plugin.close()
            finally:
                if ring_buffer is not None and slot_idx is not None:
                    ring_buffer.release(slot_idx)
                plugin.in_queue.task_done()

    async def _fan_out(
        self, source_queue: Any, target_plugins: list, ring_buffer: Any = None
    ) -> None:
        """Distribute frames from one source queue to multiple independent plugins."""
        loop = asyncio.get_running_loop()
        while True:
            item = await source_queue.get()
            try:
                if ring_buffer is not None:
                    frame, metadata = item
                    slot_idx = await loop.run_in_executor(
                        None, ring_buffer.publish, frame, metadata
                    )
                    for plugin in target_plugins:
                        if plugin.blocking:
                            view, meta = ring_buffer.get_view(slot_idx)
                            frame_copy = view.copy()
                            ring_buffer.release(slot_idx)
                            await self._put_to_queue(
                                plugin.in_queue,
                                (frame_copy, meta),
                                plugin.drop_policy,
                            )
                        else:
                            await self._put_to_queue(
                                plugin.in_queue,
                                slot_idx,
                                plugin.drop_policy,
                                ring_buffer=ring_buffer,
                            )
                else:
                    for plugin in target_plugins:
                        await self._put_to_queue(
                            plugin.in_queue, item, plugin.drop_policy
                        )
            finally:
                source_queue.task_done()

    async def _process_plugin_pipeline(
        self, ctx: PipelineContext, multiprocess: bool = False
    ) -> None:
        """Orchestrate acquisition, plugin chain, and fan-out."""
        if multiprocess:
            acquisition_task = asyncio.create_task(self._acquire_frames_mp(ctx))
        else:
            acquisition_task = asyncio.create_task(self._acquire_frames(ctx))

        serial_plugins = list(ctx.plugins)
        independent_plugins = []

        while serial_plugins and serial_plugins[-1].independent:
            independent_plugins.insert(0, serial_plugins.pop())

        plugin_tasks = []
        for cur_plugin, next_plugin in zip(serial_plugins, serial_plugins[1:]):
            cur_plugin.out_queue = next_plugin.in_queue
            plugin_tasks.append(
                asyncio.create_task(self._plugin_process(ctx, cur_plugin))
            )

        fan_out_queue = None
        ring_buffer = None
        if independent_plugins:
            fan_out_queue = asyncio.Queue()

            num_slots = max(
                sum(
                    p.in_queue.maxsize
                    for p in independent_plugins
                    if p.in_queue.maxsize > 0
                ),
                8,
            )
            try:
                from rataGUI.frame_ring_buffer import FrameRingBuffer

                ring_buffer = FrameRingBuffer(
                    num_slots=num_slots,
                    height=1,
                    width=1,
                    channels=3,
                    num_consumers=len(independent_plugins),
                )
                logger.info(
                    "Ring buffer enabled for %d independent plugins (%d slots)",
                    len(independent_plugins),
                    num_slots,
                )
            except Exception as err:
                logger.warning(
                    "Ring buffer init failed, falling back to queue fan-out: %s", err
                )
                ring_buffer = None

            if serial_plugins:
                serial_plugins[-1].out_queue = fan_out_queue
                plugin_tasks.append(
                    asyncio.create_task(self._plugin_process(ctx, serial_plugins[-1]))
                )
            else:
                ctx._acquisition_queue = fan_out_queue

            plugin_tasks.append(
                asyncio.create_task(
                    self._fan_out(fan_out_queue, independent_plugins, ring_buffer)
                )
            )

            for plugin in independent_plugins:
                plugin_tasks.append(
                    asyncio.create_task(
                        self._plugin_process(ctx, plugin, ring_buffer=ring_buffer)
                    )
                )
        else:
            plugin_tasks.append(
                asyncio.create_task(self._plugin_process(ctx, serial_plugins[-1]))
            )

        await acquisition_task

        for plugin in ctx.plugins:
            await plugin.in_queue.join()
        if fan_out_queue is not None:
            await fan_out_queue.join()

        for task in plugin_tasks:
            task.cancel()

        ctx._acquisition_queue = None
