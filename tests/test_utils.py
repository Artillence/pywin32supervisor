import unittest
from unittest.mock import patch

from pywin32supervisor.supervisor import filter_args, format_uptime, main


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


if __name__ == "__main__":
    unittest.main()
