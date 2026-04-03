from rataGUI.triggers.base_trigger import BaseTrigger, ConfigManager

import logging

logger = logging.getLogger(__name__)


class TemplateTrigger(BaseTrigger):
    """
    Example subclass to overwrite with code to trigger custom external devices
    """

    DEFAULT_CONFIG = {}

    @staticmethod
    def getAvailableDevices():
        """Returns list of trigger objects wrapping every available device"""
        return [TemplateTrigger("test")]

    def __init__(self, deviceID):
        """Initialize the template trigger with the given device ID."""
        super().__init__(deviceID)
        self.interval = -1

    def initialize(self, config: ConfigManager):
        """Initialize trigger hardware (override with custom logic). Returns True on success."""
        self.initialized = True
        return True

    def execute(self, signal):
        """Execute the trigger action (override with custom logic). Returns True on success."""
        if self.initialized:
            logger.info(f"Trigger: {str(self.deviceID)} executed")

    def close(self):
        """Deactivate and clean up trigger resources."""
        logger.info("Template trigger stopped")
        self.initialized = False
