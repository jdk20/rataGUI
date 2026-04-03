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

    def __init_subclass__(cls, **kwargs):
        """Auto-register each trigger subclass keyed by its module filename.

        Importing a trigger module automatically makes it available in
        ``BaseTrigger.modules`` without manual registration.
        """
        super().__init_subclass__(**kwargs)
        module_name = cls.__module__.split(".")[-1]
        cls.modules[module_name] = cls

    @staticmethod
    @abstractmethod
    def getAvailableDevices() -> list:
        """Return a list of trigger instances for every available device.

        Each subclass must implement this to discover connected hardware.
        """
        pass

    @staticmethod
    def releaseResources() -> None:
        """Release static resources shared across all instances (optional override)."""
        pass

    def __init__(self, deviceID: str):
        """Initialize the trigger with a device identifier.

        :param deviceID: Unique identifier for the trigger device.
        """
        self.initialized = False
        self.active = False
        self.deviceID = deviceID

    def initialize(self, config: ConfigManager) -> bool:
        """Initialize the trigger hardware and return whether it was successful.

        :param config: ConfigManager that stores settings to initialize trigger.
        """
        raise NotImplementedError()

    @abstractmethod
    def execute(self, signal: Any) -> bool:
        """Execute the trigger action with the given signal value.

        :param signal: The signal or payload to send to the trigger device.
        :return: True if execution succeeded.
        """
        raise NotImplementedError()

    def close(self) -> None:
        """
        Deactivates trigger and closes any trigger-dependent objects
        """
        self.active = False  # Overwrite for custom behavior
        logger.info(f"{type(self).__name__} closed")
