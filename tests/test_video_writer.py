import pytest
from unittest.mock import patch, MagicMock
import rataGUI.plugins.video_writer as vw_module
from rataGUI.plugins.video_writer import (
    VideoWriter, FFMPEG_Writer, _get_nvidia_driver_version,
    _check_ffmpeg_encoder_available, _check_ffmpeg_cuda_available,
)


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
        vw_module._ffmpeg_encoder_cache = {}
        vw_module._ffmpeg_cuda_available_cache = None

    def _make_nvenc_writer(self, **overrides):
        """Helper to create a MagicMock VideoWriter with standard NVENC attributes."""
        writer = MagicMock(spec=VideoWriter)
        defaults = {
            "output_params": {"-preset": "p4", "-pix_fmt": "yuv420p"},
            "rate_control": "auto",
            "bitrate_mbps": 0,
            "gpu_index": -1,
            "b_frames": 0,
            "tune": "none",
            "gpu_pixel_conversion": False,
            "_use_hwaccel": False,
        }
        defaults.update(overrides)
        for k, v in defaults.items():
            setattr(writer, k, v)
        return writer

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_sdk10_legacy_preset_mapping(self, mock_driver, _mock_enc):
        mock_driver.return_value = 535
        writer = self._make_nvenc_writer(
            output_params={"-preset": "fast", "-crf": "32", "-pix_fmt": "yuv420p"}
        )
        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)
        assert writer.output_params["-preset"] == "p1"

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_legacy_driver_new_preset_mapping(self, mock_driver, _mock_enc):
        mock_driver.return_value = 400  # old driver
        writer = self._make_nvenc_writer(
            output_params={"-preset": "p4", "-crf": "32", "-pix_fmt": "yuv420p"}
        )
        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)
        assert writer.output_params["-preset"] == "medium"

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_rate_control_constqp(self, mock_driver, _mock_enc):
        mock_driver.return_value = 535
        writer = self._make_nvenc_writer(
            output_params={"-preset": "p4", "-crf": "28", "-pix_fmt": "yuv420p"},
            rate_control="constqp",
        )
        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)
        assert writer.output_params["-rc"] == "constqp"
        assert writer.output_params["-cq"] == "28"
        assert "-crf" not in writer.output_params

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_rate_control_cbr_with_bitrate(self, mock_driver, _mock_enc):
        mock_driver.return_value = 535
        writer = self._make_nvenc_writer(rate_control="cbr", bitrate_mbps=10)
        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)
        assert writer.output_params["-rc"] == "cbr"
        assert writer.output_params["-b:v"] == "10M"

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_rate_control_cbr_zero_bitrate_defaults(self, mock_driver, _mock_enc):
        mock_driver.return_value = 535
        writer = self._make_nvenc_writer(rate_control="cbr", bitrate_mbps=0)
        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)
        assert writer.output_params["-b:v"] == "8M"

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_gpu_index(self, mock_driver, _mock_enc):
        mock_driver.return_value = 535
        writer = self._make_nvenc_writer(gpu_index=2)
        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)
        assert writer.output_params["-gpu"] == "2"

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_b_frames(self, mock_driver, _mock_enc):
        mock_driver.return_value = 535
        writer = self._make_nvenc_writer(b_frames=3)
        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)
        assert writer.output_params["-bf"] == "3"

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_unsupported_pix_fmt_defaults(self, mock_driver, _mock_enc):
        mock_driver.return_value = 535
        writer = self._make_nvenc_writer(
            output_params={"-preset": "p4", "-pix_fmt": "rgb24"}
        )
        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)
        assert writer.output_params["-pix_fmt"] == "yuv420p"

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_sdk10_tune_applied(self, mock_driver, _mock_enc):
        mock_driver.return_value = 535
        writer = self._make_nvenc_writer(tune="hq")
        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)
        assert writer.output_params["-tune"] == "hq"

    # --- av1_nvenc-specific tests ---

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_av1_nvenc_b_frames_skipped(self, mock_driver, _mock_enc):
        """av1_nvenc does not support B-frames; -bf should not appear."""
        mock_driver.return_value = 535
        writer = self._make_nvenc_writer(b_frames=3)
        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "av1_nvenc", config)
        assert "-bf" not in writer.output_params

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_av1_nvenc_low_driver_warns(self, mock_driver, _mock_enc):
        """av1_nvenc should warn when driver < 520."""
        mock_driver.return_value = 470
        writer = self._make_nvenc_writer()
        config = MagicMock()
        with patch("rataGUI.plugins.video_writer.logger") as mock_logger:
            VideoWriter._configure_nvenc(writer, "av1_nvenc", config)
            warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
            assert any("520" in w for w in warning_msgs)

    # --- CUDA safety tests ---

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_cuda_available", return_value=False)
    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_cuda_unavailable_disables_hwaccel(self, mock_driver, _mock_enc, _mock_cuda):
        """When CUDA is not in ffmpeg, gpu_pixel_conversion should be disabled."""
        mock_driver.return_value = 535
        writer = self._make_nvenc_writer(gpu_pixel_conversion=True)
        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)
        assert writer._use_hwaccel is False
        assert writer.gpu_pixel_conversion is False

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_cuda_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_cuda_available_enables_hwaccel(self, mock_driver, _mock_enc, _mock_cuda):
        """When CUDA is available, gpu_pixel_conversion should enable hwaccel."""
        mock_driver.return_value = 535
        writer = self._make_nvenc_writer(gpu_pixel_conversion=True)
        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)
        assert writer._use_hwaccel is True


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


class TestHwaccelFlags:
    @patch("rataGUI.plugins.video_writer.which")
    def test_hwaccel_flags_in_command(self, mock_which, tmp_path):
        """Verify -hwaccel cuda flags appear in ffmpeg command when use_hwaccel=True."""
        mock_which.return_value = "/usr/bin/ffmpeg"
        writer = FFMPEG_Writer(
            str(tmp_path / "test.mp4"),
            input_dict={},
            output_dict={"-vcodec": "h264_nvenc"},
            use_hwaccel=True,
        )

        with patch("rataGUI.plugins.video_writer.sp") as mock_sp:
            mock_proc = MagicMock()
            mock_sp.Popen.return_value = mock_proc
            mock_sp.PIPE = -1
            mock_sp.DEVNULL = -2
            mock_sp.STDOUT = -3

            writer.start_process(480, 640, 3)

            assert "-hwaccel" in writer._cmd
            assert "cuda" in writer._cmd
            assert "-hwaccel_output_format" in writer._cmd

    @patch("rataGUI.plugins.video_writer.which")
    def test_no_hwaccel_flags_by_default(self, mock_which, tmp_path):
        """Verify no hwaccel flags when use_hwaccel=False (default)."""
        mock_which.return_value = "/usr/bin/ffmpeg"
        writer = FFMPEG_Writer(
            str(tmp_path / "test.mp4"),
            input_dict={},
            output_dict={"-vcodec": "libx264"},
        )

        with patch("rataGUI.plugins.video_writer.sp") as mock_sp:
            mock_proc = MagicMock()
            mock_sp.Popen.return_value = mock_proc
            mock_sp.PIPE = -1
            mock_sp.DEVNULL = -2
            mock_sp.STDOUT = -3

            writer.start_process(480, 640, 3)

            assert "-hwaccel" not in writer._cmd

    @patch("rataGUI.plugins.video_writer.which")
    def test_increased_pipe_buffer_with_hwaccel(self, mock_which, tmp_path):
        """Verify 2MB pipe buffer when hwaccel is active."""
        mock_which.return_value = "/usr/bin/ffmpeg"
        writer = FFMPEG_Writer(
            str(tmp_path / "test.mp4"),
            input_dict={},
            output_dict={"-vcodec": "h264_nvenc"},
            use_hwaccel=True,
        )

        with patch("rataGUI.plugins.video_writer.sp") as mock_sp:
            mock_proc = MagicMock()
            mock_sp.Popen.return_value = mock_proc
            mock_sp.PIPE = -1
            mock_sp.DEVNULL = -2
            mock_sp.STDOUT = -3

            writer.start_process(480, 640, 3)

            # Check Popen was called with 2MB bufsize
            call_kwargs = mock_sp.Popen.call_args
            assert call_kwargs[1]["bufsize"] == 2 * 1024 * 1024

    @patch("rataGUI.plugins.video_writer.which")
    def test_default_pipe_buffer_without_hwaccel(self, mock_which, tmp_path):
        """Verify 1MB pipe buffer when hwaccel is not active."""
        mock_which.return_value = "/usr/bin/ffmpeg"
        writer = FFMPEG_Writer(
            str(tmp_path / "test.mp4"),
            input_dict={},
            output_dict={"-vcodec": "libx264"},
        )

        with patch("rataGUI.plugins.video_writer.sp") as mock_sp:
            mock_proc = MagicMock()
            mock_sp.Popen.return_value = mock_proc
            mock_sp.PIPE = -1
            mock_sp.DEVNULL = -2
            mock_sp.STDOUT = -3

            writer.start_process(480, 640, 3)

            call_kwargs = mock_sp.Popen.call_args
            assert call_kwargs[1]["bufsize"] == 1024 * 1024

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_cuda_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_configure_nvenc_sets_hwaccel_flag(self, mock_driver, _mock_enc, _mock_cuda):
        """Verify _configure_nvenc sets _use_hwaccel when gpu_pixel_conversion is True."""
        mock_driver.return_value = 535
        writer = MagicMock()
        writer.output_params = {"-preset": "p4", "-pix_fmt": "yuv420p"}
        writer.rate_control = "auto"
        writer.bitrate_mbps = 0
        writer.gpu_index = -1
        writer.b_frames = 0
        writer.tune = "none"
        writer.gpu_pixel_conversion = True
        writer._use_hwaccel = False

        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)

        assert writer._use_hwaccel is True

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    @patch("rataGUI.plugins.video_writer._get_nvidia_driver_version")
    def test_configure_nvenc_no_hwaccel_without_gpu_conversion(self, mock_driver, _mock_enc):
        """Verify _configure_nvenc does NOT set _use_hwaccel when gpu_pixel_conversion is False."""
        mock_driver.return_value = 535
        writer = MagicMock()
        writer.output_params = {"-preset": "p4", "-pix_fmt": "yuv420p"}
        writer.rate_control = "auto"
        writer.bitrate_mbps = 0
        writer.gpu_index = -1
        writer.b_frames = 0
        writer.tune = "none"
        writer.gpu_pixel_conversion = False
        writer._use_hwaccel = False

        config = MagicMock()
        VideoWriter._configure_nvenc(writer, "h264_nvenc", config)

        assert writer._use_hwaccel is False


class TestCheckFfmpegEncoderAvailable:
    def setup_method(self):
        vw_module._ffmpeg_encoder_cache = {}

    @patch("rataGUI.plugins.video_writer._which", return_value="/usr/bin/ffmpeg")
    @patch("rataGUI.plugins.video_writer._sp")
    def test_encoder_found(self, mock_sp, _mock_which):
        mock_sp.run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "Encoders:\n"
                " V..... libx264              libx264 H.264\n"
                " V..... av1_nvenc            NVIDIA NVENC AV1\n"
            ),
        )
        assert _check_ffmpeg_encoder_available("av1_nvenc") is True

    @patch("rataGUI.plugins.video_writer._which", return_value="/usr/bin/ffmpeg")
    @patch("rataGUI.plugins.video_writer._sp")
    def test_encoder_not_found(self, mock_sp, _mock_which):
        mock_sp.run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "Encoders:\n"
                " V..... libx264              libx264 H.264\n"
            ),
        )
        assert _check_ffmpeg_encoder_available("av1_nvenc") is False

    @patch("rataGUI.plugins.video_writer._which", return_value="/usr/bin/ffmpeg")
    @patch("rataGUI.plugins.video_writer._sp")
    def test_caching(self, mock_sp, _mock_which):
        mock_sp.run.return_value = MagicMock(
            returncode=0,
            stdout=" V..... libsvtav1            SVT-AV1\n",
        )
        _check_ffmpeg_encoder_available("libsvtav1")
        _check_ffmpeg_encoder_available("libsvtav1")
        assert mock_sp.run.call_count == 1

    @patch("rataGUI.plugins.video_writer._which", return_value=None)
    def test_no_ffmpeg(self, _mock_which):
        assert _check_ffmpeg_encoder_available("libx264") is False


class TestCheckFfmpegCudaAvailable:
    def setup_method(self):
        vw_module._ffmpeg_cuda_available_cache = None

    @patch("rataGUI.plugins.video_writer._which", return_value="/usr/bin/ffmpeg")
    @patch("rataGUI.plugins.video_writer._sp")
    def test_cuda_available(self, mock_sp, _mock_which):
        mock_sp.run.return_value = MagicMock(
            returncode=0,
            stdout="Hardware acceleration methods:\ncuda\nvdpau\n",
        )
        assert _check_ffmpeg_cuda_available() is True

    @patch("rataGUI.plugins.video_writer._which", return_value="/usr/bin/ffmpeg")
    @patch("rataGUI.plugins.video_writer._sp")
    def test_cuda_not_available(self, mock_sp, _mock_which):
        mock_sp.run.return_value = MagicMock(
            returncode=0,
            stdout="Hardware acceleration methods:\nvdpau\nvaapi\n",
        )
        assert _check_ffmpeg_cuda_available() is False

    @patch("rataGUI.plugins.video_writer._which", return_value="/usr/bin/ffmpeg")
    @patch("rataGUI.plugins.video_writer._sp")
    def test_caching(self, mock_sp, _mock_which):
        mock_sp.run.return_value = MagicMock(
            returncode=0,
            stdout="Hardware acceleration methods:\ncuda\n",
        )
        _check_ffmpeg_cuda_available()
        _check_ffmpeg_cuda_available()
        assert mock_sp.run.call_count == 1


class TestConfigureSvtav1:
    def setup_method(self):
        vw_module._ffmpeg_encoder_cache = {}

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    def test_text_preset_mapped(self, _mock_enc):
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "fast", "-crf": "30"}
        VideoWriter._configure_svtav1(writer, "libsvtav1")
        assert writer.output_params["-preset"] == "8"

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    def test_nvenc_preset_mapped(self, _mock_enc):
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "p4", "-crf": "30"}
        VideoWriter._configure_svtav1(writer, "libsvtav1")
        assert writer.output_params["-preset"] == "5"

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    def test_numeric_preset_preserved(self, _mock_enc):
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "8", "-crf": "30"}
        VideoWriter._configure_svtav1(writer, "libsvtav1")
        assert writer.output_params["-preset"] == "8"

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=True)
    def test_out_of_range_numeric_defaults(self, _mock_enc):
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "20", "-crf": "30"}
        VideoWriter._configure_svtav1(writer, "libsvtav1")
        assert writer.output_params["-preset"] == "5"

    @patch("rataGUI.plugins.video_writer._check_ffmpeg_encoder_available", return_value=False)
    def test_encoder_unavailable_warns(self, _mock_enc):
        writer = MagicMock(spec=VideoWriter)
        writer.output_params = {"-preset": "medium"}
        with patch("rataGUI.plugins.video_writer.logger") as mock_logger:
            VideoWriter._configure_svtav1(writer, "libsvtav1")
            mock_logger.warning.assert_called()
