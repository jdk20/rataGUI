"""Shared dynamic module loader for cameras, plugins, and triggers.

Each package (cameras/, plugins/, triggers/) uses the same pattern to discover
and import its modules at package init time.  This utility centralises that
logic so the three ``__init__.py`` files stay minimal.
"""

import os
import logging
from importlib import import_module

from rataGUI import launch_config

logger = logging.getLogger(__name__)


def load_modules(
    package_name: str, config_key: str, label: str, exclude_files: list[str]
) -> None:
    """Import submodules of a package, triggering ``__init_subclass__`` registration.

    When a saved launch config exists and the user chose "Don't show again",
    only the modules listed under *config_key* are loaded.  Otherwise every
    ``.py`` file in the package directory is imported (minus *exclude_files*)
    so that the start menu can display all available options.

    :param package_name: Fully-qualified package name (e.g. ``"rataGUI.cameras"``).
    :param config_key: Key in ``launch_config`` listing enabled module names
        (e.g. ``"Enabled Camera Modules"``).
    :param label: Human-readable label for log messages (e.g. ``"camera"``).
    :param exclude_files: Filenames to skip when loading all modules
        (e.g. ``["BaseCamera.py", "TemplateCamera.py"]``).
    """
    enabled = launch_config.get(config_key)

    if enabled is not None and launch_config.get("Don't show again"):
        # Load only the modules the user explicitly enabled
        for module_name in enabled:
            try:
                import_module(f"{package_name}.{module_name}")
                logger.info(f"Loaded {label} module: {module_name}.py")
            except ImportError as err:
                logger.warning(f"Unable to load {label} module: {module_name}.py")
                logger.error(str(err))
            except Exception as err:
                logger.exception(err)
    else:
        # Start menu required — load every module so all options are visible
        package_dir = os.path.dirname(import_module(package_name).__file__)
        for fname in os.listdir(package_dir):
            if (
                fname.endswith(".py")
                and not fname.startswith("_")
                and fname not in exclude_files
            ):
                try:
                    import_module(f"{package_name}.{fname[:-3]}")
                    logger.info(f"Loaded {label} module: {fname}")
                except ImportError as err:
                    logger.warning(f"Unable to load {label} module: {fname}")
                    logger.error(str(err))
                except Exception as err:
                    logger.exception(err)
