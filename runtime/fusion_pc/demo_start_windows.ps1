param(
    [ValidateSet("full4ch", "demo2ch")]
    [string]$Mode = "full4ch",

    [switch]$SkipPreflight
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
}
else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw "Python was not found. Create and activate runtime\fusion_pc\.venv first."
    }
    $Python = $PythonCommand.Source
}

if (-not $SkipPreflight) {
    & powershell.exe -ExecutionPolicy Bypass -File (Join-Path $Root "demo_preflight.ps1") -Mode $Mode
    if ($LASTEXITCODE -ne 0) {
        throw "Preflight failed. Runtime was not started."
    }
}

$Programs = if ($Mode -eq "full4ch") {
    @(
        @{ File = "5_final_fusion.py"; DelayMs = 1200 },
        @{ File = "ai_decision_dashboard.py"; DelayMs = 600 },
        @{ File = "6_turret_server.py"; DelayMs = 0 }
    )
}
else {
    @(
        @{ File = "tcp_zmq_bridge.py"; DelayMs = 700 },
        @{ File = "5_final_fusion.py"; DelayMs = 1200 },
        @{ File = "ai_decision_dashboard.py"; DelayMs = 600 },
        @{ File = "6_turret_server.py"; DelayMs = 0 }
    )
}

Write-Host "Starting AEGIS mode: $Mode" -ForegroundColor Cyan
if ($Mode -eq "full4ch") {
    Write-Host "Full 4CH uses direct ZMQ/JPEG input on port 5555; tcp_zmq_bridge.py is intentionally omitted."
}
else {
    Write-Host "Simplified 2CH demo uses RAW TCP 5560 and starts tcp_zmq_bridge.py."
}

foreach ($Program in $Programs) {
    $File = $Program.File
    $Command = "& '$Python' '.\$File'"

    Start-Process `
        powershell.exe `
        -ArgumentList "-NoExit", "-Command", "Set-Location -LiteralPath '$Root'; $Command"

    if ($Program.DelayMs -gt 0) {
        Start-Sleep -Milliseconds $Program.DelayMs
    }
}
