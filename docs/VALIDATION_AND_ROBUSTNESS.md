# Validation, Failure Analysis & Robustness

## 1. Validation Strategy

AEGIS does not treat every error as an AI problem. Failures are isolated by layer:

```text
Transport
→ Camera Geometry
→ Triangulation / Fusion
→ Tracking
→ Turret Kinematics
→ AI Classification
→ Decision / Response
```

This makes it possible to verify a subsystem with HSV or synthetic targets before introducing a learned detector.

## 2. Development Challenges

| Issue | Root Cause | Engineering Response | Verified Effect |
|---|---|---|---|
| Frame delay | async queue accumulation, sender clock gap | wired Ethernet, low HWM, latest-first, corrected timestamp, sync window | stale frames and invalid pair combinations are rejected earlier |
| 3D coordinate jump | calibration quality and pair variance | high-resolution single/stereo calibration, pair quality gate, runtime rescale | consistent triangulation input and reduced depth spikes |
| Turret aiming error | installation tilt, laser offset, zero trim | measured target points, pan/tilt trim, axis_tilt/lean, geometry optimization | report records PT1 Pan/Tilt MAE reduction |
| Detection instability | small bbox, background, label contamination | HSV baseline, hard negative, duplicate/blur/non-bird/wrong-label audit | data-quality criteria established before training |

## 3. Communication Robustness

Calibration profile:

```text
1280×720 · 20 FPS · JPEG Q76 · sensor mode 2304:1296
```

Runtime profile:

```text
640×360 · 30 FPS · JPEG Q70
```

Transport policy:

- wired Ethernet
- ZMQ/JPEG and current RAW-TCP bridge path
- sender SNDHWM 1 / receiver RCVHWM 2
- latest-state priority rather than queued-history completeness
- pair timestamp window and soft-weight region

## 4. 3D Robustness

- six calibrated stereo combinations
- required connected pair chain plus optional redundant pairs
- rectified-y and timestamp validity checks
- baseline-aware weighting
- pair reliability weighting
- geometric and temporal outlier handling
- Track3D smoothing after multi-pair fusion, not before pair validation

## 5. Tracking Continuity

Current configuration:

| Parameter | Value |
|---|---:|
| Velocity LPF beta | 0.70 |
| Track hold | 0.30 s |
| Track drop | 1.00 s |
| Aim hold | 0.20 s |
| Max target speed gate | 3.5 m/s |
| Position gate margin | 0.12 m |

Short detection loss does not immediately erase the track. During hold, threat is decayed and actuation safety remains active.

## 6. Predictive Lead Snapshot vs Release Preset

The competition deck's verification snapshot records:

```text
system_delay 0.14 s
max_lead_dist 0.22 m
```

The current public Runtime keeps `system_delay = 0.14 s` but sets:

```text
max_lead_dist = 0.0
command_lead_ratio = 0.0
```

This is a conservative exhibition preset that disables forward lead until a new end-to-end field-delay calibration is completed. The architecture and code path remain available.

## 7. Turret & Output Safety

| Parameter | Value |
|---|---:|
| Critical distance | 1.5 m |
| Max laser distance | 2.2 m |
| Servo min send interval | 0.020 s |
| Pan range | 20°–160° |
| Tilt range | 45°–150° |
| Arduino watchdog / keepalive design | latest-command + periodic resend |

Output is activated only after target validity, range and actuator limits are checked. Laser use remains operator-supervised.

## 8. AI Robustness

- classifier crop-size gate
- Top-1 confidence threshold
- Top1–Top2 margin threshold
- `UNKNOWN` fallback
- 5-of-7 temporal vote
- independent Track3D continuity
- background hard-negative dataset
- held-out metrics separated from live-field claims

## 9. Known Limits

- current data does not represent every airport, weather and lighting condition
- Y is a relative altitude signal, not absolute sea-level altitude
- the current risk weights are prototype rules, not certified biological risk tables
- camera/turret relocation requires recalibration
- RC-Car is an extension prototype, not autonomous dispatch
