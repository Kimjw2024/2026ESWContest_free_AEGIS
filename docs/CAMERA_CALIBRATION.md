# Camera Calibration & Multi-Baseline 3D

## 1. Calibration Scope

AEGIS는 4개 카메라 각각의 내부 파라미터와 가능한 6개 stereo pair를 모두 보정한다.

```text
Single:  camera 0 / 1 / 2 / 3
Stereo:  01 / 02 / 03 / 12 / 13 / 23
```

- Checkerboard square: **25.0 mm**
- Calibration resolution: **1280×720**
- Runtime stream: **640×360**
- Runtime detection center는 calibration 좌표계로 재스케일한 뒤 triangulation한다.

<p align="center"><img src="../assets/hardware/calibration_setup.png" alt="checkerboard and four-camera calibration" width="900"></p>

## 2. Single-Camera Calibration

각 카메라에서 다음 파라미터를 추정한다.

- camera matrix `K`
- distortion coefficients `D`
- calibrated `image_size`
- RMS reprojection error
- pose-coverage / quality metadata

Repository artifacts:

```text
calibration/intrinsics/intrinsics_0.npz
calibration/intrinsics/intrinsics_1.npz
calibration/intrinsics/intrinsics_2.npz
calibration/intrinsics/intrinsics_3.npz
```

## 3. Stereo Calibration

각 pair는 다음을 포함한다.

- `K1, D1, K2, D2`
- relative rotation `R`
- translation `T`
- rectification `R1, R2`
- projection `P1, P2`
- disparity-to-depth matrix `Q`
- actual/command baseline metadata
- RMS and quality flags

Repository artifacts:

```text
calibration/stereo_pairs/calib_01.npz
calibration/stereo_pairs/calib_02.npz
calibration/stereo_pairs/calib_03.npz
calibration/stereo_pairs/calib_12.npz
calibration/stereo_pairs/calib_13.npz
calibration/stereo_pairs/calib_23.npz
```

## 4. Quality Gates

Current Runtime validation config:

| Gate | Value |
|---|---:|
| Minimum single images | 15 |
| Minimum stereo pairs | 15 |
| Maximum selected single views | 60 |
| Maximum selected stereo views | 50 |
| Single RMS good threshold | 0.50 px |
| Stereo RMS good threshold | 0.75 px |
| Baseline error good threshold | 7% |

Selection does not simply keep a fixed number of images. It preserves board position, scale, roll and distance diversity while removing near-duplicate, weak or outlier views.

## 5. Required vs Loadable Pairs

```text
Required connected chain: 01 / 12 / 23
Loadable pairs:           01 / 02 / 03 / 12 / 13 / 23
```

- `01/12/23` connect all four cameras into one coordinate chain.
- `02/13/03` are additional medium/long-baseline observations.
- All valid pairs can be fused, but a missing optional pair does not disconnect the entire rig.

## 6. Runtime Triangulation Flow

```text
Detection center at 640×360
→ rescale to 1280×720 calibration coordinates
→ pair rectification
→ triangulation using P1/P2
→ pair validity / timestamp / geometry check
→ robust weighting
→ common Track3D coordinate
```

Longer baselines improve depth sensitivity, while short baselines preserve overlap and reduce close-range disparity failure. AEGIS therefore treats each pair as a reliability-weighted observation rather than selecting one fixed pair.

## 7. Quantitative Results

| Metric | Result |
|---|---:|
| Single-camera RMS | **0.154–0.181 px** |
| Six stereo-pair RMS | **0.217–0.289 px** |

Depth sensitivity simulation at `Z = 2.2 m`, `1 px` center perturbation:

| Baseline | Depth error P95 |
|---:|---:|
| 0.15 m | 95.3 mm |
| 0.30 m | 49.2 mm |
| 0.45 m | 33.1 mm |

The 0.45 m baseline reduces the simulated P95 sensitivity error by approximately **65.3%** relative to 0.15 m.

> This is a sensitivity simulation, not an absolute airport-field distance-accuracy claim.

## 8. Recalibration Conditions

Recalibrate after camera relocation, holder replacement, focus change, significant impact, or baseline change. Camera calibration is the reference for both triangulation and the downstream turret-coordinate transform.
