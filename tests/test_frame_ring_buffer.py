import threading
import time

import numpy as np

from rataGUI.frame_ring_buffer import FrameRingBuffer


class TestFrameRingBufferInit:
    def test_allocates_correct_shape(self):
        buf = FrameRingBuffer(4, 480, 640, 3, num_consumers=2)
        assert buf.frames.shape == (4, 480, 640, 3)
        assert buf.frames.dtype == np.uint8

    def test_initial_state(self):
        buf = FrameRingBuffer(4, 480, 640, 3, num_consumers=2)
        assert buf.write_pos == 0
        assert buf.num_consumers == 2
        assert all(rc == 0 for rc in buf.ref_counts)


class TestPublishAndGetView:
    def test_publish_returns_slot_index(self):
        buf = FrameRingBuffer(4, 2, 2, 3, num_consumers=1)
        frame = np.ones((2, 2, 3), dtype=np.uint8) * 42
        idx = buf.publish(frame, {"key": "value"})
        assert idx == 0

    def test_get_view_returns_correct_data(self):
        buf = FrameRingBuffer(4, 2, 2, 3, num_consumers=1)
        frame = np.ones((2, 2, 3), dtype=np.uint8) * 42
        meta = {"Frame Index": 1}
        idx = buf.publish(frame, meta)
        view, view_meta = buf.get_view(idx)
        np.testing.assert_array_equal(view, frame)
        assert view_meta["Frame Index"] == 1

    def test_view_is_read_only(self):
        buf = FrameRingBuffer(4, 2, 2, 3, num_consumers=1)
        frame = np.ones((2, 2, 3), dtype=np.uint8)
        idx = buf.publish(frame, {})
        view, _ = buf.get_view(idx)
        assert not view.flags.writeable

    def test_view_is_zero_copy(self):
        buf = FrameRingBuffer(4, 2, 2, 3, num_consumers=1)
        frame = np.ones((2, 2, 3), dtype=np.uint8) * 99
        idx = buf.publish(frame, {})
        view, _ = buf.get_view(idx)
        # View should share memory with the internal buffer
        assert view.base is not None  # it's a view, not an owner


class TestRefCountLifecycle:
    def test_ref_count_set_on_publish(self):
        buf = FrameRingBuffer(4, 2, 2, 3, num_consumers=3)
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        idx = buf.publish(frame, {})
        assert buf.ref_counts[idx] == 3

    def test_release_decrements_ref_count(self):
        buf = FrameRingBuffer(4, 2, 2, 3, num_consumers=3)
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        idx = buf.publish(frame, {})
        buf.release(idx)
        assert buf.ref_counts[idx] == 2
        buf.release(idx)
        assert buf.ref_counts[idx] == 1
        buf.release(idx)
        assert buf.ref_counts[idx] == 0

    def test_release_does_not_go_negative(self):
        buf = FrameRingBuffer(4, 2, 2, 3, num_consumers=1)
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        idx = buf.publish(frame, {})
        buf.release(idx)
        buf.release(idx)  # extra release
        assert buf.ref_counts[idx] == 0


class TestRingWraparound:
    def test_wraps_around(self):
        buf = FrameRingBuffer(3, 2, 2, 3, num_consumers=1)
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        indices = []
        for i in range(6):
            idx = buf.publish(frame, {"i": i})
            indices.append(idx)
            buf.release(idx)  # free slot for reuse
        assert indices == [0, 1, 2, 0, 1, 2]

    def test_write_pos_increments(self):
        buf = FrameRingBuffer(3, 2, 2, 3, num_consumers=1)
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        for i in range(5):
            idx = buf.publish(frame, {})
            buf.release(idx)
        assert buf.write_pos == 5


class TestBackpressure:
    def test_blocks_when_slot_occupied(self):
        buf = FrameRingBuffer(2, 2, 2, 3, num_consumers=1)
        frame = np.zeros((2, 2, 3), dtype=np.uint8)

        # Fill both slots without releasing
        buf.publish(frame, {})
        buf.publish(frame, {})

        # Next publish should block; use a thread to test
        published = threading.Event()

        def delayed_publish():
            buf.publish(frame, {})
            published.set()

        t = threading.Thread(target=delayed_publish, daemon=True)
        t.start()

        # Should NOT be published yet (both slots occupied)
        time.sleep(0.05)
        assert not published.is_set()

        # Release slot 0 — publish should unblock
        buf.release(0)
        t.join(timeout=2)
        assert published.is_set()


class TestLazyReallocation:
    def test_realloc_on_shape_change(self):
        buf = FrameRingBuffer(4, 2, 2, 3, num_consumers=1)
        assert buf.frames.shape == (4, 2, 2, 3)

        # Publish a frame with different shape triggers reallocation
        new_frame = np.ones((4, 6, 3), dtype=np.uint8) * 55
        idx = buf.publish(new_frame, {"resized": True})
        assert buf.frames.shape == (4, 4, 6, 3)
        view, meta = buf.get_view(idx)
        np.testing.assert_array_equal(view, new_frame)
        assert meta["resized"] is True


class TestSetNumConsumers:
    def test_updates_consumer_count(self):
        buf = FrameRingBuffer(4, 2, 2, 3, num_consumers=1)
        buf.set_num_consumers(5)
        assert buf.num_consumers == 5

        # New publishes use updated count
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        idx = buf.publish(frame, {})
        assert buf.ref_counts[idx] == 5


class TestConcurrentRefCounts:
    def test_concurrent_release_from_multiple_threads(self):
        """Multiple threads releasing the same slot must not race."""
        num_threads = 4
        buf = FrameRingBuffer(4, 2, 2, 3, num_consumers=num_threads)
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        idx = buf.publish(frame, {})
        assert buf.ref_counts[idx] == num_threads

        barrier = threading.Barrier(num_threads)

        def release_one():
            barrier.wait()
            buf.release(idx)

        threads = [threading.Thread(target=release_one) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert buf.ref_counts[idx] == 0

    def test_publish_blocks_until_all_consumers_release(self):
        """With a full ring, publish must block until consumers free a slot."""
        buf = FrameRingBuffer(2, 2, 2, 3, num_consumers=2)
        frame = np.zeros((2, 2, 3), dtype=np.uint8)

        # Fill both slots
        buf.publish(frame, {"i": 0})
        buf.publish(frame, {"i": 1})

        published = threading.Event()

        def delayed_publish():
            buf.publish(frame, {"i": 2})
            published.set()

        t = threading.Thread(target=delayed_publish, daemon=True)
        t.start()

        # Should still be blocked (both slots held by 2 consumers each)
        time.sleep(0.05)
        assert not published.is_set()

        # Release slot 0 once — still blocked (ref_count=1)
        buf.release(0)
        time.sleep(0.05)
        assert not published.is_set()

        # Release slot 0 again — now free (ref_count=0), publish should unblock
        buf.release(0)
        t.join(timeout=2)
        assert published.is_set()


class TestMetadata:
    def test_metadata_stored_per_slot(self):
        buf = FrameRingBuffer(3, 2, 2, 3, num_consumers=1)
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        buf.publish(frame, {"slot": "A"})
        buf.release(0)
        buf.publish(frame, {"slot": "B"})
        buf.release(1)
        buf.publish(frame, {"slot": "C"})
        buf.release(2)

        _, meta_a = buf.get_view(0)
        _, meta_b = buf.get_view(1)
        _, meta_c = buf.get_view(2)
        assert meta_a["slot"] == "A"
        assert meta_b["slot"] == "B"
        assert meta_c["slot"] == "C"
