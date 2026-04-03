from rataGUI.cameras.BaseCamera import BaseCamera

from pypylon import pylon

import logging

logger = logging.getLogger(__name__)


READ_TIMEOUT = 10000  # 10 sec


class BaslerCamera(BaseCamera):
    """Basler camera interface using the pypylon SDK."""

    _TlFactory = pylon.TlFactory.GetInstance()

    @staticmethod
    def getCameraList():
        """Return a list of Basler camera pointers."""
        cam_list = BaslerCamera._TlFactory.EnumerateDevices()
        return cam_list

    @staticmethod
    def getAvailableCameras():
        """Returns list of all available Basler cameras"""
        cameras = []
        cam_list = BaslerCamera.getCameraList()
        for cam in cam_list:
            serial_number = cam.GetSerialNumber()
            # Create camera wrapper object
            cameras.append(BaslerCamera(serial_number))
        return cameras

    def __init__(self, cameraID: str):
        """Initialize a BaslerCamera wrapper for a given serial number."""
        super().__init__(cameraID)
        self.last_frame = None
        self.frames_dropped = 0
        self.last_index = -1
        self.buffer_size = 0
        self.initial_frameID = 0  # on camera transport layer
        self.FPS = -1

    def initializeCamera(self, prop_config, plugin_names=[]) -> bool:
        """Open the Basler camera device and start the video stream. Returns True on success."""
        # Re-initialize instance variables to reset session state between runs
        self.__init__(self.cameraID)

        try:
            cam_list = BaslerCamera.getCameraList()
            for device in cam_list:
                if device.GetSerialNumber() == self.cameraID:
                    self._stream = pylon.InstantCamera(
                        BaslerCamera._TlFactory.CreateDevice(device)
                    )
                    break
            if self._stream is None:
                raise OSError(f"Camera {self.getDisplayName()} not found")

            if not self._stream.IsOpen():
                self._stream.Open()
        except (Exception, pylon.GenericException) as err:
            logger.exception(err)
            return False

        # Start video stream
        self._stream.MaxNumBuffer = 20
        self._stream.StartGrabbing(pylon.GrabStrategy_OneByOne)
        self._running = True

        self.converter = pylon.ImageFormatConverter()
        self.converter.OutputPixelFormat = pylon.PixelType_RGB8packed
        self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

        return True

    def readCamera(self):
        """Read the next frame from the Basler camera. Returns (success, frame)."""
        try:
            grab_data = self._stream.RetrieveResult(
                READ_TIMEOUT, pylon.TimeoutHandling_ThrowException
            )
            if grab_data is None or not grab_data.GrabSucceeded():
                return False, None

            img_data = self.converter.Convert(grab_data)
            self.frames_acquired += 1

            self.last_frame = img_data.GetArray()
            grab_data.Release()
            return True, self.last_frame

        except pylon.GenericException as err:
            logger.exception(err)
            return False, None

    def closeCamera(self):
        """Stop grabbing and release the camera stream. Returns True on success."""
        try:
            if self._stream is not None:
                self._stream.StopGrabbing()

            self._running = False
            return True
        except Exception as err:
            logger.exception(err)
            return False

    def isOpened(self):
        """Return whether the camera is currently running."""
        return self._running
