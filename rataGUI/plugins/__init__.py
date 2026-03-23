"""
Loads plugin modules listed in config.py (defaults to all plugins if none are specified) 

Stores utility functions available to every plugin in folder
"""

import logging

logger = logging.getLogger(__name__)

import os
from importlib import import_module
from rataGUI import launch_config

enabled_plugins = launch_config.get("Enabled Plugin Modules")
if enabled_plugins is not None and launch_config.get("Don't show again"):
    for module_name in enabled_plugins:
        try:
            abs_module_path = f"{__name__}.{module_name}"
            import_module(abs_module_path)
            logger.info(f"Loaded plugin module: {module_name}.py")
        except ImportError as err:
            logger.warning(f"Unable to load plugin module: {module_name}.py")
            logger.error(str(err))
        except Exception as err:
            logger.exception(err)

else:  # Load all modules if launch config requires a start menu
    for fname in os.listdir(os.path.dirname(__file__)):
        if (
            fname.endswith(".py")
            and not fname.startswith("_")
            and fname not in ["base_plugin.py", "template_plugin.py"]
        ):
            try:
                abs_module_path = f"{__name__}.{fname[:-3]}"
                import_module(abs_module_path)
                logger.info(f"Loaded plugin module: {fname}")
            except ImportError as err:
                logger.warning(f"Unable to load plugin module: {fname}")
                logger.error(str(err))
            except Exception as err:
                logger.exception(err)
