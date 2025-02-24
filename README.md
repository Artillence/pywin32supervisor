# pywin32supervisor

A Python-based Windows service for process supervision, inspired by the Unix [`supervisor`](http://supervisord.org/) tool. This package leverages [`pywin32`](https://github.com/mhammond/pywin32) to manage subprocesses on Windows, providing features like autostart, autorestart, logging, and remote control via an [XML-RPC](https://docs.python.org/3/library/xmlrpc.html) interface.

---

## Features

- **Service Management**: Install, start, stop, and debug as a Windows service.
- **Process Supervision**: Manage multiple programs with configurable autostart and autorestart policies.
- **Logging**: Redirect stdout/stderr to files or combine them as needed.
- **Remote Control**: Use an XML-RPC server to monitor and control programs.
- **Environment Variables**: Substitute variables in the config file with command-line provided values.

---

## Requirements

- Python 3.10 or higher
- Windows operating system
- `pywin32` library (version 308 or higher)

---

## Installation

### From PyPI (Not Yet Published)
Once published, install using pip:
```bash
pip install pywin32supervisor
```

### From Source
1. Clone the repository:
   ```bash
   git clone https://github.com/Artillence/pywin32supervisor.git
   cd pywin32supervisor
   ```
2. Install dependencies and the package:
   ```bash
   pip install .
   ```

---

## Usage

### Running as a Script
You can run the supervisor directly from the source file:
```bash
python pywin32supervisor/supervisor.py --service install --config "C:\path\to\supervisord.conf" --env PYTHON_PATH=C:\venv\Scripts\python.exe
python pywin32supervisor/supervisor.py --service start
python pywin32supervisor/supervisor.py status
```

### Running as an Installed Package
After installation, use the `pywin32supervisor` command:
```bash
pywin32supervisor --service install --config "C:\path\to\supervisord.conf" --env PYTHON_PATH=C:\venv\Scripts\python.exe --env MY_VAR=C:\some_path
pywin32supervisor --service start
pywin32supervisor status
```

### Commands
- `--service install`: Installs the service with the specified config and environment variables.
- `--service start`: Starts the installed service.
- `--service stop`: Stops the running service.
- `--service remove`: Uninstalls the service.
- `--service debug`: Runs the service in debug mode (foreground).
- `status`: Displays the status of all managed programs.
- `start <program>`: Starts a specific program (or `all`).
- `stop <program>`: Stops a specific program (or `all`).
- `restart <program>`: Restarts a specific program (or `all`).

### Environment Variables
Use the `--env` flag to pass environment variables (e.g., `--env KEY=VALUE`). These are prefixed with `ENV_` in the environment and can be referenced in the config file as `%(ENV_KEY)s`.

Example:
```bash
pywin32supervisor --service install --config "C:\supervisord.conf" --env PYTHON_PATH=C:\venv\Scripts\python.exe
```
In `supervisord.conf`:
```ini
[program:myapp]
command=%(ENV_PYTHON_PATH)s my_script.py
```

---

## Configuration File

The service uses an INI-style configuration file (e.g., `supervisord.conf`). Each managed program is defined in a `[program:<name>]` section.

### Example `supervisord.conf`
```ini
[program:worker]
command=C:\venv\Scripts\python.exe C:\app\worker.py
autostart=true
autorestart=true
stdout_logfile=C:\logs\worker\stdout.log
stderr_logfile=C:\logs\worker\stderr.log
redirect_stderr=false

[program:server]
command=%(PYTHON_PATH)s C:\app\server.py
autostart=true
autorestart=false
stdout_logfile=C:\logs\server\stdout.log
```

### Configuration Options
- `command`: The command to execute (required).
- `autostart`: Start the program when the service starts (`true`/`false`, default: `false`).
- `autorestart`: Restart the program if it exits unexpectedly (`true`/`false`, default: `false`).
- `stdout_logfile`: Path to redirect stdout (optional).
- `stderr_logfile`: Path to redirect stderr (optional).
- `redirect_stderr`: Combine stderr with stdout (`true`/`false`, default: `false`).

---

## Development

### Directory Structure
```
pywin32supervisor/
├── README.md
├── pyproject.toml
├── ruff.toml
├── .pre-commit-config.yaml
└── pywin32supervisor/
    ├── __init__.py
    └── supervisor.py
```

### Setup
1. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

2. Install pre-commit hooks:
   ```bash
   pre-commit install
   ```

### Linting and Formatting
- Linting is configured with `ruff` (see `ruff.toml`).
- Run `ruff check .` to lint or `ruff check . --fix` to auto-fix issues.
- Formatting is handled by `ruff format`.

---

## Known Limitations
- Requires administrative privileges to install/start/stop the service.
- XML-RPC server binds to `127.0.0.1:9001` with no authentication (local access only).
- Config file must be trusted; no sanitization of commands.

---

## Contributing
Contributions are welcome! Please:
1. Fork the repository.
2. Create a feature branch.
3. Submit a pull request with a clear description.

See [GitHub Issues](https://github.com/Artillence/pywin32supervisor/issues) for current tasks or to report bugs.

---

## License
This project is licensed under the terms specified in the `LICENSE` file.

---

## Contact
For questions or support, contact [Greg Karz](mailto:greg.karz@artillence.com) or visit the [project homepage](https://github.com/Artillence/pywin32supervisor).
```
