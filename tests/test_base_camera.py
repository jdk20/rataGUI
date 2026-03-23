import pytest
from rataGUI.cameras.BaseCamera import BaseCamera


class ConcreteCamera(BaseCamera):
    """Minimal concrete subclass for testing BaseCamera."""

    @staticmethod
    def getAvailableCameras():
        return []

    def initializeCamera(self, prop_config, plugin_names=[]):
        self._running = True
        return True

    def readCamera(self):
        return False, None

    def closeCamera(self):
        self._running = False
        return True


class TestBaseCameraInit:
    def test_defaults(self):
        cam = ConcreteCamera("cam0")
        assert cam._stream is None
        assert cam._running is False
        assert cam.frames_acquired == 0
        assert cam.display_name is None
        assert cam.cameraID == "cam0"

    def test_get_display_name_default(self):
        cam = ConcreteCamera(42)
        assert cam.getDisplayName() == "42"

    def test_get_display_name_custom(self):
        cam = ConcreteCamera("cam0")
        cam.display_name = "My Camera"
        assert cam.getDisplayName() == "My Camera"

    def test_is_opened_default(self):
        cam = ConcreteCamera("cam0")
        assert cam.isOpened() is False

    def test_is_opened_after_running(self):
        cam = ConcreteCamera("cam0")
        cam._running = True
        assert cam.isOpened() is True

    def test_get_metadata(self):
        cam = ConcreteCamera("cam0")
        cam.frames_acquired = 10
        meta = cam.getMetadata()
        assert meta == {"Frame Index": 10}

    def test_str_representation(self):
        cam = ConcreteCamera("cam0")
        assert str(cam) == "Camera ID: cam0"

    def test_release_resources_noop(self):
        BaseCamera.releaseResources()


class TestBaseCameraRegistration:
    def test_subclass_registered(self):
        # ConcreteCamera should be registered by module name
        module_name = ConcreteCamera.__module__.split(".")[-1]
        assert module_name in BaseCamera.modules
        assert BaseCamera.modules[module_name] is ConcreteCamera

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseCamera("cam0")
