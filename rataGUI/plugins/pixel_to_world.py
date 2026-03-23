from rataGUI.plugins.base_plugin import BasePlugin
from rataGUI.utils import slugify

import datetime
import os
import numpy as np
from scipy.io import loadmat
import csv
import cv2 as cv

import logging

logger = logging.getLogger(__name__)


class Pixel2World(BasePlugin):

    DEFAULT_CONFIG = {
        "Calibration Validation Mode": {"Disabled": False, "Enabled": True},
        "# of Columns": 10,
        "# of Rows": 9,
        "Publish to socket": {"Disabled": False, "Enabled": True},
        "Write to file": {"Disabled": False, "Enabled": True},
        "Save file (.csv)": "data",
    }

    def __init__(self, cam_widget, config, queue_size=0):
        super().__init__(cam_widget, config, queue_size)

        try:
            param_file = os.path.normpath(
                os.path.abspath(cam_widget.camera_config.get("Camera Parameters File"))
            )

            f = loadmat(param_file)
            self.cam_mtx = f["K"].squeeze()
            rad = f["RadialDistortion"].squeeze()
            tan = f["TangentialDistortion"].squeeze()
            tform = f["tform"].squeeze()

            self.dist_coeffs = np.concatenate((rad[:2], tan))
            if rad.size == 3:
                self.dist_coeffs = np.append(self.dist_coeffs, rad[-1])
            tform_sub = np.concatenate((tform[:3, :2], tform[:3, -1, None]), axis=1)
            self.inv_map = np.linalg.inv(self.cam_mtx @ tform_sub)

        except Exception as err:
            logger.exception(err)
            logger.debug(
                "Unable to load Parameters File ... auto-disabling Pixel2World plugin"
            )
            self.active = False

        # these are copied from the DLCInference plugin
        self.save_file = None
        self.csv_writer = None
        if config.get("Write to file"):
            file_name = slugify(config.get("Save file (.csv)"))
            if len(file_name) == 0:  # Use default file name
                file_name = (
                    slugify(cam_widget.camera.getDisplayName())
                    + "_DLCInference_Real_World_Coords_"
                    + datetime.now().strftime("%H-%M-%S")
                    + ".csv"
                )
            elif not file_name.endswith(".csv"):
                file_name += ".csv"

            self.file_path = os.path.join(cam_widget.save_dir, file_name)
            self.save_file = open(self.file_path, "w")

            self.csv_writer = csv.writer(self.save_file)

        self.socket_trigger = None
        if config.get("Publish to socket"):
            triggers = []
            for trigger in cam_widget.triggers:
                if type(trigger).__name__ == "UDPSocket":
                    triggers.append(trigger)
            if len(triggers) > 1:
                pass
            elif len(triggers) == 1:
                self.socket_trigger = triggers[0]
            else:
                logger.error("Unable to find enabled socket trigger")

        self.validate = config.get("Calibration Validation Mode")
        self.ncols = config.get("# of Columns")
        self.nrows = config.get("# of Rows")

    def process(self, frame, metadata):
        undistorted = metadata.get("Undistorted")
        _poses = metadata.get("DLC Poses")

        if not self.validate:
            if _poses:
                coords = [np.array([(x, y) for (y, x), _ in pose]) for pose in _poses]
                confs = [np.array([conf for _, conf in pose]) for pose in _poses]

                if not undistorted:
                    coords = [
                        cv.undistortImagePoints(
                            i, self.cam_mtx, self.dist_coeffs
                        ).squeeze()
                        for i in coords
                    ]

                poses = []
                for pose_coords, pose_confs in zip(coords, confs):
                    poses.append(
                        [
                            ((y, x), c)
                            for (x, y), c in zip(
                                self.pixel_to_world(pose_coords), pose_confs
                            )
                        ]
                    )
                if self.csv_writer:
                    self.csv_writer.writerow(poses)
                if self.socket_trigger:
                    self.socket_trigger.execute(str(poses))
                metadata["Real World Coordinates"] = poses
            else:
                logger.debug("No DLC Poses found. auto-disabling")
                self.active = False

        else:
            gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
            ret, corners = cv.findChessboardCorners(
                gray, (self.ncols, self.nrows), flags=cv.CALIB_CB_FAST_CHECK
            )
            if ret:
                frame = cv.drawChessboardCorners(
                    frame, (self.ncols, self.nrows), corners, ret
                )
                corners = corners.squeeze()
                if not undistorted:
                    corners = cv.undistortImagePoints(
                        corners, self.cam_mtx, self.dist_coeffs
                    ).squeeze()
                corners = self.pixel_to_world(corners)[None, :, :].reshape(
                    self.nrows, self.ncols, 2
                )
                x_dist = (
                    np.abs(corners[:, 1:] - corners[:, :-1])
                    .reshape(-1, 2)
                    .mean(axis=0)
                    .max()
                )
                y_dist = (
                    np.abs(corners[1:] - corners[:-1]).reshape(-1, 2).mean(axis=0).max()
                )
                logger.info(f"mean x distance: {x_dist}; mean y distance {y_dist}")

        return frame, metadata

    def pixel_to_world(self, points):
        _points = np.concatenate((points, np.ones((points.shape[0], 1))), axis=1)
        world = (self.inv_map @ _points.T).T
        world = world[:, :2] / world[:, -1, None]
        return world

    def close(self):
        logger.info("Pixel to world mapper closed")
        if self.save_file:
            self.save_file.close()
        self.active = False
