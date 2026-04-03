import os
import json
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog,
    QListWidget,
    QListWidgetItem,
    QDialogButtonBox,
    QFileDialog,
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt

from rataGUI.interface.design.Ui_StartMenu import Ui_StartMenu
from rataGUI import config_path, launch_config, rataGUI_icon

import logging

logger = logging.getLogger(__name__)


class StartMenu(QDialog, Ui_StartMenu):
    """Configuration dialog shown before launching the main window.

    Allows users to select which camera, plugin, and trigger modules to enable,
    set the save directory, and optionally restore a previous session.
    """

    def __init__(self, camera_modules=[], plugin_modules=[], trigger_modules=[]):
        super().__init__()
        self.setupUi(self)
        self.setWindowIcon(QIcon(rataGUI_icon))

        self.camera_models = {}
        enabled_cameras = launch_config.get("Enabled Camera Modules")
        for cls in camera_modules:
            self.camera_models[cls.__name__] = cls
            item = QListWidgetItem(cls.__name__)
            if enabled_cameras is None or module_name(cls) in enabled_cameras:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.camera_modules.addItem(item)
        self.camera_modules.itemDoubleClicked.connect(
            lambda item: item.setCheckState(
                Qt.CheckState.Checked
                if item.checkState() == Qt.CheckState.Unchecked
                else Qt.CheckState.Unchecked
            )
        )

        self.plugins = {}
        enabled_plugins = launch_config.get("Enabled Plugin Modules")
        for cls in plugin_modules:
            self.plugins[cls.__name__] = cls
            item = QListWidgetItem(cls.__name__)
            if enabled_plugins is None or module_name(cls) in enabled_plugins:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.plugin_modules.addItem(item)
        self.plugin_modules.itemDoubleClicked.connect(
            lambda item: item.setCheckState(
                Qt.CheckState.Checked
                if item.checkState() == Qt.CheckState.Unchecked
                else Qt.CheckState.Unchecked
            )
        )

        self.trigger_types = {}
        enabled_triggers = launch_config.get("Enabled Trigger Modules")
        for cls in trigger_modules:
            self.trigger_types[cls.__name__] = cls
            item = QListWidgetItem(cls.__name__)
            if enabled_triggers is None or module_name(cls) in enabled_triggers:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.trigger_modules.addItem(item)
        self.trigger_modules.itemDoubleClicked.connect(
            lambda item: item.setCheckState(
                Qt.CheckState.Checked
                if item.checkState() == Qt.CheckState.Unchecked
                else Qt.CheckState.Unchecked
            )
        )

        prev_save_dir = launch_config.get("Save Directory")
        if prev_save_dir is not None:
            self.save_directory.setText(prev_save_dir)
            self.session_dir.setText(os.path.join(prev_save_dir, "settings"))
        self.dontShowAgain.setChecked(launch_config.get("Don't show again", False))

        # Browse path buttons
        self.save_dir_btn.clicked.connect(
            lambda state, edit=self.save_directory: self.open_dir_dialog(edit)
        )
        self.sess_dir_btn.clicked.connect(
            lambda state, edit=self.session_dir: self.open_dir_dialog(edit)
        )

        # Save and close menu buttons
        self.buttonBox.button(QDialogButtonBox.StandardButton.Save).clicked.connect(
            self.save_settings
        )
        self.buttonBox.button(QDialogButtonBox.StandardButton.Close).clicked.connect(
            self.load_settings
        )
        # Closing without saving clears launch_config so main() exits gracefully
        self.closeEvent = lambda event: launch_config.clear()

    def load_settings(self, event=None):
        """Read widget state into launch_config and validate the save directory."""
        save_dir = self.save_directory.text()
        if len(save_dir) == 0:
            save_dir = os.path.abspath("rataGUI_" + datetime.now().strftime("%Y-%m-%d"))
            logger.warning(f"Save directory not specified ... defaulting to {save_dir}")
        else:
            save_dir = os.path.abspath(os.path.normpath(save_dir))

        session_dir = self.session_dir.text()
        if os.path.isdir(session_dir):
            session_dir = os.path.abspath(os.path.normpath(session_dir))
        else:
            logger.warning("Session settings not found ... using defaults")

        try:
            os.makedirs(save_dir, exist_ok=True)
            logger.info(f"Saving all session data to {save_dir}")
        except Exception as err:
            logger.exception(err)
            logger.error("Invalid save directory specified")
            raise

        launch_config["Enabled Camera Modules"] = [
            module_name(self.camera_models[name])
            for name in get_checked_names(self.camera_modules)
        ]
        launch_config["Enabled Plugin Modules"] = [
            module_name(self.plugins[name])
            for name in get_checked_names(self.plugin_modules)
        ]
        launch_config["Enabled Trigger Modules"] = [
            module_name(self.trigger_types[name])
            for name in get_checked_names(self.trigger_modules)
        ]
        launch_config["Save Directory"] = save_dir
        launch_config["Session Settings"] = session_dir
        launch_config["Don't show again"] = self.dontShowAgain.isChecked()

    def save_settings(self):
        """Persist launch_config to disk so the start menu can be skipped next time."""
        logger.info('Launch settings saved. Run "rataGUI --start-menu" to reconfigure.')
        self.load_settings()
        with open(config_path, "w") as file:
            json.dump(launch_config, file, indent=2)

    def open_dir_dialog(self, line_edit):
        """Open a native directory picker and write the result into *line_edit*."""
        dir_name = QFileDialog.getExistingDirectory(
            self,
            "Select a Directory",
            directory=os.getcwd(),
            options=QFileDialog.Option.ShowDirsOnly,
        )
        if dir_name:
            path = os.path.normpath(dir_name)
            line_edit.setText(str(path))


def get_checked_names(check_list: QListWidget) -> list:
    """Return the text of all checked items in *check_list*."""
    checked = []
    for idx in range(check_list.count()):
        item = check_list.item(idx)
        if item.checkState() == Qt.CheckState.Checked:
            checked.append(item.text())
    return checked


def module_name(cls):
    """Extract the leaf module name from a class (e.g. ``'WebCamera'`` from ``'rataGUI.cameras.WebCamera'``)."""
    return cls.__module__.split(".")[-1]
