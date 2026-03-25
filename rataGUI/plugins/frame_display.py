from rataGUI.plugins.base_plugin import BasePlugin

from PyQt6 import QtGui
from PyQt6.QtCore import Qt, QObject, pyqtSignal

import cv2
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
        try:
            self.interval = max(0, self.interval - 1)
            if self.interval == 0:
                img_h, img_w, num_ch = frame.shape
                target_w, target_h = self.frame_width, self.frame_height

                # Downscale with cv2 before creating QImage — faster than Qt scaling
                # and produces a smaller QImage, reducing memory and QPixmap conversion cost
                if img_w != target_w or img_h != target_h:
                    if self.config.get("Aspect ratio"):
                        scale = min(target_w / img_w, target_h / img_h)
                        new_w = int(img_w * scale)
                        new_h = int(img_h * scale)
                    else:
                        new_w, new_h = target_w, target_h
                    frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                    img_h, img_w, num_ch = frame.shape

                bytes_per_line = num_ch * img_w
                # Deep copy so QImage owns its pixel data independently of the
                # numpy buffer.  Without .copy() the QImage holds a raw pointer
                # that can dangle when the ring-buffer slot is released or the
                # numpy array is garbage-collected before the Qt main thread
                # processes the queued signal — causing a use-after-free crash.
                qt_image = QtGui.QImage(
                    frame.data, img_w, img_h, bytes_per_line, QtGui.QImage.Format.Format_RGB888
                ).copy()

                logger.debug(
                    "FrameDisplay emitting QImage: %dx%d (%d bytes/line)",
                    img_w, img_h, bytes_per_line,
                )
                self.signal.image.emit(qt_image)
                self.interval = self.config.get("Fixed Interval")
        except Exception as err:
            logger.error(
                "FrameDisplay.process failed: frame_shape=%s, error=%s",
                frame.shape if frame is not None else None, err,
            )
            raise

        return frame, metadata

    def close(self):
        logger.info("Frame display closed")
        self.active = False
