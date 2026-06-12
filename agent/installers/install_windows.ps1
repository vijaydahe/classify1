# ClassifyHub endpoint agent installer for Windows (command-line fallback).
# For the graphical setup, double-click "Install ClassifyHub.bat" instead.
#
# This script installs the agent under %LOCALAPPDATA% and registers a Scheduled
# Task so it runs at logon. It traps errors and pauses so the window never just
# flashes and closes.

try {
    $ErrorActionPreference = "Stop"
    $InstallDir = Join-Path $env:LOCALAPPDATA "ClassifyHub"
    $SrcDir = Split-Path -Parent $MyInvocation.MyCommand.Path

    # Find a real Python — skip the Microsoft Store alias stub in WindowsApps,
    # which exits silently and is the usual cause of the "red flash and close".
    $Python = $null
    foreach ($name in @("py.exe", "python.exe", "python3.exe")) {
        foreach ($cmd in (Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($cmd.Source -and ($cmd.Source -notmatch "WindowsApps")) { $Python = $cmd.Source; break }
        }
        if ($Python) { break }
    }
    if (-not $Python) {
        throw "Python 3 was not found. Install it from https://www.python.org/downloads/ and tick 'Add python.exe to PATH', then re-run."
    }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Copy-Item (Join-Path $SrcDir "agent.py") $InstallDir -Force
    Copy-Item (Join-Path $SrcDir "config.json") $InstallDir -Force
    if (Test-Path (Join-Path $SrcDir "stamp.py")) { Copy-Item (Join-Path $SrcDir "stamp.py") $InstallDir -Force }

    $AgentPath = Join-Path $InstallDir "agent.py"
    $Action  = New-ScheduledTaskAction -Execute $Python -Argument "`"$AgentPath`" --daemon"
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

    Unregister-ScheduledTask -TaskName "ClassifyHubAgent" -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName "ClassifyHubAgent" -Action $Action -Trigger $Trigger -Settings $Settings | Out-Null

    Write-Host ""
    Write-Host "ClassifyHub agent installed to $InstallDir and will run at every login." -ForegroundColor Green
    Write-Host "Running a first scan now..."
    & $Python "$AgentPath"
    Write-Host "Done." -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "Install failed: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Write-Host ""
    Read-Host "Press Enter to close"
}
