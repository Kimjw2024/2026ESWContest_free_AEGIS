$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Required = @(
    "5_final_fusion.py",
    "5_final_fusion_async.py",
    "config_turret.py",
    "tcp_zmq_bridge.py",
    "6_turret_server.py",
    "ai_decision_dashboard.py",
    "aegis_species_classifier.py",
    "aegis_decision_engine.py",
    "models\yolo26n.pt",
    "models\custom\aegis_bird_resnet18_v2.pt",
    "data\calib_01.npz",
    "data\calib_12.npz",
    "data\calib_23.npz"
)

$Missing = @(
    $Required |
    Where-Object {
        -not (Test-Path (Join-Path $Root $_))
    }
)

if ($Missing.Count -gt 0) {
    Write-Host "MISSING REQUIRED FILES:" -ForegroundColor Red
    $Missing | ForEach-Object { Write-Host " - $_" }
    exit 1
}

$PythonFiles = @(
    "5_final_fusion.py",
    "5_final_fusion_async.py",
    "config_turret.py",
    "tcp_zmq_bridge.py",
    "6_turret_server.py",
    "ai_decision_dashboard.py",
    "aegis_species_classifier.py",
    "aegis_decision_engine.py"
)

foreach ($File in $PythonFiles) {
    py -3.11 -m py_compile (Join-Path $Root $File)

    if ($LASTEXITCODE -ne 0) {
        throw "Python compile failed: $File"
    }
}

Write-Host "AEGIS PREFLIGHT PASSED" -ForegroundColor Green
