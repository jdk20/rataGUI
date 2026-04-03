from rataGUI.plugins.base_plugin import BasePlugin
from rataGUI.utils import slugify

import os
import csv
import cv2
import numpy as np
from datetime import datetime

import logging

logger = logging.getLogger(__name__)

try:
    import tensorflow as tf
except ImportError:
    logger.error("Unable to import tensorflow. Check installation process")


class SleapInference(BasePlugin):
    """
    Plugin that inferences on frames using trained SLEAP model to predict animal pose and write keypoints as metadata
    """

    DEFAULT_CONFIG = {
        "Model directory": "",
        "Save file (.csv)": "data",
        "Inference FPS": ["Match Camera", "Every Interval"],
        "Fixed Interval": 0,
        "Score Threshold": 0.5,
        "Kalman Filter": {"Disabled": False, "Enabled": True},
        "Draw on frame": {"Enabled": True, "Disabled": False},
        "Write to file": {"Disabled": False, "Enabled": True},
        "Publish to socket": {"Disabled": False, "Enabled": True},
    }

    def __init__(self, cam_widget, config, queue_size=0):
        """Initialize the SLEAP inference plugin, loading the frozen TF model."""
        super().__init__(cam_widget, config, queue_size)
        self.model_dir = os.path.normpath(config.get("Model directory"))

        try:
            self.model = load_frozen_model(self.model_dir)
            self.model_input = self.model.inputs[0]

            # Warm start to load cuDNN
            input_shape = self.model_input.shape.as_list()
            input_shape[0] = 1  # Batch size
            dummy_frame = tf.zeros(input_shape, self.model_input.dtype)
            self.model(tf.constant(dummy_frame))

            self.batch_size = input_shape[0]
            self.input_height = input_shape[1]
            self.input_width = input_shape[2]
            self.num_channels = input_shape[3]
        except Exception as err:
            logger.exception(err)
            logger.info("Unable to load model ... auto-disabling SLEAP plugin")
            self.active = False

        self.interval = 0
        self.poses = []

        self.save_file = None
        self.csv_writer = None
        if config.get("Write to file"):
            file_name = slugify(config.get("Save file (.csv)"))
            if len(file_name) == 0:  # Use default file name
                file_name = (
                    slugify(cam_widget.camera.getDisplayName())
                    + "_DLCInference_"
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

    def process(self, frame, metadata):
        """Run SLEAP pose estimation on the frame. Returns (frame, metadata)."""
        img_h, img_w, num_ch = frame.shape
        self.interval -= 1

        if self.interval <= 0:
            image = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            image = cv2.resize(
                image, (self.input_width, self.input_height)
            )  # resize uses reverse order
            image = np.reshape(image, (-1, self.input_height, self.input_width, 1))
            prediction = self.model(
                x=tf.constant(image, dtype=self.model_input.dtype)
            )  # outputs list of tensors

            # new list of lists (instances) of tuples (points) with format ((h,w), score)
            self.poses = []

            for points, scores in zip(
                prediction[1].numpy()[0], prediction[0].numpy()[0]
            ):
                pose = []
                for point, score in zip(points, scores):
                    w_pos, h_pos = point
                    resized_h = h_pos * (img_h / self.input_height)
                    resized_w = w_pos * (img_w / self.input_width)
                    pose.append(((resized_h, resized_w), score))

                self.poses.append(pose)

            fps_mode = self.config.get("Inference FPS")
            if fps_mode == "Match Camera":
                self.interval = self.in_queue.qsize()
                self.blocking = True
            else:
                self.interval = self.config.get("Fixed Interval")
                self.blocking = False

        if self.config.get("Draw on frame"):
            threshold = self.config.get("Score Threshold")
            for num, pose in enumerate(self.poses):
                color = [0, 0, 0]
                color[num % 3] = 255

                for point, score in pose:
                    h_pos, w_pos = point
                    if not (np.isnan(h_pos) or np.isnan(w_pos)) and score >= threshold:
                        frame = cv2.circle(
                            frame, (round(w_pos), round(h_pos)), 5, color, -1
                        )

        metadata["SLEAP Poses"] = self.poses

        return frame, metadata

    def close(self):
        """Deactivate SLEAP inference and close the CSV writer if open."""
        logger.info("Sleap Inference closed")
        self.active = False

        if self.save_file is not None:
            self.save_file.close()


import json
import re


def load_frozen_model(model_dir):
    """Load a frozen TensorFlow graph from the given model directory. Returns a TF session."""
    # Load frozen graph using TensorFlow 1.x functions
    model_file = [file for file in os.listdir(model_dir) if file.endswith(".pb")]
    if len(model_file) > 1:
        raise IOError(
            "Multiple model files found. Model folder should only contain one .pb file"
        )
    elif len(model_file) == 0:
        raise IOError("Could not find frozen model (.pb) file in specified folder")
    else:
        model_file = model_file[0]

    with tf.io.gfile.GFile(os.path.join(model_dir, model_file), "rb") as f:
        graph_def = tf.compat.v1.GraphDef()
        graph_def.ParseFromString(f.read())

    def _imports_graph_def():
        tf.compat.v1.import_graph_def(graph_def, name="")

    wrapped_import = tf.compat.v1.wrap_function(_imports_graph_def, [])
    import_graph = wrapped_import.graph

    with open(os.path.join(model_dir, "info.json"), "r") as file:
        model_info = json.load(file)
        inputs = re.findall('"([^"]*)"', str(model_info["frozen_model_inputs"]))
        outputs = re.findall('"([^"]*)"', str(model_info["frozen_model_outputs"]))

    model = wrapped_import.prune(
        tf.nest.map_structure(import_graph.as_graph_element, inputs),
        tf.nest.map_structure(import_graph.as_graph_element, outputs),
    )

    return model
