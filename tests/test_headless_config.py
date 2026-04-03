"""Tests for HeadlessConfigManager."""

from rataGUI.headless.context import HeadlessConfigManager


class TestHeadlessConfigManager:

    def test_get_set(self):
        config = HeadlessConfigManager({"key": "value"})
        assert config.get("key") == "value"
        config.set("key", "new")
        assert config.get("key") == "new"

    def test_get_default(self):
        config = HeadlessConfigManager()
        assert config.get("missing") is None
        assert config.get("missing", 42) == 42

    def test_as_dict_returns_copy(self):
        config = HeadlessConfigManager({"a": 1})
        d = config.as_dict()
        d["a"] = 999
        assert config.get("a") == 1

    def test_set_defaults_does_not_overwrite(self):
        config = HeadlessConfigManager({"x": "user_value"})
        config.set_defaults({"x": "default_value", "y": "default_only"})
        assert config.get("x") == "user_value"
        assert config.get("y") == "default_only"

    def test_set_defaults_normalizes_list(self):
        config = HeadlessConfigManager()
        config.set_defaults({"codec": ["libx264", "libx265", "rawvideo"]})
        assert config.get("codec") == "libx264"

    def test_set_defaults_normalizes_empty_list(self):
        config = HeadlessConfigManager()
        config.set_defaults({"empty": []})
        assert config.get("empty") is None

    def test_set_defaults_normalizes_tuple(self):
        config = HeadlessConfigManager()
        config.set_defaults({"framerate": (30, 1, 120)})
        assert config.get("framerate") == 30

    def test_set_defaults_normalizes_dict(self):
        config = HeadlessConfigManager()
        config.set_defaults({"Aspect ratio": {"Keep": True, "Ignore": False}})
        assert config.get("Aspect ratio") is True

    def test_set_defaults_plain_values(self):
        config = HeadlessConfigManager()
        config.set_defaults({"width": 1920, "enabled": True, "name": "cam1"})
        assert config.get("width") == 1920
        assert config.get("enabled") is True
        assert config.get("name") == "cam1"

    def test_set_many(self):
        config = HeadlessConfigManager({"a": 1, "b": 2})
        config.set_many({"b": 20, "c": 30})
        assert config.get("a") == 1
        assert config.get("b") == 20
        assert config.get("c") == 30
