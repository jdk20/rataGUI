"""Tests for the headless CLI."""

import json
import signal
from unittest.mock import patch, MagicMock

from rataGUI.headless import cli


class TestCLIParsing:
    def test_positional_config(self, tmp_path):
        config = {
            "Enabled Camera Modules": ["VideoReader"],
            "Save Directory": str(tmp_path),
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        with (
            patch("rataGUI.headless.runner.PipelineRunner") as MockRunner,
            patch("sys.argv", ["rataGUI-headless", str(config_path)]),
        ):
            instance = MockRunner.return_value
            instance.start = MagicMock()
            cli.main()
            MockRunner.assert_called_once()
            call_config = MockRunner.call_args[0][0]
            assert call_config["Enabled Camera Modules"] == ["VideoReader"]

    def test_save_dir_override(self, tmp_path):
        config = {"Enabled Camera Modules": [], "Save Directory": "/old"}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        with (
            patch("rataGUI.headless.runner.PipelineRunner") as MockRunner,
            patch(
                "sys.argv", ["rataGUI-headless", str(config_path), "--save-dir", "/new"]
            ),
        ):
            instance = MockRunner.return_value
            instance.start = MagicMock()
            cli.main()
            call_config = MockRunner.call_args[0][0]
            assert call_config["Save Directory"] == "/new"

    def test_multiprocess_flag(self, tmp_path):
        config = {"Enabled Camera Modules": [], "Save Directory": str(tmp_path)}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        with (
            patch("rataGUI.headless.runner.PipelineRunner") as MockRunner,
            patch("sys.argv", ["rataGUI-headless", str(config_path), "--multiprocess"]),
        ):
            instance = MockRunner.return_value
            instance.start = MagicMock()
            cli.main()
            call_config = MockRunner.call_args[0][0]
            assert call_config["multiprocess"] is True

    def test_empty_config_exits_cleanly(self):
        with (
            patch("rataGUI.launch_config", {}),
            patch("sys.argv", ["rataGUI-headless"]),
        ):
            # Should not raise
            cli.main()


class TestCLISignalHandling:
    def test_signal_handlers_registered(self, tmp_path):
        config = {"Enabled Camera Modules": [], "Save Directory": str(tmp_path)}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        registered_signals = {}

        def mock_signal(signum, handler):
            registered_signals[signum] = handler

        with (
            patch("rataGUI.headless.runner.PipelineRunner") as MockRunner,
            patch("signal.signal", side_effect=mock_signal),
            patch("sys.argv", ["rataGUI-headless", str(config_path)]),
        ):
            instance = MockRunner.return_value
            instance.start = MagicMock()
            cli.main()

        assert signal.SIGINT in registered_signals
        assert signal.SIGTERM in registered_signals
