import pytest
from unittest.mock import patch, MagicMock
from rataGUI.triggers.udp_socket import UDPSocket


class TestUDPSocketInit:
    def test_init(self):
        trigger = UDPSocket("device0")
        assert trigger._socket is None
        assert trigger.initialized is False
        assert trigger.active is False
        assert trigger.deviceID == "device0"

    def test_get_available_devices(self):
        devices = UDPSocket.getAvailableDevices()
        assert len(devices) == 1
        assert isinstance(devices[0], UDPSocket)


class TestUDPSocketInitialize:
    def test_initialize(self):
        trigger = UDPSocket("device0")
        config = MagicMock()
        config.get.side_effect = lambda key: {
            "Server IP": "192.168.1.1",
            "Socket Port": 5000,
        }[key]

        with patch("rataGUI.triggers.udp_socket.socket") as mock_socket_module:
            mock_sock = MagicMock()
            mock_socket_module.socket.return_value = mock_sock
            mock_socket_module.AF_INET = 2
            mock_socket_module.SOCK_DGRAM = 2

            result = trigger.initialize(config)

            assert result is True
            assert trigger.initialized is True
            assert trigger.server_ip == "192.168.1.1"
            assert trigger.port == 5000
            mock_sock.settimeout.assert_called_once_with(1.0)


class TestUDPSocketExecute:
    def test_execute_sends_data(self):
        trigger = UDPSocket("device0")
        trigger.initialized = True
        trigger.server_ip = "127.0.0.1"
        trigger.port = 1234
        trigger._socket = MagicMock()

        trigger.execute("hello")

        trigger._socket.sendto.assert_called_once_with(
            b"hello", ("127.0.0.1", 1234)
        )

    def test_execute_not_initialized(self):
        trigger = UDPSocket("device0")
        trigger.initialized = False
        trigger._socket = MagicMock()

        trigger.execute("hello")

        trigger._socket.sendto.assert_not_called()

    def test_execute_handles_error(self):
        trigger = UDPSocket("device0")
        trigger.initialized = True
        trigger.server_ip = "127.0.0.1"
        trigger.port = 1234
        trigger._socket = MagicMock()
        trigger._socket.sendto.side_effect = OSError("Connection refused")

        # Should not raise
        trigger.execute("hello")


class TestUDPSocketClose:
    def test_close(self):
        trigger = UDPSocket("device0")
        trigger._socket = MagicMock()
        trigger.initialized = True

        trigger.close()

        trigger._socket.close.assert_called_once()
        assert trigger.initialized is False
