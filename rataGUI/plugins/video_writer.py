from rataGUI.plugins.base_plugin import BasePlugin
from rataGUI.plugins.video_codec_rules import (
    NVENC_CODECS as _NVENC_CODECS,
    NVENC_ONLY_KEYS as _NVENC_ONLY_KEYS,
    NVENC_PIXEL_FORMATS as _NVENC_PIXEL_FORMATS,
)
from rataGUI.utils import slugify

import os
import subprocess as _sp
import numpy as np
from datetime import datetime
from shutil import which as _which

import logging

logger = logging.getLogger(__name__)


# Cached NVIDIA driver version (None = not yet checked, False = unavailable).
# Caching avoids repeated nvidia-smi subprocess calls on every VideoWriter init.
_nvidia_driver_version_cache = None


def _get_nvidia_driver_version():
    """Query the NVIDIA driver major version via nvidia-smi.

    Returns the major version as an int (e.g. 535), or None if
    nvidia-smi is unavailable or the version cannot be parsed.
    The result is cached for the lifetime of the process.
    """
    global _nvidia_driver_version_cache
    if _nvidia_driver_version_cache is not None:
        return (
            _nvidia_driver_version_cache
            if _nvidia_driver_version_cache is not False
            else None
        )

    import subprocess as sp

    try:
        result = sp.run(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            version_str = result.stdout.strip().splitlines()[0]
            major = int(version_str.split(".")[0])
            _nvidia_driver_version_cache = major
            logger.info(
                f"Detected NVIDIA driver version: {version_str} (major={major})"
            )
            return major
    except Exception as err:
        logger.debug(f"Could not detect NVIDIA driver version: {err}")

    _nvidia_driver_version_cache = False
    return None


# Cached set of encoder names available in the ffmpeg binary.
# Populated once by running `ffmpeg -encoders` to avoid repeated subprocess calls.
_ffmpeg_encoder_cache = {}


def _check_ffmpeg_encoder_available(encoder_name):
    """Check if a specific encoder is compiled into the ffmpeg binary.

    Runs ``ffmpeg -encoders`` once, caches the full set of encoder names,
    and returns True/False for the requested encoder.
    """
    global _ffmpeg_encoder_cache
    if _ffmpeg_encoder_cache:  # already populated
        return encoder_name in _ffmpeg_encoder_cache

    ffmpeg_path = _which("ffmpeg")
    if ffmpeg_path is None:
        return False

    try:
        result = _sp.run(
            [ffmpeg_path, "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.strip().split()
                # Format: "V..... libx264  ..." (6-char flags field, then name)
                if len(parts) >= 2 and len(parts[0]) == 6:
                    _ffmpeg_encoder_cache[parts[1]] = True
    except Exception as err:
        logger.debug(f"Could not query ffmpeg encoders: {err}")

    return encoder_name in _ffmpeg_encoder_cache


# Cached CUDA hwaccel availability (None = not checked, True/False = result).
# Avoids repeated `ffmpeg -hwaccels` subprocess calls.
_ffmpeg_cuda_available_cache = None


def _check_ffmpeg_cuda_available():
    """Check if ffmpeg was compiled with CUDA hwaccel support.

    Runs ``ffmpeg -hwaccels`` and checks for 'cuda' in the output.
    Result is cached for the process lifetime.
    """
    global _ffmpeg_cuda_available_cache
    if _ffmpeg_cuda_available_cache is not None:
        return _ffmpeg_cuda_available_cache

    ffmpeg_path = _which("ffmpeg")
    if ffmpeg_path is None:
        _ffmpeg_cuda_available_cache = False
        return False

    try:
        result = _sp.run(
            [ffmpeg_path, "-hwaccels"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            hwaccels = result.stdout.lower().split()
            _ffmpeg_cuda_available_cache = "cuda" in hwaccels
            return _ffmpeg_cuda_available_cache
    except Exception as err:
        logger.debug(f"Could not query ffmpeg hwaccels: {err}")

    _ffmpeg_cuda_available_cache = False
    return False


# Cached per-codec check for NVENC P-series preset support.
# Keyed by encoder name; avoids repeated `ffmpeg -h encoder=...` calls.
_ffmpeg_nvenc_new_presets_cache = {}


def _check_nvenc_new_presets_available(encoder_name="h264_nvenc"):
    """Check if the ffmpeg binary supports NVENC P-series presets (p1-p7).

    Runs ``ffmpeg -h encoder=<encoder_name>`` and looks for P-series preset
    names in the output.  Result is cached per encoder name.
    """
    if encoder_name in _ffmpeg_nvenc_new_presets_cache:
        return _ffmpeg_nvenc_new_presets_cache[encoder_name]

    ffmpeg_path = _which("ffmpeg")
    if ffmpeg_path is None:
        _ffmpeg_nvenc_new_presets_cache[encoder_name] = False
        return False

    try:
        result = _sp.run(
            [ffmpeg_path, "-h", f"encoder={encoder_name}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            import re

            # Look for p1-p7 in the preset option description
            has_new = bool(re.search(r"\bp[1-7]\b", result.stdout))
            _ffmpeg_nvenc_new_presets_cache[encoder_name] = has_new
            if not has_new:
                logger.info(
                    "ffmpeg %s does not advertise P-series presets; "
                    "will use legacy preset names",
                    encoder_name,
                )
            return has_new
    except Exception as err:
        logger.debug(f"Could not probe {encoder_name} presets: {err}")

    _ffmpeg_nvenc_new_presets_cache[encoder_name] = False
    return False


class VideoWriter(BasePlugin):
    """
    Plugin that writes frames to video file using FFMPEG

    :param vcodec: Video codec used by ffmpeg binary
    """

    DEFAULT_CONFIG = {
        "Save directory": "",  # Defaults to camera widget's save directory
        "filename suffix": "",
        "vcodec": [
            "libx264",
            "libx265",
            "h264_nvenc",
            "hevc_nvenc",
            "av1_nvenc",
            "libsvtav1",
            "rawvideo",
        ],
        "framerate": 30,
        "speed (preset)": [
            "p1",  # fastest (NVENC SDK 10+)
            "p2",
            "p3",
            "p4",  # medium (NVENC SDK 10+)
            "p5",
            "p6",
            "p7",  # best quality (NVENC SDK 10+)
            "fast",  # shared (x264 + NVENC legacy)
            "medium",  # shared
            "slow",  # shared
            "veryfast",  # x264 only
            "ultrafast",  # x264 only
            "slower",  # x264 only
            "veryslow",  # x264 only
        ],  # Defaults to first item
        "quality (0-51)": (32, 0, 51),
        "pixel format": [
            "yuv420p",
            "yuv422p",
            "yuv444p",
            "rgb24",
            "yuv420p10le",
            "yuv422p10le",
            "yuv444p10le",
            "gray",
        ],
        "Write Frame Index": True,
        "Buffer Size (frames)": 120,
        # NVENC-specific options (ignored for CPU codecs)
        "Rate Control": ["auto", "constqp", "vbr", "cbr"],
        "Bitrate (Mbps)": (0, 0, 100),
        "GPU Index": (-1, -1, 7),
        "B-Frames": (0, 0, 4),
        "Tune": ["none", "hq", "ll", "ull"],
        "GPU Pixel Conversion": False,
    }

    DISPLAY_CONFIG_MAP = {
        "speed (preset)": "preset",
        "quality (0-51)": "crf",
        "pixel format": "pix_fmt",
    }

    # NVENC-specific config keys that should not be passed directly as ffmpeg args
    _NVENC_CONFIG_KEYS = _NVENC_ONLY_KEYS | {"B-Frames"}

    def __init__(self, cam_widget, config, queue_size=0):
        """Initialize the video writer, detecting available codecs and configuring ffmpeg settings."""
        super().__init__(cam_widget, config, queue_size)
        self.blocking = True
        self.independent = True
        self.input_params = {}
        self.output_params = {}

        # NVENC-specific settings (extracted before output_params)
        self.rate_control = "auto"
        self.bitrate_mbps = 0
        self.gpu_index = -1
        self.b_frames = 0
        self.tune = "none"
        self.gpu_pixel_conversion = False

        for name, value in self.config.items():
            prop_name = VideoWriter.DISPLAY_CONFIG_MAP.get(name)
            if prop_name is None:
                prop_name = name

            if prop_name == "Save directory":
                if len(value) == 0:  # default to widget save_dir
                    self.save_dir = cam_widget.save_dir
                elif not os.path.isdir(value):
                    logger.info(
                        "Specified save directory not found ... using widget directory"
                    )
                    self.save_dir = cam_widget.save_dir
                else:
                    self.save_dir = os.path.normpath(value)
            elif prop_name == "Write Frame Index":
                self.write_frame_index = value
            elif prop_name == "Buffer Size (frames)":
                self.buffer_size = int(value)
            elif prop_name == "filename suffix":
                self.file_name = slugify(cam_widget.camera.getDisplayName())
                if len(value) > 0:
                    self.file_name += "_" + slugify(value)
            # Intercept NVENC-specific config keys
            elif name == "Rate Control":
                self.rate_control = value
            elif name == "Bitrate (Mbps)":
                self.bitrate_mbps = int(value)
            elif name == "GPU Index":
                self.gpu_index = int(value)
            elif name == "B-Frames":
                self.b_frames = int(value)
            elif name == "Tune":
                self.tune = value
            elif name == "GPU Pixel Conversion":
                self.gpu_pixel_conversion = bool(value)
            elif (
                prop_name
                in [
                    "framerate",
                ]
                and value >= 0
            ):  # input parameters
                self.input_params["-" + prop_name] = str(value)

            else:  # output parameters
                self.output_params["-" + prop_name] = str(value)

        extension = ".mp4"

        # Configure codec-specific parameters
        self._use_hwaccel = False
        vcodec = self.output_params.get("-vcodec")
        if vcodec in ["rawvideo"]:
            extension = ".raw"
        elif vcodec in _NVENC_CODECS:
            self._configure_nvenc(vcodec, config)
        elif vcodec in ["libx264", "libx265"]:
            self._validate_cpu_preset(vcodec)
        elif vcodec == "libsvtav1":
            self._configure_svtav1(vcodec)

        try:
            if os.access(self.save_dir, os.W_OK):
                fld_name = datetime.now().strftime("video_%Y_%m_%d_%H_%M_%S")
                self.save_dir = os.path.join(self.save_dir, fld_name)
                os.makedirs(self.save_dir, exist_ok=True)
                if self.write_frame_index:
                    self.frameindex_file = open(
                        os.path.join(self.save_dir, f"frameindex_{self.file_name}"),
                        "wb",
                    )
                    self.timestamps_file = open(
                        os.path.join(self.save_dir, f"timestamps_{self.file_name}.txt"),
                        "w",
                    )
            else:
                raise OSError(
                    "Inaccessible save directory ... auto-disabling Video Writer plugin"
                )
        except Exception as err:
            logger.exception(err)
            self.active = False

        self.file_path = os.path.join(self.save_dir, self.file_name + extension)

        self.writer = FFMPEG_Writer(
            str(self.file_path),
            input_dict=self.input_params,
            output_dict=self.output_params,
            verbosity=0,
            buffer_size=getattr(self, "buffer_size", 120),
            gpu_pixel_conversion=self.gpu_pixel_conversion and vcodec in _NVENC_CODECS,
            use_hwaccel=self._use_hwaccel,
        )

    def _configure_nvenc(self, vcodec, config):
        """Configure NVENC-specific ffmpeg parameters with driver version awareness."""
        # --- Encoder availability check ---
        if not _check_ffmpeg_encoder_available(vcodec):
            logger.warning(
                f"{vcodec} encoder not found in ffmpeg build; encoding may fail"
            )

        preset = self.output_params.get("-preset")
        driver_version = _get_nvidia_driver_version()

        # av1_nvenc requires NVENC SDK 12+ (driver >= 520)
        if (
            vcodec == "av1_nvenc"
            and driver_version is not None
            and driver_version < 520
        ):
            logger.warning(
                f"av1_nvenc requires NVIDIA driver >= 520 (detected {driver_version}). "
                "Encoding may fail."
            )

        # --- Preset mapping based on driver version AND ffmpeg build ---
        if (
            driver_version is not None
            and driver_version >= 456
            and _check_nvenc_new_presets_available(vcodec)
        ):
            # SDK 10+: prefer P1-P7 presets
            legacy_to_new = {
                "fast": "p1",
                "medium": "p4",
                "slow": "p7",
                "llhp": "p1",
                "llhq": "p4",
                "lossless": "p7",
                "losslesshp": "p1",
            }
            valid_new = {"p1", "p2", "p3", "p4", "p5", "p6", "p7"}
            if preset in legacy_to_new:
                new_preset = legacy_to_new[preset]
                logger.info(
                    f"Mapping legacy NVENC preset '{preset}' to '{new_preset}' (SDK 10+)"
                )
                self.output_params["-preset"] = new_preset
            elif preset not in valid_new:
                logger.warning(
                    f"'{preset}' is not supported for {vcodec}, defaulting to p4"
                )
                self.output_params["-preset"] = "p4"
                config.set("speed (preset)", "p4")
                self.config["speed (preset)"] = "p4"

            # -tune is only supported on SDK 10+
            if self.tune != "none":
                self.output_params["-tune"] = self.tune
        else:
            # Legacy driver (pre-SDK 10) or nvidia-smi unavailable: use old preset names
            valid_legacy = {
                "slow",
                "medium",
                "fast",
                "llhp",
                "llhq",
                "lossless",
                "losslesshp",
            }
            new_to_legacy = {
                "p1": "fast",
                "p2": "fast",
                "p3": "medium",
                "p4": "medium",
                "p5": "slow",
                "p6": "slow",
                "p7": "slow",
            }
            if preset in new_to_legacy:
                old_preset = new_to_legacy[preset]
                logger.info(
                    f"Legacy NVIDIA driver: mapping preset '{preset}' to '{old_preset}'"
                )
                self.output_params["-preset"] = old_preset
            elif preset not in valid_legacy:
                logger.warning(
                    f"'{preset}' is not supported for {vcodec}, defaulting to medium"
                )
                self.output_params["-preset"] = "medium"
                config.set("speed (preset)", "medium")
                self.config["speed (preset)"] = "medium"
            # -tune not supported on legacy drivers, skip it

        # --- Rate control ---
        rc = self.rate_control
        if rc == "auto":
            rc = "constqp"

        # NVENC uses -cq instead of -crf for constant quality
        crf_value = self.output_params.pop("-crf", None)

        if rc == "constqp":
            self.output_params["-rc"] = "constqp"
            if crf_value is not None:
                self.output_params["-cq"] = crf_value
        elif rc == "vbr":
            self.output_params["-rc"] = "vbr"
            if crf_value is not None:
                self.output_params["-cq"] = crf_value
            if self.bitrate_mbps > 0:
                self.output_params["-b:v"] = f"{self.bitrate_mbps}M"
        elif rc == "cbr":
            self.output_params["-rc"] = "cbr"
            if self.bitrate_mbps > 0:
                self.output_params["-b:v"] = f"{self.bitrate_mbps}M"
            else:
                logger.warning(
                    "CBR rate control selected but bitrate is 0, defaulting to 8 Mbps"
                )
                self.output_params["-b:v"] = "8M"

        # --- GPU index ---
        if self.gpu_index >= 0:
            self.output_params["-gpu"] = str(self.gpu_index)

        # --- B-Frames ---
        if self.b_frames > 0:
            if vcodec == "av1_nvenc":
                logger.warning(
                    "av1_nvenc does not support B-frames; ignoring B-Frames setting"
                )
            else:
                self.output_params["-bf"] = str(self.b_frames)

        # --- Pixel format validation for NVENC ---
        pix_fmt = self.output_params.get("-pix_fmt", "yuv420p")
        if pix_fmt not in _NVENC_PIXEL_FORMATS:
            logger.warning(
                f"Pixel format '{pix_fmt}' is not supported by {vcodec}, defaulting to yuv420p"
            )
            self.output_params["-pix_fmt"] = "yuv420p"

        # --- CUDA hardware acceleration ---
        if self.gpu_pixel_conversion:
            if _check_ffmpeg_cuda_available():
                self._use_hwaccel = True
                logger.info("CUDA hardware acceleration enabled for %s", vcodec)
            else:
                logger.warning(
                    "GPU Pixel Conversion requested but ffmpeg was not compiled with CUDA support. "
                    "Disabling hardware acceleration."
                )
                self.gpu_pixel_conversion = False

    def _validate_cpu_preset(self, vcodec):
        """Validate that an NVENC-only preset isn't used with a CPU codec."""
        preset = self.output_params.get("-preset")
        nvenc_only_presets = {
            "p1",
            "p2",
            "p3",
            "p4",
            "p5",
            "p6",
            "p7",
            "llhp",
            "llhq",
            "lossless",
            "losslesshp",
        }
        if preset in nvenc_only_presets:
            logger.warning(
                f"'{preset}' is an NVENC preset and not supported for {vcodec}, defaulting to medium"
            )
            self.output_params["-preset"] = "medium"

    def _configure_svtav1(self, vcodec):
        """Configure libsvtav1-specific ffmpeg parameters.

        Maps text-based presets to SVT-AV1 numeric presets (0=slowest, 13=fastest).
        """
        if not _check_ffmpeg_encoder_available("libsvtav1"):
            logger.warning(
                "libsvtav1 encoder not found in ffmpeg build; encoding may fail"
            )

        preset = self.output_params.get("-preset")
        text_to_numeric = {
            "ultrafast": "12",
            "veryfast": "10",
            "fast": "8",
            "medium": "5",
            "slow": "3",
            "slower": "1",
            "veryslow": "0",
            # NVENC presets mapped to reasonable SVT-AV1 equivalents
            "p1": "12",
            "p2": "10",
            "p3": "8",
            "p4": "5",
            "p5": "3",
            "p6": "1",
            "p7": "0",
        }
        if preset in text_to_numeric:
            mapped = text_to_numeric[preset]
            logger.info(f"Mapping preset '{preset}' to SVT-AV1 numeric preset {mapped}")
            self.output_params["-preset"] = mapped
        elif preset is not None:
            try:
                val = int(preset)
                if not (0 <= val <= 13):
                    logger.warning(
                        f"SVT-AV1 preset {val} out of range (0-13), defaulting to 5"
                    )
                    self.output_params["-preset"] = "5"
            except ValueError:
                logger.warning(
                    f"Unknown preset '{preset}' for libsvtav1, defaulting to 5"
                )
                self.output_params["-preset"] = "5"

    def process(self, frame, metadata):
        """Write a frame to the video file, starting the ffmpeg subprocess on the first frame."""
        logger.debug(
            "VideoWriter.process: frame_index=%s, shape=%s",
            metadata.get("Frame Index", "?"),
            frame.shape,
        )
        try:
            self.writer.write_frame(frame)
        except Exception as err:
            logger.error(
                "VideoWriter.write_frame failed: frame_index=%s, frame_shape=%s, error=%s",
                metadata.get("Frame Index", "?"),
                frame.shape,
                err,
            )
            raise

        if self.write_frame_index:
            try:
                fi = metadata["Frame Index"] - 1
                self.frameindex_file.write(fi.to_bytes(4, byteorder="little"))
                self.timestamps_file.write(
                    str(metadata["Timestamp"].timestamp()) + "\n"
                )
            except Exception as err:
                logger.error(
                    "VideoWriter failed writing frame index/timestamp: frame_index=%s, error=%s",
                    metadata.get("Frame Index", "?"),
                    err,
                )
                raise

        return frame, metadata

    def close(self):
        """Flush remaining frames and close the ffmpeg subprocess."""
        if self.write_frame_index:
            self.frameindex_file.close()
            self.timestamps_file.close()
        logger.info("Video writer closed")
        self.active = False
        self.writer.close()


import subprocess as sp
import threading
import queue
import time
from collections import deque
from shutil import which  # noqa: F401 — used as mock target by tests


class FFMPEG_Writer:
    """Write frames using ffmpeg as backend

    Uses an internal bounded queue and dedicated writer thread to decouple
    frame encoding from the caller, preventing blocking I/O from stalling
    the plugin pipeline.

    :param filename: path to write video file to
    :param input_dict: dictionary of input parameters to interpret data from Python
    :param output_dict: dictionary of output parameters to encode data to disk
    :param buffer_size: max frames to buffer before backpressure (default 120 ~4s at 30fps)
    :param gpu_pixel_conversion: if True, use hwupload_cuda filter for GPU-side format conversion
    """

    def __init__(
        self,
        file_path,
        input_dict={},
        output_dict={},
        verbosity=0,
        buffer_size=120,
        gpu_pixel_conversion=False,
        use_hwaccel=False,
    ):
        """Initialize an ffmpeg pipe-based video writer.

        :param file_path: Output video file path.
        :param vcodec: Video codec name.
        :param fps: Target frame rate.
        """

        self.file_path = os.path.abspath(os.path.normpath(file_path))
        dir_path = os.path.dirname(self.file_path)

        # Check for write permissions
        if not os.access(dir_path, os.W_OK):
            logger.error("Cannot write to directory: " + dir_path)

        self.input_dict = input_dict
        self.output_dict = output_dict
        self.verbosity = verbosity
        self.initialized = False
        self.gpu_pixel_conversion = gpu_pixel_conversion
        self.use_hwaccel = use_hwaccel

        self._FFMPEG_PATH = _which("ffmpeg")

        # Fallback: on Windows/conda, ffmpeg lives in the env's Library/bin
        # which is not always on PATH when launched from a GUI shortcut.
        if self._FFMPEG_PATH is None:
            import sys

            _candidate = os.path.join(sys.prefix, "Library", "bin", "ffmpeg.exe")
            if os.path.isfile(_candidate):
                self._FFMPEG_PATH = _candidate
                logger.info("Found ffmpeg via conda env fallback: %s", _candidate)

        if self._FFMPEG_PATH is None:
            raise IOError("Could not find ffmpeg executable in the environment PATH.")

        self._write_queue = queue.Queue(maxsize=buffer_size)
        self._write_thread = None
        self._write_error = None
        self._stderr_thread = None
        self._stderr_lines = deque(maxlen=50)
        self._proc = None
        self._frame_count = 0

    def _stderr_drain(self):
        """Drain stderr into a bounded buffer to prevent pipe deadlock."""
        try:
            for line in self._proc.stderr:
                text = line.decode("utf-8", errors="replace").rstrip()
                self._stderr_lines.append(text)
                if text:
                    logger.debug("ffmpeg stderr: %s", text)
        except Exception:
            pass

    def _get_stderr_output(self):
        """Return captured stderr lines as a single string."""
        return "\n".join(self._stderr_lines)

    def _write_loop(self):
        """Dedicated thread that drains the write queue to FFMPEG stdin."""
        try:
            while True:
                data = self._write_queue.get()
                if data is None:  # Sentinel: shutdown
                    break
                try:
                    # Write numpy buffer directly via memoryview — zero-copy to pipe
                    self._proc.stdin.write(memoryview(data))
                except IOError as err:
                    stderr_msg = self._get_stderr_output()
                    if stderr_msg:
                        self._write_error = IOError(
                            f"{err}\nFFMPEG stderr:\n{stderr_msg}"
                        )
                    else:
                        self._write_error = err
                    break
        except Exception as err:
            self._write_error = err

    def start_process(self, H, W, C):
        """Launch the ffmpeg subprocess with the configured codec and resolution."""
        self.initialized = True

        if "-s" not in self.input_dict:
            self.input_dict["-s"] = str(W) + "x" + str(H)

        if "-pix_fmt" not in self.input_dict:
            if C == 1:
                self.input_dict["-pix_fmt"] = "gray"
            elif C == 2:
                self.input_dict["-pix_fmt"] = "ya8"
            elif C == 3:
                self.input_dict["-pix_fmt"] = "rgb24"
            elif C == 4:
                self.input_dict["-pix_fmt"] = "rgba"

        in_args = []
        for key, value in self.input_dict.items():
            in_args.append(key)
            in_args.append(value)

        out_args = []
        for key, value in self.output_dict.items():
            out_args.append(key)
            out_args.append(value)

        # GPU-side pixel format conversion via hwupload_cuda filter
        vcodec = self.output_dict.get("-vcodec", "")
        if self.gpu_pixel_conversion and vcodec in _NVENC_CODECS:
            pix_fmt = self.output_dict.get("-pix_fmt", "yuv420p")
            out_args = ["-vf", f"format={pix_fmt},hwupload_cuda"] + out_args

        # CUDA hardware acceleration: add hwaccel flags before input
        hwaccel_args = []
        if self.use_hwaccel:
            hwaccel_args = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
            logger.info("Adding CUDA hwaccel flags to ffmpeg command")

        cmd = (
            [self._FFMPEG_PATH, "-y", "-f", "rawvideo"]
            + hwaccel_args
            + in_args
            + ["-i", "-", "-an", "-threads", "0"]
            + out_args
            + [self.file_path]
        )

        self._cmd = " ".join(cmd)

        # Use 2MB pipe buffer when hwaccel is active (larger frames benefit),
        # otherwise 1MB
        pipe_bufsize = 2 * 1024 * 1024 if self.use_hwaccel else 1024 * 1024

        if self.verbosity >= 2:
            logger.info(cmd)
            self._proc = sp.Popen(
                cmd, stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE, bufsize=pipe_bufsize
            )
        elif self.verbosity == 1:
            cmd += ["-v", "warning"]
            logger.info(cmd)
            self._proc = sp.Popen(
                cmd, stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE, bufsize=pipe_bufsize
            )
        else:
            cmd += ["-v", "error"]
            self._proc = sp.Popen(
                cmd,
                stdin=sp.PIPE,
                stdout=sp.DEVNULL,
                stderr=sp.PIPE,
                bufsize=pipe_bufsize,
            )

        # Drain stderr in a background thread to prevent pipe buffer deadlock
        self._stderr_thread = threading.Thread(target=self._stderr_drain, daemon=True)
        self._stderr_thread.start()

        self._write_thread = threading.Thread(target=self._write_loop, daemon=True)
        self._write_thread.start()

        # Brief check: if ffmpeg exits immediately (e.g. missing codec),
        # raise now with the actual error instead of a cryptic broken pipe later.
        time.sleep(0.05)
        if self._proc.poll() is not None:
            # Give stderr drain thread a moment to capture output
            self._stderr_thread.join(timeout=1)
            stderr_output = self._get_stderr_output()
            raise IOError(
                f"ffmpeg exited immediately (code {self._proc.returncode}): "
                f"{stderr_output}\n\nFFMPEG COMMAND: {self._cmd}"
            )

    def write_frame(self, img_array):
        """Writes one frame to the file."""

        H, W, C = img_array.shape

        if not self.initialized:
            logger.info(
                "FFMPEG_Writer starting: frame_shape=(%d,%d,%d), file=%s",
                H,
                W,
                C,
                self.file_path,
            )
            self.start_process(H, W, C)
            self._frame_count = 0

        if self._write_error is not None:
            stderr_output = self._get_stderr_output()
            msg = f"{str(self._write_error)}\n\n FFMPEG COMMAND:{self._cmd}\n"
            if stderr_output:
                msg += f"\nFFMPEG stderr:\n{stderr_output}\n"
            raise IOError(msg)

        # Ensure uint8 C-contiguous layout; no-copy when already correct
        img_array = np.ascontiguousarray(img_array, dtype=np.uint8)

        # Enqueue numpy array directly; byte serialization deferred to writer thread
        self._write_queue.put(img_array)

        self._frame_count += 1
        if self._frame_count % 1000 == 0:
            qsize = self._write_queue.qsize()
            proc_alive = self._proc.poll() is None if self._proc else False
            logger.debug(
                "FFMPEG_Writer health: frames_written=%d, queue_depth=%d, "
                "proc_alive=%s, file=%s",
                self._frame_count,
                qsize,
                proc_alive,
                self.file_path,
            )

    def close(self):
        """Closes the writer, flushing all buffered frames before terminating."""
        if self._write_thread is not None and self._write_thread.is_alive():
            self._write_queue.put(None)  # Sentinel to stop write loop
            self._write_thread.join(timeout=30)

        if self._proc is None or self._proc.poll() is not None:
            if self._stderr_thread is not None:
                self._stderr_thread.join(timeout=5)
            return

        if self._proc.stdin:
            self._proc.stdin.close()

        self._proc.wait()

        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=5)

        self._proc = None
