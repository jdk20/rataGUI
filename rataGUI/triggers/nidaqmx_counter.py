from rataGUI.triggers.base_trigger import BaseTrigger, ConfigManager

import nidaqmx
from nidaqmx.stream_writers import CounterWriter
from nidaqmx.constants import AcquisitionType

import logging

logger = logging.getLogger(__name__)


class NIDAQmxCounter(BaseTrigger):
    """
    Interface for triggering connected National Instrument devices through the NI-DAQmx driver.

    Current implementation produces TTL pulses to trigger cameras at specified FPS and phase.
    """

    DEFAULT_CONFIG = {
        "FPS": 30,
        "Phase offset (deg)": 0.0,
    }

    @staticmethod
    def getAvailableDevices():
        """Returns list of all available NI-DAQmx counter channels"""
        counter_channels = []
        local_system = nidaqmx.system.System.local()
        for device in local_system.devices:
            counter_channels.extend(
                [NIDAQmxCounter(co.name) for co in device.co_physical_chans]
            )
        return counter_channels

    def __init__(self, deviceID):
        """Initialize an NI-DAQmx counter trigger for the given channel."""
        super().__init__(deviceID)
        self._task = None

    def initialize(self, config: ConfigManager):
        """Configure the counter channel for pulse output. Returns True on success."""
        task = nidaqmx.Task()
        # Configure a counter output channel for time-based pulse generation
        task.co_channels.add_co_pulse_chan_time(counter=self.deviceID)
        # Run continuously without an external sample clock
        task.timing.cfg_implicit_timing(sample_mode=AcquisitionType.CONTINUOUS)
        cw = CounterWriter(task.out_stream, auto_start=True)
        task.start()
        cw.write_one_sample_pulse_frequency(
            # 50% duty cycle means equal on/off time
            frequency=config.get("FPS"),
            duty_cycle=0.5,
            timeout=10,
        )

        self._task = task
        self.initialized = True
        return True

    def execute(self, signal):
        """Update the pulse frequency on the counter channel."""
        logger.warning("NIDAQmxCounter execute function should not be called")

    def close(self):
        """Stop the counter task and deactivate the trigger."""
        logger.info("NIDAQmxCounter stopped")
        self.initialized = False
        if self._task is not None:
            self._task.stop()
            self._task.close()
