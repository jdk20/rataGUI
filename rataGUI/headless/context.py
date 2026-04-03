"""Duck-type replacements for Qt objects used in headless mode."""

from __future__ import annotations

import os
import json
import shutil
import logging
from typing import Any

from rataGUI import __version__
from rataGUI.utils import slugify

logger = logging.getLogger(__name__)


class HeadlessConfigManager:
    """Minimal dict-backed replacement for pyqtconfig.ConfigManager.

    Supports the same interface that cameras, plugins, and triggers use:
    ``get``, ``as_dict``, ``set``, ``set_defaults``, ``set_many``.
    """

    def __init__(self, data: dict | None = None):
        """Initialize the config manager with an optional starting dict."""
        self._data = dict(data) if data else {}

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for *key*, or *default* if not present."""
        return self._data.get(key, default)

    def as_dict(self) -> dict:
        """Return a shallow copy of the current configuration as a plain dict."""
        return dict(self._data)

    def set(self, key: str, value: Any) -> None:
        """Set a single configuration key to *value*."""
        self._data[key] = value

    def set_defaults(self, defaults: dict) -> None:
        """Set defaults, normalizing DEFAULT_CONFIG value types.

        Mirrors the normalization in ``main_window.py:add_config_handler``:
        - ``list`` -> first element (dropdown default)
        - ``tuple(value, min, max)`` -> ``value`` (spinbox default)
        - ``dict{name: value}`` -> value of first key (radio default)
        """
        for key, value in defaults.items():
            if key in self._data:
                continue  # User-provided value takes precedence
            if isinstance(value, list):
                self._data[key] = value[0] if value else None
            elif isinstance(value, tuple):
                self._data[key] = value[0]
            elif isinstance(value, dict):
                # Radio-button style: {name: value, ...} — use first key's value
                first_key = next(iter(value), None)
                self._data[key] = value[first_key] if first_key is not None else None
            else:
                self._data[key] = value

    def set_many(self, d: dict) -> None:
        """Bulk-update configuration from a dict."""
        self._data.update(d)


class PipelineContext:
    """Lightweight replacement for CameraWidget passed to plugins as ``cam_widget``.

    Satisfies the duck-type interface that all non-display plugins use:
    ``camera``, ``camera_config``, ``save_dir``, ``triggers``, ``camera_type``.
    """

    def __init__(
        self,
        camera,
        camera_config: HeadlessConfigManager,
        save_dir: str,
        triggers: list,
        session_dir: str = "",
    ):
        """Initialize a lightweight pipeline context for headless operation.

        :param camera: Camera instance to acquire frames from.
        :param camera_config: HeadlessConfigManager with camera settings.
        :param save_dir: Directory for this camera's output data.
        :param triggers: List of initialized trigger objects.
        :param session_dir: Root session directory containing all camera outputs.
        """
        self.camera = camera
        self.camera_type = type(camera).__name__
        self.camera_config = camera_config
        self.triggers = triggers

        self.session_dir = session_dir
        self.save_dir = save_dir
        os.makedirs(self.save_dir, exist_ok=True)

        self.plugins = []
        self.plugin_names = []
        self.failed_plugins = {}

        self.avg_latency = 0
        self.active = True
        self.multiprocess = False

        # Multiprocess resources (initialised lazily by runner)
        self._acquisition_queue = None
        self._mp_process = None
        self._mp_shm = None
        self._mp_shm_frames = None
        self._mp_meta_queue = None
        self._mp_control_queue = None
        self._mp_error_queue = None

    def stop_camera_pipeline(self) -> None:
        """Signal the pipeline to stop."""
        self.camera._running = False
        self.active = False
        if self._mp_control_queue is not None:
            try:
                self._mp_control_queue.put("stop")
            except Exception:
                pass
        self.clean_session_dir()

    def save_widget_data(self) -> None:
        """Log pipeline metadata to JSON file."""
        metadata = {}
        metadata["RataGUI Version"] = __version__
        metadata["Session Directory"] = self.session_dir
        metadata["Camera ID"] = str(self.camera.cameraID)
        metadata["Display Name"] = str(self.camera.display_name)
        metadata["Camera Type"] = self.camera_type
        metadata["Frames Acquired"] = str(self.camera.frames_acquired)
        metadata["Camera Settings"] = self.camera_config.as_dict()
        active_plugins = {}
        disabled_plugins = {}
        for name, plugin in zip(self.plugin_names, self.plugins):
            if plugin.active:
                active_plugins[name] = plugin.config
            else:
                disabled_plugins[name] = plugin.config
        metadata["Active Plugins"] = active_plugins
        metadata["Disabled Plugins"] = disabled_plugins
        metadata["Failed Plugins"] = self.failed_plugins
        metadata["Enabled Triggers"] = [str(trig.deviceID) for trig in self.triggers]

        file_path = os.path.join(
            self.save_dir, slugify(self.camera.getDisplayName()) + "_metadata.json"
        )
        with open(file_path, "w") as file:
            json.dump(metadata, file, indent=2)

    def clean_session_dir(self) -> None:
        """Remove save_dir if it contains only the metadata file or is empty."""
        if os.path.isdir(self.save_dir):
            dir_list = os.listdir(self.save_dir)
            metadata_file = slugify(self.camera.getDisplayName()) + "_metadata.json"
            if len(dir_list) == 0 or (
                len(dir_list) == 1 and metadata_file == dir_list[0]
            ):
                shutil.rmtree(self.save_dir)

                sess_dir_list = (
                    os.listdir(self.session_dir)
                    if os.path.isdir(self.session_dir)
                    else []
                )
                if len(sess_dir_list) == 0 or (
                    len(sess_dir_list) == 1 and "settings" == sess_dir_list[0]
                ):
                    shutil.rmtree(self.session_dir, ignore_errors=True)
            else:
                self.save_widget_data()
