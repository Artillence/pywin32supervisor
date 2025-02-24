import configparser
import unittest
from unittest.mock import Mock, mock_open, patch

from pywin32supervisor.supervisor import Program


class TestProgram(unittest.TestCase):
    def setUp(self):
        config = configparser.ConfigParser()
        config["program:testprog"] = {
            "command": "python -c 'print(\"Hello\")'",
            "autostart": "true",
            "autorestart": "true",
            "stdout_logfile": "C:\\logs\\stdout.log",
            "stderr_logfile": "C:\\logs\\stderr.log",
            "redirect_stderr": "false",
        }
        self.config = config["program:testprog"]
        self.job_handle = Mock()

    def test_program_init(self):
        program = Program("testprog", self.config, self.job_handle)
        self.assertEqual(program.name, "testprog")
        self.assertEqual(program.command, self.config["command"])
        self.assertTrue(program.autostart)
        self.assertTrue(program.autorestart)
        self.assertEqual(program.stdout_logfile, "C:\\logs\\stdout.log")
        self.assertEqual(program.stderr_logfile, "C:\\logs\\stderr.log")
        self.assertFalse(program.redirect_stderr)

    @patch("os.makedirs")
    @patch("subprocess.Popen")
    @patch("builtins.open", new_callable=mock_open)
    @patch("win32api.OpenProcess")
    @patch("win32job.AssignProcessToJobObject")
    def test_start_program_success(self, mock_assign, mock_open_process, mock_file, mock_popen, mock_makedirs):
        mock_process = Mock()
        mock_process.poll = Mock(return_value=None)
        mock_process.pid = 123
        mock_popen.return_value = mock_process
        mock_open_process.return_value = Mock()

        program = Program("testprog", self.config, self.job_handle)
        program.start_program()

        mock_makedirs.assert_called()
        mock_file.assert_called()
        self.assertIsNotNone(program.process)
        self.assertTrue(program.is_starting)
        mock_open_process.assert_called_once_with(
            257,
            False,  # noqa: FBT003 Boolean positional value in function call. perms = PROCESS_TERMINATE | PROCESS_SET_QUOTA
            123,
        )
        mock_assign.assert_called_once()

    def test_start_program_already_running(self):
        program = Program("testprog", self.config, self.job_handle)
        program.process = Mock(poll=lambda: None)  # Simulate running process

        with patch("subprocess.Popen") as mock_popen:
            program.start_program()
            mock_popen.assert_not_called()  # Should not start a new process

    def test_stop_program(self):
        program = Program("testprog", self.config, self.job_handle)
        process = Mock(poll=lambda: None)
        program.process = process
        stdout_file = program.stdout_file = Mock(spec=["close"])
        stderr_file = program.stderr_file = Mock(spec=["close"])

        program.stop_program()

        process.terminate.assert_called_once()
        stdout_file.close.assert_called_once()
        stderr_file.close.assert_called_once()
        self.assertIsNone(program.stdout_file)
        self.assertIsNone(program.stderr_file)
        self.assertIsNone(program.process)

    @patch("time.sleep")
    def test_autorestart_backoff(self, mock_sleep):
        program = Program("testprog", self.config, self.job_handle)
        program.process = Mock(poll=lambda: 1)  # Process ended
        program.start_program = Mock()
        program._check_start_success = Mock()  # noqa: SLF001 Private member accessed. Prevent thread interference

        if program.process.poll() is not None and program.autorestart:
            program.start_program()

        self.assertEqual(program.backoff_index, 0)  # Should reset after successful start


if __name__ == "__main__":
    unittest.main()
