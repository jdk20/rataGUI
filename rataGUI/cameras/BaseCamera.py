from abc import ABC, abstractmethod
from pyqtconfig import ConfigManager
from typing import Any, Tuple, List, Dict
from numpy.typing import NDArray


class BaseCamera(ABC):
    """
    Abstract camera class with generic functions. All camera models should be subclassed
    to ensure that all the necessary methods are available to the camera acquisition engine.
    """

    # Static variable mapping names of loaded camera modules to their corresponding subclass
    modules = {}

    def __init_subclass__(cls, **kwargs):
        """Auto-register each camera subclass keyed by its module filename.

        Importing a camera module automatically makes it available in
        ``BaseCamera.modules`` without manual registration.
        """
        super().__init_subclass__(**kwargs)
        module_name = cls.__module__.split(".")[-1]
        cls.modules[module_name] = cls

    @staticmethod
    @abstractmethod
    def getAvailableCameras() -> List[Any]:
        """Returns list of camera objects wrapping every available device"""
        pass

    # Optional method to release static resources upon exiting program
    @staticmethod
    def releaseResources():
        pass

    def __init__(self, cameraID):
        self._stream = None
        self.cameraID = cameraID
        self.display_name = None
        self._running = False
        self.frames_acquired = 0

    @abstractmethod
    def initializeCamera(
        self, prop_config: ConfigManager, plugin_names: List[str]
    ) -> bool:
        """
        Initializes the camera and returns whether or not it was successful

        :param prop_config: ConfigManager that stores settings to initialize camera
        :param plugin_names: List of plugin names to determine plugin-dependent settings
        """
        raise NotImplementedError()

    @abstractmethod
    def readCamera(self) -> Tuple[bool, NDArray]:
        """
        Reads next frame on camera and whether retrieval was successful
        """
        raise NotImplementedError()

    @abstractmethod
    def closeCamera(self) -> bool:
        """
        Stops the acquisition and closes the connection with the camera.
        """
        raise NotImplementedError()

    def getDisplayName(self) -> str:
        """
        Returns the display name of the camera. Defaults to cameraID if display is not set.
        """
        if self.display_name is not None:
            return str(self.display_name)
        return str(self.cameraID)

    def isOpened(self) -> bool:
        """
        Returns true if camera has been initialized and is streaming.
        """
        return self._running  # Overwrite for custom behavior

    def getMetadata(self) -> Dict[str, Any]:
        """
        Returns camera metadata associated with last acquired frame
        """
        return {"Frame Index": self.frames_acquired}

    @classmethod
    def create_and_initialize(cls, camera_id, config_dict, plugin_names):
        """Factory method for subprocess use.

        Creates a camera instance, builds a mock ConfigManager from a plain
        dict, and initialises the camera.  Returns the camera instance on
        success or raises on failure.

        :param camera_id: Camera identifier passed to ``__init__``.
        :param config_dict: Plain dict of camera settings.
        :param plugin_names: List of plugin name strings.
        """
        from unittest.mock import MagicMock

        camera = cls(camera_id)
        config = MagicMock()
        config.as_dict.return_value = dict(config_dict)
        config.get.side_effect = lambda key, default=None: config_dict.get(key, default)
        config.set = MagicMock()

        success = camera.initializeCamera(config, plugin_names)
        if not success:
            raise IOError(f"Camera {camera_id} failed to initialize")

        camera._running = True
        camera.frames_acquired = 0
        return camera

    def __str__(self):
        return "Camera ID: {}".format(str(self.cameraID))
