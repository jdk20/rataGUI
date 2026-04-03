"""
Loads plugin modules listed in launch_config.json (defaults to all plugins
if none are specified).
"""

from rataGUI._module_loader import load_modules

load_modules(
    package_name=__name__,
    config_key="Enabled Plugin Modules",
    label="plugin",
    exclude_files=["base_plugin.py", "template_plugin.py"],
)
