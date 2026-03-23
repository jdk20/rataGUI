import pytest
from asyncio import Queue
from unittest.mock import MagicMock
from rataGUI.plugins.base_plugin import BasePlugin


class ConcretePlugin(BasePlugin):
    """Minimal concrete subclass for testing BasePlugin."""

    def process(self, frame, metadata):
        return frame, metadata


@pytest.fixture
def plugin(mock_cam_widget, mock_config_manager):
    config = mock_config_manager({"key1": "value1", "key2": 42})
    return ConcretePlugin(mock_cam_widget, config)


class TestBasePluginInit:
    def test_defaults(self, plugin):
        assert plugin.active is True
        assert plugin.blocking is False
        assert plugin.independent is False
        assert plugin.drop_policy == "block"

    def test_freezes_config(self, plugin):
        assert isinstance(plugin.config, dict)
        assert plugin.config == {"key1": "value1", "key2": 42}

    def test_creates_queue(self, plugin):
        assert isinstance(plugin.in_queue, Queue)
        assert plugin.out_queue is None

    def test_queue_size(self, mock_cam_widget, mock_config_manager):
        config = mock_config_manager({})
        p = ConcretePlugin(mock_cam_widget, config, queue_size=5)
        assert p.in_queue.maxsize == 5


class TestBasePluginClose:
    def test_close_deactivates(self, plugin):
        assert plugin.active is True
        plugin.close()
        assert plugin.active is False


class TestBasePluginRegistration:
    def test_subclass_registered(self):
        module_name = ConcretePlugin.__module__.split(".")[-1]
        assert module_name in BasePlugin.modules

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            config = MagicMock()
            config.as_dict.return_value = {}
            widget = MagicMock()
            widget.camera.getDisplayName.return_value = "test"
            BasePlugin(widget, config)


class TestBasePluginProcess:
    def test_concrete_process(self, plugin):
        frame = "test_frame"
        metadata = {"key": "value"}
        result_frame, result_metadata = plugin.process(frame, metadata)
        assert result_frame == "test_frame"
        assert result_metadata == {"key": "value"}
