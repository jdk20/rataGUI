"""Fixed-size ring buffer for zero-copy frame distribution to independent plugins."""

import threading
import numpy as np

import logging

logger = logging.getLogger(__name__)


class FrameRingBuffer:
    """Pre-allocated ring buffer that allows multiple consumers to read frames
    via zero-copy numpy views.

    The producer calls :meth:`publish` to copy a frame into the next available
    slot.  Each consumer calls :meth:`get_view` to obtain a **read-only** numpy
    view of the frame (no copy) and :meth:`release` when it is done.  A slot
    becomes reusable once all consumers have released it.

    :param num_slots: Number of frame slots in the ring.
    :param height: Frame height in pixels.
    :param width: Frame width in pixels.
    :param channels: Number of colour channels (e.g. 3 for RGB).
    :param num_consumers: Expected number of concurrent consumers.
    """

    def __init__(self, num_slots: int, height: int, width: int, channels: int,
                 num_consumers: int = 1):
        self.num_slots = num_slots
        self.num_consumers = num_consumers
        self._shape = (height, width, channels)

        # Contiguous allocation for all frame slots
        self.frames = np.zeros((num_slots, height, width, channels), dtype=np.uint8)
        self.metadata = [None] * num_slots
        self.ref_counts = [0] * num_slots

        # Condition variable for backpressure (wait_for_slot)
        self._slot_released = threading.Condition(threading.Lock())

        # Monotonically increasing write position
        self.write_pos = 0

        logger.info(
            "Allocated FrameRingBuffer: %d slots, %dx%dx%d (%d consumers)",
            num_slots, height, width, channels, num_consumers,
        )

    # -- Producer API --------------------------------------------------------

    def publish(self, frame: np.ndarray, metadata: dict) -> int:
        """Copy *frame* into the next ring slot and store *metadata*.

        Blocks if the target slot is still held by consumers (backpressure).
        Returns the slot index that was written.
        """
        slot_idx = self.write_pos % self.num_slots

        # Wait until slot is free (ref_count == 0)
        with self._slot_released:
            while self.ref_counts[slot_idx] > 0:
                logger.debug("Backpressure on slot %d (ref_count=%d)",
                             slot_idx, self.ref_counts[slot_idx])
                self._slot_released.wait()

        # Resize buffer lazily if frame shape changed
        frame_shape = frame.shape
        if frame_shape != self._shape:
            self._reallocate(frame_shape)
            slot_idx = self.write_pos % self.num_slots

        np.copyto(self.frames[slot_idx], frame)
        self.metadata[slot_idx] = metadata
        self.ref_counts[slot_idx] = self.num_consumers
        self.write_pos += 1
        return slot_idx

    # -- Consumer API --------------------------------------------------------

    def get_view(self, slot_idx: int):
        """Return a *read-only* numpy view of the frame and its metadata.

        :returns: ``(frame_view, metadata)`` tuple.
        """
        view = self.frames[slot_idx]
        view = view.view()          # new view object so writeable flag is local
        view.flags.writeable = False
        return view, self.metadata[slot_idx]

    def release(self, slot_idx: int):
        """Signal that this consumer is done with *slot_idx*.

        When all consumers have released the slot it becomes available for
        reuse by the producer.
        """
        with self._slot_released:
            self.ref_counts[slot_idx] = max(0, self.ref_counts[slot_idx] - 1)
            if self.ref_counts[slot_idx] == 0:
                logger.debug("Slot %d fully released, notifying producer", slot_idx)
                self._slot_released.notify_all()

    # -- Configuration -------------------------------------------------------

    def set_num_consumers(self, n: int):
        """Update the expected consumer count for future publishes."""
        self.num_consumers = n

    # -- Internal ------------------------------------------------------------

    def _reallocate(self, new_shape):
        """Resize the internal buffer when frame dimensions change."""
        h, w, c = new_shape
        logger.info(
            "Reallocating FrameRingBuffer: %dx%dx%d -> %dx%dx%d",
            *self._shape, h, w, c,
        )
        self._shape = (h, w, c)
        self.frames = np.zeros((self.num_slots, h, w, c), dtype=np.uint8)
        self.metadata = [None] * self.num_slots
        self.ref_counts = [0] * self.num_slots
        self.write_pos = 0
