import sys
from unittest.mock import MagicMock

# Mock PyQt6 and pyqtconfig before any rataGUI module imports them.
# This allows tests to run headlessly without native Qt libraries.
_qt_modules = [
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "pyqtconfig",
]
for mod_name in _qt_modules:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import pytest
import numpy as np
from datetime import datetime


@pytest.fixture
def sample_frame():
    """A 480x640 RGB uint8 frame."""
    return np.zeros((480, 640, 3), dtype=np.uint8)


@pytest.fixture
def sample_metadata():
    """Typical metadata dict passed through the plugin pipeline."""
    return {
        "Frame Index": 1,
        "Timestamp": datetime(2024, 1, 15, 12, 30, 45, 123456),
        "Camera Name": "TestCam",
    }


@pytest.fixture
def mock_cam_widget(tmp_path):
    """Mock camera widget with save_dir, camera, and triggers."""
    widget = MagicMock()
    widget.save_dir = str(tmp_path)
    widget.camera.getDisplayName.return_value = "TestCam"
    widget.camera_config = MagicMock()
    widget.triggers = []
    return widget


@pytest.fixture
def mock_config_manager():
    """Factory fixture to create a mock ConfigManager with a given config dict."""
    def _make(config_dict):
        config = MagicMock()
        config.as_dict.return_value = dict(config_dict)
        config.get.side_effect = lambda key, default=None: config_dict.get(key, default)
        config.set = MagicMock()
        return config
    return _make
