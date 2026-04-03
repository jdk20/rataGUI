from rataGUI.plugins.base_plugin import BasePlugin
import numpy as np
import cv2 as cv
from scipy.io import loadmat
import os

import logging

logger = logging.getLogger(__name__)


class Undistort(BasePlugin):
    """Plugin that removes lens distortion using camera calibration parameters."""

    def __init__(self, cam_widget, config, queue_size=0):
        """Initialize the undistort plugin, computing rectification maps from calibration data."""
        super().__init__(cam_widget, config, queue_size)
        logger.debug(str(BasePlugin.modules.keys()))

        try:
            param_file = os.path.normpath(
                os.path.abspath(cam_widget.camera_config.get("Camera Parameters File"))
            )

            f = loadmat(param_file)
            cam_mtx = f["K"].squeeze()
            rad = f["RadialDistortion"].squeeze()
            tan = f["TangentialDistortion"].squeeze()
            h, w = f["ImageSize"].squeeze()
            logger.debug(str((w, h)))

            dist_coeffs = np.concatenate((rad[:2], tan))
            if rad.size == 3:
                dist_coeffs = np.append(dist_coeffs, rad[-1])
            # initUndistortRectifyMap precomputes per-pixel (x,y) lookup maps so that
            # remap() can warp each frame in a single pass without recomputing the
            # distortion model every time.
            self.map1, self.map2 = cv.initUndistortRectifyMap(
                cam_mtx, dist_coeffs, None, cam_mtx, (w, h), cv.CV_32FC1
            )

        except Exception as err:
            logger.exception(err)
            logger.debug(
                "Unable to load Parameters File ... auto-disabling Undistort plugin"
            )
            self.active = False

    def process(self, frame, metadata):
        """Apply lens undistortion to the frame using precomputed maps. Returns (frame, metadata)."""
        frame = cv.remap(frame, self.map1, self.map2, cv.INTER_LINEAR)
        metadata["Undistorted"] = True
        return frame, metadata
