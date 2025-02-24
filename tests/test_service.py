import configparser
import unittest
from unittest.mock import MagicMock, Mock, patch

from pywin32supervisor.supervisor import MyServiceFramework, Program


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

    @patch("sys.argv", ["script.py", "service", "debug", "--config", "C:\\test\\supervisord.conf"])
    def test_parse_arguments_debug_mode(self):
        args = self.service.parse_arguments()
        self.assertEqual(args.config, "C:\\test\\supervisord.conf")

    @patch("os.path.exists", return_value=True)
    @patch("os.environ", {"ENV_TEST": "value"})
    def test_load_config_with_env_substitution(self, mock_exists):
        config = configparser.RawConfigParser()
        config.read_string("[program:test]\ncommand=%(ENV_TEST)s test.py")
        with patch("configparser.RawConfigParser") as mock_config_parser:
            mock_instance = mock_config_parser.return_value
            mock_instance.read.return_value = None
            mock_instance.sections.return_value = config.sections()
            mock_instance.__getitem__.side_effect = lambda s: config[s]
            loaded_config = self.service.load_config("C:\\test\\supervisord.conf")
            self.assertEqual(loaded_config["program:test"]["command"], "value test.py")

    @patch("win32job.CreateJobObject")
    @patch("win32job.QueryInformationJobObject")
    @patch("win32job.SetInformationJobObject")
    @patch("win32job.AssignProcessToJobObject")
    @patch("ctypes.windll.kernel32.GetCurrentProcess")
    def test_create_job(self, mock_get_process, mock_assign, mock_set, mock_query, mock_create):
        mock_job = Mock()
        mock_create.return_value = mock_job
        mock_query.return_value = {"BasicLimitInformation": {"LimitFlags": 0}}
        mock_get_process.return_value = Mock()

        job_handle = self.service.create_job()
        mock_create.assert_called_once_with(None, "")
        mock_set.assert_called_once()
        mock_assign.assert_called_once()
        self.assertEqual(job_handle, mock_job)

    @patch("os.path.exists", return_value=True)
    def test_load_programs(self, mock_exists):
        config = configparser.RawConfigParser()
        config.read_string("[program:test]\ncommand=cmd")
        with patch("configparser.RawConfigParser") as mock_config_parser:
            mock_instance = mock_config_parser.return_value
            mock_instance.read.return_value = None
            mock_instance.sections.return_value = config.sections()
            mock_instance.__getitem__.side_effect = lambda s: config[s]
            self.service.config_path = "C:\\test\\supervisord.conf"
            self.service.job_handle = Mock()
            self.service.load_config = lambda _: config
            programs = self.service.load_programs(config)
            self.assertIn("test", programs)
            self.assertIsInstance(programs["test"], Program)

    @patch("xmlrpc.server.SimpleXMLRPCServer")
    @patch("threading.Thread")
    def test_start_xmlrpc_server(self, mock_thread, mock_server):
        mock_server_instance = Mock()
        mock_server.return_value = mock_server_instance
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance

        self.service.start_xmlrpc_server()
        mock_server.assert_called_once_with(("127.0.0.1", 9001), allow_none=True)
        mock_server_instance.register_instance.assert_called_once_with(self.service)
        mock_thread.assert_called_once_with(target=mock_server_instance.serve_forever)
        mock_thread_instance.start.assert_called_once()

    @patch("time.sleep")
    def test_monitor_programs_autorestart(self, mock_sleep):
        self.service.is_running = MagicMock(side_effect=[True, False])
        mock_program = Mock(
            process=Mock(poll=Mock(return_value=1)),  # Process ended
            autorestart=True,
            is_starting=False,
            close_files=Mock(),
            start_program=Mock(),
            backoff_index=0,
            backoff_periods=[0, 1, 2],
            restart_count=0,
        )
        self.service.programs = {"test": mock_program}
        self.service.monitor_programs()
        mock_program.close_files.assert_called_once()
        mock_program.start_program.assert_called_once()
        self.assertEqual(mock_program.restart_count, 1)
        self.assertEqual(mock_program.backoff_index, 1)

    def test_svc_stop(self):
        self.service.running = True
        self.service.xmlrpc_server = Mock()
        self.service.xmlrpc_thread = Mock()
        self.service.programs = {"test": Mock(stop_program=Mock())}

        self.service.SvcStop()
        self.assertFalse(self.service.running)
        self.service.programs["test"].stop_program.assert_called_once()
        self.service.xmlrpc_server.shutdown.assert_called_once()
        self.service.xmlrpc_thread.join.assert_called_once()


if __name__ == "__main__":
    unittest.main()
