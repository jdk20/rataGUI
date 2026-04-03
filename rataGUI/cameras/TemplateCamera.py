from rataGUI.cameras.BaseCamera import BaseCamera

import cv2

import logging

logger = logging.getLogger(__name__)


class TemplateCamera(BaseCamera):
    """
    Example subclass to overwrite with the required functionality for a custom camera model
    """

    DEFAULT_PROPS = {
        # TODO: Put user-configurable properties here (see other camera models for examples)
    }

    @staticmethod
    def getAvailableCameras():
        """Return a list of available template cameras (override in subclass)."""
        # TODO: Return list of camera objects wrapping every available device
        return []

    def __init__(self, cameraID):
        """Initialize a TemplateCamera with the given camera ID."""
        super().__init__(cameraID)
        self.last_frame = None

    def initializeCamera(self, prop_config, plugin_names=[]):
        """Initialize camera hardware and return True on success."""
        cap = cv2.VideoCapture(self.cameraID)
        if cap.isOpened():
            self._running = True
            self._stream = cap
            return True
        else:
            self._running = False
            cap.release()
            return False

    def readCamera(self, colorspace="RGB"):
        """Read the next frame. Returns (success, frame)."""
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
        """Release camera resources."""
        if self._stream is not None:
            self._stream.release()

        self._running = False
