import argparse
import unittest
from unittest.mock import Mock, patch

from pywin32supervisor.supervisor import (
    create_argument_parser,
    filter_args,
    format_uptime,
    handle_program_command,
    handle_service_command,
    is_service_mode,
    main,
    print_result,
    print_status,
    validate_install_arguments,
)


class TestUtils(unittest.TestCase):
    @patch("sys.argv", ["script.py", "service"])
    @patch("servicemanager.Initialize")
    @patch("servicemanager.PrepareToHostSingle")
    @patch("servicemanager.StartServiceCtrlDispatcher")
    def test_main_service_mode(self, mock_dispatcher, mock_prepare, mock_init):
        main()
        mock_init.assert_called_once()

    def test_filter_args(self):
        args = ["--service", "install", "--config", "path", "extra"]
        filtered = filter_args(args, {"--service", "--config"})
        self.assertEqual(filtered, ["extra"])

    def test_format_uptime(self):
        self.assertEqual(format_uptime(0), "N/A")
        self.assertEqual(format_uptime(3665), "1h 1m 5s")
        self.assertEqual(format_uptime(90000), "1d 1h")

    @patch("sys.argv", ["script.py"])
    @patch("argparse.ArgumentParser.print_help")
    def test_main_non_service_mode_no_args(self, mock_print_help):
        with patch("pywin32supervisor.supervisor.create_argument_parser") as mock_parser:
            mock_parser_instance = mock_parser.return_value
            mock_parser_instance.parse_args.return_value = argparse.Namespace(
                service=None,
                config=None,
                env=None,
                command=None,
                program=None,
            )
            mock_parser_instance.print_help = mock_print_help
            main()
            mock_print_help.assert_called_once()

    @patch("sys.argv", ["script.py", "service"])
    def test_is_service_mode_true(self):
        self.assertTrue(is_service_mode())

    @patch("sys.argv", ["script.py"])
    def test_is_service_mode_false(self):
        self.assertFalse(is_service_mode())

    def test_create_argument_parser(self):
        parser = create_argument_parser()
        args = parser.parse_args(["--service", "install", "--config", "test.conf"])
        self.assertEqual(args.service, "install")
        self.assertEqual(args.config, "test.conf")

    @patch("sys.argv", ["script.py", "--service", "install", "--config", "test.conf"])
    @patch("win32serviceutil.HandleCommandLine")
    def test_handle_service_command_install(self, mock_handle):
        parser = create_argument_parser()
        args = parser.parse_args(["--service", "install", "--config", "test.conf"])
        with patch("pywin32supervisor.supervisor.MyServiceFramework"), patch("os.path.isfile", return_value=True):
            handle_service_command(args, parser)
            mock_handle.assert_called_once()

    def test_validate_install_arguments_missing_config(self):
        parser = create_argument_parser()
        args = parser.parse_args(["--service", "install"])
        with self.assertRaises(SystemExit):
            validate_install_arguments(args, parser)

    @patch("xmlrpc.client.ServerProxy", side_effect=ConnectionRefusedError)
    def test_handle_program_command_connection_error(self, mock_proxy):
        args = argparse.Namespace(command="status", program="all")
        with patch("logging.exception") as mock_log:
            handle_program_command(args)
            mock_log.assert_called_once_with(
                "Service is not running. Please start the service first with 'python supervisor.py --service start'.",
            )

    def test_format_uptime_full_range(self):
        self.assertEqual(format_uptime(0), "N/A")
        self.assertEqual(format_uptime(65), "1m 5s")
        self.assertEqual(format_uptime(3665), "1h 1m 5s")
        self.assertEqual(format_uptime(90061), "1d 1h 1m 1s")

    @patch("logging.info")
    def test_print_status_dynamic_width(self, mock_log):
        server = Mock()
        server.status.return_value = [{"name": "longname", "state": "RUNNING", "uptime": 65, "restart_count": 1}]
        print_status(server)
        mock_log.assert_called()

    @patch("logging.info")
    def test_print_result(self, mock_log):
        print_result("OK", "testprog", "Started")
        mock_log.assert_called_once_with("%s program '%s': %s", "Started", "testprog", "OK")


if __name__ == "__main__":
    unittest.main()
