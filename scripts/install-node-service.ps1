# ===========================================================================
# PHOENIX Node Service Installer — Windows (Build #91)
#
# Installs node_service.py as a startup task using Task Scheduler.
#
# Usage (Run as Administrator):
#   .\install-node-service.ps1 -Token YOUR_TOKEN -Server https://phoenix.example.com
#   .\install-node-service.ps1 -Uninstall
#   .\install-node-service.ps1 -Status
# ===========================================================================

param(
    [string]$Token = "",
    [string]$Server = "http://localhost:5000",
    [switch]$Uninstall,
    [switch]$Status,
    [switch]$Help
)

$TaskName = "PhoenixNodeService"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$NodeServicePath = Join-Path $ProjectDir "node_service.py"
$LogDir = Join-Path $env:LOCALAPPDATA "Phoenix"
$LogFile = Join-Path $LogDir "phoenix-node-service.log"

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

if ($Help) {
    Write-Host "Phoenix Node Service Installer (Windows)"
    Write-Host ""
    Write-Host "Usage:"
    Write-Host "  .\install-node-service.ps1 -Token TOKEN [-Server URL]"
    Write-Host "  .\install-node-service.ps1 -Uninstall"
    Write-Host "  .\install-node-service.ps1 -Status"
    exit 0
}

# ---------------------------------------------------------------------------
# Python detection
# ---------------------------------------------------------------------------

function Find-Python {
    $candidates = @("python3", "python", "py")
    foreach ($cmd in $candidates) {
        $path = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($path) {
            $version = & $path.Source --version 2>&1
            if ($version -match "Python 3") {
                return $path.Source
            }
        }
    }
    return $null
}

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

if ($Status) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "Phoenix Node Service: $($task.State)"
        $task | Format-List TaskName, State, LastRunTime, NextRunTime
    } else {
        Write-Host "Phoenix Node Service: NOT INSTALLED"
    }
    exit 0
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

if ($Uninstall) {
    Write-Host "Uninstalling Phoenix Node Service..."
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Service removed."
    } else {
        Write-Host "Service not found."
    }
    exit 0
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

if (-not $Token) {
    Write-Host "ERROR: -Token is required for installation"
    Write-Host "  Get your token from: https://your-phoenix-server/helper/dashboard"
    exit 1
}

if (-not (Test-Path $NodeServicePath)) {
    Write-Host "ERROR: node_service.py not found at $NodeServicePath"
    exit 1
}

$PythonPath = Find-Python
if (-not $PythonPath) {
    Write-Host "ERROR: Python 3 not found. Please install Python 3.9+ from python.org"
    exit 1
}

# Check aiohttp
$aioCheck = & $PythonPath -c "import aiohttp" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: aiohttp is required. Install with:"
    Write-Host "  $PythonPath -m pip install aiohttp"
    exit 1
}

Write-Host "Installing Phoenix Node Service (Windows Task Scheduler)..."
Write-Host "  Python: $PythonPath"
Write-Host "  Service: $NodeServicePath"
Write-Host "  Server: $Server"
Write-Host "  Log: $LogFile"

# Create log directory
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Remove existing task if any
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create scheduled task that runs at logon and restarts on failure
$action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "$NodeServicePath --token $Token --server $Server" `
    -WorkingDirectory $ProjectDir

$trigger = New-ScheduledTaskTrigger -AtLogon

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Phoenix Node Service - background data bridge for CitizenSERP network" | Out-Null

# Start it now
Start-ScheduledTask -TaskName $TaskName

Write-Host ""
Write-Host "Phoenix Node Service installed and started."
Write-Host "  To check status:   .\install-node-service.ps1 -Status"
Write-Host "  To uninstall:      .\install-node-service.ps1 -Uninstall"
Write-Host "  To view logs:      Get-Content '$LogFile' -Tail 50 -Wait"
