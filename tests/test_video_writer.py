import pytest
from unittest.mock import patch, MagicMock
import rataGUI.plugins.video_writer as vw_module
from rataGUI.plugins.video_writer import VideoWriter, FFMPEG_Writer, _get_nvidia_driver_version


class TestGetNvidiaDriverVersion:
    def setup_method(self):
        # Reset the module-level cache before each test
        vw_module._nvidia_driver_version_cache = None

    @patch("subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="535.86.10\n")

        version = _get_nvidia_driver_version()
        assert version == 535

    @patch("subprocess.run")
    def test_failure(self, mock_run):
        mock_run.side_effect = FileNotFoundError("nvidia-smi not found")

        version = _get_nvidia_driver_version()
        assert version is None

    @patch("subprocess.run")
    def test_nonzero_return(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        version = _get_nvidia_driver_version()
        assert version is None

    @patch("subprocess.run")
    def test_caching(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="535.86.10\n")

        v1 = _get_nvidia_driver_version()
        v2 = _get_nvidia_driver_version()

        assert v1 == v2 == 535
        # subprocess.run should only be called once due to caching
        assert mock_run.call_count == 1

    @patch("subprocess.run")
    def test_cache_failure(self, mock_run):
        mock_run.side_effect = FileNotFoundError()

        v1 = _get_nvidia_driver_version()
        v2 = _get_nvidia_driver_version()

        assert v1 is None
        assert v2 is None
        # subprocess.run only called once, failure is cached too
        assert mock_run.call_count == 1


class TestValidateCpuPreset:
    def test_nvenc_preset_remapped(self):
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "p4"}
        VideoWriter._validate_cpu_preset(writer, "libx264")
        assert writer.output_params["-preset"] == "medium"

    def test_valid_cpu_preset_unchanged(self):
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "medium"}
        VideoWriter._validate_cpu_preset(writer, "libx264")
        assert writer.output_params["-preset"] == "medium"

    def test_cpu_preset_ultrafast(self):
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "ultrafast"}
        VideoWriter._validate_cpu_preset(writer, "libx264")
        assert writer.output_params["-preset"] == "ultrafast"

    def test_all_nvenc_presets_remapped(self):
        nvenc_presets = {"p1", "p2", "p3", "p4", "p5", "p6", "p7"}
        for preset in nvenc_presets:
            writer = MagicMock(spec=VideoWriter)
            writer.output_params = {"-preset": preset}
            VideoWriter._validate_cpu_preset(writer, "libx264")
            assert writer.output_params["-preset"] == "medium"


class TestConfigureNvenc:
    def setup_method(self):
        vw_module._nvidia_driver_version_cache = None

    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_sdk10_legacy_preset_mapping(self, mock_driver):
        mock_driver.return_value = 535
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "fast", "-crf": "32", "-pix_fmt": "yuv420p"}
        writer.rate_control = "auto"
        writer.bitrate_mbps = 0
        writer.gpu_index = -1
        writer.b_frames = 0
        writer.tune = "none"

        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)

        assert writer.output_params["-preset"] == "p1"

    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_legacy_driver_new_preset_mapping(self, mock_driver):
        mock_driver.return_value = 400  # old driver
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "p4", "-crf": "32", "-pix_fmt": "yuv420p"}
        writer.rate_control = "auto"
        writer.bitrate_mbps = 0
        writer.gpu_index = -1
        writer.b_frames = 0
        writer.tune = "none"

        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)

        assert writer.output_params["-preset"] == "medium"

    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_rate_control_constqp(self, mock_driver):
        mock_driver.return_value = 535
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "p4", "-crf": "28", "-pix_fmt": "yuv420p"}
        writer.rate_control = "constqp"
        writer.bitrate_mbps = 0
        writer.gpu_index = -1
        writer.b_frames = 0
        writer.tune = "none"

        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)

        assert writer.output_params["-rc"] == "constqp"
        assert writer.output_params["-cq"] == "28"
        assert "-crf" not in writer.output_params

    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_rate_control_cbr_with_bitrate(self, mock_driver):
        mock_driver.return_value = 535
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "p4", "-pix_fmt": "yuv420p"}
        writer.rate_control = "cbr"
        writer.bitrate_mbps = 10
        writer.gpu_index = -1
        writer.b_frames = 0
        writer.tune = "none"

        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)

        assert writer.output_params["-rc"] == "cbr"
        assert writer.output_params["-b:v"] == "10M"

    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_rate_control_cbr_zero_bitrate_defaults(self, mock_driver):
        mock_driver.return_value = 535
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "p4", "-pix_fmt": "yuv420p"}
        writer.rate_control = "cbr"
        writer.bitrate_mbps = 0
        writer.gpu_index = -1
        writer.b_frames = 0
        writer.tune = "none"

        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)

        assert writer.output_params["-b:v"] == "8M"

    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_gpu_index(self, mock_driver):
        mock_driver.return_value = 535
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "p4", "-pix_fmt": "yuv420p"}
        writer.rate_control = "auto"
        writer.bitrate_mbps = 0
        writer.gpu_index = 2
        writer.b_frames = 0
        writer.tune = "none"

        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)

        assert writer.output_params["-gpu"] == "2"

    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_b_frames(self, mock_driver):
        mock_driver.return_value = 535
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "p4", "-pix_fmt": "yuv420p"}
        writer.rate_control = "auto"
        writer.bitrate_mbps = 0
        writer.gpu_index = -1
        writer.b_frames = 3
        writer.tune = "none"

        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)

        assert writer.output_params["-bf"] == "3"

    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_unsupported_pix_fmt_defaults(self, mock_driver):
        mock_driver.return_value = 535
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "p4", "-pix_fmt": "rgb24"}
        writer.rate_control = "auto"
        writer.bitrate_mbps = 0
        writer.gpu_index = -1
        writer.b_frames = 0
        writer.tune = "none"

        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)

        assert writer.output_params["-pix_fmt"] == "yuv420p"

    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_sdk10_tune_applied(self, mock_driver):
        mock_driver.return_value = 535
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "p4", "-pix_fmt": "yuv420p"}
        writer.rate_control = "auto"
        writer.bitrate_mbps = 0
        writer.gpu_index = -1
        writer.b_frames = 0
        writer.tune = "hq"

        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)

        assert writer.output_params["-tune"] == "hq"


class TestFFMPEGWriter:
    @patch("rataGUI.plugins.video_writer.which")
    def test_init_finds_ffmpeg(self, mock_which, tmp_path):
        mock_which.return_value = "/usr/bin/ffmpeg"
        writer = FFMPEG_Writer(str(tmp_path / "test.mp4"), input_dict={}, output_dict={})
        assert writer._FFMPEG_PATH == "/usr/bin/ffmpeg"
        assert writer.initialized is False

    @patch("rataGUI.plugins.video_writer.which")
    def test_init_no_ffmpeg_raises(self, mock_which):
        mock_which.return_value = None
        with pytest.raises(IOError, match="ffmpeg"):
            FFMPEG_Writer("/tmp/test.mp4", input_dict={}, output_dict={})

    @patch("rataGUI.plugins.video_writer.which")
    def test_start_process_sets_input_size(self, mock_which, tmp_path):
        mock_which.return_value = "/usr/bin/ffmpeg"
        writer = FFMPEG_Writer(str(tmp_path / "test.mp4"), input_dict={}, output_dict={})

        with patch("rataGUI.plugins.video_writer.sp") as mock_sp:
            mock_proc = MagicMock()
            mock_sp.Popen.return_value = mock_proc
            mock_sp.PIPE = -1
            mock_sp.DEVNULL = -2
            mock_sp.STDOUT = -3

            writer.start_process(480, 640, 3)

            assert writer.initialized is True
            assert writer.input_dict["-s"] == "640x480"
            assert writer.input_dict["-pix_fmt"] == "rgb24"

    @patch("rataGUI.plugins.video_writer.which")
    def test_start_process_grayscale(self, mock_which, tmp_path):
        mock_which.return_value = "/usr/bin/ffmpeg"
        writer = FFMPEG_Writer(str(tmp_path / "test.mp4"), input_dict={}, output_dict={})

        with patch("rataGUI.plugins.video_writer.sp") as mock_sp:
            mock_proc = MagicMock()
            mock_sp.Popen.return_value = mock_proc
            mock_sp.PIPE = -1
            mock_sp.DEVNULL = -2
            mock_sp.STDOUT = -3

            writer.start_process(480, 640, 1)

            assert writer.input_dict["-pix_fmt"] == "gray"
