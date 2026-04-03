from rataGUI.plugins.base_plugin import BasePlugin

import logging

logger = logging.getLogger(__name__)


class TemplatePlugin(BasePlugin):
    """
    Example plugin to overwrite with custom processing functionality
    """

    DEFAULT_CONFIG = {
        # TODO: Put user-configurable settings here (see other plugins for examples)
    }

    def __init__(self, cam_widget, config, queue_size=0):
        """Initialize the template plugin."""
        super().__init__(cam_widget, config, queue_size)

    def process(self, frame, metadata):
        """Process a single frame (override with custom logic). Returns (frame, metadata)."""
        # TODO: Implement custom processing functionality here

        # It is important to return the frame to make it available to the next plugin in the pipeline
        return frame, metadata

    def close(self):
        """Deactivate and clean up the template plugin."""
        # TODO: Close any plugin-specific resources here

        logger.info(f"{type(self).__name__} closed")
        self.active = False
