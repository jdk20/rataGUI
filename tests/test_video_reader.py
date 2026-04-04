import numpy as np
from unittest.mock import patch, MagicMock
from rataGUI.cameras.VideoReader import VideoReader


class TestVideoReaderInit:
    def test_init(self):
        vr = VideoReader("Video Reader 1")
        assert vr.last_frame is None
        assert vr.file_path == ""
        assert vr.cameraID == "Video Reader 1"

    def test_get_available_cameras(self):
        cameras = VideoReader.getAvailableCameras()
        assert len(cameras) == 1
        assert isinstance(cameras[0], VideoReader)


class TestVideoReaderInitializeCamera:
    @patch("rataGUI.cameras.VideoReader.cv2")
    def test_success(self, mock_cv2):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cv2.VideoCapture.return_value = mock_cap

        vr = VideoReader("vr1")
        config = MagicMock()
        config.as_dict.return_value = {"File path": "/fake/video.mp4"}
        result = vr.initializeCamera(config)

        assert result is True
        assert vr._running is True
        assert vr._stream is mock_cap

    @patch("rataGUI.cameras.VideoReader.cv2")
    def test_failure(self, mock_cv2):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        mock_cv2.VideoCapture.return_value = mock_cap

        vr = VideoReader("vr1")
        config = MagicMock()
        config.as_dict.return_value = {"File path": "/nonexistent.mp4"}
        result = vr.initializeCamera(config)

        assert result is False
        assert vr._running is False
        mock_cap.release.assert_called_once()


class TestVideoReaderReadCamera:
    def test_read_rgb(self):
        vr = VideoReader("vr1")
        mock_stream = MagicMock()
        fake_frame = np.ones((480, 640, 3), dtype=np.uint8)
        mock_stream.read.return_value = (True, fake_frame)
        vr._stream = mock_stream

        with patch("rataGUI.cameras.VideoReader.cv2") as mock_cv2:
            converted = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cv2.cvtColor.return_value = converted
            mock_cv2.COLOR_BGR2RGB = 4

            ret, frame = vr.readCamera(colorspace="RGB")

            assert ret is True
            assert vr.frames_acquired == 1
            mock_cv2.cvtColor.assert_called_once_with(fake_frame, 4)

    def test_read_gray(self):
        vr = VideoReader("vr1")
        mock_stream = MagicMock()
        fake_frame = np.ones((480, 640, 3), dtype=np.uint8)
        mock_stream.read.return_value = (True, fake_frame)
        vr._stream = mock_stream

        with patch("rataGUI.cameras.VideoReader.cv2") as mock_cv2:
            converted = np.zeros((480, 640), dtype=np.uint8)
            mock_cv2.cvtColor.return_value = converted
            mock_cv2.COLOR_BGR2GRAY = 6

            ret, frame = vr.readCamera(colorspace="GRAY")

            assert ret is True
            mock_cv2.cvtColor.assert_called_once_with(fake_frame, 6)

    def test_read_bgr_passthrough(self):
        vr = VideoReader("vr1")
        mock_stream = MagicMock()
        fake_frame = np.ones((480, 640, 3), dtype=np.uint8)
        mock_stream.read.return_value = (True, fake_frame)
        vr._stream = mock_stream

        ret, frame = vr.readCamera(colorspace="BGR")

        assert ret is True
        assert frame is fake_frame

    def test_read_failure(self):
        vr = VideoReader("vr1")
        mock_stream = MagicMock()
        mock_stream.read.return_value = (False, None)
        vr._stream = mock_stream
        vr.last_frame = "previous"

        ret, frame = vr.readCamera()

        assert ret is False
        assert frame == "previous"
        assert vr.frames_acquired == 0


class TestVideoReaderCloseCamera:
    def test_close(self):
        vr = VideoReader("vr1")
        vr._stream = MagicMock()
        vr._running = True

        vr.closeCamera()

        vr._stream.release.assert_called_once()
        assert vr._running is False

    def test_close_no_stream(self):
        vr = VideoReader("vr1")
        vr._stream = None

        vr.closeCamera()
        assert vr._running is False
