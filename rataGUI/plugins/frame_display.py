from rataGUI.plugins.base_plugin import BasePlugin

from PyQt6 import QtGui
from PyQt6.QtCore import Qt, QObject, pyqtSignal

import logging

logger = logging.getLogger(__name__)


class DisplaySignal(QObject):
    image = pyqtSignal(QtGui.QImage)


class FrameDisplay(BasePlugin):
    """
    Plugin that displays frames in a separate window.

    :param aspect_ratio: Whether to maintain frame aspect ratio or force into frame
    """

    DEFAULT_CONFIG = {
        "Frame width": 960,
        "Frame height": 720,
        "Aspect ratio": {"Keep": True, "Ignore": False},
        "Fixed Interval": 0,
    }

    def __init__(self, cam_widget, config, queue_size=3):
        super().__init__(cam_widget, config, queue_size)
        self.independent = True
        self.drop_policy = "drop_oldest"

        self.frame_width = config.get("Frame width")
        self.frame_height = config.get("Frame height")
        self.interval = config.get("Fixed Interval")
        cam_widget.resize(self.frame_width, self.frame_height)

        self.signal = DisplaySignal()
        self.signal.image.connect(cam_widget.set_window_pixmap)

    def process(self, frame, metadata):
        """Sets pixmap image to video frame"""
        # Get image dimensions
        self.interval = max(0,self.interval-1)
        if self.interval == 0:
            img_h, img_w, num_ch = frame.shape

            # Convert to pixmap and set to video frame
            bytes_per_line = num_ch * img_w
            qt_image = QtGui.QImage(
                frame.data, img_w, img_h, bytes_per_line, QtGui.QImage.Format.Format_RGB888
            )
            if self.config.get("Aspect ratio"):
                qt_image = qt_image.scaled(
                    self.frame_width, self.frame_height, Qt.AspectRatioMode.KeepAspectRatio
                )
            else:
                qt_image = qt_image.scaled(
                    self.frame_width,
                    self.frame_height,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                )

            self.signal.image.emit(qt_image)
            self.interval = self.config.get("Fixed Interval")

        return frame, metadata

    def close(self):
        logger.info("Frame display closed")
        self.active = False
