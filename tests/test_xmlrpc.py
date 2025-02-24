import configparser
import time
import unittest
from unittest.mock import Mock, patch

from pywin32supervisor.supervisor import MyServiceFramework, Program


class TestXMLRPC(unittest.TestCase):
    def setUp(self):
        with patch("win32serviceutil.ServiceFramework.__init__", return_value=None):
            self.service = MyServiceFramework()
        config = configparser.ConfigParser()
        config["program:prog1"] = {"command": "cmd", "autostart": "false", "autorestart": "false"}
        config["program:prog2"] = {"command": "cmd", "autostart": "false", "autorestart": "false"}
        self.service.programs = {
            "prog1": Program("prog1", config["program:prog1"], Mock()),
            "prog2": Program("prog2", config["program:prog2"], Mock()),
        }
        self.service.programs["prog1"].process = Mock(poll=lambda: None)
        self.service.programs["prog1"].start_time = time.time() - 60
        self.service.programs["prog1"].restart_count = 2
        self.service.programs["prog1"].is_starting = False
        self.service.programs["prog2"].process = None
        self.service.programs["prog2"].start_time = None
        self.service.programs["prog2"].restart_count = 0
        self.service.programs["prog2"].is_starting = False

    def test_status(self):
        status = self.service.status()
        self.assertEqual(len(status), 2)
        self.assertEqual(status[0]["name"], "prog1")
        self.assertEqual(status[0]["state"], "RUNNING")
        self.assertGreater(status[0]["uptime"], 0)
        self.assertEqual(status[0]["restart_count"], 2)
        self.assertEqual(status[1]["name"], "prog2")
        self.assertEqual(status[1]["state"], "STOPPED")
        self.assertEqual(status[1]["uptime"], 0)

    def test_start_all(self):
        for prog in self.service.programs.values():
            prog.start_program = Mock()
        result = self.service.start("all")

        for prog in self.service.programs.values():
            prog.start_program.assert_called_once()
        self.assertEqual(result, "OK")

    def test_stop_program_not_found(self):
        result = self.service.stop("nonexistent")
        self.assertEqual(result, "Program 'nonexistent' not found")

    def test_status_starting_state(self):
        self.service.programs["prog1"].is_starting = True
        status = self.service.status()
        self.assertEqual(status[0]["state"], "STARTING")
        self.assertEqual(status[0]["uptime"], 0)

    def test_start_single_program(self):
        self.service.programs["prog1"].start_program = Mock()
        result = self.service.start("prog1")
        self.service.programs["prog1"].start_program.assert_called_once()
        self.assertEqual(result, "OK")

    def test_start_program_not_found(self):
        result = self.service.start("nonexistent")
        self.assertEqual(result, "Program 'nonexistent' not found")

    def test_stop_single_program(self):
        self.service.programs["prog1"].stop_program = Mock()
        result = self.service.stop("prog1")
        self.service.programs["prog1"].stop_program.assert_called_once()
        self.assertEqual(result, "OK")

    def test_restart_single_program(self):
        self.service.programs["prog1"].stop_program = Mock()
        self.service.programs["prog1"].start_program = Mock()
        result = self.service.restart("prog1")
        self.service.programs["prog1"].stop_program.assert_called_once()
        self.service.programs["prog1"].start_program.assert_called_once()
        self.assertEqual(result, "OK")


if __name__ == "__main__":
    unittest.main()
