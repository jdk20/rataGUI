from rataGUI.cameras.BaseCamera import BaseCamera

import cv2
import PySpin

import os
import logging

logger = logging.getLogger(__name__)


READ_TIMEOUT = 15000


class FLIRCamera(BaseCamera):

    DEFAULT_PROPS = {  # Order Sensitive
        "Line0 Output": {
            "None": PySpin.LineSource_Off,
        },
        "Line1 Output": {
            "None": PySpin.LineSource_Off,
        },
        "Line2 Output": {
            "User Output 0": PySpin.LineSource_UserOutput0,
            "Frame Acquired": PySpin.LineSource_ExposureActive,
        },
        "Line3 Output": {
            "None": PySpin.LineSource_Off,
        },
        "TriggerSource": {
            "Off": "TriggerMode_Off",
            "Line 3": PySpin.TriggerSource_Line3,
            "Line 0": PySpin.TriggerSource_Line0,
            "Line 1": PySpin.TriggerSource_Line1,
            "Line 2": PySpin.TriggerSource_Line2,
        },
        "Buffer Mode": {
            "OldestFirst": PySpin.StreamBufferHandlingMode_OldestFirst,
            "NewestOnly": PySpin.StreamBufferHandlingMode_NewestOnly,
        },
        "Limit Framerate": {"On": True, "Off": False},
        "Framerate": 30,
        "Buffer Size": 20,  # Auto
        "Gain": -1,
        "Gamma": -1.0,
        "Exposure (μs)": -1,
        "Width": 10000,
        "Height": 10000,
        "OffsetX": 0,
        "OffsetY": 0,
    }

    DISPLAY_PROP_MAP = {
        "Limit Framerate": "AcquisitionFrameRateEnable",
        "Framerate": "AcquisitionFrameRate",
        "Buffer Mode": "TLStream.StreamBufferHandlingMode",
        "Buffer Size": "TLStream.StreamBufferCountManual",
        "Exposure (μs)": "ExposureTime",
    }

    # Global pyspin system variable
    _SYSTEM = None

    @staticmethod
    def getCameraList():
        """
        Return a list of Spinnaker camera pointers that must be cleared and initializes the PySpin 'System' interface
        """

        if FLIRCamera._SYSTEM is None:
            FLIRCamera._SYSTEM = PySpin.System.GetInstance()
        else:
            FLIRCamera._SYSTEM.UpdateCameras()

        return FLIRCamera._SYSTEM.GetCameras()

    @staticmethod
    def getAvailableCameras():
        """Returns list of all available FLIR cameras"""
        cameras = []
        cam_list = FLIRCamera.getCameraList()
        for cam in cam_list:
            # print(camera.TLDevice.DeviceSerialNumber.ToString())
            if cam.TLDevice.DeviceSerialNumber.GetAccessMode() == PySpin.RO:
                serial_number = cam.TLDevice.DeviceSerialNumber.ToString()
                # Create camera wrapper object
                cameras.append(FLIRCamera(serial_number))
        cam_list.Clear()
        return cameras

    @staticmethod
    def releaseResources():
        if FLIRCamera._SYSTEM is not None and not FLIRCamera._SYSTEM.IsInUse():
            FLIRCamera._SYSTEM.ReleaseInstance()
            del FLIRCamera._SYSTEM

    def __init__(self, serial: str):
        super().__init__("FLIR:" + serial)
        self.serial_num = serial
        self.last_frame = None
        self.frames_dropped = 0
        self.last_index = -1
        self.buffer_size = 0
        self.initial_frameID = 0  # on camera transport layer

    def configure_custom_settings(self, prop_config, plugin_names):
        """Configure plugin-dependent settings when initializing camera"""

        # Note: set the underlying value, not the display name
        if "VideoWriter" in plugin_names:  # Camera is recording
            prop_config.set("Line2 Output", PySpin.LineSource_ExposureActive)
        else:
            prop_config.set("Line2 Output", PySpin.LineSource_UserOutput0)

        if (
            prop_config.get("TriggerSource") != "TriggerMode_Off"
        ):  # Camera is being driven
            prop_config.set("Limit Framerate", False)

    def initializeCamera(self, prop_config, plugin_names=[]) -> bool:
        # Reset camera session variables
        self.frames_dropped = 0
        self.last_index = -1
        self.buffer_size = 0
        self.initial_frameID = 0

        try:
            cam_list = FLIRCamera.getCameraList()
            self._stream = cam_list.GetBySerial(self.serial_num)

            # Force a clean camera state regardless of previous session.
            # If the previous process crashed, the camera may still be
            # streaming or initialized, which makes property nodes read-only.
            if self._stream.IsStreaming():
                logger.warning(
                    "Camera %s was still streaming (stale session?), stopping acquisition",
                    self.serial_num,
                )
                self._stream.EndAcquisition()

            if self._stream.IsInitialized():
                logger.warning(
                    "Camera %s was already initialized, reinitializing for clean state",
                    self.serial_num,
                )
                self._stream.DeInit()

            self._stream.Init()
            logger.info("Camera %s initialized successfully", self.serial_num)
        except PySpin.SpinnakerException as err:
            logger.exception(err)
            logger.error("PySpin failed to find and initialize camera")
            return False
        finally:
            cam_list.Clear()

        self.configure_custom_settings(prop_config, plugin_names)
        try:
            nodemap = self._stream.GetNodeMap()
            enabled_chunks = [
                "FrameID",
            ]  # ExposureTime, PixelFormat
            self.configure_chunk_data(nodemap, enabled_chunks)

            for name, value in prop_config.as_dict().items():

                if name.startswith("Line") and name.endswith("Output"):
                    line_num = name[4]
                    selector = getattr(PySpin, "LineSelector_Line" + line_num)
                    self._stream.LineSelector.SetValue(selector)
                    try:
                        self._stream.LineMode.SetValue(PySpin.LineMode_Output)
                        self._stream.LineSource.SetValue(value)
                    except PySpin.SpinnakerException as ex:
                        logger.debug(f"Unable to write enum entry to Line {line_num}")
                        pass
                elif name == "TriggerSource":
                    if value == "TriggerMode_Off":
                        self._stream.TriggerMode.SetValue(PySpin.TriggerMode_Off)
                    else:
                        self._stream.TriggerMode.SetValue(PySpin.TriggerMode_On)
                        self._stream.TriggerOverlap.SetValue(
                            PySpin.TriggerOverlap_ReadOut
                        )  # Off or ReadOut to speed up
                        self._stream.TriggerSource.SetValue(value)
                        self._stream.TriggerActivation.SetValue(
                            PySpin.TriggerActivation_RisingEdge
                        )  # LevelHigh or RisingEdge
                        self._stream.TriggerSelector.SetValue(
                            PySpin.TriggerSelector_FrameStart
                        )  # require trigger for each frame

                else:
                    # Set to auto mode if value is negative
                    if name == "Buffer Size":
                        # if value < 0: # No buffer auto mode
                        #     continue
                        self._stream.TLStream.StreamBufferCountMode.SetValue(
                            PySpin.StreamBufferCountMode_Manual
                        )
                    elif name == "Gain":
                        if value < 0:
                            self._stream.GainAuto.SetValue(PySpin.GainAuto_Continuous)
                            continue
                        self._stream.GainAuto.SetValue(PySpin.GainAuto_Off)
                    elif name == "Gamma":
                        if value < 0:
                            self._stream.GammaEnable.SetValue(False)
                            continue
                        self._stream.GammaEnable.SetValue(True)
                    elif name == "Exposure (μs)":
                        if value < 0:
                            self._stream.ExposureAuto.SetValue(
                                PySpin.ExposureAuto_Continuous
                            )
                            continue
                        self._stream.ExposureAuto.SetValue(PySpin.ExposureAuto_Off)
                        self._stream.ExposureMode.SetValue(PySpin.ExposureMode_Timed)

                    # Recursively access QuickSpin API
                    prop_name = FLIRCamera.DISPLAY_PROP_MAP.get(name, name)
                    node = self._stream
                    attrs = prop_name.split(".")
                    if len(attrs) > 0 and hasattr(node, attrs[0]):
                        for attr in prop_name.split("."):
                            node = getattr(node, attr)

                        if type(node) in [PySpin.IInteger, PySpin.IFloat]:
                            node_min = node.GetMin()
                            node_max = node.GetMax()
                            clipped = min(max(value, node_min), node_max)
                            if clipped != value:
                                logger.warning(
                                    f"{prop_name} must be in the range [{node_min}, {node_max}]"
                                    f" so {value} was clipped to {clipped}"
                                )
                                prop_config.set(name, int(clipped))
                                value = clipped

                        if node.GetAccessMode() == PySpin.RW:
                            node.SetValue(value)
            # Ensure RGB pixel format
            # self._stream.PixelFormat.SetValue(PySpin.PixelFormat_RGB8Packed)
            if self._stream.PixelFormat.GetAccessMode() == PySpin.RW:
                self._stream.PixelFormat.SetValue(PySpin.PixelFormat_BayerRG8)
            else:
                logger.warning(
                    "PixelFormat node is not writable for camera %s (access mode: %s)",
                    self.serial_num, self._stream.PixelFormat.GetAccessMode(),
                )

            if self._stream.IspEnable.GetAccessMode() == PySpin.RW:
                self._stream.IspEnable.SetValue(False)
            else:
                logger.warning(
                    "IspEnable node is not writable for camera %s (access mode: %s)",
                    self.serial_num, self._stream.IspEnable.GetAccessMode(),
                )

        except PySpin.SpinnakerException as err:
            logger.exception(err)
            logger.error("PySpin failed to configure camera property values")
            return False

        # print(dir(self._stream.TLStream))
        # print(self._stream.TLStream.StreamBufferHandlingMode.ToString())
        # print(self._stream.AcquisitionMode.ToString())

        logger.info("Camera %s beginning acquisition", self.serial_num)
        self._stream.BeginAcquisition()
        self._running = True
        logger.info("Camera %s acquisition started", self.serial_num)

        return True

    def readCamera(self, colorspace="RGB"):
        try:
            img_data = self._stream.GetNextImage(READ_TIMEOUT)
            if img_data.IsIncomplete():
                logger.error(
                    "Image incomplete with image status %d ..."
                    % img_data.GetImageStatus()
                )
                return False, None

            # Parse image metadata
            chunk_data = img_data.GetChunkData()
            new_index = chunk_data.GetFrameID()
            # time_stamp = chunk_data.GetTimestamp()

            # Detect dropped frames
            if self.last_index >= 0:
                self.frames_dropped += new_index - self.last_index - 1
                self.buffer_size = self._stream.TLStream.StreamOutputBufferCount.GetValue()
            else:
                self.initial_frameID = new_index
            self.last_index = new_index
            self.frames_acquired += 1

            self.last_frame = img_data.GetNDArray()
            if colorspace == "BGR":
                self.last_frame = cv2.cvtColor(self.last_frame, cv2.COLOR_BayerBG2BGR)
            elif colorspace == "RGB":
                self.last_frame = cv2.cvtColor(self.last_frame, cv2.COLOR_BayerBG2RGB)
            elif colorspace == "GRAY":
                self.last_frame = cv2.cvtColor(self.last_frame, cv2.COLOR_BayerBG2GRAY)
            else:
                self.last_frame = self.last_frame

            # Release image from camera buffer
            img_data.Release()
            return True, self.last_frame

        except PySpin.SpinnakerException as ex:
            logger.exception(ex)
            return False, None

    def getMetadata(self):
        return {
            "Camera Index": self.last_index - self.initial_frameID,
            "Frame Index": self.frames_acquired,
        }

    def closeCamera(self):
        logger.info(f"Closing camera: {self.getDisplayName()}")
        try:
            if self._stream is not None:
                if self._stream.IsStreaming():
                    self._stream.EndAcquisition()

                self._stream.DeInit()
                self._stream = None

            self._running = False
            return True
        except Exception as err:
            logger.exception(err)
            return False

    def configure_chunk_data(self, nodemap, selected_chucks, enable=True) -> bool:
        """
        Configures the camera to add chunk data to each image.

        :param nodemap: Transport layer device nodemap.
        :type nodemap: INodeMap
        """
        try:
            result = True

            # Activate chunk mode
            # Once enabled, chunk data will be available at the end of the payload of every image captured until it is disabled.
            chunk_mode_active = PySpin.CBooleanPtr(nodemap.GetNode("ChunkModeActive"))

            if PySpin.IsAvailable(chunk_mode_active) and PySpin.IsWritable(
                chunk_mode_active
            ):
                chunk_mode_active.SetValue(True)

            chunk_selector = PySpin.CEnumerationPtr(nodemap.GetNode("ChunkSelector"))

            if not PySpin.IsAvailable(chunk_selector) or not PySpin.IsReadable(
                chunk_selector
            ):
                logger.error("Unable to retrieve chunk selector. Aborting...\n")
                return False

            # Retrieve entries from enumeration ptr
            entries = [
                PySpin.CEnumEntryPtr(chunk_selector_entry)
                for chunk_selector_entry in chunk_selector.GetEntries()
            ]

            # Select entry nodes to enable
            for chunk_selector_entry in entries:
                # Go to next node if problem occurs
                if not PySpin.IsAvailable(
                    chunk_selector_entry
                ) or not PySpin.IsReadable(chunk_selector_entry):
                    result = False
                    continue

                chunk_str = chunk_selector_entry.GetSymbolic()

                if chunk_str in selected_chucks:
                    chunk_selector.SetIntValue(chunk_selector_entry.GetValue())

                    # Retrieve corresponding boolean
                    chunk_enable = PySpin.CBooleanPtr(nodemap.GetNode("ChunkEnable"))

                    # Enable the corresponding chunk data
                    if enable:
                        if chunk_enable.GetValue() is True:
                            logger.info(
                                f"{chunk_str} enabled for FLIR camera: {self.serial_num}"
                            )
                        elif PySpin.IsWritable(chunk_enable):
                            chunk_enable.SetValue(True)
                            logger.info(
                                f"{chunk_str} enabled for FLIR camera: {self.serial_num}"
                            )
                        else:
                            logger.error(
                                f"{chunk_str} not writable for FLIR cameraa: {self.serial_num}"
                            )
                            result = False
                    else:
                        # Disable the boolean to disable the corresponding chunk data
                        if PySpin.IsWritable(chunk_enable):
                            chunk_enable.SetValue(False)
                        else:
                            result = False

        except PySpin.SpinnakerException as ex:
            logger.exception(ex)
            result = False

        return result
