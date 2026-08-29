# Turret Kinematics, Calibration & Safety

## 1. Why Calibration Is Required

A pinhole 3D coordinate alone does not produce an accurate servo command. Real hardware contains:

- turret base position error
- pan/tilt zero offset
- pivot height and tilt-arm geometry
- laser optical offset
- base tilt and side lean
- camera depth-scale bias
- servo quantization and backlash

AEGIS separates the nominal kinematic model from the measured override so that the same control code can be recalibrated after mechanical changes.

## 2. Inverse Kinematics

For a target expressed relative to the turret:

```text
pan = 90° − atan2(x_rel − dx_laser, z_rel − dz_laser) + pan_trim

dist_h  = horizontal distance to target
dist_PT = distance from pan/tilt pivot to target

tilt = 90°
       + atan2(y_rel, dist_h)
       − asin(l_arm / dist_PT)
       + tilt_trim
```

`axis_tilt` and `axis_lean` add pan-dependent correction to absorb front/back and left/right installation tilt.

## 3. Mechanical Parameters

| Parameter | Meaning |
|---|---|
| `pos_global` | turret pivot position in the global camera coordinate frame |
| `h_pivot` | pivot height |
| `l_arm` | tilt mechanism arm length |
| `dx_laser`, `dz_laser` | laser optical offset from mechanical axis |
| `pan_trim`, `tilt_trim` | zero-angle trim |
| `axis_tilt`, `axis_lean` | installation tilt/lean correction |
| `z_scale` | camera-depth scale correction used by prediction/control |

## 4. Calibration Data

`runtime/fusion_pc/calib_data.json` contains:

- **PT1: 22 measured target points**
- **PT2: 22 measured target points**
- each sample: `[[X, Y, Z], measured_pan, measured_tilt]`

The samples span multiple horizontal, vertical and depth positions so that trim-only fitting does not hide geometry error.

## 5. Interactive Calibration Procedure

`runtime/fusion_pc/calibration_turret.py` follows this sequence:

```text
Fusion provides stable 3D target
→ nominal IK computes initial PT1 angle
→ operator fine-adjusts laser to target and confirms
→ nominal IK computes initial PT2 angle
→ operator fine-adjusts laser to target and confirms
→ repeat across near/far and left/center/right target positions
→ optimize geometry + trim + axis correction + z_scale
→ save turret_calibration_overrides.json
→ verify both lasers on the recorded 3D targets
```

The tool recommends a grid of left/center/right and low/mid/high positions across more than one distance. Fusion must remain active because the camera system supplies each calibration target's 3D coordinate.

## 6. Current Runtime Override

`runtime/fusion_pc/turret_calibration_overrides.json` is the authoritative release configuration.

```text
prediction.z_scale = 0.7611
```

| Parameter | PT1 | PT2 |
|---|---:|---:|
| `pos_global` | `[0.0758, 0, -0.0869]` m | `[0.3755, 0, -0.0918]` m |
| `dx_laser` | 0.000 m | 0.000 m |
| `dz_laser` | 0.012 m | 0.012 m |
| `h_pivot` | 0.1280 m | 0.1280 m |
| `l_arm` | 0.0410 m | 0.0410 m |
| `pan_trim` | +4.0° | +3.0° |
| `tilt_trim` | −5.8° | −1.6° |
| `axis_tilt` | −0.81° | +0.21° |
| `axis_lean` | +0.40° | −5.80° |

### Mechanical Reference Version Note

The first competition deck lists an initial `dx_laser = 0.002 m` reference. The current archived Runtime override uses `0.000 m` after the final remeasurement. For reproduction, the current JSON is authoritative; the deck value is retained as development-history evidence.

## 7. Reported Calibration Effect

The development report records PT1 mean-angle-error reduction after trim/axis optimization:

- Pan MAE: **35.0% reduction**
- Tilt MAE: **37.7% reduction**

These percentages refer to the report's calibration comparison and should not be interpreted as end-to-end 3D localization accuracy.

## 8. Runtime Control & Safety

Current control configuration includes:

| Item | Value |
|---|---:|
| Critical distance | 1.5 m |
| Maximum laser distance | 2.2 m |
| Track hold / drop | 0.30 s / 1.00 s |
| Servo minimum send interval | 0.015 s |
| Pan safe range | 20°–160° |
| Tilt safe range | 45°–150° |
| Arduino baud | 115200 |

The PC server applies geometry, filtering, limits and command freshness before serial transmission. The UNO firmware uses a latest-command parser and watchdog. Laser output remains subject to venue safety rules and operator supervision.

## 9. Predictive-Lead Version Note

The competition-deck verification snapshot records `system_delay = 0.14 s` and `max_lead_dist = 0.22 m`. The current public release keeps the architecture but uses a conservative demonstration preset with `max_lead_dist = 0.0` and `command_lead_ratio = 0.0`, effectively disabling forward lead until a new field timing calibration is completed.

This distinction prevents an older experiment parameter from being presented as the current release preset.
