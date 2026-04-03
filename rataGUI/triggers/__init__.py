"""
Loads trigger modules listed in launch_config.json (defaults to all triggers
if none are specified).
"""

from rataGUI._module_loader import load_modules

load_modules(
    package_name=__name__,
    config_key="Enabled Trigger Modules",
    label="trigger",
    exclude_files=["base_trigger.py", "template_trigger.py"],
)
