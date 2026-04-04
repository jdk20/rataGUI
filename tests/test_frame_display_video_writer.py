"""Tests for concurrent VideoWriter + FrameDisplay operation.

Validates the QImage use-after-free fix (QImage.copy()), concurrent
fan_out behaviour with mixed blocking/non-blocking plugins, and video
file integrity via the real ffmpeg binary.
"""

import asyncio
import os
import sys
from shutil import which
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from rataGUI.frame_ring_buffer import FrameRingBuffer


# ---------------------------------------------------------------------------
# Helpers (replicated from test_fan_out.py to keep tests self-contained)
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
                            plugin.in_queue,
                            (frame_copy, meta),
                            plugin.drop_policy,
                        )
                    else:
                        await _put_to_queue(
                            plugin.in_queue,
                            slot_idx,
                            plugin.drop_policy,
                            ring_buffer=ring_buffer,
                        )
            else:
                for plugin in target_plugins:
                    await _put_to_queue(plugin.in_queue, item, plugin.drop_policy)
        finally:
            source_queue.task_done()


async def _run_fan_out_n(fan_out_coro, source_queue, n_items, timeout=5.0):
    """Run fan_out as a task, let it process *n_items*, then cancel."""
    task = asyncio.create_task(fan_out_coro)
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
# Tests: QImage data ownership (validates the .copy() fix)
# ---------------------------------------------------------------------------


class TestQImageDataOwnership:
    """Verify that QImage.copy() produces data independent of the ring buffer."""

    def test_copied_data_survives_ring_buffer_overwrite(self):
        """After .copy(), the numpy data snapshot must not reflect ring buffer
        overwrites — simulating what the fixed FrameDisplay does."""
        ring = FrameRingBuffer(2, 4, 4, 3, num_consumers=1)

        # Publish frame A (all 42s) to slot 0
        frame_a = np.full((4, 4, 3), 42, dtype=np.uint8)
        idx = ring.publish(frame_a, {"i": 0})

        # Simulate FrameDisplay: get view, copy the data
        view, _ = ring.get_view(idx)
        snapshot = view.copy()  # equivalent to QImage.copy() owning its data

        # Release slot 0 and fill slot 1 so ring wraps around
        ring.release(idx)
        frame_fill = np.full((4, 4, 3), 77, dtype=np.uint8)
        idx_b = ring.publish(frame_fill, {"i": 1})
        ring.release(idx_b)

        # Publish again — wraps to slot 0, overwriting the original data
        frame_overwrite = np.full((4, 4, 3), 99, dtype=np.uint8)
        ring.publish(frame_overwrite, {"i": 2})

        # The snapshot must still contain frame A despite slot 0 being overwritten
        np.testing.assert_array_equal(snapshot, frame_a)
        assert snapshot.mean() == 42

    def test_raw_view_sees_overwrite_without_copy(self):
        """Demonstrate the bug: a raw numpy view IS corrupted when the ring
        buffer slot is overwritten.  This proves the fix is necessary."""
        ring = FrameRingBuffer(2, 4, 4, 3, num_consumers=1)

        # Publish frame A to slot 0
        frame_a = np.full((4, 4, 3), 42, dtype=np.uint8)
        idx_a = ring.publish(frame_a, {"i": 0})
        assert idx_a == 0

        view, _ = ring.get_view(idx_a)
        # Intentionally do NOT copy — hold a read-only view
        raw_view = view

        # Release slot 0 so it can be reused
        ring.release(idx_a)

        # Publish to slot 1 (fills remaining slot)
        frame_fill = np.full((4, 4, 3), 77, dtype=np.uint8)
        idx_b = ring.publish(frame_fill, {"i": 1})
        ring.release(idx_b)

        # Publish again — wraps around to slot 0, overwriting frame A
        frame_overwrite = np.full((4, 4, 3), 99, dtype=np.uint8)
        idx_c = ring.publish(frame_overwrite, {"i": 2})
        assert idx_c == 0  # confirms slot 0 was reused

        # The raw view now reflects the overwritten data
        assert raw_view.mean() == 99, (
            "Expected raw view to be corrupted by overwrite (demonstrating the bug)"
        )


# ---------------------------------------------------------------------------
# Tests: Concurrent fan_out with blocking + non-blocking plugins
# ---------------------------------------------------------------------------


class TestConcurrentFanOutBothPlugins:
    """Validate fan_out + plugin_process with both plugin types simultaneously."""

    @pytest.mark.asyncio
    async def test_both_plugins_receive_all_frames(self):
        """Fan_out N frames; both blocking and non-blocking plugins get all N."""
        n_frames = 5
        ring = FrameRingBuffer(8, 4, 4, 3, num_consumers=2)
        source = asyncio.Queue()

        blocking = _make_plugin(blocking=True, queue_size=n_frames + 2)
        nonblocking = _make_plugin(blocking=False, queue_size=n_frames + 2)

        for i in range(n_frames):
            frame = np.full((4, 4, 3), i, dtype=np.uint8)
            await source.put((frame, {"Frame Index": i}))

        await _run_fan_out_n(
            fan_out(source, [blocking, nonblocking], ring_buffer=ring),
            source,
            n_frames,
        )

        assert blocking.in_queue.qsize() == n_frames
        assert nonblocking.in_queue.qsize() == n_frames

    @pytest.mark.asyncio
    async def test_ref_counts_correct_mixed_plugins(self):
        """After fan_out, blocking plugin ref released (count=1),
        non-blocking still pending."""
        ring = FrameRingBuffer(4, 4, 4, 3, num_consumers=2)
        source = asyncio.Queue()

        blocking = _make_plugin(blocking=True)
        nonblocking = _make_plugin(blocking=False)

        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        await source.put((frame, {"i": 0}))

        await _run_fan_out_n(
            fan_out(source, [blocking, nonblocking], ring_buffer=ring),
            source,
            1,
        )

        # Blocking plugin's ref was released in fan_out; non-blocking still holds
        assert ring.ref_counts[0] == 1

        # Simulate non-blocking plugin releasing its slot
        ring.release(0)
        assert ring.ref_counts[0] == 0

    @pytest.mark.asyncio
    async def test_blocking_plugin_gets_writable_copy(self):
        """Blocking plugin receives a writable frame copy, not a read-only view."""
        ring = FrameRingBuffer(4, 4, 4, 3, num_consumers=2)
        source = asyncio.Queue()

        blocking = _make_plugin(blocking=True)
        nonblocking = _make_plugin(blocking=False)

        frame = np.ones((4, 4, 3), dtype=np.uint8) * 77
        await source.put((frame, {"Frame Index": 1}))

        await _run_fan_out_n(
            fan_out(source, [blocking, nonblocking], ring_buffer=ring),
            source,
            1,
        )

        item = blocking.in_queue.get_nowait()
        recv_frame, recv_meta = item
        assert isinstance(recv_frame, np.ndarray)
        assert recv_frame.flags.writeable, "Blocking plugin must get a writable copy"
        np.testing.assert_array_equal(recv_frame, frame)

    @pytest.mark.asyncio
    async def test_nonblocking_plugin_receives_slot_index(self):
        """Non-blocking plugin receives an int slot index, not a tuple."""
        ring = FrameRingBuffer(4, 4, 4, 3, num_consumers=2)
        source = asyncio.Queue()

        blocking = _make_plugin(blocking=True)
        nonblocking = _make_plugin(blocking=False)

        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        await source.put((frame, {"i": 0}))

        await _run_fan_out_n(
            fan_out(source, [blocking, nonblocking], ring_buffer=ring),
            source,
            1,
        )

        item = nonblocking.in_queue.get_nowait()
        assert isinstance(item, int), f"Expected int slot index, got {type(item)}"

    @pytest.mark.asyncio
    async def test_multiple_frames_all_slots_freed(self):
        """After full consumption by both consumers, all ring buffer
        ref_counts must be 0.

        Uses a concurrent consumer that releases non-blocking slots so
        the ring buffer does not block on backpressure during fan_out.
        """
        n_frames = 10
        ring = FrameRingBuffer(4, 4, 4, 3, num_consumers=2)
        source = asyncio.Queue()

        blocking = _make_plugin(blocking=True, queue_size=n_frames + 2)
        nonblocking = _make_plugin(blocking=False, queue_size=n_frames + 2)

        for i in range(n_frames):
            frame = np.full((4, 4, 3), i % 256, dtype=np.uint8)
            await source.put((frame, {"Frame Index": i}))

        async def drain_nonblocking():
            """Simulates plugin_process draining the non-blocking queue."""
            consumed = 0
            while consumed < n_frames:
                slot_idx = await nonblocking.in_queue.get()
                ring.release(slot_idx)
                nonblocking.in_queue.task_done()
                consumed += 1

        # Run fan_out and consumer concurrently
        fan_out_task = asyncio.create_task(
            fan_out(source, [blocking, nonblocking], ring_buffer=ring)
        )
        drain_task = asyncio.create_task(drain_nonblocking())

        try:
            await asyncio.wait_for(
                asyncio.gather(source.join(), drain_task),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            pass
        finally:
            fan_out_task.cancel()
            try:
                await fan_out_task
            except asyncio.CancelledError:
                pass

        # All ref_counts should be 0
        assert all(rc == 0 for rc in ring.ref_counts), (
            f"Expected all ref_counts to be 0, got {ring.ref_counts}"
        )


# ---------------------------------------------------------------------------
# Tests: Video file integrity via real ffmpeg
# ---------------------------------------------------------------------------


def _find_ffmpeg():
    """Locate ffmpeg: check PATH first, then the conda environment's Library/bin."""
    path = which("ffmpeg")
    if path is not None:
        return path
    # On Windows/conda, ffmpeg lives in the env's Library/bin
    candidate = os.path.join(sys.prefix, "Library", "bin", "ffmpeg.exe")
    if os.path.isfile(candidate):
        return candidate
    return None


_FFMPEG_PATH = _find_ffmpeg()


@pytest.mark.skipif(_FFMPEG_PATH is None, reason="ffmpeg not found")
class TestVideoIntegrity:
    """Write video files via FFMPEG_Writer and verify integrity with cv2."""

    def _make_writer(self, file_path, codec="libx264", framerate=30, buffer_size=60):
        """Create an FFMPEG_Writer with reasonable test defaults."""
        from rataGUI.plugins.video_writer import FFMPEG_Writer

        # Patch which() so FFMPEG_Writer finds the conda env's ffmpeg
        with patch("rataGUI.plugins.video_writer.which", return_value=_FFMPEG_PATH):
            return FFMPEG_Writer(
                str(file_path),
                input_dict={"-framerate": str(framerate)},
                output_dict={
                    "-vcodec": codec,
                    "-preset": "ultrafast",
                    "-crf": "23",
                    "-pix_fmt": "yuv420p",
                },
                buffer_size=buffer_size,
            )

    def _make_gradient_frame(self, index, height=120, width=160, channels=3):
        """Generate a deterministic frame with a gradient pattern."""
        base = np.zeros((height, width, channels), dtype=np.uint8)
        # Horizontal gradient modulated by frame index
        for c in range(channels):
            base[:, :, c] = (np.arange(width)[None, :] + index * 7 + c * 30) % 256
        return base

    def test_ffmpeg_writer_produces_valid_video(self, tmp_path):
        """Write 30 frames, verify file exists, frame count, and dimensions."""
        import cv2

        n_frames = 30
        h, w = 120, 160

        file_path = tmp_path / "test_valid.mp4"
        writer = self._make_writer(file_path)

        for i in range(n_frames):
            writer.write_frame(self._make_gradient_frame(i, h, w))
        writer.close()

        assert file_path.exists()
        assert file_path.stat().st_size > 0

        cap = cv2.VideoCapture(str(file_path))
        try:
            assert cap.isOpened(), "cv2.VideoCapture failed to open video"

            # Verify frame count
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            assert count == n_frames, f"Expected {n_frames} frames, got {count}"

            # Verify dimensions of first frame
            ret, frame = cap.read()
            assert ret, "Failed to read first frame"
            assert frame.shape[:2] == (h, w), (
                f"Expected {(h, w)}, got {frame.shape[:2]}"
            )
        finally:
            cap.release()

    def test_ffmpeg_writer_frame_content_integrity(self, tmp_path):
        """Write known patterns, read back, verify within lossy tolerance."""
        import cv2

        n_frames = 10
        h, w = 120, 160

        file_path = tmp_path / "test_content.mp4"
        writer = self._make_writer(file_path)

        originals = []
        for i in range(n_frames):
            frame = self._make_gradient_frame(i, h, w)
            originals.append(frame.copy())
            writer.write_frame(frame)
        writer.close()

        cap = cv2.VideoCapture(str(file_path))
        try:
            for i in range(n_frames):
                ret, decoded = cap.read()
                assert ret, f"Failed to read frame {i}"
                # cv2 reads as BGR; our frames are RGB — convert for comparison
                decoded_rgb = cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)
                # Allow lossy compression tolerance (H.264 is lossy)
                diff = np.abs(originals[i].astype(int) - decoded_rgb.astype(int))
                mean_diff = diff.mean()
                assert mean_diff < 30, (
                    f"Frame {i}: mean pixel diff {mean_diff:.1f} exceeds tolerance"
                )
        finally:
            cap.release()

    def test_ffmpeg_writer_close_flushes_all_frames(self, tmp_path):
        """Closing the writer must flush all queued frames to the output."""
        import cv2

        n_frames = 50
        h, w = 60, 80

        file_path = tmp_path / "test_flush.mp4"
        writer = self._make_writer(file_path, buffer_size=120)

        for i in range(n_frames):
            frame = np.full((h, w, 3), i % 256, dtype=np.uint8)
            writer.write_frame(frame)
        writer.close()

        cap = cv2.VideoCapture(str(file_path))
        try:
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            assert count == n_frames, (
                f"Expected {n_frames} frames after flush, got {count}"
            )
        finally:
            cap.release()
