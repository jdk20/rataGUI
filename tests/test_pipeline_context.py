"""Tests for PipelineContext."""

import os
import json
from unittest.mock import MagicMock

from rataGUI.headless.context import PipelineContext, HeadlessConfigManager


def _make_camera(display_name="TestCam"):
    camera = MagicMock()
    camera.cameraID = "cam-001"
    camera.display_name = display_name
    camera.getDisplayName.return_value = display_name
    camera._running = False
    camera.frames_acquired = 0
    return camera


class TestPipelineContext:
    def test_attributes(self, tmp_path):
        camera = _make_camera()
        config = HeadlessConfigManager({"fps": 30})
        ctx = PipelineContext(
            camera=camera,
            camera_config=config,
            save_dir=str(tmp_path / "output"),
            triggers=[],
            session_dir=str(tmp_path),
        )
        assert ctx.camera is camera
        assert ctx.camera_config is config
        assert ctx.triggers == []
        assert ctx.camera_type == "MagicMock"
        assert ctx.active is True
        assert ctx.avg_latency == 0
        assert os.path.isdir(ctx.save_dir)

    def test_stop_camera_pipeline(self, tmp_path):
        camera = _make_camera()
        camera._running = True
        ctx = PipelineContext(
            camera=camera,
            camera_config=HeadlessConfigManager(),
            save_dir=str(tmp_path / "output"),
            triggers=[],
            session_dir=str(tmp_path),
        )
        ctx.stop_camera_pipeline()
        assert camera._running is False
        assert ctx.active is False

    def test_stop_sends_mp_signal(self, tmp_path):
        camera = _make_camera()
        camera._running = True
        ctx = PipelineContext(
            camera=camera,
            camera_config=HeadlessConfigManager(),
            save_dir=str(tmp_path / "output"),
            triggers=[],
            session_dir=str(tmp_path),
        )
        ctx._mp_control_queue = MagicMock()
        ctx.stop_camera_pipeline()
        ctx._mp_control_queue.put.assert_called_once_with("stop")

    def test_save_widget_data(self, tmp_path):
        camera = _make_camera("MyCam")
        ctx = PipelineContext(
            camera=camera,
            camera_config=HeadlessConfigManager({"fps": 30}),
            save_dir=str(tmp_path / "output"),
            triggers=[],
            session_dir=str(tmp_path),
        )
        ctx.save_widget_data()
        metadata_path = os.path.join(ctx.save_dir, "MyCam_metadata.json")
        assert os.path.isfile(metadata_path)
        with open(metadata_path) as f:
            data = json.load(f)
        assert data["Camera Type"] == "MagicMock"
        assert data["Camera Settings"] == {"fps": 30}

    def test_clean_session_dir_removes_empty(self, tmp_path):
        session = tmp_path / "session"
        save = session / "output"
        save.mkdir(parents=True)
        camera = _make_camera("Cam")
        ctx = PipelineContext(
            camera=camera,
            camera_config=HeadlessConfigManager(),
            save_dir=str(save),
            triggers=[],
            session_dir=str(session),
        )
        ctx.clean_session_dir()
        assert not save.exists()
        assert not session.exists()

    def test_clean_session_dir_keeps_nonempty(self, tmp_path):
        session = tmp_path / "session"
        save = session / "output"
        save.mkdir(parents=True)
        (save / "video.mp4").write_text("data")
        camera = _make_camera("Cam")
        ctx = PipelineContext(
            camera=camera,
            camera_config=HeadlessConfigManager(),
            save_dir=str(save),
            triggers=[],
            session_dir=str(session),
        )
        ctx.clean_session_dir()
        assert save.exists()
        # save_widget_data should have been called, creating metadata file
        assert any("metadata.json" in f for f in os.listdir(save))

    def test_duck_type_for_base_plugin(self, tmp_path):
        """PipelineContext can be passed to BasePlugin.__init__ as cam_widget."""
        from rataGUI.plugins.base_plugin import BasePlugin

        camera = _make_camera()
        ctx = PipelineContext(
            camera=camera,
            camera_config=HeadlessConfigManager({"fps": 30}),
            save_dir=str(tmp_path),
            triggers=[],
        )

        class DummyPlugin(BasePlugin):
            def process(self, frame, metadata):
                return frame, metadata

        config = HeadlessConfigManager({"setting": "value"})
        plugin = DummyPlugin(ctx, config)
        assert plugin.active is True
        assert plugin.config == {"setting": "value"}
