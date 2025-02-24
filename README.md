# pywin32supervisor
Python win32 service similar to supervisor for Unix based systems.

# Works:

```
sc create MySupervisorService binPath= "\"C:\tmp\ims_windows_deploy\venv\Scripts\python.exe\" \"C:\Users\gregk\Desktop\winpython\WPy64-31090\click\supervisor_service.py\" service --config \"C:\tmp\ims_windows_deploy\inventory_source\configs\server_configs\supervisord.conf\" --install-dir \"C:\tmp\ims_windows_deploy\inventory_source\""
sc delete MySupervisorService
```


# Works:

```
python supervisor.py install --config "C:\tmp\ims_windows_deploy\inventory_source\configs\server_configs\supervisord.conf" --install-dir "C:\tmp\ims_windows_deploy\inventory_source"
```
