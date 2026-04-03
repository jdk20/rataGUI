# RataGUI package version
__version__ = "0.2.1"

import os
import sys
from datetime import datetime

import logging

logger = logging.getLogger(__name__)
# Prevent log messages from bubbling up to the root logger, which would
# cause duplicate output when other libraries configure their own handlers.
logger.propagate = False
logger.setLevel(logging.DEBUG)

# set up logging DEBUG messages or higher to sys.stdout
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(levelname)-8s %(module)-16s %(message)s")
console.setFormatter(formatter)
logger.addHandler(console)


# set up logging INFO messages or higher to log file
# file_handlers = {}
def add_file_logger(file_path: str) -> None:
    """Attach a file handler to the package logger that writes INFO+ messages.

    Creates the log directory if it does not exist.  The log filename includes
    a timestamp to avoid collisions across sessions.

    :param file_path: Directory in which to create the log file.
    """
    os.makedirs(file_path, exist_ok=True)
    file_name = "info_" + datetime.now().strftime("%Y_%m_%d-%H_%M_%S") + ".log"
    logging_file = os.path.join(file_path, file_name)
    file_handler = logging.FileHandler(logging_file)
    file_handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d  %(levelname)-8s %(module)-16s %(message)s",
        "%Y-%m-%d,%H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.info(f"Logging to {logging_file}")


import json

config_path = os.path.join(os.path.dirname(__file__), "launch_config.json")
launch_config = {}
if os.path.isfile(config_path) and os.stat(config_path).st_size > 0:
    with open(config_path, "r") as file:
        launch_config = json.load(file)

# Path to rataGUI project icon
rataGUI_icon = os.path.join(
    os.path.dirname(__file__), "interface/design/ratagui-icon.png"
)
