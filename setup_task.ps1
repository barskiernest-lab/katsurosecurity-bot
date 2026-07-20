Unregister-ScheduledTask -TaskName "TelegramBot" -Confirm:$false -ErrorAction SilentlyContinue
$pythonPath = (Get-Command python).Source
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"C:\Users\ASUS\Documents\Default Project\bot.py`"" -WorkingDirectory 'C:\Users\ASUS\Documents\Default Project'
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "TelegramBot" -Action $action -Trigger $trigger -Settings $settings -Force -Description "KATSUROSECURITY Bot"
