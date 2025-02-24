import argparse
import configparser
import logging
import os
import re
import subprocess
import sys
import threading
import time
import xmlrpc.client
import xmlrpc.server

import servicemanager
import win32service
import win32serviceutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # Logs to console
    ],
)


class Program:
    """Represents a managed program."""

    def __init__(self, name, config):
        self.name = name
        self.command = config["command"]
        self.autostart = config.getboolean("autostart", False)
        self.autorestart = config.getboolean("autorestart", False)
        self.stdout_logfile = config.get("stdout_logfile", None)
        self.stderr_logfile = config.get("stderr_logfile", None)
        self.redirect_stderr = config.getboolean("redirect_stderr", False)
        self.process = None
        self.start_time = None
        self.restart_count = 0
        self.stdout_file = None
        self.stderr_file = None

    def start_program(self):
        if self.process is not None and self.process.poll() is None:
            return  # Already running
        try:
            if self.stdout_logfile:
                os.makedirs(os.path.dirname(self.stdout_logfile), exist_ok=True)
                self.stdout_file = open(self.stdout_logfile, "a")  # noqa: SIM115 Use a context manager for opening files. File handle is needed during the subprocess' lifetime.
            else:
                self.stdout_file = None
            if self.redirect_stderr:
                stderr = subprocess.STDOUT
                self.stderr_file = None
            elif self.stderr_logfile:
                os.makedirs(os.path.dirname(self.stderr_logfile), exist_ok=True)
                self.stderr_file = open(self.stderr_logfile, "a")  # noqa: SIM115 Use a context manager for opening files. File handle is needed during the subprocess' lifetime.
                stderr = self.stderr_file
            else:
                self.stderr_file = None
                stderr = None

            cmd_args = self.command.split()
            self.process = subprocess.Popen(cmd_args, stdout=self.stdout_file, stderr=stderr)  # noqa: S603 `subprocess` call: check for execution of untrusted input. user has to make sure that cmd_args is safe.
            self.start_time = time.time()
        except (OSError, ValueError) as e:
            servicemanager.LogErrorMsg(f"Failed to start {self.name}: {e!s}")

    def stop_program(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self._close_files()
        self.process = None

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
        self._close_files()


class MyServiceFramework(win32serviceutil.ServiceFramework):
    _svc_name_ = "MySupervisorService"
    _svc_display_name_ = "My Supervisor Service"
    _exe_name_ = sys.executable
    _exe_args_ = '-u -E "' + os.path.abspath(__file__) + '"'

    def SvcDoRun(self):  # noqa: N802 (Function name should be lowercase): overriding interface method.
        self.ReportServiceStatus(win32service.SERVICE_START_PENDING)

        # Initialize and parse arguments
        args = self.parse_arguments()
        self.config_path = args.config
        os.environ["ENV_INVENTORY_INSTALL_DIR"] = args.install_dir

        # Load and process config
        config = self.load_config(self.config_path)

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
        """Parses command-line arguments."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--config", required=True)
        parser.add_argument("--install-dir", required=True)
        return parser.parse_args(sys.argv[2:])  # Skip script and "service"

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

    def load_programs(self, config):
        """Loads program definitions from the configuration."""
        programs = {}
        for section in config.sections():
            if section.startswith("program:"):
                program_name = section.split(":", 1)[1]
                programs[program_name] = Program(program_name, config[section])
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

    def monitor_programs(self):
        """Monitors the running programs and restarts if necessary."""
        while self.running:
            time.sleep(1)
            for program in self.programs.values():
                if program.process is not None and program.process.poll() is not None:
                    # Process exited
                    program.close_files()
                    if program.autorestart:
                        program.restart_count += 1
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
            if program.process is not None and program.process.poll() is None:
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
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in keys_to_remove:
            skip_next = True
            continue
        filtered_args.append(arg)
    return filtered_args


def init():
    """Main entry point for initializing the service or command-line execution."""
    if is_service_mode():
        start_service_mode()
    else:
        parser = create_argument_parser()
        args = parser.parse_args(sys.argv[1:])
        handle_arguments(args, parser)


def is_service_mode():
    """Check if the script is started in service mode."""
    return len(sys.argv) > 1 and sys.argv[1] == "service"


def start_service_mode():
    """Initialize and start the service dispatcher."""
    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(MyServiceFramework)
    servicemanager.StartServiceCtrlDispatcher()


def create_argument_parser():
    """Create and return the argument parser."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", choices=["install", "remove", "start", "stop", "restart", "debug"])
    parser.add_argument("--config")
    parser.add_argument("--install-dir")
    parser.add_argument("command", nargs="?", choices=["status", "start", "stop", "restart"])
    parser.add_argument("program", nargs="?", default="all")
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
        MyServiceFramework._exe_args_ += f' service --config "{args.config}" --install-dir "{args.install_dir}"'

    keys_to_remove = {"--service", "--config", "--install-dir"}
    filtered_argv = [*filter_args(sys.argv, keys_to_remove), args.service]

    sys.frozen = True
    win32serviceutil.HandleCommandLine(MyServiceFramework, argv=filtered_argv)


def validate_install_arguments(args, parser):
    """Ensure required arguments are provided for service installation."""
    if not args.config or not args.install_dir:
        parser.error("--config and --install-dir are required for install")


def handle_program_command(args):
    """Handle program-related commands such as status, start, stop, and restart."""
    server = xmlrpc.client.ServerProxy("http://127.0.0.1:9001")

    try:
        if args.command == "status":
            print_status(server)
        elif args.command == "start":
            print_result(server.start(args.program), args.program, "Started")
        elif args.command == "stop":
            print_result(server.stop(args.program), args.program, "Stopped")
        elif args.command == "restart":
            print_result(server.restart(args.program), args.program, "Restarted")

    except ConnectionRefusedError:
        logging.exception("Service is not running. Please start the service first with 'python script.py --service start'.")

    except ValueError:
        logging.exception("Error")


def print_status(server):
    """Retrieve and log the status of programs from the XML-RPC server."""
    status = server.status()
    for s in status:
        uptime = f"{s['uptime']:.2f} seconds" if s["uptime"] > 0 else "N/A"
        logging.info(
            "%s: %s, Uptime: %s, Restarts: %d",
            s["name"],
            s["state"],
            uptime,
            s["restart_count"],
        )


def print_result(result, program, action):
    """Log the result of a start, stop, or restart action."""
    logging.info("%s program '%s': %s", action, program, result)


if __name__ == "__main__":
    init()
