param(
    [string]$RepositoryUrl = "https://github.com/tigerjueun/2026ESWContest_free_AEGIS.git",
    [string]$Destination = (Join-Path $env:TEMP "AEGIS_RELEASE_VERIFY"),
    [switch]$KeepClone
)

$ErrorActionPreference = "Stop"

if (Test-Path $Destination) {
    Remove-Item $Destination -Recurse -Force
}

Write-Host "Cloning release into: $Destination" -ForegroundColor Cyan
git clone $RepositoryUrl $Destination
if ($LASTEXITCODE -ne 0) {
    throw "git clone failed."
}

Push-Location $Destination
try {
    git lfs install --local
    git lfs pull
    if ($LASTEXITCODE -ne 0) {
        throw "git lfs pull failed."
    }

    $RequiredFiles = @(
        "models\detector\yolo\yolo26n.pt",
        "models\classifier\resnet\aegis_bird_resnet18_v2.pt",
        "models\research\aegis_bird_yolov8s_best.pt",
        "runtime\fusion_pc\models\yolo26n.pt",
        "runtime\fusion_pc\models\custom\aegis_bird_resnet18_v2.pt",
        "calibration\intrinsics\intrinsics_0.npz",
        "calibration\intrinsics\intrinsics_1.npz",
        "calibration\intrinsics\intrinsics_2.npz",
        "calibration\intrinsics\intrinsics_3.npz",
        "calibration\stereo_pairs\calib_01.npz",
        "calibration\stereo_pairs\calib_02.npz",
        "calibration\stereo_pairs\calib_03.npz",
        "calibration\stereo_pairs\calib_12.npz",
        "calibration\stereo_pairs\calib_13.npz",
        "calibration\stereo_pairs\calib_23.npz"
    )

    $Missing = @()
    foreach ($RelativePath in $RequiredFiles) {
        if (-not (Test-Path $RelativePath)) {
            $Missing += $RelativePath
        }
    }
    if ($Missing.Count -gt 0) {
        $Missing | ForEach-Object { Write-Host "MISSING: $_" -ForegroundColor Red }
        throw "Fresh-clone verification failed: files are missing."
    }

    $ModelFiles = Get-ChildItem "models" -Recurse -File -Filter "*.pt"
    foreach ($File in $ModelFiles) {
        if ($File.Length -lt 1MB) {
            throw "Unresolved Git LFS pointer: $($File.FullName)"
        }
    }

    $CalibrationFiles = Get-ChildItem "calibration" -Recurse -File -Filter "*.npz"
    foreach ($File in $CalibrationFiles) {
        if ($File.Length -lt 1KB) {
            throw "Unresolved Git LFS pointer: $($File.FullName)"
        }
    }

    Write-Host ""
    Write-Host "FRESH CLONE + GIT LFS VERIFICATION PASSED" -ForegroundColor Green
    Write-Host "Models      : $($ModelFiles.Count)"
    Write-Host "Calibration : $($CalibrationFiles.Count)"
    Write-Host ""
    Write-Host "Next, install the Python environment and run:"
    Write-Host "  cd runtime\fusion_pc"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\demo_preflight.ps1 -Mode full4ch"
}
finally {
    Pop-Location
    if (-not $KeepClone -and (Test-Path $Destination)) {
        Remove-Item $Destination -Recurse -Force
        Write-Host "Removed verification clone: $Destination"
    }
}
