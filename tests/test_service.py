import configparser
import unittest
from unittest.mock import Mock, patch

from pywin32supervisor.supervisor import MyServiceFramework


class TestServiceFramework(unittest.TestCase):
    def setUp(self):
        with patch("win32serviceutil.ServiceFramework.__init__", return_value=None):
            self.service = MyServiceFramework()
        self.service.ReportServiceStatus = Mock()

    @patch("sys.argv", ["script.py", "service", "--config", "C:\\test\\supervisord.conf", "--env", "KEY=VALUE"])
    def test_parse_arguments(self):
        args = self.service.parse_arguments()
        self.assertEqual(args.config, "C:\\test\\supervisord.conf")
        self.assertEqual(args.env, [("KEY", "VALUE")])

    @patch("os.path.exists", return_value=True)
    @patch("os.environ", {"KEY": "VALUE"})
    def test_load_config_success(self, mock_exists):
        # Create a pre-configured config object
        config = configparser.RawConfigParser()
        config.read_string("[program:test]\ncommand=python test.py")

        # Patch RawConfigParser to return our config object when instantiated
        with patch("configparser.RawConfigParser") as mock_config_parser:
            mock_instance = mock_config_parser.return_value
            mock_instance.read.return_value = None  # Simulate reading the file
            mock_instance.sections.return_value = config.sections()
            for section in config.sections():
                mock_instance.__getitem__.return_value = config[section]

            loaded_config = self.service.load_config("C:\\test\\supervisord.conf")

            # Verify the loaded config
            self.assertIn("program:test", loaded_config.sections())
            self.assertEqual(loaded_config["program:test"]["command"], "python test.py")

    @patch("os.path.exists", return_value=False)
    @patch("servicemanager.LogErrorMsg")
    def test_load_config_file_not_found(self, mock_log, mock_exists):
        with self.assertRaises(FileNotFoundError):
            self.service.load_config("nonexistent.conf")

    def test_start_autostart_programs(self):
        self.service.programs = {
            "prog1": Mock(autostart=True, start_program=Mock()),
            "prog2": Mock(autostart=False, start_program=Mock()),
        }
        self.service.start_autostart_programs()

        self.service.programs["prog1"].start_program.assert_called_once()
        self.service.programs["prog2"].start_program.assert_not_called()


if __name__ == "__main__":
    unittest.main()
