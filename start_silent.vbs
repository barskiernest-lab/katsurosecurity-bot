Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\ASUS\Documents\Default Project"
WshShell.Run "python.exe watchdog.py", 0, False
