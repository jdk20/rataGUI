import os


class TestPackageInit:
    def test_version_defined(self):
        import rataGUI

        assert hasattr(rataGUI, "__version__")
        assert isinstance(rataGUI.__version__, str)
        assert len(rataGUI.__version__) > 0

    def test_launch_config_is_dict(self):
        import rataGUI

        assert isinstance(rataGUI.launch_config, dict)

    def test_add_file_logger(self, tmp_path):
        import rataGUI

        log_dir = str(tmp_path / "logs")
        rataGUI.add_file_logger(log_dir)

        assert os.path.isdir(log_dir)
        log_files = os.listdir(log_dir)
        assert len(log_files) == 1
        assert log_files[0].startswith("info_")
        assert log_files[0].endswith(".log")
