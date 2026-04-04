import os
import time
import json
from datetime import datetime
from collections import OrderedDict

from pyqtconfig import ConfigManager
from PyQt6 import QtWidgets, QtGui
from PyQt6.QtCore import Qt, QTimer

from rataGUI.interface.design.Ui_MainWindow import Ui_MainWindow
from rataGUI.interface.camera_widget import CameraWidget
from rataGUI import launch_config, rataGUI_icon, __version__

import logging

logger = logging.getLogger(__name__)


class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    """Main application window for RataGUI.

    Manages the lifecycle of cameras, plugins, and triggers through a tabbed
    Qt interface.  Provides UI for selecting, configuring, and running real-time
    video processing pipelines, and persists session settings to disk.

    :param camera_models: List of camera subclasses discovered at startup.
    :param plugins: List of plugin subclasses discovered at startup.
    :param trigger_types: List of trigger subclasses discovered at startup.
    :param dark_mode: If True, use dark colour scheme for status indicators.
    :param restore_dir: Path to a saved settings directory to restore on launch.
    """

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------

    def _camera_id_from_name(self, cam_name: str) -> str:
        """Look up the internal camera ID for a given display name.

        :param cam_name: Display name shown in the camera list.
        :return: Camera ID key used in ``self.cameras`` and related dicts.
        :raises ValueError: If no camera matches *cam_name*.
        """
        for cam_id, name in self.camera_names.items():
            if name == cam_name:
                return cam_id
        raise ValueError(f"No camera found with display name: {cam_name}")

    @staticmethod
    def _merge_and_save_json(path: str, new_entries: dict) -> None:
        """Load existing JSON from *path*, merge *new_entries*, and write back.

        Creates the file if it does not exist.

        :param path: File path to read from and write to.
        :param new_entries: Dict of key-value pairs to merge into the file.
        """
        existing = {}
        if os.path.isfile(path):
            with open(path, "r") as f:
                contents = f.read()
                if contents:
                    existing = json.loads(contents)
        existing.update(new_entries)
        with open(path, "w") as f:
            json.dump(existing, f, indent=2)

    @staticmethod
    def _load_json_if_exists(path: str) -> dict | None:
        """Load and return parsed JSON from *path*, or ``None`` if missing/empty.

        :param path: File path to a JSON file.
        :return: Parsed dict, or ``None``.
        """
        if os.path.isfile(path) and os.stat(path).st_size > 0:
            with open(path, "r") as f:
                return json.load(f)
        return None

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(
        self,
        camera_models=[],
        plugins=[],
        trigger_types=[],
        dark_mode=True,
        restore_dir="",
    ):
        super().__init__()
        self.setupUi(self)
        self.setWindowIcon(QtGui.QIcon(rataGUI_icon))

        # Set geometry relative to screen
        self.screen = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        x_pos = (self.screen.width() - self.width()) // 2
        y_pos = 3 * (self.screen.height() - self.height()) // 4
        self.move(x_pos, y_pos)

        # Configure color scheme
        if dark_mode:
            self.active_color = QtGui.QColorConstants.DarkMagenta
            self.paused_color = QtGui.QColorConstants.DarkGray
            self.failed_color = QtGui.QColorConstants.DarkRed
            self.inactive_color = QtGui.QColorConstants.Black
        else:
            self.active_color = QtGui.QColorConstants.Green
            self.paused_color = QtGui.QColorConstants.LightGray
            self.failed_color = QtGui.QColorConstants.Red
            self.inactive_color = QtGui.QColorConstants.DarkGray

        # Create mappings from camID to camera, widget, config and model
        self.cameras = {}
        self.camera_widgets = {}
        self.camera_configs = {}
        self.camera_names = OrderedDict()  # holds camera display name and order
        self.camera_models = {c.__name__: c for c in camera_models}
        self.populate_camera_list()
        self.populate_camera_properties()
        self.populate_camera_stats()

        # Create mappings from name to plugin class and configs
        self.plugins = OrderedDict([(p.__name__, p) for p in plugins])
        self.plugin_configs = {}
        self.populate_plugin_list()
        self.populate_plugin_settings()
        self.populate_plugin_pipeline()

        self.triggers = {}  # deviceID -> trigger object
        self.trigger_tabs = {}  # trigger type -> tab widget
        self.trigger_configs = {}  # added trigger -> config manager
        self.trigger_types = {t.__name__: t for t in trigger_types}
        self.populate_trigger_list()
        self.populate_trigger_settings()

        # Create camera widget and start pipeline
        self.start_button.clicked.connect(self.start_camera_widgets)
        self.start_button.setStyleSheet(
            "background-color: darkgreen; color: white; font-weight: bold"
        )

        # Pause camera and plugin pipeline
        self.pause_button.clicked.connect(self.pause_camera_widgets)
        self.pause_button.setStyleSheet(
            "background-color: grey; color: white; font-weight: bold"
        )

        # Close camera, stop pipeline and delete widget
        self.stop_button.clicked.connect(self.stop_camera_widgets)
        self.stop_button.setStyleSheet(
            "background-color: darkred; color: white; font-weight: bold"
        )

        # Load saved session config
        if os.path.isdir(restore_dir):
            self.restore_settings(restore_dir)

        # Update camera stats occasionally
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_camera_stats)
        self.update_timer.start(250)

    def update_camera_stats(self):
        """Refresh the camera statistics table with current frame counts, latency, and buffer sizes."""
        for row, camID in enumerate(self.camera_names.keys()):
            camera = self.cameras[camID]
            self.cam_stats.item(row, 0).setText(camera.getDisplayName())
            self.cam_stats.item(row, 1).setText(str(camera.frames_acquired))
            if hasattr(camera, "frames_dropped"):
                self.cam_stats.item(row, 2).setText(str(camera.frames_dropped))

            if hasattr(camera, "buffer_size"):
                self.cam_stats.item(row, 3).setText(str(camera.buffer_size))

            cam_widget = self.camera_widgets.get(camID)
            if cam_widget is not None:
                latency_str = str(round(cam_widget.avg_latency, 3)) + " ms"
                self.cam_stats.item(row, 4).setText(latency_str)

        self.update_plugin_pipeline()

    def update_plugin_pipeline(self):
        """Refresh plugin pipeline table to reflect runtime state changes."""
        for row, camID in enumerate(self.camera_names.keys()):
            widget = self.camera_widgets.get(camID)
            if widget is None:
                continue
            for col in range(self.plugin_pipeline.columnCount()):
                header = self.plugin_pipeline.horizontalHeaderItem(col)
                if header is None:
                    continue
                plugin_name = header.text()
                if plugin_name not in self.plugins:
                    continue

                item = self.plugin_pipeline.item(row, col)
                if item is None:
                    continue

                plugin_active = None
                plugin_failed = False
                for plugin in widget.plugins:
                    if isinstance(plugin, self.plugins[plugin_name]):
                        plugin_active = plugin.active
                        plugin_failed = getattr(plugin, "failed", False)
                        break

                if plugin_active is None:
                    # Check if this plugin failed during initialization
                    current_text = item.text()
                    if plugin_name in getattr(widget, 'failed_plugins', {}) and current_text != "Failed":
                        self.plugin_pipeline.blockSignals(True)
                        item.setText("Failed")
                        item.setBackground(self.failed_color)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                        self.plugin_pipeline.blockSignals(False)
                    continue

                current_text = item.text()
                if plugin_failed and current_text != "Failed":
                    self.plugin_pipeline.blockSignals(True)
                    item.setText("Failed")
                    item.setBackground(self.failed_color)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    self.plugin_pipeline.blockSignals(False)
                elif (
                    not plugin_active and not plugin_failed and current_text == "Active"
                ):
                    self.plugin_pipeline.blockSignals(True)
                    item.setText("Paused")
                    item.setCheckState(Qt.CheckState.Unchecked)
                    item.setBackground(self.paused_color)
                    self.plugin_pipeline.blockSignals(False)

    def populate_camera_stats(self):
        """Build the initial camera statistics table rows from discovered cameras."""
        self.cam_stats.setRowCount(len(self.cameras))
        for row, camID in enumerate(self.camera_names.keys()):
            camera = self.cameras[camID]
            name_item = QtWidgets.QTableWidgetItem(camera.getDisplayName())
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cam_stats.setItem(row, 0, name_item)

            stat_item = QtWidgets.QTableWidgetItem(str(camera.frames_acquired))
            stat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cam_stats.setItem(row, 1, stat_item)

            if hasattr(camera, "frames_dropped"):
                stat_item = QtWidgets.QTableWidgetItem(str(camera.frames_dropped))
                stat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.cam_stats.setItem(row, 2, stat_item)
            else:
                nan_item = QtWidgets.QTableWidgetItem("N/A")
                nan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.cam_stats.setItem(row, 2, nan_item)

            if hasattr(camera, "buffer_size"):
                stat_item = QtWidgets.QTableWidgetItem(str(camera.buffer_size))
                stat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.cam_stats.setItem(row, 3, stat_item)
            else:
                nan_item = QtWidgets.QTableWidgetItem("N/A")
                nan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.cam_stats.setItem(row, 3, nan_item)

            cam_widget = self.camera_widgets.get(camID)
            if cam_widget is not None:
                stat_item = QtWidgets.QTableWidgetItem(str(cam_widget.avg_latency))
                stat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.cam_stats.setItem(row, 4, stat_item)
            else:
                nan_item = QtWidgets.QTableWidgetItem("N/A")
                nan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.cam_stats.setItem(row, 4, nan_item)

        self.cam_stats.resizeColumnsToContents()

    def populate_camera_list(self):
        """Populate the camera list widget with discovered cameras and wire rename/check signals."""

        def rename_camera(item):
            new_name = item.text()
            cur_index = self.cam_list.currentRow()
            cur_item = self.cam_list.currentItem()
            if (
                cur_item is not None and new_name == cur_item.text()
            ):  # Ignore checkbox changes
                camID, prev_name = list(self.camera_names.items())[cur_index]
                if new_name in self.camera_names.values() and new_name != prev_name:
                    logger.warning("Display name is already used by another camera")
                    self.cam_list.itemChanged.disconnect(rename_camera)
                    item.setText(prev_name)
                    self.cam_list.itemChanged.connect(rename_camera)
                else:
                    self.camera_names[camID] = new_name
                    self.cameras[camID].display_name = new_name
                    for i in range(self.cam_props.count()):
                        if self.cam_props.tabText(i) == prev_name:
                            self.cam_props.setTabText(i, new_name)
                            break
            self.populate_plugin_pipeline()

        self.cam_list.clear()
        self.cam_list.setItemAlignment(Qt.AlignmentFlag.AlignTop)
        self.cam_list.itemChanged.connect(rename_camera)
        self.cam_list.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
        )

        for camera_cls in self.camera_models.values():
            cam_list = camera_cls.getAvailableCameras()
            for cam in cam_list:
                camID = cam.cameraID
                # Initialize all camera-specific items
                duplicates = 0
                while camID in self.cameras.keys():
                    duplicates += 1
                    logger.warning(
                        f"CameraID: {camID} is already taken. Renaming to {camID + str(duplicates)}"
                    )
                    camID += str(duplicates)

                self.cameras[camID] = cam
                self.camera_widgets[camID] = None
                self.camera_configs[camID] = ConfigManager()
                self.camera_names[camID] = cam.getDisplayName()

                item = QtWidgets.QListWidgetItem(self.camera_names[camID])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.cam_list.addItem(item)

    def populate_camera_properties(self):
        """Create a settings tab for each camera with configurable property widgets."""
        for camID in self.camera_names.keys():
            config = self.camera_configs[camID]
            tab = QtWidgets.QWidget()
            cls = self.cameras[camID].__class__
            props = {"Camera Parameters File": ""}
            if hasattr(cls, "DEFAULT_PROPS"):
                props.update(cls.DEFAULT_PROPS)
            config.set_defaults(props)
            for key, setting in props.items():
                add_config_handler(config, key, setting)

            layout, _ = make_config_layout(config)
            tab.setLayout(layout)
            self.cam_props.addTab(tab, self.camera_names[camID])

    def populate_plugin_list(self):
        """Populate the plugin list widget with enabled plugins and wire drag-reorder signals."""

        def jump_to_config(item):
            for idx in range(self.plugin_settings.count()):
                if self.plugin_settings.tabText(idx) == item.text():
                    self.plugin_settings.setCurrentIndex(idx)
                    break

        def toggle_check_box(item):
            if item.checkState() == Qt.CheckState.Unchecked:
                item.setCheckState(Qt.CheckState.Checked)
                jump_to_config(item)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)

        def sync_tab_order(start, dest):
            if dest > start:
                dest -= 1  # Account for other rows shifting up
            self.plugin_settings.tabBar().moveTab(start, dest)
            self.populate_plugin_pipeline()
            jump_to_config(self.plugin_list.item(dest))

        self.plugin_list.clear()
        self.plugin_list.setItemAlignment(Qt.AlignmentFlag.AlignTop)
        self.plugin_list.itemChanged.connect(self.populate_plugin_pipeline)
        self.plugin_list.itemDoubleClicked.connect(toggle_check_box)
        self.plugin_list.model().rowsMoved.connect(
            lambda p, start, end, _, dest: sync_tab_order(start, dest)
        )

        if "MetadataWriter" in self.plugins:
            self.plugins.move_to_end("MetadataWriter")
        if "VideoWriter" in self.plugins:
            self.plugins.move_to_end("VideoWriter")
        if "FrameDisplay" in self.plugins:
            self.plugins.move_to_end("FrameDisplay")

        for name in self.plugins.keys():
            item = QtWidgets.QListWidgetItem(name)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.plugin_list.addItem(item)
            self.plugin_configs[name] = ConfigManager()

    def populate_plugin_settings(self):
        """Create a settings tab for each plugin with configurable default widgets."""
        for plugin_name, config in self.plugin_configs.items():
            cls = self.plugins[plugin_name]
            tab = QtWidgets.QWidget()
            if hasattr(cls, "DEFAULT_CONFIG"):
                config.set_defaults(cls.DEFAULT_CONFIG)
                for key, setting in cls.DEFAULT_CONFIG.items():
                    add_config_handler(config, key, setting)

            if cls.__name__ == "MetadataWriter":  # add missing metadata to UI
                settings = config.get_visible_keys()
                for camera in self.cameras.values():
                    metadata = camera.getMetadata()
                    for name in metadata.keys():
                        key = "Overlay " + name
                        if key not in settings:
                            add_config_handler(config, key, value=False)

            layout, row_map = make_config_layout(config, cols=2)

            if cls.__name__ == "VideoWriter":
                self._connect_videowriter_codec_signal(config, row_map)

            tab.setLayout(layout)
            self.plugin_settings.addTab(tab, plugin_name)

    def _connect_videowriter_codec_signal(self, config, row_map):
        """Wire the vcodec combobox to dynamically show/hide codec-specific options."""
        from rataGUI.plugins.video_codec_rules import (
            get_hidden_keys,
            get_valid_presets,
            get_valid_pixel_formats,
        )

        self._vw_row_map = row_map
        vcodec_widget = config.handlers["vcodec"]

        def on_vcodec_changed(codec):
            hidden = get_hidden_keys(codec)

            # Show/hide form rows
            for key, (form, row_idx) in self._vw_row_map.items():
                if key == "vcodec":
                    continue
                form.setRowVisible(row_idx, key not in hidden)

            # Repopulate preset combobox
            preset_widget = config.handlers["speed (preset)"]
            old_preset = preset_widget.currentText()
            preset_widget.blockSignals(True)
            preset_widget.clear()
            valid_presets = get_valid_presets(codec)
            if valid_presets:
                preset_widget.addItems(valid_presets)
                idx = preset_widget.findText(old_preset)
                preset_widget.setCurrentIndex(idx if idx >= 0 else 0)
            preset_widget.blockSignals(False)

            # Repopulate pixel format combobox
            pf_widget = config.handlers["pixel format"]
            old_pf = pf_widget.currentText()
            pf_widget.blockSignals(True)
            pf_widget.clear()
            valid_pf = get_valid_pixel_formats(codec)
            if valid_pf:
                pf_widget.addItems(valid_pf)
                idx = pf_widget.findText(old_pf)
                pf_widget.setCurrentIndex(idx if idx >= 0 else 0)
            pf_widget.blockSignals(False)

        vcodec_widget.currentTextChanged.connect(on_vcodec_changed)
        # Set initial visibility based on default codec
        on_vcodec_changed(vcodec_widget.currentText())

    def populate_plugin_pipeline(self):
        """Build and refresh the camera-plugin pipeline matrix table."""
        self.plugin_pipeline.setRowCount(0)  # Clear QTableWidget
        try:
            self.plugin_pipeline.disconnect()  # Disconnect all signal-slots
        except Exception:
            pass

        self.plugin_pipeline.setRowCount(len(self.camera_widgets))
        self.plugin_pipeline.setColumnCount(self.plugin_list.count())
        column_labels = []

        # TODO: Use self.cam_list directly if order can change
        checked_camera_names = [c.text() for c in get_checked_items(self.cam_list)]

        for row, camID in enumerate(self.camera_names.keys()):
            widget = self.camera_widgets[camID]
            for col in range(self.plugin_list.count()):
                plugin_item = self.plugin_list.item(col)
                plugin_name = plugin_item.text()
                if row == 0:  # Add column label once
                    column_labels.append(plugin_name)

                item = self.plugin_pipeline.item(row, col)
                if item is None:
                    item = QtWidgets.QTableWidgetItem()
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.plugin_pipeline.setItem(row, col, item)

                if widget is not None:  # Active
                    plugin_active = None
                    plugin_failed = False
                    for plugin in widget.plugins:  # Find plugin by name
                        if isinstance(plugin, self.plugins[plugin_name]):
                            plugin_active = plugin.active
                            plugin_failed = getattr(plugin, "failed", False)
                            break

                    if not widget.active:
                        item.setText("Paused")
                        item.setBackground(self.paused_color)
                    elif plugin_active is None:
                        if plugin_name in getattr(widget, 'failed_plugins', {}):
                            item.setText("Failed")
                            item.setBackground(self.failed_color)
                        else:
                            item.setText("Inactive")
                            item.setBackground(self.inactive_color)
                    elif plugin_active:
                        item.setText("Active")
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(Qt.CheckState.Checked)
                        item.setBackground(self.active_color)
                    elif plugin_failed:
                        item.setText("Failed")
                        item.setBackground(self.failed_color)
                    else:
                        item.setText("Paused")
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(Qt.CheckState.Unchecked)
                        item.setBackground(self.paused_color)
                elif (
                    self.camera_names[camID] in checked_camera_names
                ):  # Camera is enabled
                    if (
                        plugin_item.checkState() == Qt.CheckState.Checked
                    ):  # Plugin is enabled
                        item.setText("Enabled")
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(Qt.CheckState.Checked)
                    else:
                        item.setText("")
                        item.setBackground(self.inactive_color)
                else:
                    item.setText("")
                    item.setData(
                        Qt.ItemDataRole.BackgroundRole, None
                    )  # Reset to default color

        self.plugin_pipeline.setVerticalHeaderLabels(self.camera_names.values())
        self.plugin_pipeline.verticalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.plugin_pipeline.setHorizontalHeaderLabels(column_labels)

        self.plugin_pipeline.itemChanged.connect(self.toggle_camera_plugin)
        self.plugin_pipeline.resizeColumnsToContents()

    def toggle_camera_plugin(self, item):
        """Handle check-state changes in the pipeline table to pause/resume individual plugins."""
        cam_name = self.plugin_pipeline.verticalHeaderItem(item.row()).text()
        camID = self._camera_id_from_name(cam_name)
        plugin_name = self.plugin_pipeline.horizontalHeaderItem(item.column()).text()

        if item.checkState() == Qt.CheckState.Checked:
            if item.text() == "Paused":
                item.setText("Active")
                item.setBackground(self.active_color)
                widget = self.camera_widgets[camID]
                for plugin in widget.plugins:  # Find plugin by name
                    if isinstance(plugin, self.plugins[plugin_name]):
                        plugin.active = True
                        break
            elif item.text() == "Disabled":
                item.setText("Enabled")
                item.setData(
                    Qt.ItemDataRole.BackgroundRole, None
                )  # Reset to default color

        elif item.checkState() == Qt.CheckState.Unchecked:
            if item.text() == "Active":
                item.setText("Paused")
                item.setBackground(self.paused_color)
                widget = self.camera_widgets[camID]
                for plugin in widget.plugins:  # Find plugin by name
                    if isinstance(plugin, self.plugins[plugin_name]):
                        plugin.active = False
                        break
            elif item.text() == "Enabled":
                item.setText("Disabled")
                item.setBackground(self.inactive_color)

    def _on_plugin_failed(self, camera_name, plugin_name):
        """Show a warning dialog when a plugin is deactivated due to errors."""
        QtWidgets.QMessageBox.warning(
            self,
            "Plugin Failed",
            f"Plugin '{plugin_name}' has been deactivated due to repeated errors "
            f"on camera '{camera_name}'.\n\n"
            f"If this is VideoWriter, video is NOT being saved.\n"
            f"Check the log for details.",
        )

    def populate_trigger_list(self):
        """Initialize the trigger list widget and wire double-click toggle behaviour."""

        def sync_check_box(item):
            deviceID = item.text()
            trigger_type = type(self.triggers[deviceID]).__name__
            layout = self.trigger_tabs[trigger_type].layout()
            for idx in range(layout.count()):  # Find device QGroupBox in layout
                widget = layout.itemAt(idx).widget()
                if (
                    isinstance(widget, QtWidgets.QGroupBox)
                    and widget.title() == deviceID
                ):
                    widget.setChecked(item.checkState() == Qt.CheckState.Checked)
                    break

        self.trigger_list.clear()
        self.trigger_list.setItemAlignment(Qt.AlignmentFlag.AlignTop)
        self.trigger_list.itemDoubleClicked.connect(
            lambda item: item.setCheckState(
                Qt.CheckState.Checked
                if item.checkState() == Qt.CheckState.Unchecked
                else Qt.CheckState.Unchecked
            )
        )
        self.trigger_list.itemChanged.connect(sync_check_box)
        # trigger_list is initially empty as triggers are added dynamically

    def populate_trigger_settings(self):
        """Create device selector and settings tab for each trigger type."""
        for trigger_cls in self.trigger_types.values():
            tab = QtWidgets.QWidget()
            self.cam_triggers.addTab(tab, trigger_cls.__name__)
            layout = QtWidgets.QVBoxLayout()
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)

            options = QtWidgets.QComboBox()
            options.view().setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            device_list = trigger_cls.getAvailableDevices()
            for trigger in device_list:
                deviceID = str(trigger.deviceID)
                if deviceID not in self.triggers.keys():
                    self.triggers[deviceID] = trigger
                    options.addItem(deviceID)

            options.model().sort(0)
            options_layout = QtWidgets.QHBoxLayout()
            options_layout.addWidget(options, stretch=2)
            add_btn = QtWidgets.QPushButton("Add Trigger")
            add_btn.clicked.connect(lambda state, x=options: self.add_trigger_config(x))
            options_layout.addWidget(add_btn, stretch=1)

            layout.addLayout(options_layout)
            tab.setLayout(layout)
            self.trigger_tabs[trigger_cls.__name__] = tab

    def add_trigger_config(self, options):
        """Add a trigger device to the configuration panel and trigger list.

        :param options: QComboBox listing available device IDs.
        """

        def sync_check_box(group_box):
            deviceID = group_box.title()
            for idx in range(self.trigger_list.count()):
                item = self.trigger_list.item(idx)
                if item.text() == deviceID:
                    item.setCheckState(
                        Qt.CheckState.Checked
                        if group_box.isChecked()
                        else Qt.CheckState.Unchecked
                    )
                    break

        deviceID = options.currentText()
        if deviceID == "":
            return
        # Add device item to trigger list
        item = QtWidgets.QListWidgetItem(deviceID)
        item.setCheckState(Qt.CheckState.Checked)
        self.trigger_list.addItem(item)

        config = ConfigManager()
        trigger_cls = type(self.triggers[deviceID])
        if hasattr(trigger_cls, "DEFAULT_CONFIG"):
            config.set_defaults(trigger_cls.DEFAULT_CONFIG)
            for key, setting in trigger_cls.DEFAULT_CONFIG.items():
                add_config_handler(config, key, setting)
        self.trigger_configs[deviceID] = config

        config_layout, _ = make_config_layout(config, extend_line_edits=False)
        delete_btn = QtWidgets.QToolButton()
        delete_btn.setFixedSize(15, 15)
        delete_btn.setText("X")
        config_layout.addWidget(delete_btn)

        config_box = QtWidgets.QGroupBox(deviceID)
        config_box.setLayout(config_layout)
        config_box.setCheckable(True)
        layout = self.trigger_tabs[trigger_cls.__name__].layout()
        layout.insertWidget(layout.count() - 1, config_box)

        config_box.clicked.connect(lambda: sync_check_box(config_box))
        delete_btn.clicked.connect(
            lambda: self.remove_trigger_config(config_box, options)
        )
        options.removeItem(options.currentIndex())

    def remove_trigger_config(self, config_box, options):
        """Remove a trigger device from the config panel, list, and close it if initialized."""
        deviceID = config_box.title()
        # Delete from trigger list
        for idx in range(self.trigger_list.count()):
            if self.trigger_list.item(idx).text() == deviceID:
                item = self.trigger_list.takeItem(idx)
                trigger = self.triggers[item.text()]
                if trigger.initialized:
                    trigger.close()
                break

        # Delete from config
        config_box.setParent(None)
        config_box.deleteLater()
        self.trigger_configs.pop(deviceID)

        for i in range(options.count()):
            if options.itemText(i) > deviceID:
                options.insertItem(i, deviceID)
                break
        if options.count() == 0:
            options.addItem(deviceID)

    def start_camera_widgets(self):
        """Create and start CameraWidget instances for all checked cameras with their enabled plugins."""

        def reset_interface(camID, item):
            self.camera_widgets[camID] = None
            item.setData(Qt.ItemDataRole.BackgroundRole, None)

        session_dir = os.path.join(
            launch_config["Save Directory"],
            datetime.now().strftime("%Y_%m_%d-%H_%M_%S"),
        )
        # Save session configuration as json files
        self.save_settings(os.path.join(session_dir, "settings"))

        # Find all enabled triggers
        enabled_triggers = []
        for item in get_checked_items(self.trigger_list):
            deviceID = item.text()
            enabled_triggers.append(self.triggers[deviceID])

        screen_width = self.screen.width()
        for cam_idx in range(self.plugin_pipeline.rowCount()):
            cam_name = self.plugin_pipeline.verticalHeaderItem(cam_idx).text()
            camID = self._camera_id_from_name(cam_name)
            widget = self.camera_widgets[camID]
            if widget is None:  # Create new widget
                enabled_plugins = []
                for col in range(self.plugin_pipeline.columnCount()):
                    plugin_name = self.plugin_pipeline.horizontalHeaderItem(col).text()
                    item = self.plugin_pipeline.item(cam_idx, col)
                    if item.text() == "Enabled":
                        enabled_plugins.append(
                            (
                                self.plugins[plugin_name],
                                self.plugin_configs[plugin_name],
                            )
                        )
                if len(enabled_plugins) == 0:
                    continue

                config = self.camera_configs[camID]
                widget = CameraWidget(
                    camera=self.cameras[camID],
                    cam_config=config,
                    plugins=enabled_plugins,
                    triggers=enabled_triggers,
                    session_dir=session_dir,
                )

                # Update interface once camera widget opens or closes
                cam_item = self.cam_list.item(cam_idx)
                widget.pipeline_initialized.connect(
                    lambda item=cam_item: item.setBackground(self.active_color)
                )

                widget.plugin_failed.connect(self._on_plugin_failed)

                widget.destroyed.connect(
                    lambda _, id=camID, item=cam_item: reset_interface(id, item)
                )

                widgets_per_row = round(screen_width / widget.width())
                x_pos = min(
                    widget.width() * (cam_idx % widgets_per_row),
                    screen_width - widget.width(),
                )
                y_pos = (2 * widget.height() // 3) * (cam_idx // widgets_per_row)
                widget.move(x_pos, y_pos)
                self.camera_widgets[camID] = widget
            elif not widget.active:  # Toggle paused widget to resume
                widget.active = True
                self.camera_widgets[camID].show()
                self.cam_list.item(cam_idx).setBackground(self.active_color)

        # Initialize all enabled triggers
        for item in get_checked_items(self.trigger_list):
            deviceID = item.text()
            trigger = self.triggers[deviceID]
            try:
                if not trigger.initialized:
                    success = trigger.initialize(self.trigger_configs[deviceID])
                    if not success:
                        raise IOError(f"Trigger: {deviceID} failed to initialize")
                    trigger.initialized = True
                    item.setBackground(self.active_color)
                    logger.info(f"Trigger: {deviceID} initialized")
            except Exception as err:
                logger.exception(err)
                trigger.initialized = False
                item.setData(Qt.ItemDataRole.BackgroundRole, None)
                continue

    def pause_camera_widgets(self):
        """Pause frame acquisition on all checked camera widgets."""
        for cam_item in get_checked_items(self.cam_list):
            cam_name = cam_item.text()
            camID = self._camera_id_from_name(cam_name)
            cam_widget = self.camera_widgets[camID]
            if cam_widget is not None:
                cam_widget.active = False
                cam_item.setBackground(self.paused_color)

    def stop_camera_widgets(self):
        """Stop all checked camera pipelines and close checked triggers."""
        # Stop all checked triggers
        for trig_item in get_checked_items(self.trigger_list):
            try:
                trigger = self.triggers[trig_item.text()]
                if trigger.initialized:
                    trigger.close()
                trig_item.setData(
                    Qt.ItemDataRole.BackgroundRole, None
                )  # Reset to default color
            except Exception as err:
                logger.exception(err)
                logger.error(f"Trigger: {trig_item.text()} failed to close")

        for cam_item in get_checked_items(self.cam_list):
            cam_name = cam_item.text()
            camID = self._camera_id_from_name(cam_name)
            cam_widget = self.camera_widgets[camID]
            if cam_widget is not None:
                cam_widget.stop_camera_pipeline()

    def save_settings(self, save_dir):
        """Persist all camera, plugin, trigger, and UI settings to JSON files.

        :param save_dir: Directory to write setting files into (created if absent).
        """
        os.makedirs(save_dir, exist_ok=True)

        self._merge_and_save_json(
            os.path.join(save_dir, "camera_settings.json"),
            {camID: cfg.as_dict() for camID, cfg in self.camera_configs.items()},
        )
        self._merge_and_save_json(
            os.path.join(save_dir, "plugin_settings.json"),
            {name: cfg.as_dict() for name, cfg in self.plugin_configs.items()},
        )
        self._merge_and_save_json(
            os.path.join(save_dir, "trigger_settings.json"),
            {devID: cfg.as_dict() for devID, cfg in self.trigger_configs.items()},
        )

        ui_settings = {}
        ui_settings["RataGUI Version"] = __version__
        ui_settings["checked_cameras"] = [
            c.text() for c in get_checked_items(self.cam_list)
        ]

        plugin_states = {}
        for idx in range(self.plugin_list.count()):
            item = self.plugin_list.item(idx)
            plugin_states[item.text()] = item.checkState() == Qt.CheckState.Checked
        ui_settings["plugin_states"] = plugin_states

        ui_settings["active_camera_tab"] = self.camAttributes.tabText(
            self.camAttributes.currentIndex()
        )
        ui_settings["active_plugin_tab"] = self.plugin_settings.tabText(
            self.plugin_settings.currentIndex()
        )

        ui_settings["window_width"] = self.size().width()
        ui_settings["window_height"] = self.size().height()
        ui_settings["window_x"] = self.pos().x()
        ui_settings["window_y"] = self.pos().y()
        with open(os.path.join(save_dir, "interface_settings.json"), "w+") as file:
            contents = file.read()
            ui_settings["camera_names"] = self.camera_names
            if len(contents) != 0:
                old_names = json.loads(contents).get("camera_names")
                if old_names is not None:
                    old_names.update(self.camera_names)
                    ui_settings["camera_names"] = old_names
            json.dump(ui_settings, file, indent=2)

        logger.info(f"Saved session settings to {save_dir}")

    def restore_settings(self, save_dir):
        """Restore camera, plugin, trigger, and UI settings from saved JSON files.

        :param save_dir: Directory containing previously saved setting files.
        """
        saved_configs = self._load_json_if_exists(
            os.path.join(save_dir, "camera_settings.json")
        )
        if saved_configs is not None:
            for camID, config in self.camera_configs.items():
                if camID in saved_configs:
                    try:
                        config.set_many(saved_configs[camID])
                    except Exception as err:
                        logger.warning(
                            f"Some saved settings for camera: {camID} could not be restored "
                            f"as it no longer exists in the camera's DEFAULT_PROPS"
                        )
                        logger.debug(err)
            logger.info("Restored saved camera settings")
        else:
            logger.info("No saved camera settings ... using defaults")

        saved_configs = self._load_json_if_exists(
            os.path.join(save_dir, "plugin_settings.json")
        )
        if saved_configs is not None:
            for name, config in self.plugin_configs.items():
                if name in saved_configs:
                    try:
                        config.set_many(saved_configs[name])
                    except Exception as err:
                        logger.warning(
                            f"Some saved settings for plugin: {name} could not be restored "
                            f"as it no longer exists in the plugin's DEFAULT_CONFIG"
                        )
                        logger.debug(err)
            logger.info("Restored saved plugin settings")
        else:
            logger.info("No saved plugin settings ... using defaults")

        saved_configs = self._load_json_if_exists(
            os.path.join(save_dir, "trigger_settings.json")
        )
        if saved_configs is not None:
            for deviceID, trigger in self.triggers.items():
                if deviceID in saved_configs:
                    # Add trigger by "pressing" interface button
                    trigger_type = type(trigger).__name__
                    layout = self.trigger_tabs[trigger_type].layout()
                    options = layout.itemAt(layout.count() - 1).itemAt(0).widget()
                    options.setCurrentText(deviceID)
                    self.add_trigger_config(options)
            logger.info("Restored saved trigger settings")
        else:
            logger.info("No saved trigger settings ... using defaults")

        saved_configs = self._load_json_if_exists(
            os.path.join(save_dir, "interface_settings.json")
        )
        if saved_configs is not None:
            # Restore camera list to saved state
            for idx in range(self.cam_list.count()):
                item = self.cam_list.item(idx)
                cam_name = item.text()
                camID = self._camera_id_from_name(cam_name)
                # Rename cameras to saved display names
                self.cam_list.setCurrentItem(item)
                if camID in saved_configs["camera_names"]:
                    display_name = saved_configs["camera_names"][camID]
                    item.setText(display_name)
                    if display_name in saved_configs["checked_cameras"]:
                        self.cam_list.setCurrentItem(None)
                        item.setCheckState(Qt.CheckState.Checked)

            # Repopulate list with saved plugin state and order
            self.plugin_list.clear()
            for name, checked in saved_configs["plugin_states"].items():
                if name in self.plugins:
                    item = QtWidgets.QListWidgetItem(name)
                    item.setCheckState(Qt.CheckState.Unchecked)
                    if checked:
                        item.setCheckState(Qt.CheckState.Checked)
                    self.plugin_list.addItem(item)

            # Append any new plugins to the end
            new_plugins = list(set(self.plugins) - set(saved_configs["plugin_states"]))
            for name in new_plugins:
                item = QtWidgets.QListWidgetItem(name)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.plugin_list.addItem(item)

            # Move tabs to match plugin order
            tab_bar = self.plugin_settings.tabBar()
            for dest in range(self.plugin_list.count()):
                name = self.plugin_list.item(dest).text()
                for idx in range(tab_bar.count()):
                    if tab_bar.tabText(idx) == name:
                        tab_bar.moveTab(idx, dest)
                        break

            self.populate_plugin_pipeline()
            self.show()

            # Restore tab focus after window is shown
            for idx in range(self.camAttributes.count()):
                if self.camAttributes.tabText(idx) == saved_configs.get(
                    "active_camera_tab"
                ):
                    self.camAttributes.setCurrentIndex(idx)
                    break
            for idx in range(self.plugin_settings.count()):
                if self.plugin_settings.tabText(idx) == saved_configs.get(
                    "active_plugin_tab"
                ):
                    self.plugin_settings.setCurrentIndex(idx)
                    break

            if "window_width" in saved_configs and "window_height" in saved_configs:
                self.resize(
                    saved_configs["window_width"], saved_configs["window_height"]
                )
                self.move(saved_configs["window_x"], saved_configs["window_y"])

            logger.info("Restored saved interface settings")
        else:
            logger.info("No saved interface settings ... using defaults")

    def closeEvent(self, event):
        """Handle window close: stop pipelines, save settings, wait for cleanup, release resources."""
        widgets_active = False
        for cam_widget in self.camera_widgets.values():
            if cam_widget is not None:
                cam_widget.stop_camera_pipeline()
                widgets_active = True

        # Save root configuration as json files
        self.save_settings(os.path.join(launch_config["Save Directory"], "settings"))

        # Wait for all camera widgets to close
        while widgets_active:
            time.sleep(0.05)
            widgets_active = any(
                widget is not None for widget in self.camera_widgets.values()
            )

        # Close all initialized triggers
        for trigger in self.triggers.values():
            try:
                if trigger.initialized:
                    trigger.close()
            except Exception as err:
                logger.exception(err)
                logger.error(f"Trigger: {trigger.deviceID} failed to close")

        # Release camera-specific resources
        for cam_type in self.camera_models.values():
            cam_type.releaseResources()

        QtWidgets.QMainWindow.closeEvent(self, event)  # let the window close


def get_checked_items(check_list: QtWidgets.QListWidget) -> list:
    """Return a list of all checked QListWidgetItem entries from *check_list*."""
    checked = []
    for idx in range(check_list.count()):
        item = check_list.item(idx)
        if item.checkState() == Qt.CheckState.Checked:
            checked.append(item)
    return checked


def add_config_handler(config, key: str, value) -> None:
    """Create and register a Qt widget handler for a single config key-value pair.

    The widget type is determined by the value's Python type:
    bool -> QCheckBox, str -> QLineEdit, int -> QSpinBox, float -> QDoubleSpinBox,
    tuple -> bounded spin box, list -> QComboBox, dict -> mapped QComboBox.

    :param config: ConfigManager to register the handler with.
    :param key: Configuration key name.
    :param value: Default value (its type determines the widget created).
    """
    try:
        # Identity mapper pair (get, set) — overridden by dict-type values below
        mapper = (lambda x: x, lambda x: x)
        if isinstance(value, bool):
            widget = QtWidgets.QCheckBox()
            widget.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Preferred,
                QtWidgets.QSizePolicy.Policy.Preferred,
            )
        elif isinstance(value, str):
            widget = QtWidgets.QLineEdit()
        elif isinstance(value, int):
            widget = QtWidgets.QSpinBox()
            widget.setRange(int(-1e6), int(1e6))
            widget.setMinimum(-1)
        elif isinstance(value, float):
            widget = QtWidgets.QDoubleSpinBox()
            widget.setRange(int(-1e6), int(1e6))
            widget.setSingleStep(0.1)
        elif isinstance(value, tuple):
            if isinstance(value[0], int):
                widget = QtWidgets.QSpinBox()
            elif isinstance(value[0], float):
                widget = QtWidgets.QDoubleSpinBox()
            if len(value) == 3:
                widget.setRange(value[1], value[2])
            config.set_default(key, value[0])
        elif isinstance(value, list):
            widget = QtWidgets.QComboBox()
            widget.view().setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            widget.addItems(value)
            config.set_default(key, value[0])  # Default to first value
        elif isinstance(value, dict):
            widget = QtWidgets.QComboBox()
            widget.view().setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            options = list(value.keys())
            widget.addItems(options)
            config.set_default(key, value[options[0]])  # Default to first value
            mapper = value

        config.add_handler(key, widget, mapper)
    except Exception as err:
        logger.exception(err)
        logger.error(
            "Failed to create setting handler. Each setting must correspond to a valid set of values"
        )


def make_config_layout(config, cols: int = 2, extend_line_edits: bool = True):
    """Generate a QHBoxLayout based on the input ConfigManager where each column is a QFormLayout.

    For each row, the label is the config dict key, and the field is the config handler for that key.

    :param config: ConfigManager
    :param cols: Number of columns to use
    :return: Tuple of (layout, row_map) where row_map maps config key to
        ``(QFormLayout, row_index)`` for use with ``setRowVisible()``.
    """
    layout = QtWidgets.QHBoxLayout()
    forms = [QtWidgets.QFormLayout() for _ in range(cols)]
    for form in forms:
        form.setContentsMargins(8, 0, 8, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(8)
        layout.addLayout(form)

    row_map = {}
    long_line_edits = []
    count = 0
    for key in config.get_visible_keys():
        f_index = count % cols
        handler = config.handlers[key]
        label = QtWidgets.QLabel(key)

        if isinstance(handler, QtWidgets.QLineEdit) and extend_line_edits:
            long_line_edits.append((key, label, handler))
        else:
            row_idx = forms[f_index].rowCount()
            forms[f_index].addRow(label, handler)
            row_map[key] = (forms[f_index], row_idx)
            count += 1

    if len(long_line_edits) > 0:
        line_form = QtWidgets.QFormLayout()
        line_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for key, label, handler in long_line_edits:
            row_idx = line_form.rowCount()
            label_text = label.text().lower()
            if "directory" in label_text:
                hbox = QtWidgets.QHBoxLayout()
                hbox.addWidget(handler)
                browse_btn = QtWidgets.QPushButton("Browse")
                browse_btn.clicked.connect(
                    lambda state, edit=handler: open_file_dialog(edit, True)
                )
                hbox.addWidget(browse_btn)
                line_form.addRow(label, hbox)
            elif ("file" in label_text) and ("save" not in label_text):
                hbox = QtWidgets.QHBoxLayout()
                hbox.addWidget(handler)
                browse_btn = QtWidgets.QPushButton("Browse")
                browse_btn.clicked.connect(
                    lambda state, edit=handler: open_file_dialog(edit, False)
                )
                hbox.addWidget(browse_btn)
                line_form.addRow(label, hbox)
            else:
                line_form.addRow(label, handler)
            row_map[key] = (line_form, row_idx)

        new_layout = QtWidgets.QVBoxLayout()
        new_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        new_layout.addLayout(line_form)
        new_layout.addLayout(layout)
        return new_layout, row_map

    return layout, row_map


def open_file_dialog(line_edit, is_dir: bool) -> None:
    """Open a native file/directory dialog and write the selected path into *line_edit*.

    :param line_edit: Target QLineEdit to populate with the chosen path.
    :param is_dir: If True, open a directory picker; otherwise a file picker.
    """
    if is_dir:
        res = QtWidgets.QFileDialog.getExistingDirectory(
            caption="Select a Directory",
            directory=os.getcwd(),
            options=QtWidgets.QFileDialog.Option.ShowDirsOnly,
        )
    else:
        res, _ = QtWidgets.QFileDialog.getOpenFileName(
            caption="Select a File", directory=os.getcwd()
        )
    if res:
        path = os.path.normpath(res)
        line_edit.setText(str(path))
