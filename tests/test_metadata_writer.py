import os
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime
from rataGUI.plugins.metadata_writer import MetadataWriter


@pytest.fixture
def writer_config_all_off(mock_config_manager):
    return mock_config_manager({
        "Overlay Frame Index": False,
        "Abbreviate": False,
        "Overlay Timestamp": False,
        "Include date": False,
        "Overlay Camera Name": False,
    })


@pytest.fixture
def writer_config_all_on(mock_config_manager):
    return mock_config_manager({
        "Overlay Frame Index": True,
        "Abbreviate": False,
        "Overlay Timestamp": True,
        "Include date": False,
        "Overlay Camera Name": True,
    })


@pytest.fixture
def metadata_writer(mock_cam_widget, writer_config_all_off):
    return MetadataWriter(mock_cam_widget, writer_config_all_off)


class TestMetadataWriterInit:
    def test_creates_file_path(self, metadata_writer, mock_cam_widget):
        expected = os.path.join(mock_cam_widget.save_dir, "timestamps.csv")
        assert metadata_writer.file_path == expected

    def test_active_by_default(self, metadata_writer):
        assert metadata_writer.active is True


class TestMetadataWriterProcess:
    def test_writes_csv(self, metadata_writer, sample_frame, sample_metadata):
        metadata_writer.process(sample_frame, sample_metadata)

        with open(metadata_writer.file_path, "r") as f:
            content = f.read()
        assert "1," in content  # Frame Index
        assert str(sample_metadata["Timestamp"].timestamp()) in content

    def test_csv_appends(self, metadata_writer, sample_frame, sample_metadata):
        metadata_writer.process(sample_frame, sample_metadata)
        sample_metadata["Frame Index"] = 2
        metadata_writer.process(sample_frame, sample_metadata)

        with open(metadata_writer.file_path, "r") as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_no_overlay_returns_frame(self, metadata_writer, sample_frame, sample_metadata):
        original = sample_frame.copy()
        result_frame, result_metadata = metadata_writer.process(sample_frame, sample_metadata)

        assert result_metadata is sample_metadata
        assert isinstance(result_frame, np.ndarray)

    @patch("rataGUI.plugins.metadata_writer.cv2")
    def test_overlay_frame_index(self, mock_cv2, mock_cam_widget, mock_config_manager,
                                  sample_frame, sample_metadata):
        mock_cv2.getTextSize.return_value = ((100, 20), 0)
        mock_cv2.FONT_HERSHEY_SIMPLEX = 0
        mock_cv2.LINE_4 = 4
        mock_cv2.FILLED = -1

        config = mock_config_manager({
            "Overlay Frame Index": True,
            "Abbreviate": False,
            "Overlay Timestamp": False,
            "Include date": False,
            "Overlay Camera Name": False,
        })
        writer = MetadataWriter(mock_cam_widget, config)
        writer.process(sample_frame, sample_metadata)

        mock_cv2.putText.assert_called_once()
        call_args = mock_cv2.putText.call_args
        assert "Frame Index" in call_args[0][1]

    @patch("rataGUI.plugins.metadata_writer.cv2")
    def test_overlay_timestamp_without_date(self, mock_cv2, mock_cam_widget,
                                             mock_config_manager, sample_frame, sample_metadata):
        mock_cv2.getTextSize.return_value = ((100, 20), 0)
        mock_cv2.FONT_HERSHEY_SIMPLEX = 0
        mock_cv2.LINE_4 = 4
        mock_cv2.FILLED = -1

        config = mock_config_manager({
            "Overlay Frame Index": False,
            "Abbreviate": False,
            "Overlay Timestamp": True,
            "Include date": False,
            "Overlay Camera Name": False,
        })
        writer = MetadataWriter(mock_cam_widget, config)
        writer.process(sample_frame, sample_metadata)

        call_args = mock_cv2.putText.call_args
        overlay_text = call_args[0][1]
        # Should be time only (no date), format: HH:MM:SS.ffffff
        assert ":" in overlay_text
        assert "/" not in overlay_text

    @patch("rataGUI.plugins.metadata_writer.cv2")
    def test_overlay_timestamp_with_date(self, mock_cv2, mock_cam_widget,
                                          mock_config_manager, sample_frame, sample_metadata):
        mock_cv2.getTextSize.return_value = ((100, 20), 0)
        mock_cv2.FONT_HERSHEY_SIMPLEX = 0
        mock_cv2.LINE_4 = 4
        mock_cv2.FILLED = -1

        config = mock_config_manager({
            "Overlay Frame Index": False,
            "Abbreviate": False,
            "Overlay Timestamp": True,
            "Include date": True,
            "Overlay Camera Name": False,
        })
        writer = MetadataWriter(mock_cam_widget, config)
        writer.process(sample_frame, sample_metadata)

        call_args = mock_cv2.putText.call_args
        overlay_text = call_args[0][1]
        # Should include date: MM/DD/YY-HH:MM:SS.ffffff
        assert "/" in overlay_text

    @patch("rataGUI.plugins.metadata_writer.cv2")
    def test_abbreviate_names(self, mock_cv2, mock_cam_widget,
                               mock_config_manager, sample_frame, sample_metadata):
        mock_cv2.getTextSize.return_value = ((100, 20), 0)
        mock_cv2.FONT_HERSHEY_SIMPLEX = 0
        mock_cv2.LINE_4 = 4
        mock_cv2.FILLED = -1

        config = mock_config_manager({
            "Overlay Frame Index": True,
            "Abbreviate": True,
            "Overlay Timestamp": False,
            "Include date": False,
            "Overlay Camera Name": False,
        })
        writer = MetadataWriter(mock_cam_widget, config)
        writer.process(sample_frame, sample_metadata)

        call_args = mock_cv2.putText.call_args
        overlay_text = call_args[0][1]
        # "Frame Index" abbreviated to "FI"
        assert "FI" in overlay_text


class TestMetadataWriterClose:
    def test_close(self, metadata_writer):
        metadata_writer.close()
        assert metadata_writer.active is False
