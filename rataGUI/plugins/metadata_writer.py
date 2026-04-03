from rataGUI.plugins.base_plugin import BasePlugin

import os
import cv2

import logging

logger = logging.getLogger(__name__)


class MetadataWriter(BasePlugin):
    """
    Plugin that overlays metadata onto frames and/or into a log file
    """

    DEFAULT_CONFIG = {
        "Overlay Frame Index": False,
        "Abbreviate": False,
        "Overlay Timestamp": False,
        "Include date": False,
        "Overlay Camera Name": False,
    }

    def __init__(self, cam_widget, config, queue_size=0):
        """Initialize the metadata overlay writer with camera-specific settings."""
        super().__init__(cam_widget, config, queue_size)

        self.save_dir = cam_widget.save_dir
        logger.info(f"Saving metadata timestamp file to : {self.save_dir}")

        try:
            if os.access(self.save_dir, os.W_OK):
                os.makedirs(self.save_dir, exist_ok=True)
            else:
                raise OSError("Inaccessible save directory for metadata timestamp file")
        except Exception as err:
            logger.exception(err)

        self.file_path = os.path.join(self.save_dir, "timestamps.csv")

    def process(self, frame, metadata):
        """Overlay selected metadata fields as text onto the frame. Returns (frame, metadata)."""

        img_h, img_w, num_ch = frame.shape

        abbreviate = self.config.get("Abbreviate")
        count = 0

        # Write to log
        with open(self.file_path, "a") as f:
            f.write(f"{metadata['Frame Index']},{metadata['Timestamp'].timestamp()}\n")

        for name, value in metadata.items():
            key = "Overlay " + name

            # Check config to determine what to write
            if self.config.get(key):
                if name == "Timestamp":
                    if self.config.get("Include date"):
                        overlay = value.strftime("%m/%d/%y-%H:%M:%S.%f")
                    else:
                        overlay = value.strftime("%H:%M:%S.%f")

                    if abbreviate:
                        overlay = overlay[:-4]
                else:
                    if abbreviate:
                        name = "".join(
                            [word[0] for word in name.split(" ")]
                        )  # find initials
                    overlay = name + ": " + str(value)

                (text_w, text_h), _ = cv2.getTextSize(
                    overlay, cv2.FONT_HERSHEY_SIMPLEX, fontScale=0.7, thickness=2
                )
                # Stack text lines from the bottom of the image upward; each line
                # is offset by (text_h + 5) so successive overlays don't overlap.
                pos = (5, img_h - 5 - count * (text_h + 5))
                cv2.rectangle(
                    frame,
                    pos,
                    (pos[0] + text_w, pos[1] - text_h),
                    (0, 0, 0),
                    cv2.FILLED,
                )
                cv2.putText(
                    frame,
                    overlay,
                    pos,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    fontScale=0.7,
                    color=(255, 255, 255),
                    thickness=2,
                    lineType=cv2.LINE_4,
                )
                count += 1

        return frame, metadata

    def close(self):
        """Deactivate the metadata writer plugin."""
        logger.info("Metadata writer closed")
        self.active = False
