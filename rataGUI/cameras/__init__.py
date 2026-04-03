"""
Loads camera modules listed in launch_config.json (defaults to all camera
models if none are specified).
"""

from rataGUI._module_loader import load_modules

load_modules(
    package_name=__name__,
    config_key="Enabled Camera Modules",
    label="camera",
    exclude_files=["BaseCamera.py", "TemplateCamera.py"],
)
