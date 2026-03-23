from rataGUI.plugins.base_plugin import BasePlugin
from rataGUI.utils import slugify
from rataGUI import launch_config
from pathlib import Path

import os
import numpy as np
from datetime import datetime

import logging

logger = logging.getLogger(__name__)


class VideoWriter(BasePlugin):
    """
    Plugin that writes frames to video file using FFMPEG

    :param vcodec: Video codec used by ffmpeg binary
    """

    DEFAULT_CONFIG = {
        "Save directory": "",  # Defaults to camera widget's save directory
        "filename suffix": "",
        "vcodec": ["libx264", "libx265", "h264_nvenc", "hevc_nvenc", "rawvideo"],
        "framerate": 30,
        "speed (preset)": [
            "fast",
            "veryfast",
            "ultrafast",
            "medium",
            "slow",
            "slower",
            "veryslow",
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
    }

    DISPLAY_CONFIG_MAP = {
        "speed (preset)": "preset",
        "quality (0-51)": "crf",
        "pixel format": "pix_fmt",
    }

    def __init__(self, cam_widget, config, queue_size=0):
        super().__init__(cam_widget, config, queue_size)
        self.blocking = True
        self.independent = True
        self.input_params = {}
        self.output_params = {}

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
            elif prop_name == "filename suffix":
                self.file_name = slugify(cam_widget.camera.getDisplayName())
                if len(value)>0:
                    self.file_name += "_" + slugify(value)
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
        vcodec = self.output_params.get("-vcodec")
        if vcodec in ["rawvideo"]:
            extension = ".raw"
        elif vcodec in ['h264_nvenc', 'hevc_nvenc']:
            # Handle unsupported preset for nvidia codecs
            preset = self.output_params.get("-preset")
            if preset not in ['slow', 'medium', 'fast', 'llhp', 'llhq']:
                logger.warning(f"{preset} preset is not supported for vcodec {vcodec} ... defaulting to medium")
                config.set("speed (preset)", 'medium')
                self.config["speed (preset)"] = 'medium'
                self.output_params["-preset"] = 'medium'
                
            # self.output_params['-cq'] = self.output_params.pop('-crf')

        try:
            if os.access(self.save_dir, os.W_OK):
                fld_name = datetime.now().strftime("video_%Y_%m_%d_%H_%M_%S")
                self.save_dir = os.path.join(self.save_dir, fld_name)
                os.makedirs(self.save_dir, exist_ok=True)
                if self.write_frame_index:
                    self.frameindex_file = open(os.path.join(self.save_dir, f"frameindex_{self.file_name}"), "wb")
                    self.timestamps_file = open(os.path.join(self.save_dir, f"timestamps_{self.file_name}.txt"), "w")
            else:
                raise OSError(
                    "Inaccessible save directory ... auto-disabling Video Writer plugin"
                )
        except Exception as err:
            logger.exception(err)
            self.active = False

        self.file_path = os.path.join(self.save_dir, self.file_name + extension)
        # count = 0
        # while os.path.exists(self.file_path):  # file already exists -> add copy
        #     count += 1
        #     self.file_path = os.path.join(
        #         self.save_dir, self.file_name + f" ({count})" + extension
        #     )

        self.writer = FFMPEG_Writer(
            str(self.file_path),
            input_dict=self.input_params,
            output_dict=self.output_params,
            verbosity=0,
        )

    def process(self, frame, metadata):
        self.writer.write_frame(frame)
        if self.write_frame_index:
            fi = metadata['Frame Index'] - 1
            self.frameindex_file.write(fi.to_bytes(4, byteorder="little"))
            self.timestamps_file.write(str(metadata["Timestamp"].timestamp()) + '\n')
        return frame, metadata

    def close(self):
        if self.write_frame_index:
            self.frameindex_file.close()
            self.timestamps_file.close()
        logger.info("Video writer closed")
        self.active = False
        self.writer.close()


import subprocess as sp
import threading
import queue
from shutil import which


class FFMPEG_Writer:
    """Write frames using ffmpeg as backend

    Uses an internal bounded queue and dedicated writer thread to decouple
    frame encoding from the caller, preventing blocking I/O from stalling
    the plugin pipeline.

    :param filename: path to write video file to
    :param input_dict: dictionary of input parameters to interpret data from Python
    :param output_dict: dictionary of output parameters to encode data to disk
    :param buffer_size: max frames to buffer before backpressure (default 120 ~4s at 30fps)
    """

    def __init__(self, file_path, input_dict={}, output_dict={}, verbosity=0, buffer_size=120):

        self.file_path = os.path.abspath(os.path.normpath(file_path))
        dir_path = os.path.dirname(self.file_path)

        # Check for write permissions
        if not os.access(dir_path, os.W_OK):
            logger.error("Cannot write to directory: " + dir_path)

        self.input_dict = input_dict
        self.output_dict = output_dict
        self.verbosity = verbosity
        self.initialized = False

        self._FFMPEG_PATH = which("ffmpeg")

        if self._FFMPEG_PATH is None:
            raise IOError("Could not find ffmpeg executable in the environment PATH.")

        self._write_queue = queue.Queue(maxsize=buffer_size)
        self._write_thread = None
        self._write_error = None

    def _write_loop(self):
        """Dedicated thread that drains the write queue to FFMPEG stdin."""
        try:
            while True:
                data = self._write_queue.get()
                if data is None:  # Sentinel: shutdown
                    break
                try:
                    self._proc.stdin.write(data)
                except IOError as err:
                    self._write_error = err
                    break
        except Exception as err:
            self._write_error = err

    def start_process(self, H, W, C):
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

        # Explicitly replaces VBR with CBR when using a GPU encoder
        """
        vcodec = self.output_dict['-vcodec']
        if vcodec in ['h264_nvenc', 'hevc_nvenc']:
            out_args.append('-rc')
            out_args.append('cbr_hq')
            out_args.append('-b:v')
            out_args.append('8M')
        """

        cmd = [self._FFMPEG_PATH, "-y", "-f", "rawvideo"] + in_args + ["-i", "-", '-an'] + out_args + [self.file_path]

        self._cmd = " ".join(cmd)

        if self.verbosity >= 2:
            logger.info(cmd)
            self._proc = sp.Popen(cmd, stdin=sp.PIPE, stdout=sp.PIPE, stderr=None)
        elif self.verbosity == 1:
            cmd += ["-v", "warning"]
            logger.info(cmd)
            self._proc = sp.Popen(cmd, stdin=sp.PIPE, stdout=sp.PIPE, stderr=None)
        else:
            self._proc = sp.Popen(
                cmd, stdin=sp.PIPE, stdout=sp.DEVNULL, stderr=sp.STDOUT
            )

        self._write_thread = threading.Thread(target=self._write_loop, daemon=True)
        self._write_thread.start()

    def write_frame(self, img_array):
        """Writes one frame to the file."""

        H, W, C = img_array.shape

        if not self.initialized:
            self.start_process(H, W, C)

        if self._write_error is not None:
            msg = f"{str(self._write_error)}\n\n FFMPEG COMMAND:{self._cmd}\n"
            raise IOError(msg)

        img_array = img_array.astype(np.uint8)

        # Enqueue frame bytes; blocks if buffer is full (backpressure)
        self._write_queue.put(img_array.tobytes())

    def close(self):
        """Closes the writer, flushing all buffered frames before terminating."""
        if self._write_thread is not None and self._write_thread.is_alive():
            self._write_queue.put(None)  # Sentinel to stop write loop
            self._write_thread.join(timeout=30)

        if self._proc is None or self._proc.poll() is not None:
            return

        if self._proc.stdin:
            self._proc.stdin.close()
        if self._proc.stderr:
            self._proc.stderr.close()

        self._proc.wait()
        self._proc = None
