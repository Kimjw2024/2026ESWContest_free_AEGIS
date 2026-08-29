param(
    [ValidateSet("full4ch", "demo2ch")]
    [string]$Mode = "full4ch"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $Root "..\..")).Path
Set-Location $Root

$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCommand) {
    throw "Python was not found. Activate runtime\fusion_pc\.venv first."
}
$Python = $PythonCommand.Source

$Version = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to execute Python: $Python"
}
if ($Version -ne "3.11") {
    Write-Warning "Python 3.11 is recommended; current interpreter is Python $Version."
}

$CommonRequired = @(
    "5_final_fusion.py",
    "5_final_fusion_async.py",
    "config_turret.py",
    "6_turret_server.py",
    "ai_decision_dashboard.py",
    "aegis_species_classifier.py",
    "aegis_decision_engine.py",
    "calib_data.json",
    "turret_calibration_overrides.json",
    "models\yolo26n.pt",
    "models\custom\aegis_bird_resnet18_v2.pt",
    "data\intrinsics_0.npz",
    "data\intrinsics_1.npz",
    "data\intrinsics_2.npz",
    "data\intrinsics_3.npz",
    "data\calib_01.npz",
    "data\calib_02.npz",
    "data\calib_03.npz",
    "data\calib_12.npz",
    "data\calib_13.npz",
    "data\calib_23.npz"
)

$ModeRequired = if ($Mode -eq "full4ch") {
    @(
        (Join-Path $RepoRoot "runtime\raspberry_pi\sender_FIXED_2.py"),
        (Join-Path $RepoRoot "runtime\raspberry_pi\sender2_FIXED_2.py"),
        (Join-Path $RepoRoot "scripts\rpi_start_sender.sh")
    )
}
else {
    @(
        "tcp_zmq_bridge.py",
        (Join-Path $RepoRoot "runtime\raspberry_pi\sender_TCP_5560.py"),
        (Join-Path $RepoRoot "scripts\rpi_start_demo_2ch.sh")
    )
}

$Missing = @()

foreach ($File in $CommonRequired) {
    $Path = Join-Path $Root $File
    if (-not (Test-Path $Path)) {
        $Missing += $Path
    }
}

foreach ($Path in $ModeRequired) {
    if (-not (Test-Path $Path)) {
        $Missing += $Path
    }
}

if ($Missing.Count -gt 0) {
    Write-Host "MISSING REQUIRED FILES:" -ForegroundColor Red
    $Missing | ForEach-Object { Write-Host " - $_" }
    throw "AEGIS preflight failed: required files are missing."
}

$LargeModelFiles = @(
    (Join-Path $Root "models\yolo26n.pt"),
    (Join-Path $Root "models\custom\aegis_bird_resnet18_v2.pt")
)

foreach ($Path in $LargeModelFiles) {
    if ((Get-Item $Path).Length -lt 1MB) {
        throw "Model file looks like an unresolved Git LFS pointer: $Path. Run 'git lfs pull'."
    }
}

$CalibrationFiles = Get-ChildItem (Join-Path $Root "data") -File |
    Where-Object { $_.Extension -eq ".npz" }

foreach ($File in $CalibrationFiles) {
    if ($File.Length -lt 1KB) {
        throw "Calibration file looks like an unresolved Git LFS pointer: $($File.FullName). Run 'git lfs pull'."
    }
}

$RequiredModules = @(
    @{ Label = "OpenCV"; Import = "cv2" },
    @{ Label = "NumPy"; Import = "numpy" },
    @{ Label = "Pillow"; Import = "PIL" },
    @{ Label = "PyZMQ"; Import = "zmq" },
    @{ Label = "pySerial"; Import = "serial" },
    @{ Label = "SciPy"; Import = "scipy" },
    @{ Label = "Ultralytics"; Import = "ultralytics" },
    @{ Label = "PySide6"; Import = "PySide6" },
    @{ Label = "PyTorch"; Import = "torch" },
    @{ Label = "torchvision"; Import = "torchvision" }
)

$MissingModules = @()
foreach ($Module in $RequiredModules) {
    & $Python -c "import $($Module.Import)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        $MissingModules += "$($Module.Label) [$($Module.Import)]"
    }
}

if ($MissingModules.Count -gt 0) {
    Write-Host "MISSING PYTHON MODULES:" -ForegroundColor Red
    $MissingModules | ForEach-Object { Write-Host " - $_" }
    throw "Install PyTorch/torchvision for the target CPU/CUDA environment, then run 'pip install -r requirements.txt'."
}

$PythonFiles = @(
    "5_final_fusion.py",
    "5_final_fusion_async.py",
    "config_turret.py",
    "tcp_zmq_bridge.py",
    "6_turret_server.py",
    "ai_decision_dashboard.py",
    "aegis_species_classifier.py",
    "aegis_decision_engine.py",
    "calibration_turret.py",
    "servo_zero_trim.py"
)

foreach ($File in $PythonFiles) {
    $Path = Join-Path $Root $File
    & $Python -m py_compile $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Python compile failed: $Path"
    }
}

$SenderFiles = @(
    (Join-Path $RepoRoot "runtime\raspberry_pi\sender_FIXED_2.py"),
    (Join-Path $RepoRoot "runtime\raspberry_pi\sender2_FIXED_2.py"),
    (Join-Path $RepoRoot "runtime\raspberry_pi\sender_TCP_5560.py")
)

foreach ($Path in $SenderFiles) {
    & $Python -m py_compile $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Python compile failed: $Path"
    }
}

Get-ChildItem $RepoRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "AEGIS PREFLIGHT PASSED" -ForegroundColor Green
Write-Host " Mode       : $Mode"
Write-Host " Python     : $Python ($Version)"
if ($Mode -eq "full4ch") {
    Write-Host " Topology   : 2 Raspberry Pis / 4 Cameras / direct ZMQ-JPEG :5555"
    Write-Host " Profile    : 640x360 @ 30 FPS / JPEG Q70"
}
else {
    Write-Host " Topology   : 1 Raspberry Pi / 2 Cameras / RAW TCP :5560 -> ZMQ :5555"
    Write-Host " Profile    : 640x360 @ 20 FPS / JPEG Q60"
}
