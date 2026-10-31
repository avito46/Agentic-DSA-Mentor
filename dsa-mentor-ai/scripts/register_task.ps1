# PowerShell script to register DSA Mentor AI in Windows Task Scheduler
# Schedules daily execution at specified time with run-at-next-login support.

param (
    [string]$TaskName = "DSAMentorAI_Daily",
    [string]$DailyTime = "08:00",
    [switch]$RunAtNextLogin,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

# Unregister if requested
if ($Unregister) {
    Write-Host "Unregistering Task Scheduler task '$TaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task '$TaskName' successfully unregistered." -ForegroundColor Green
    exit 0
}

# Resolve project paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = (Resolve-Path "$ScriptDir\..").Path
$PythonVenv = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$DailyScript = Join-Path $ProjectDir "scripts\run_daily.py"

if (-not (Test-Path $PythonVenv)) {
    Write-Error "Virtual environment python was not found at $PythonVenv. Please create .venv first."
    exit 1
}

Write-Host "Configuring Windows Task Scheduler Task: $TaskName" -ForegroundColor Cyan
Write-Host "Project Directory: $ProjectDir"
Write-Host "Python Executable: $PythonVenv"
Write-Host "Daily Schedule Time: $DailyTime (Asia/Kolkata timezone)"

# Action: Execute run_daily.py inside venv
$Action = New-ScheduledTaskAction -Execute $PythonVenv -Argument "`"$DailyScript`"" -WorkingDirectory $ProjectDir

# Trigger: Daily at specified time
$DailyTrigger = New-ScheduledTaskTrigger -Daily -At $DailyTime

$Triggers = @($DailyTrigger)
if ($RunAtNextLogin) {
    Write-Host "Adding trigger: Run at user logon" -ForegroundColor Cyan
    $LogonTrigger = New-ScheduledTaskTrigger -AtLogOn
    $Triggers += $LogonTrigger
}

# Settings: Allow run on battery, start when available if missed, wake to run
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

# Register the task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Description "DSA Mentor AI Daily Problem Recommendation & Coaching Pipeline" `
    -Force

Write-Host "`nTask '$TaskName' registered successfully!" -ForegroundColor Green
Write-Host "To test run immediately: Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host "To view task: Get-ScheduledTask -TaskName `"$TaskName`""
Write-Host "To unregister: .\register_task.ps1 -Unregister"
