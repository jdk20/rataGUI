from abc import ABC, abstractmethod

from pyqtconfig import ConfigManager

from typing import Any

import logging

logger = logging.getLogger(__name__)


class BaseTrigger(ABC):
    """
    Abstract trigger class with generic functions. All custom triggers should be subclassed
    to ensure that all the necessary methods are available to the triggering interface.
    """

    # Static variable mapping names of loaded trigger modules to their corresponding subclass
    modules = {}

    # For every class that inherits from BaseTrigger, the module name will be added to trigger_types
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        module_name = cls.__module__.split(".")[-1]
        cls.modules[module_name] = cls

    @staticmethod
    @abstractmethod
    def getAvailableDevices():
        pass

    # Optional method to release static resources upon exiting
    @staticmethod
    def releaseResources():
        pass

    def __init__(self, deviceID):
        self.initialized = False
        self.active = False
        self.deviceID = deviceID

    def initialize(self, config: ConfigManager) -> bool:
        """
        Initializes the trigger and returns whether or not it was successful

        :param config: ConfigManager that stores settings to initialize trigger
        """
        raise NotImplementedError()

    @abstractmethod
    def execute(self, signal: Any) -> bool:
        raise NotImplementedError()

    def close(self):
        """
        Deactivates trigger and closes any trigger-dependent objects
        """
        self.active = False  # Overwrite for custom behavior
        logger.info(f"{type(self).__name__} closed")
