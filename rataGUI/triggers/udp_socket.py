from rataGUI.triggers.base_trigger import BaseTrigger, ConfigManager

import socket

import logging

logger = logging.getLogger(__name__)


class UDPSocket(BaseTrigger):
    """
    Interface for publishing information to a socket
    """

    DEFAULT_CONFIG = {
        "Server IP": "127.0.0.1",
        "Socket Port": 1234,
    }

    @staticmethod
    def getAvailableDevices():
        """Returns list of test trigger(s)"""
        return [UDPSocket(f"Rasberry Pi {i + 1}") for i in range(1)]

    def __init__(self, deviceID):
        """Initialize a UDP socket trigger for the given host:port address."""
        super().__init__(deviceID)
        self._socket = None

    def initialize(self, config: ConfigManager):
        """Create and bind the UDP socket. Returns True on success."""
        self.server_ip = config.get("Server IP")
        self.port = config.get("Socket Port")
        # Creates a UDP (connectionless) socket
        self._socket = socket.socket(socket.AF_INET, type=socket.SOCK_DGRAM)
        # Timeout prevents blocking indefinitely on send errors
        self._socket.settimeout(1.0)

        self.initialized = True
        return True

    def execute(self, signal: str):
        """Send a signal string to the configured UDP address. Returns True on success."""
        try:
            if self.initialized:
                self._socket.sendto(
                    bytes(signal, encoding="utf-8"), (self.server_ip, self.port)
                )
        except Exception as err:
            logger.exception(err)
            logger.info(f"Trigger: {str(self.deviceID)} failed to execute")

    def close(self):
        """Close the UDP socket and deactivate the trigger."""
        logger.info("Test trigger stopped")
        self._socket.close()
        self.initialized = False
