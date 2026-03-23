import pytest
from rataGUI.triggers.base_trigger import BaseTrigger


class ConcreteTrigger(BaseTrigger):
    """Minimal concrete subclass for testing BaseTrigger."""

    @staticmethod
    def getAvailableDevices():
        return []

    def execute(self, signal):
        return True


class TestBaseTriggerInit:
    def test_defaults(self):
        trigger = ConcreteTrigger("device0")
        assert trigger.initialized is False
        assert trigger.active is False
        assert trigger.deviceID == "device0"


class TestBaseTriggerClose:
    def test_close_deactivates(self):
        trigger = ConcreteTrigger("device0")
        trigger.active = True
        trigger.close()
        assert trigger.active is False


class TestBaseTriggerRegistration:
    def test_subclass_registered(self):
        module_name = ConcreteTrigger.__module__.split(".")[-1]
        assert module_name in BaseTrigger.modules

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseTrigger("device0")

    def test_release_resources_noop(self):
        BaseTrigger.releaseResources()
