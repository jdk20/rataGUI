from abc import ABC, abstractmethod

from asyncio import Queue
from PyQt6.QtWidgets import QWidget
from pyqtconfig import ConfigManager

from typing import Dict, Tuple
from numpy.typing import NDArray

import logging

logger = logging.getLogger(__name__)


class BasePlugin(ABC):
    """
    Abstract plugin class with generic functions. All custom plugins should be subclassed
    to ensure that all the necessary methods are available to the processing pipeline.
    """

    # Static variable mapping names of loaded plugin modules to their corresponding subclass
    modules = {}

    # For every class that inherits from BasePlugin, the module name will be added to plugins
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        module_name = cls.__module__.split(".")[-1]
        cls.modules[module_name] = cls

    def __init__(self, cam_widget: QWidget, config: ConfigManager, queue_size=0):
        logger.info(
            f"Started {type(self).__name__} for: {cam_widget.camera.getDisplayName()}"
        )
        self.active = True
        self.failed = False
        self.blocking = False
        self.independent = False  # Independent plugins can run in parallel via fan-out
        self.drop_policy = "block"  # "block" or "drop_oldest" when in_queue is full
        self.config = config.as_dict()  # freeze plugin settings
        self.in_queue = Queue(queue_size)
        self.out_queue = None

    @abstractmethod
    def process(self, frame: NDArray, metadata: Dict) -> Tuple[NDArray, Dict]:
        raise NotImplementedError("Plugin process function not implemented")

    # Override for custom behavior
    def close(self):
        """Deactivates plugin and closes any plugin-specific resources"""
        self.active = False
        logger.info(f"{type(self).__name__} closed")

    # # Overwrite with any metadata produced by plugin
    # @staticmethod
    # def get_metadata_names(self) -> list:
    #     """
    #     Returns list of metadata names produced by plugin (ex. DLC Pose)

    #     Used to populate metadata
    #     """
    #     return list()