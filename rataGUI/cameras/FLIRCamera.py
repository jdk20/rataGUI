from rataGUI.cameras.BaseCamera import BaseCamera

import cv2
import PySpin

import logging
from typing import Any, Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


READ_TIMEOUT = 15000


class FLIRCamera(BaseCamera):
    DEFAULT_PROPS = {  # Order Sensitive
        "Line1 Output": {
            "UserOutput0": PySpin.LineSource_UserOutput0,
            "ExposureActive": PySpin.LineSource_ExposureActive,
        },
        "Line2 Output": {
            "UserOutput1": PySpin.LineSource_UserOutput1,
            "ExposureActive": PySpin.LineSource_ExposureActive,
        },
        "Timestamp Line": ["None", "Line1", "Line2"],
        "Timestamp While Recording": True,
        "TriggerSource": {
            "Off": "TriggerMode_Off",          # sentinel, not a device entry
            "Line3": PySpin.TriggerSource_Line3,
            "Line0": PySpin.TriggerSource_Line0,
            "Line1": PySpin.TriggerSource_Line1,
            "Line2": PySpin.TriggerSource_Line2,
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
        "Pixel Format": {
            "Bayer RG 8-bit": PySpin.PixelFormat_BayerRG8,
            "Mono 8-bit": PySpin.PixelFormat_Mono8,
        },
    }

    DISPLAY_PROP_MAP = {
        "Limit Framerate": "AcquisitionFrameRateEnable",
        "Framerate": "AcquisitionFrameRate",
        "Buffer Size": "TLStream.StreamBufferCountManual",
        "Exposure (μs)": "ExposureTime",
    }

    # Default order of Enums keys
    LINE_SOURCE_ORDER = ["Off", "UserOutput0", "ExposureActive"]
    TRIGGER_SOURCE_ORDER = ["Line0", "Line1", "Line2", "Line3", "Software"]
    PIXEL_FORMAT_ORDER = ["BayerRG8", "Mono8"]  # preserve current color default

    # Pixel Format Info
    PIXEL_FORMAT_NAMES = {
        "Mono8": "Mono 8-bit",
        "BayerRG8": "Bayer RG 8-bit",
        "BayerGR8": "Bayer GR 8-bit",
        "BayerGB8": "Bayer GB 8-bit",
        "BayerBG8": "Bayer BG 8-bit",
        "RGB8": "RGB 8-bit (camera ISP)",
        "BGR8": "BGR 8-bit (camera ISP)",
    }
    MONO_FORMATS = {"Mono8", "Mono16"}

    # NOTE: OpenCV's Bayer naming is offset by one row/column relative to the
    # GenICam convention, so GenICam BayerRG maps to cv2.COLOR_BayerBG*. This
    # is intentional — do not "correct" it to COLOR_BayerRG*.
    BAYER_CONVERSIONS = {
        "BayerRG8": (cv2.COLOR_BayerBG2RGB, cv2.COLOR_BayerBG2BGR),
        "BayerGR8": (cv2.COLOR_BayerGB2RGB, cv2.COLOR_BayerGB2BGR),
        "BayerGB8": (cv2.COLOR_BayerGR2RGB, cv2.COLOR_BayerGR2BGR),
        "BayerBG8": (cv2.COLOR_BayerRG2RGB, cv2.COLOR_BayerRG2BGR),
    }

    # Discovered props cached per DeviceModelName — line/format capability is
    # fixed by firmware, so one query per model is enough.
    _DEVICE_PROPS_CACHE: Dict[str, Tuple[Dict[str, Any], List[str]]] = {}

    # Properties to skip when looping through and setting camera properties
    SKIP_PROPS = {
        "Camera Parameters File",
        "Pixel Format",                 # handled separately after the main loop
        "Timestamp Line",               # handled in configure_custom_settings
        "Timestamp While Recording"     # handled in configure_custom_settings
    }

    # Global pyspin system variable
    _SYSTEM = None

    @staticmethod
    def _order_options(entries, names={}, preferred=None, order=None) -> Dict[str, Any]:
        order = order or []

        def sort_key(item):
            symbolic, _value = item
            if preferred is not None and symbolic == preferred:
                return (0, 0, symbolic)
            if symbolic in order:
                return (1, order.index(symbolic), symbolic)
            return (2, 0, symbolic)

        return {
            names.get(symbolic, symbolic): value
            for symbolic, value in sorted(entries.items(), key=sort_key)
        }

    @staticmethod
    def _sdk_value(prefix: str, symbolic: str) -> Optional[int]:
        """Resolve a symbolic entry name to the SDK constant QuickSpin's SetValue wants."""
        return getattr(PySpin, f"{prefix}_{symbolic}", None)


    @staticmethod
    def _set_enum(node, value, label: str = "") -> bool:
        """Set a QuickSpin enumeration node to an SDK enum constant."""
        try:
            if node.GetAccessMode() != PySpin.RW:
                logger.warning("Node is not writable%s", f" for {label}" if label else "")
                return False
            node.SetValue(value)
            return True
        except PySpin.SpinnakerException as err:
            logger.warning("Could not set value%s", f" for {label}" if label else "")
            logger.debug(err)
            return False

    @staticmethod
    def _enum_options(node, prefix, names={}, preferred=None, order=None, strict=False):
        """Enumerate a QuickSpin enum node as an ordered {display name: SDK constant}."""
        if node.GetAccessMode() not in (PySpin.RO, PySpin.RW):
            return {}
        entries = {}
        for ptr in node.GetEntries():
            entry = PySpin.CEnumEntryPtr(ptr)
            if not PySpin.IsAvailable(entry) or not PySpin.IsReadable(entry):
                continue
            symbolic = entry.GetSymbolic()
            if strict and symbolic not in names:
                continue
            value = FLIRCamera._sdk_value(prefix, symbolic)
            if value is None:
                # Device offers an entry this SDK build has no constant for
                logger.debug("No SDK constant for %s_%s; not offered", prefix, symbolic)
                continue
            entries[symbolic] = value
        return FLIRCamera._order_options(entries, names, preferred, order)
    
    @staticmethod
    def _iter_selector(selector, prefix_name: str, prefix: str = ""):
        """Yield each selectable entry's symbolic name, restoring the selector after.

        :param selector: QuickSpin selector node (e.g. ``stream.LineSelector``).
        :param prefix_name: SDK constant prefix for that selector, e.g. "LineSelector".

        Note: do not ``break`` out of this loop — the selector is restored when the
        generator closes, which is deferred on an early exit.
        """
        if selector.GetAccessMode() not in (PySpin.RO, PySpin.RW):
            return
        original = selector.GetValue()
        try:
            for ptr in selector.GetEntries():
                entry = PySpin.CEnumEntryPtr(ptr)
                if not PySpin.IsAvailable(entry) or not PySpin.IsReadable(entry):
                    continue
                symbolic = entry.GetSymbolic()
                if prefix and not symbolic.startswith(prefix):
                    continue
                value = FLIRCamera._sdk_value(prefix_name, symbolic)
                if value is None:
                    logger.debug("No SDK constant for %s_%s", prefix_name, symbolic)
                    continue
                selector.SetValue(value)
                yield symbolic
        finally:
            selector.SetValue(original)


    @staticmethod
    def _query_pixel_formats(stream) -> Dict[str, Any]:
        return FLIRCamera._enum_options(
            stream.PixelFormat, "PixelFormat",
            names=FLIRCamera.PIXEL_FORMAT_NAMES,
            order=FLIRCamera.PIXEL_FORMAT_ORDER,
        )

    @staticmethod
    def _query_trigger_sources(stream, input_lines=None) -> Dict[str, Any]:
        options = FLIRCamera._enum_options(
            stream.TriggerSource, "TriggerSource",
            order=FLIRCamera.TRIGGER_SOURCE_ORDER,
        )
        if input_lines is not None:
            # allowed holds display names of Input-capable lines only
            options = {d: v for d, v in options.items()
                        if d in input_lines}
        if not options:
            return {}
        return {"Off": "TriggerMode_Off", **options}


    @staticmethod
    def _query_line_props(stream, modes: Dict[str, set]) -> Dict[str, Dict[str, Any]]:
        props = {}
        for line_name in FLIRCamera._iter_selector(
            stream.LineSelector, "LineSelector", prefix="Line"
        ):
            if "Output" not in modes.get(line_name, set()):
                continue
            options = FLIRCamera._enum_options(
                stream.LineSource, "LineSource",
                order=FLIRCamera.LINE_SOURCE_ORDER, 
                strict=False,
            )
            if options:
                props[f"{line_name} Output"] = options
        return props


    @staticmethod
    def _query_line_modes(stream) -> Dict[str, set]:
        modes = {}
        for line_name in FLIRCamera._iter_selector(
            stream.LineSelector, "LineSelector", prefix="Line"
        ):
            mode = stream.LineMode
            access = mode.GetAccessMode()
            if access not in (PySpin.RO, PySpin.RW):
                continue
            if access == PySpin.RW:
                available = {m for m in ("Input", "Output")
                            if (e := mode.GetEntryByName(m)) is not None
                            and PySpin.IsAvailable(e)}
            else:
                current = mode.GetCurrentEntry()
                available = {current.GetSymbolic()} if current is not None else set()
            if available:
                modes[line_name] = available
        return modes

    def getDeviceProps(self) -> Tuple[Dict[str, Any], List[str]]:
        """Query this camera for the settings it actually supports.

        :return: (props to merge over DEFAULT_PROPS, DEFAULT_PROPS keys to drop)
        """
        cam_list = None
        stream = None
        did_init = False
        self.props_complete = True
        try:
            cam_list = FLIRCamera.getCameraList()
            stream = cam_list.GetBySerial(self.serial_num)

            model = "unknown"
            if stream.TLDevice.DeviceModelName.GetAccessMode() == PySpin.RO:
                model = stream.TLDevice.DeviceModelName.ToString()
            if model in FLIRCamera._DEVICE_PROPS_CACHE:
                props, remove = FLIRCamera._DEVICE_PROPS_CACHE[model]
                return dict(props), list(remove)

            if not stream.IsInitialized():
                stream.Init()
                did_init = True

            props: Dict[str, Any] = {}
            remove: List[str] = []

            modes = FLIRCamera._query_line_modes(stream)
            lines = FLIRCamera._query_line_props(stream, modes)
            if lines:
                props.update(lines)
                # Prune hardcoded lines this model doesn't expose as outputs.
                # Only when the query succeeded — otherwise keep the fallbacks.
                remove = [
                    k for k in FLIRCamera.DEFAULT_PROPS
                    if k.startswith("Line") and k.endswith("Output") and k not in lines
                ]
                if remove:
                    logger.debug("Camera %s does not expose %s", self.serial_num, remove)

                # Only offer lines that can actually be driven by ExposureActive
                capable = [
                    key.split()[0] for key, opts in lines.items()
                    if "ExposureActive" in opts.values()
                ]
                if capable:
                    props["Timestamp Line"] = ["None"] + capable
                    props["Timestamp While Recording"] = True
            else:
                self.props_complete = False
                logger.warning("No line outputs discovered on camera %s; using DEFAULT_PROPS",
                            self.serial_num)
    
            formats = FLIRCamera._query_pixel_formats(stream)
            if formats:
                props["Pixel Format"] = formats
            else:
                self.props_complete = False
                logger.warning("No pixel formats discovered on camera %s; using DEFAULT_PROPS",
                            self.serial_num)

            input_lines = {name for name, m in modes.items() if "Input" in m}
            triggers = FLIRCamera._query_trigger_sources(stream, input_lines or None)
            if triggers:
                props["TriggerSource"] = triggers

            FLIRCamera._DEVICE_PROPS_CACHE[model] = (dict(props), list(remove))
            return props, remove

        except (PySpin.SpinnakerException, AttributeError) as err:
            self.props_complete = False
            logger.warning(
                "Could not query device properties for camera %s; using DEFAULT_PROPS",
                self.serial_num,
            )
            logger.debug(err)
            return {}, []
        finally:
            try:
                if did_init and stream is not None and stream.IsInitialized():
                    stream.DeInit()
            except PySpin.SpinnakerException:
                pass
            del stream
            if cam_list is not None:
                cam_list.Clear()

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
        """Initialize a FLIRCamera wrapper for the given serial number."""
        super().__init__("FLIR:" + serial)
        self.serial_num = serial
        self.last_frame = None
        self.frames_dropped = 0
        self.last_index = -1
        self.buffer_size = 0
        self.initial_frameID = 0  # on camera transport layer
        self.pixel_format = None

    def configure_custom_settings(self, prop_config, plugin_names):
        """Apply plugin-dependent settings when initializing camera."""
        recording = "VideoWriter" in plugin_names
        settings = prop_config.as_dict()

        self._timestamp_line = None
        self._timestamp_idle = None

        line = settings.get("Timestamp Line", "None")
        if settings.get("Timestamp While Recording", False) and line != "None":
            key = f"{line} Output"
            if key not in settings:
                logger.warning(
                    "Timestamp line %s is not available on camera %s; "
                    "frame timestamps will not be generated", line, self.serial_num,
                )
            elif recording:
                # Applied to hardware after the property loop; the config keeps the
                # user's idle value so it survives save/restore.
                self._timestamp_line = line
                self._timestamp_idle = settings[key]

        if prop_config.get("TriggerSource") != "TriggerMode_Off":
            prop_config.set("Limit Framerate", False)

    def _set_line_source(self, line: str, value) -> bool:
        """Select `line` and set its LineSource. Returns True on success."""
        selector = FLIRCamera._sdk_value("LineSelector", line)
        if selector is None:
            logger.warning("No SDK constant for %s", line)
            return False
        if not FLIRCamera._set_enum(self._stream.LineSelector, selector, label=line):
            return False
        FLIRCamera._set_enum(self._stream.LineMode, PySpin.LineMode_Output, label=line)
        return FLIRCamera._set_enum(self._stream.LineSource, value, label=line)

    def initializeCamera(self, prop_config, plugin_names=[]) -> bool:
        """Configure and start the FLIR camera stream via PySpin. Returns True on success."""
        # Reset camera session variables
        self.frames_dropped = 0
        self.last_index = -1
        self.buffer_size = 0
        self.initial_frameID = 0
        self.pixel_format = None

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
            # configure_chunk_data works on the GenApi nodemap; everything else in this
            # method uses QuickSpin nodes, which take SDK enum constants.
            self.configure_chunk_data(self._stream.GetNodeMap(), ["FrameID"])

            for name, value in prop_config.as_dict().items():
                if name in FLIRCamera.SKIP_PROPS:
                    continue
                if name.startswith("Line") and name.endswith("Output"):
                    line = name.split()[0]
                    if line == self._timestamp_line:
                        if not self._set_line_source(line, PySpin.LineSource_ExposureActive):
                            self._timestamp_line = None      # nothing to restore
                        else:
                            logger.info("Recording: driving %s with ExposureActive", self._timestamp_line)
                    else:
                        self._set_line_source(name.split()[0], value)
                elif name == "TriggerSource":
                    if value == "TriggerMode_Off":
                        FLIRCamera._set_enum(self._stream.TriggerMode, PySpin.TriggerMode_Off, label=name)
                    else:
                        FLIRCamera._set_enum(self._stream.TriggerMode, PySpin.TriggerMode_Off, label=name)
                        FLIRCamera._set_enum(self._stream.TriggerSelector,
                                            PySpin.TriggerSelector_FrameStart, label=name)
                        FLIRCamera._set_enum(self._stream.TriggerSource, value, label=name)
                        FLIRCamera._set_enum(self._stream.TriggerActivation,
                                            PySpin.TriggerActivation_RisingEdge, label=name)
                        FLIRCamera._set_enum(self._stream.TriggerOverlap,
                                            PySpin.TriggerOverlap_ReadOut, label=name)
                        FLIRCamera._set_enum(self._stream.TriggerMode, PySpin.TriggerMode_On, label=name)

                else:
                    # Set to auto mode if value is negative
                    if name == "Buffer Size":
                        FLIRCamera._set_enum(
                            self._stream.TLStream.StreamBufferCountMode,
                            PySpin.StreamBufferCountMode_Manual, label=name)
                    elif name == "Gain":
                        if value < 0:
                            FLIRCamera._set_enum(self._stream.GainAuto,
                                                PySpin.GainAuto_Continuous, label=name)
                            continue
                        FLIRCamera._set_enum(self._stream.GainAuto, PySpin.GainAuto_Off, label=name)
                    elif name == "Exposure (μs)":
                        if value < 0:
                            FLIRCamera._set_enum(self._stream.ExposureAuto,
                                                PySpin.ExposureAuto_Continuous, label=name)
                            continue
                        FLIRCamera._set_enum(self._stream.ExposureAuto,
                                            PySpin.ExposureAuto_Off, label=name)
                        FLIRCamera._set_enum(self._stream.ExposureMode,
                                            PySpin.ExposureMode_Timed, label=name)
                    elif name == "Gamma":
                        if value < 0:
                            self._stream.GammaEnable.SetValue(False)
                            continue
                        self._stream.GammaEnable.SetValue(True)
                    elif name == "Buffer Mode":
                        FLIRCamera._set_enum(self._stream.TLStream.StreamBufferHandlingMode,
                                            value, label=name)
                        continue

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

            fmt = prop_config.get("Pixel Format")     # SDK constant again
            if self._stream.IspEnable.GetAccessMode() == PySpin.RW:
                self._stream.IspEnable.SetValue(
                    fmt in (PySpin.PixelFormat_RGB8, PySpin.PixelFormat_BGR8))
            if fmt is not None:
                FLIRCamera._set_enum(self._stream.PixelFormat, fmt, label="Pixel Format")
            self.pixel_format = self._stream.PixelFormat.GetCurrentEntry().GetSymbolic()

        except PySpin.SpinnakerException as err:
            logger.exception(err)
            logger.error("PySpin failed to configure camera property values")
            return False

        logger.info("Camera %s beginning acquisition", self.serial_num)
        self._stream.BeginAcquisition()
        self._running = True
        logger.info("Camera %s acquisition started", self.serial_num)

        return True

    def readCamera(self, colorspace="RGB"):
        """Read the next frame from the FLIR camera. Returns (success, frame)."""
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
                self.buffer_size = (
                    self._stream.TLStream.StreamOutputBufferCount.GetValue()
                )
            else:
                self.initial_frameID = new_index
            self.last_index = new_index
            self.frames_acquired += 1


            raw = img_data.GetNDArray()
            fmt = self.pixel_format

            if fmt in FLIRCamera.MONO_FORMATS:
                # Expand to (H, W, 3): the ring buffer, VideoWriter and FrameDisplay
                # all unpack a 3-tuple shape.
                code = cv2.COLOR_GRAY2BGR if colorspace == "BGR" else cv2.COLOR_GRAY2RGB
                self.last_frame = cv2.cvtColor(raw, code)
            elif fmt in FLIRCamera.BAYER_CONVERSIONS:
                rgb_code, bgr_code = FLIRCamera.BAYER_CONVERSIONS[fmt]
                self.last_frame = cv2.cvtColor(raw, bgr_code if colorspace == "BGR" else rgb_code)
            else:
                if fmt not in ("RGB8", "BGR8"):
                    logger.warning("Unhandled pixel format %s on camera %s; passing through raw",
                                fmt, self.serial_num)
                self.last_frame = raw.copy()

            # Release image from camera buffer
            img_data.Release()
            return True, self.last_frame

        except PySpin.SpinnakerException as ex:
            logger.exception(ex)
            return False, None

    def getMetadata(self):
        """Return a dict of camera-specific metadata for the most recent frame."""
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

                if self._timestamp_line is not None:
                    logger.info("Restoring %s to its idle output", self._timestamp_line)
                    self._set_line_source(self._timestamp_line, self._timestamp_idle)
                    self._timestamp_line = None
                    self._timestamp_idle = None

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
                                f"{chunk_str} not writable for FLIR camera: {self.serial_num}"
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
