from rataGUI.cameras.BaseCamera import BaseCamera

import os
import cv2

import logging

logger = logging.getLogger(__name__)


class VideoReader(BaseCamera):
    """Video file reader that replays recorded video as a camera source."""

    DEFAULT_PROPS = {
        "File path": "",
    }

    @staticmethod
    def getAvailableCameras():
        """Return a list containing a single default VideoReader instance."""
        return [VideoReader(f"Video Reader {i + 1}") for i in range(1)]

    def __init__(self, readerID):
        """Initialize a VideoReader with a reader identifier."""
        super().__init__(readerID)
        self.last_frame = None
        self.file_path = ""

    def initializeCamera(self, prop_config, plugin_names=[]):
        """Open the video file specified in the config. Returns True on success."""
        self.input_params = {}
        self.output_params = {}
        for prop_name, value in prop_config.as_dict().items():
            if prop_name == "File path":
                self.file_path = os.path.normpath(value)

        cap = cv2.VideoCapture(self.file_path)
        if cap.isOpened():
            self._running = True
            self._stream = cap
            return True
        else:
            self._running = False
            cap.release()
            return False

    def readCamera(self, colorspace="RGB"):
        """Read the next frame from the video file. Returns (success, frame)."""
        ret, frame = self._stream.read()
        if ret:
            self.frames_acquired += 1
            if colorspace == "RGB":
                self.last_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            elif colorspace == "GRAY":
                self.last_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                self.last_frame = frame

        return ret, self.last_frame

    def closeCamera(self):
        """Release the video file capture."""
        if self._stream is not None:
            self._stream.release()

        self._running = False
