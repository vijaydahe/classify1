# ClassifyHub endpoint agent installer for Windows.
# Installs the agent under %LOCALAPPDATA% and registers a Scheduled Task so it
# runs at logon and scans on the configured interval.
$ErrorActionPreference = "Stop"

$InstallDir = Join-Path $env:LOCALAPPDATA "ClassifyHub"
$SrcDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) { $Python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $Python) {
    Write-Error "Python 3 is required. Install it from https://www.python.org and re-run."
    exit 1
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item (Join-Path $SrcDir "agent.py") $InstallDir -Force
Copy-Item (Join-Path $SrcDir "config.json") $InstallDir -Force

$AgentPath = Join-Path $InstallDir "agent.py"
$Action = New-ScheduledTaskAction -Execute $Python.Source -Argument "`"$AgentPath`" --daemon"
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Unregister-ScheduledTask -TaskName "ClassifyHubAgent" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "ClassifyHubAgent" -Action $Action -Trigger $Trigger -Settings $Settings | Out-Null
Start-ScheduledTask -TaskName "ClassifyHubAgent"

Write-Host "ClassifyHub agent installed to $InstallDir and started."
Write-Host "Run once manually with: $($Python.Source) `"$AgentPath`""
