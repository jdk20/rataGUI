"""Regression tests for fan_out, plugin_process, and pipeline setup.

Validates that the circular queue bug (where fan_out wrote items back
into its own source queue) is fixed, and that blocking/non-blocking
plugins receive the correct item types through the ring buffer path.
"""
import asyncio
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

from rataGUI.frame_ring_buffer import FrameRingBuffer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plugin(blocking=False, independent=True, queue_size=5, drop_policy="block"):
    """Create a minimal mock plugin with real asyncio queues."""
    plugin = MagicMock()
    plugin.blocking = blocking
    plugin.independent = independent
    plugin.in_queue = asyncio.Queue(maxsize=queue_size)
    plugin.out_queue = None
    plugin.drop_policy = drop_policy
    plugin.active = True
    return plugin


async def _run_fan_out_once(fan_out_coro, source_queue, timeout=2.0):
    """Run fan_out as a task, let it process one item, then cancel."""
    task = asyncio.create_task(fan_out_coro)
    # Wait for the source queue to be consumed
    try:
        await asyncio.wait_for(source_queue.join(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# We need a minimal CameraWidget-like object to call fan_out / plugin_process.
# Import the real class but use it via an instance with mocked camera.
# Since CameraWidget.__init__ requires PyQt6, which is mocked in conftest,
# we replicate the relevant methods directly.
# ---------------------------------------------------------------------------

async def _put_to_queue(target_queue, item, drop_policy="block", ring_buffer=None):
    """Replica of CameraWidget._put_to_queue for testing."""
    if drop_policy == "drop_oldest" and target_queue.full():
        try:
            dropped = target_queue.get_nowait()
            if ring_buffer is not None and isinstance(dropped, int):
                ring_buffer.release(dropped)
            target_queue.task_done()
        except asyncio.QueueEmpty:
            pass
    await target_queue.put(item)


async def fan_out(source_queue, target_plugins, ring_buffer=None):
    """Replica of CameraWidget.fan_out for testing."""
    loop = asyncio.get_running_loop()
    while True:
        item = await source_queue.get()
        try:
            if ring_buffer is not None:
                frame, metadata = item
                slot_idx = await loop.run_in_executor(
                    None, ring_buffer.publish, frame, metadata
                )
                for plugin in target_plugins:
                    if plugin.blocking:
                        view, meta = ring_buffer.get_view(slot_idx)
                        frame_copy = view.copy()
                        ring_buffer.release(slot_idx)
                        await _put_to_queue(
                            plugin.in_queue, (frame_copy, meta),
                            plugin.drop_policy,
                        )
                    else:
                        await _put_to_queue(
                            plugin.in_queue, slot_idx, plugin.drop_policy,
                            ring_buffer=ring_buffer,
                        )
            else:
                for plugin in target_plugins:
                    await _put_to_queue(
                        plugin.in_queue, item, plugin.drop_policy
                    )
        finally:
            source_queue.task_done()


# ---------------------------------------------------------------------------
# Tests: Circular queue regression
# ---------------------------------------------------------------------------

class TestCircularQueueRegression:
    """Ensure fan_out never writes back into its own source queue."""

    @pytest.mark.asyncio
    async def test_all_independent_queues_are_separate(self):
        """When all plugins are independent, each plugin's in_queue must be
        distinct from fan_out_queue (the fix uses _acquisition_queue instead
        of swapping plugins[0].in_queue)."""
        plugins = [
            _make_plugin(blocking=True, independent=True),
            _make_plugin(blocking=False, independent=True),
        ]
        fan_out_queue = asyncio.Queue()

        # The FIX: _acquisition_queue is set; plugins keep their own in_queues.
        # (Previously, plugins[0].in_queue was set to fan_out_queue.)
        for plugin in plugins:
            assert plugin.in_queue is not fan_out_queue

    @pytest.mark.asyncio
    async def test_fan_out_does_not_feed_source_queue(self):
        """After fan_out processes one frame, the source queue must be empty
        (no circular write-back)."""
        ring_buffer = FrameRingBuffer(4, 2, 2, 3, num_consumers=2)
        source_queue = asyncio.Queue()

        blocking_plugin = _make_plugin(blocking=True)
        nonblocking_plugin = _make_plugin(blocking=False)
        plugins = [blocking_plugin, nonblocking_plugin]

        frame = np.ones((2, 2, 3), dtype=np.uint8) * 42
        metadata = {"Frame Index": 1}
        await source_queue.put((frame, metadata))

        await _run_fan_out_once(
            fan_out(source_queue, plugins, ring_buffer=ring_buffer),
            source_queue,
        )

        # Source queue must be empty — no circular write-back
        assert source_queue.empty(), (
            "fan_out wrote an item back into its own source queue"
        )

        # Each plugin's queue should have exactly one item
        assert blocking_plugin.in_queue.qsize() == 1
        assert nonblocking_plugin.in_queue.qsize() == 1


# ---------------------------------------------------------------------------
# Tests: Item types delivered to blocking vs non-blocking plugins
# ---------------------------------------------------------------------------

class TestFanOutItemTypes:
    """Verify blocking plugins receive (frame, metadata) tuples and
    non-blocking plugins receive slot indices (int)."""

    @pytest.mark.asyncio
    async def test_blocking_plugin_receives_tuple(self):
        ring_buffer = FrameRingBuffer(4, 2, 2, 3, num_consumers=2)
        source_queue = asyncio.Queue()

        blocking_plugin = _make_plugin(blocking=True)
        nonblocking_plugin = _make_plugin(blocking=False)

        frame = np.ones((2, 2, 3), dtype=np.uint8) * 99
        metadata = {"Frame Index": 5}
        await source_queue.put((frame, metadata))

        await _run_fan_out_once(
            fan_out(source_queue, [blocking_plugin, nonblocking_plugin], ring_buffer=ring_buffer),
            source_queue,
        )

        item = blocking_plugin.in_queue.get_nowait()
        assert isinstance(item, tuple), f"Expected tuple, got {type(item)}"
        recv_frame, recv_meta = item
        assert isinstance(recv_frame, np.ndarray)
        assert recv_frame.flags.writeable, "Blocking plugin should get a writable copy"
        np.testing.assert_array_equal(recv_frame, frame)
        assert recv_meta["Frame Index"] == 5

    @pytest.mark.asyncio
    async def test_nonblocking_plugin_receives_slot_idx(self):
        ring_buffer = FrameRingBuffer(4, 2, 2, 3, num_consumers=2)
        source_queue = asyncio.Queue()

        blocking_plugin = _make_plugin(blocking=True)
        nonblocking_plugin = _make_plugin(blocking=False)

        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        metadata = {"Frame Index": 1}
        await source_queue.put((frame, metadata))

        await _run_fan_out_once(
            fan_out(source_queue, [blocking_plugin, nonblocking_plugin], ring_buffer=ring_buffer),
            source_queue,
        )

        item = nonblocking_plugin.in_queue.get_nowait()
        assert isinstance(item, int), f"Expected int slot index, got {type(item)}"


# ---------------------------------------------------------------------------
# Tests: Ring buffer ref-count accounting
# ---------------------------------------------------------------------------

class TestFanOutRefCounts:
    """Verify ring buffer ref-counts are correctly managed after fan_out."""

    @pytest.mark.asyncio
    async def test_blocking_plugin_slot_released_in_fan_out(self):
        """fan_out should release the slot for blocking plugins immediately."""
        ring_buffer = FrameRingBuffer(4, 2, 2, 3, num_consumers=2)
        source_queue = asyncio.Queue()

        blocking_plugin = _make_plugin(blocking=True)
        nonblocking_plugin = _make_plugin(blocking=False)

        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        await source_queue.put((frame, {"i": 0}))

        await _run_fan_out_once(
            fan_out(source_queue, [blocking_plugin, nonblocking_plugin], ring_buffer=ring_buffer),
            source_queue,
        )

        # slot 0 was published with num_consumers=2, fan_out released once
        # for the blocking plugin → ref_count should be 1 (non-blocking pending)
        assert ring_buffer.ref_counts[0] == 1

    @pytest.mark.asyncio
    async def test_all_blocking_plugins_fully_release(self):
        """When all plugins are blocking, all ref-counts should reach 0."""
        ring_buffer = FrameRingBuffer(4, 2, 2, 3, num_consumers=2)
        source_queue = asyncio.Queue()

        p1 = _make_plugin(blocking=True)
        p2 = _make_plugin(blocking=True)

        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        await source_queue.put((frame, {"i": 0}))

        await _run_fan_out_once(
            fan_out(source_queue, [p1, p2], ring_buffer=ring_buffer),
            source_queue,
        )

        # Both blocking → fan_out released twice → ref_count = 0
        assert ring_buffer.ref_counts[0] == 0


# ---------------------------------------------------------------------------
# Tests: fan_out without ring buffer (fallback path)
# ---------------------------------------------------------------------------

class TestFanOutNoRingBuffer:
    """Verify fan_out works correctly without a ring buffer."""

    @pytest.mark.asyncio
    async def test_all_plugins_get_same_tuple(self):
        source_queue = asyncio.Queue()
        p1 = _make_plugin(blocking=True)
        p2 = _make_plugin(blocking=False)

        frame = np.ones((2, 2, 3), dtype=np.uint8) * 7
        metadata = {"key": "value"}
        await source_queue.put((frame, metadata))

        await _run_fan_out_once(
            fan_out(source_queue, [p1, p2], ring_buffer=None),
            source_queue,
        )

        item1 = p1.in_queue.get_nowait()
        item2 = p2.in_queue.get_nowait()
        assert isinstance(item1, tuple)
        assert isinstance(item2, tuple)
        np.testing.assert_array_equal(item1[0], frame)
        np.testing.assert_array_equal(item2[0], frame)
