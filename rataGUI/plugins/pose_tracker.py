# from rataGUI.plugins.base_plugin import BasePlugin

# import os
# import numpy as np
# import cv2

# import tensorflow as tf
# from tensorflow.python.compiler.tensorrt import trt_convert as trt

# import logging
# logger = logging.getLogger(__name__)

# class DLCInference(BasePlugin):
#     """
#     Plugin that inferences on frames using trained DLC model to predict animal pose and write keypoints as metadata
#     """

#     DEFAULT_CONFIG = {
#         "Model directory": "",
#         "Model type": ["TensorRT", "TFLite", "Default"],
#         "Score Threshold": 0.5,
#         "Inference FPS": ["Match Camera", "Every Interval"],
#         "Fixed Interval": 0,
#         "Scale factor": 1.0,
#         "Draw keypoints": False,
#         # "Write to file": False, TODO
#         # Batch processing
#     }

#     def __init__(self, cam_widget, config, queue_size=0):
#         super().__init__(cam_widget, config, queue_size)
#         self.model_dir = os.path.normpath(config.get("Model directory"))

#         try:
#             self.model_type = config.get("Model type")

#             if self.model_type == "Default":
#                 self.model = load_frozen_model(self.model_dir)
#                 self.model_input = self.model.inputs[0]

#                 # Warm start to load cuDNN
#                 input_shape = self.model_input.shape.as_list()
#                 self.batch_size = 1
#                 self.input_height = input_shape[1]  # None
#                 self.input_width = input_shape[2]   # None
#                 self.num_channels = input_shape[3]  # 3 (no grayscale)

#                 dummy_frame = tf.zeros(shape=(self.batch_size, 1, 1, self.num_channels), dtype=self.model_input.dtype) # Arbitrary size
#                 # dummy_frame = tf.zeros(input_shape, self.model_input.dtype)
#                 self.model(tf.constant(dummy_frame))
#         except Exception as err:
#             logger.exception(err)
#             logger.debug("Unable to load model ... auto-disabling DLC Inference plugin")
#             self.active = False

#         self.interval = 0
#         self.poses = []

#     def process(self, frame, metadata):

#         self.interval -= 1
#         if self.interval <= 0:
#             scale = self.config.get("Scale factor")
#             if scale != 1.0:
#                 img_h, img_w, num_ch = frame.shape
#                 image = cv2.resize(frame, (int(img_w * scale), int(img_h * scale))) # resize uses reverse order
#                 image = np.expand_dims(image, axis=0)
#             else:
#                 image = np.expand_dims(frame, axis=0)

#             prediction = self.model(tf.constant(image, dtype=self.model_input.dtype))  # outputs list of tensors

#             # new list of lists (instances) of tuples (points) with format ((h,w), score)
#             self.poses = []

#             for instance in prediction:
#                 pose = []
#                 for point in instance.numpy():
#                     if scale != 1.0:
#                         resized = (point[0] / scale, point[1] / scale)
#                         pose.append((resized, point[2]))
#                     else:
#                         pose.append((point[:2], point[2]))

#                 self.poses.append(pose)

#             fps_mode = self.config.get("Inference FPS")
#             if fps_mode == "Match Camera":
#                 self.interval = self.in_queue.qsize()
#                 self.blocking = True
#             else:
#                 self.interval = self.config.get("Fixed Interval")
#                 self.blocking = False

#         if self.config.get("Draw keypoints"):
#             threshold = self.config.get("Score Threshold")
#             for num, pose in enumerate(self.poses):
#                 color = [0,0,0]
#                 color[num % 3] = 255

#                 for point, score in pose:
#                     h_pos, w_pos = point
#                     if not(np.isnan(h_pos) or np.isnan(w_pos)) and score >= threshold:
#                         frame = cv2.circle(frame, (round(w_pos), round(h_pos)), 5, color, -1)

#         metadata["DLC Poses"] = self.poses

#         return frame, metadata

#     def close(self):
#         logger.info("DLC Inference closed")
#         self.active = False


# def load_frozen_model(model_dir):
#     # Load frozen graph using TensorFlow 1.x functions
#     model_file = [file for file in os.listdir(model_dir) if file.endswith('.pb')]
#     if len(model_file) > 1:
#         raise IOError("Multiple model files found. Model folder should only contain one .pb file")
#     elif len(model_file) == 0:
#         raise IOError("Could not find frozen model (.pb) file in specified folder")
#     else:
#         model_file = model_file[0]

#     model_path = os.path.join(model_dir, model_file)
#     with tf.io.gfile.GFile(model_path, "rb") as f:
#         graph_def = tf.compat.v1.GraphDef()
#         graph_def.ParseFromString(f.read())

#     def _imports_graph_def():
#         tf.compat.v1.import_graph_def(graph_def, name="")

#     wrapped_import = tf.compat.v1.wrap_function(_imports_graph_def, [])
#     import_graph = wrapped_import.graph

#     graph_ops = import_graph.get_operations()

#     inputs = [graph_ops[0].name + ":0"]
#     if "concat_1" in graph_ops[-1].name:
#         outputs = [graph_ops[-1].name + ":0"]
#     else:
#         outputs = [graph_ops[-1].name + ":0", graph_ops[-2].name + ":0"]

#     model = wrapped_import.prune(
#         tf.nest.map_structure(import_graph.as_graph_element, inputs),
#         tf.nest.map_structure(import_graph.as_graph_element, outputs)
#     )

#     return model
