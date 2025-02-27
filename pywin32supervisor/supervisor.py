import argparse
import configparser
import ctypes
import io
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import xmlrpc.client
import xmlrpc.server

import psutil
import servicemanager
import win32api
import win32con
import win32job
import win32service
import win32serviceutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

# Command parameter to start the service itself.
SERVICE_COMMAND_CONSTANT = "service"


def kill_process_tree(pid):
    """Recursively kill a process and all its children."""
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.terminate()
        _, still_alive = psutil.wait_procs(parent.children(recursive=True), timeout=5)
        for child in still_alive:
            child.kill()
        parent.terminate()
        try:
            parent.wait(5)
        except psutil.TimeoutExpired:
            parent.kill()
            parent.wait()
    except psutil.NoSuchProcess:
        pass


class Program:
    """Represents a managed program."""

    def __init__(self, name, config, job_handle=None):
        self.name = name
        self.command = config["command"]
        self.autostart = config.getboolean("autostart", False)
        self.autorestart = config.getboolean("autorestart", False)
        self.stdout_logfile = config.get("stdout_logfile", None)
        self.stderr_logfile = config.get("stderr_logfile", None)
        self.redirect_stderr = config.getboolean("redirect_stderr", False)
        self.directory = config.get("directory", None)
        self.process = None
        self.start_time = None
        self.restart_count = 0
        self.backoff_index = 0
        self.backoff_periods = [0, 1, 2, 5, 10, 15]  # Backoff periods in seconds
        self.stdout_file = None
        self.stderr_file = None
        self.is_starting = False

        self.job_handle = job_handle

    def start_program(self):
        if self.process is not None and self.process.poll() is None:
            return  # Already running
        self.is_starting = True
        try:
            if self.stdout_logfile:
                os.makedirs(os.path.dirname(self.stdout_logfile), exist_ok=True)
                raw_stdout_file = open(self.stdout_logfile, "ab", buffering=0)  # noqa: SIM115 Use a context manager for opening files. File handle is needed during the subprocess' lifetime.
                self.stdout_file = io.TextIOWrapper(raw_stdout_file, encoding="utf-8", line_buffering=True)  # Line buffered text wrapper
            else:
                self.stdout_file = None
            if self.redirect_stderr:
                stderr = subprocess.STDOUT
                self.stderr_file = None
            elif self.stderr_logfile:
                os.makedirs(os.path.dirname(self.stderr_logfile), exist_ok=True)
                raw_stderr_file = open(self.stderr_logfile, "ab", buffering=0)  # noqa: SIM115 Use a context manager for opening files. File handle is needed during the subprocess' lifetime.
                self.stderr_file = io.TextIOWrapper(raw_stderr_file, encoding="utf-8", line_buffering=True)
                stderr = self.stderr_file
            else:
                self.stderr_file = None
                stderr = None

            cmd_args = self.command.split()
            self.process = subprocess.Popen(cmd_args, stdout=self.stdout_file, stderr=stderr, start_new_session=False, cwd=self.directory)  # noqa: S603 `subprocess` call: check for execution of untrusted input. user has to make sure that cmd_args is safe.
            self._add_process_to_job()

            self.start_time = time.time()
            # Reset backoff if process successfully starts
            threading.Thread(target=self._check_start_success, daemon=True).start()
        except (OSError, ValueError) as e:
            servicemanager.LogErrorMsg(f"Failed to start {self.name}: {e!s}")
            self.is_starting = False

    def _check_start_success(self):
        """Check if the process starts successfully and reset backoff."""
        time.sleep(1)  # Give it a moment to start
        if self.process and self.process.poll() is None:
            self.backoff_index = 0  # Reset backoff on successful start
        self.is_starting = False

    def _add_process_to_job(self):
        # Convert process ID to handle with required permissions
        perms = win32con.PROCESS_TERMINATE | win32con.PROCESS_SET_QUOTA
        process_handle = win32api.OpenProcess(perms, False, self.process.pid)  # noqa: FBT003 Boolean positional value in function call

        # Assign the child process to the Job Object
        win32job.AssignProcessToJobObject(self.job_handle, process_handle)

    def stop_program(self):
        if self.process is not None and self.process.poll() is None:
            kill_process_tree(self.process.pid)
        self.close_files()
        self.process = None
        self.is_starting = False

    def close_files(self):
        """Closes log file handles if they are open."""
        if self.stdout_file:
            self.stdout_file.close()
            self.stdout_file = None
        if self.stderr_file:
            self.stderr_file.close()
            self.stderr_file = None

    def __del__(self):
        """Destructor to ensure resources are freed when the object is deleted."""
        self.close_files()


class MyServiceFramework(win32serviceutil.ServiceFramework):
    _svc_name_ = "PyWin32Supervisor"
    _svc_display_name_ = "Python Win32 Supervisor Service"
    _exe_name_ = sys.executable
    _exe_args_ = '-u -E "' + os.path.abspath(__file__) + '"'

    def SvcDoRun(self):  # noqa: N802 (Function name should be lowercase): overriding interface method.
        self.ReportServiceStatus(win32service.SERVICE_START_PENDING)

        # Initialize and parse arguments
        args = self.parse_arguments()
        self.config_path = args.config
        # Set environment variables from args.env
        if args.env:
            for key, value in args.env:
                os.environ[f"ENV_{key}"] = value

        # Load and process config
        config = self.load_config(self.config_path)

        self.job_handle = self.create_job()

        # Load programs from config
        self.programs = self.load_programs(config)

        # Start XML-RPC server
        self.start_xmlrpc_server()

        # Start autostart programs
        self.start_autostart_programs()

        # Mark service as running
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        self.running = True

        # Start monitoring loop
        self.monitor_programs()

    def parse_arguments(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--config", required=True)
        parser.add_argument(
            "--env",
            action="append",
            type=lambda kv: tuple(kv.split("=", 1)),
            help="Environment variable as NAME=VALUE (can be repeated)",
        )
        argv = sys.argv[2:]
        if argv and argv[0] == "debug":  # Check for empty argv to avoid IndexError
            argv = argv[1:]
        return parser.parse_args(argv)  # Skip script and "service"

    def load_config(self, config_path):
        """Loads and processes the configuration file."""
        config = configparser.RawConfigParser()
        if not os.path.exists(config_path):
            servicemanager.LogErrorMsg(f"Config file not found: {config_path}")
            raise FileNotFoundError(f"Config file not found: {config_path}")

        config.read(config_path)

        # Replace environment variables in config
        for section in config.sections():
            for key in config[section]:
                value = config[section][key]
                config[section][key] = re.sub(r"%\((\w+)\)s", lambda m: os.environ.get(m.group(1), ""), value)

        return config

    def create_job(self):
        """Needed to ensure that all processes exit when the service is terminated.

        See also: https://stackoverflow.com/questions/23434842/python-how-to-kill-child-processes-when-parent-dies
        """

        # Create a Job Object
        job_handle = win32job.CreateJobObject(None, "")

        # Set the job object to terminate all child processes when the main process exits
        extended_info = win32job.QueryInformationJobObject(job_handle, win32job.JobObjectExtendedLimitInformation)
        extended_info["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job_handle, win32job.JobObjectExtendedLimitInformation, extended_info)

        # Ensure the main process is in the job object to avoid the race condition
        current_process_handle = ctypes.windll.kernel32.GetCurrentProcess()
        win32job.AssignProcessToJobObject(job_handle, current_process_handle)

        return job_handle

    def load_programs(self, config):
        """Loads program definitions from the configuration."""
        programs = {}
        for section in config.sections():
            if section.startswith("program:"):
                program_name = section.split(":", 1)[1]
                programs[program_name] = Program(program_name, config[section], self.job_handle)
        return programs

    def start_xmlrpc_server(self):
        """Starts the XML-RPC server in a separate thread."""
        self.xmlrpc_server = xmlrpc.server.SimpleXMLRPCServer(("127.0.0.1", 9001), allow_none=True)
        self.xmlrpc_server.register_instance(self)
        self.xmlrpc_thread = threading.Thread(target=self.xmlrpc_server.serve_forever)
        self.xmlrpc_thread.start()

    def start_autostart_programs(self):
        """Starts all programs marked as autostart."""
        for program in self.programs.values():
            if program.autostart:
                program.start_program()

    def is_running(self):
        return self.running

    def monitor_programs(self):
        """Monitors the running programs and restarts if necessary."""
        while self.is_running():
            time.sleep(1)
            for program in self.programs.values():
                if program.process is not None and program.process.poll() is not None and not program.is_starting:
                    program.close_files()
                    if program.autorestart:
                        backoff = program.backoff_periods[min(program.backoff_index, len(program.backoff_periods) - 1)]
                        time.sleep(backoff)
                        program.restart_count += 1
                        program.backoff_index = min(program.backoff_index + 1, len(program.backoff_periods) - 1)
                        program.start_program()

    def SvcStop(self):  # noqa: N802 (Function name should be lowercase): overriding interface method.
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.running = False
        for program in self.programs.values():
            program.stop_program()
        self.xmlrpc_server.shutdown()
        self.xmlrpc_thread.join()
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    # XML-RPC methods
    def status(self):
        status_list = []
        for program in self.programs.values():
            if program.is_starting:
                state = "STARTING"
                uptime = 0
            elif program.process is not None and program.process.poll() is None:
                state = "RUNNING"
                uptime = time.time() - program.start_time
            else:
                state = "STOPPED"
                uptime = 0
            status_list.append(
                {
                    "name": program.name,
                    "state": state,
                    "uptime": uptime,
                    "restart_count": program.restart_count,
                },
            )
        return status_list

    def start(self, program_name):
        if program_name == "all":
            for program in self.programs.values():
                program.start_program()
        else:
            program = self.programs.get(program_name)
            if program:
                program.start_program()
            else:
                return f"Program '{program_name}' not found"
        return "OK"

    def stop(self, program_name):
        if program_name == "all":
            for program in self.programs.values():
                program.stop_program()
        else:
            program = self.programs.get(program_name)
            if program:
                program.stop_program()
            else:
                return f"Program '{program_name}' not found"
        return "OK"

    def restart(self, program_name):
        if program_name == "all":
            for program in self.programs.values():
                program.stop_program()
                program.start_program()
        else:
            program = self.programs.get(program_name)
            if program:
                program.stop_program()
                program.start_program()
            else:
                return f"Program '{program_name}' not found"
        return "OK"


def filter_args(args, keys_to_remove):
    filtered_args = []
    i = 0
    while i < len(args):
        if args[i] in keys_to_remove:
            # Skip key and value only if the next arg is a value (not a flag or command)
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                i += 2
            else:
                i += 1
        else:
            filtered_args.append(args[i])
            i += 1
    return filtered_args


def main():
    """Main entry point for initializing the service or command-line execution."""
    if is_service_mode():
        start_service_mode()
    else:
        parser = create_argument_parser()
        args = parser.parse_args(sys.argv[1:])
        handle_arguments(args, parser)


def is_service_mode():
    """Check if the script is started in service mode."""
    return len(sys.argv) > 1 and sys.argv[1] == SERVICE_COMMAND_CONSTANT


def start_service_mode():
    """Initialize and start the service dispatcher."""
    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(MyServiceFramework)
    servicemanager.StartServiceCtrlDispatcher()


def create_argument_parser():
    """Create and return the argument parser."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", choices=["install", "remove", "start", "stop", "restart", "debug"], help="Service-related command")
    # Options for 'install' and 'update'
    parser.add_argument("--startup", choices=["manual", "auto", "disabled", "delayed"], help="How the service starts (default: manual)")
    parser.add_argument("--username", help="The username the service runs under (domain\\username)")
    parser.add_argument("--password", help="The password for the username")
    parser.add_argument("--interactive", action="store_true", help="Allow the service to interact with the desktop")
    parser.add_argument("--perfmonini", help=".ini file for performance monitor data")
    parser.add_argument("--perfmondll", help=".dll file for performance data")
    # Options for 'start' and 'stop'
    parser.add_argument("--wait", type=int, help="Seconds to wait for service to start or stop")
    # Custom options
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--env", action="append", type=lambda kv: kv.split("=", 1), help="Environment variable as NAME=VALUE (can be repeated)")
    # Positional arguments for non-service mode
    parser.add_argument("command", nargs="?", choices=["status", "start", "stop", "restart"], help="Command to execute (non-service mode)")
    parser.add_argument("program", nargs="?", default="all", help="Program to manage (non-service mode)")
    return parser


def handle_arguments(args, parser):
    """Handle parsed arguments and execute the appropriate actions."""
    if args.service:
        handle_service_command(args, parser)
    elif args.command:
        handle_program_command(args)
    else:
        parser.print_help()


def handle_service_command(args, parser):
    """Handle service-related commands like install, start, stop, etc."""
    if args.service == "install":
        validate_install_arguments(args, parser)
        MyServiceFramework._exe_args_ += f' {SERVICE_COMMAND_CONSTANT} --config "{args.config}"'
        if args.env:
            for key, value in args.env:
                MyServiceFramework._exe_args_ += f' --env "{key}={value}"'

    # Find the index of '--service'
    try:
        i = sys.argv.index("--service")
    except ValueError as e:
        raise ValueError(" '--service' not found in sys.argv") from e

    command = sys.argv[i + 1]  # The service command (e.g., 'install', 'start')
    # Remove '--service' and its value
    argv_without_service = sys.argv[:i] + sys.argv[i + 2 :]

    # Remove --config and --env from remaining arguments
    options_to_remove = ["--config", "--env"]
    remaining_args = filter_args(argv_without_service[1:], options_to_remove)

    # Construct filtered_argv: script name, command, remaining arguments
    filtered_argv = [sys.argv[0], *remaining_args, command]

    sys.frozen = True  # Required for 'debug' command compatibility
    win32serviceutil.HandleCommandLine(MyServiceFramework, argv=filtered_argv)


def validate_install_arguments(args, parser):
    """Ensure required arguments are provided for service installation and that the config file exists."""
    if not args.config:
        parser.error("--config is required for install")

    if not os.path.isfile(args.config):
        parser.error(f"Config file '{args.config}' does not exist.")


def handle_program_command(args):
    """Handle program-related commands such as status, start, stop, and restart."""

    socket.setdefaulttimeout(10)
    try:
        with xmlrpc.client.ServerProxy("http://127.0.0.1:9001") as server:
            if args.command == "status":
                print_status(server)
            elif args.command == "start":
                print_result(server.start(args.program), args.program, "Started")
            elif args.command == "stop":
                print_result(server.stop(args.program), args.program, "Stopped")
            elif args.command == "restart":
                print_result(server.restart(args.program), args.program, "Restarted")
    except (ConnectionRefusedError, TimeoutError):
        logging.exception("Service is not running. Please start the service first with 'python supervisor.py --service start'.")

    except ValueError:
        logging.exception("Error")


def format_uptime(uptime):
    """Convert uptime in seconds to a human-readable format, omitting zero values."""
    if uptime <= 0:
        return "N/A"

    days, remainder = divmod(int(uptime), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds:
        parts.append(f"{seconds}s")

    return " ".join(parts)


def print_status(server):
    """Retrieve and log the status of programs from the XML-RPC server with dynamically adjusted column widths."""
    status = server.status()

    # Define headers
    headers = ["Name", "State", "Uptime", "Restarts"]

    # Convert status data into rows
    rows = [[s["name"], str(s["state"]), format_uptime(s["uptime"]), str(s["restart_count"])] for s in status]

    # Compute column widths based on maximum content length
    col_widths = [max(len(header), *(len(row[i]) for row in rows)) + 2 for i, header in enumerate(headers)]

    # Print header row
    header_row = "".join(f"{header:<{width}}" for header, width in zip(headers, col_widths, strict=False))
    logging.info(header_row)
    logging.info("-" * sum(col_widths))

    # Print status rows
    for row in rows:
        row_str = "".join(f"{cell:<{col_widths[i]}}" for i, cell in enumerate(row))
        logging.info(row_str)


def print_result(result, program, action):
    """Log the result of a start, stop, or restart action."""
    logging.info("%s program '%s': %s", action, program, result)


if __name__ == "__main__":
    main()
