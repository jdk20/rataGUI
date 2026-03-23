"""
Loads camera modules listed in config.py (defaults to all camera models if none are specified) 

Stores utility functions available to every camera model in folder
"""

import logging

logger = logging.getLogger(__name__)

import os
from importlib import import_module
from rataGUI import launch_config

enabled_cameras = launch_config.get("Enabled Camera Modules")
if enabled_cameras is not None and launch_config.get("Don't show again"):
    for module_name in enabled_cameras:
        try:
            abs_module_path = f"{__name__}.{module_name}"
            import_module(abs_module_path)
            logger.info(f"Loaded camera module: {module_name}.py")
        except ImportError as err:
            logger.warning(f"Unable to load camera module: {module_name}.py")
            logger.error(str(err))
        except Exception as err:
            logger.exception(err)

else:  # Load all modules if launch config requires a start menu
    for fname in os.listdir(os.path.dirname(__file__)):
        if (
            fname.endswith(".py")
            and not fname.startswith("_")
            and fname not in ["BaseCamera.py", "TemplateCamera.py"]
        ):
            try:
                abs_module_path = f"{__name__}.{fname[:-3]}"
                import_module(abs_module_path)
                logger.info(f"Loaded camera module: {fname}")
            except ImportError as err:
                logger.warning(f"Unable to load camera module: {fname}")
                logger.error(str(err))
            except Exception as err:
                logger.exception(err)
