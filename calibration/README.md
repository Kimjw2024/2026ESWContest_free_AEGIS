# AEGIS Calibration Artifacts

This directory contains the calibration artifacts used by the public competition Runtime.

## Intrinsics

```text
intrinsics/intrinsics_0.npz
intrinsics/intrinsics_1.npz
intrinsics/intrinsics_2.npz
intrinsics/intrinsics_3.npz
```

Each file stores camera matrix, distortion, image size, RMS and quality metadata.

## Stereo Pairs

```text
stereo_pairs/calib_01.npz
stereo_pairs/calib_02.npz
stereo_pairs/calib_03.npz
stereo_pairs/calib_12.npz
stereo_pairs/calib_13.npz
stereo_pairs/calib_23.npz
```

Each file stores relative pose, rectification/projection matrices, baseline and quality metadata.

## Detailed Documentation

- [Camera Calibration](../docs/CAMERA_CALIBRATION.md)
- [Turret Calibration](../docs/TURRET_CALIBRATION.md)
- [Metrics](../docs/METRICS.md)

Do not reuse these artifacts after moving cameras, changing holders, changing focus, or altering the baseline.
