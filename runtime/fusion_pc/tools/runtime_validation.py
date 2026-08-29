# -*- coding: utf-8 -*-
import argparse
import importlib.util
import os
import subprocess
import sys

import cv2
import numpy as np


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config_turret as cfg


REQUIRED_SINGLE_KEYS = {
    "K", "D", "image_size", "rms", "quality_passed",
    "pose_coverage_passed", "calibration_schema_version",
}
REQUIRED_STEREO_KEYS = {
    "K1", "D1", "K2", "D2", "R", "T", "R1", "R2", "P1", "P2", "Q",
    "image_size", "rms", "baseline_actual_m", "baseline_command_m",
    "quality_passed", "pose_coverage_passed", "calibration_schema_version",
}
ALL_PAIRS = ("01", "02", "03", "12", "13", "23")
CALIBRATION_QUALITY = getattr(cfg, "CALIBRATION_QUALITY", {})
RUNTIME_VALIDATION = getattr(cfg, "RUNTIME_VALIDATION", {})


def normalize_pair_text(pair):
    text = str(pair).replace("cam", "").replace("-", "").replace("_", "")
    if len(text) != 2 or not text.isdigit() or text[0] == text[1]:
        return None
    return "".join(sorted(text))


def normalize_pair_list(pairs, fallback):
    out = []
    for pair in pairs or []:
        norm = normalize_pair_text(pair)
        if norm is not None and norm not in out:
            out.append(norm)
    return tuple(out or fallback)


REQUIRED_PAIRS = normalize_pair_list(RUNTIME_VALIDATION.get("required_calib_pairs"), ("01", "12", "23"))
LOADABLE_PAIRS = list(normalize_pair_list(RUNTIME_VALIDATION.get("loadable_calib_pairs"), ALL_PAIRS))
for pair in REQUIRED_PAIRS:
    if pair not in LOADABLE_PAIRS:
        LOADABLE_PAIRS.append(pair)
LOADABLE_PAIRS = tuple(LOADABLE_PAIRS)


def status(ok, label, detail):
    prefix = "OK" if ok else "FAIL"
    print(f"[{prefix}] {label}: {detail}")
    return bool(ok)


def warn(label, detail):
    print(f"[WARN] {label}: {detail}")


def read_size(z):
    vals = np.asarray(z["image_size"]).reshape(-1)
    return int(vals[0]), int(vals[1])


def check_environment():
    ok = True
    expected_exe = os.path.normcase(os.path.abspath(sys.executable))
    ok &= status(sys.version_info[:2] == (3, 11), "python", sys.version.split()[0])
    required = ("cv2", "numpy", "zmq", "serial", "scipy", "ultralytics", "PySide6", "torch")
    for module_name in required:
        ok &= status(importlib.util.find_spec(module_name) is not None, f"module {module_name}", "installed")
    print(f"[INFO] executable: {expected_exe}")
    return ok


def check_config():
    ok = True
    calib_size = tuple(int(v) for v in cfg.CALIB_RESOLUTION)
    stream = getattr(cfg, "CAMERA_STREAM", {})
    stream_size = (int(stream.get("width", -1)), int(stream.get("height", -1)))
    ok &= status(calib_size == stream_size, "calibration stream", f"calib={calib_size[0]}x{calib_size[1]} camera_stream={stream_size[0]}x{stream_size[1]}")
    runtime_stream = getattr(cfg, "RUNTIME_STREAM", stream)
    runtime_size = (int(runtime_stream.get("width", -1)), int(runtime_stream.get("height", -1)))
    runtime_ok = runtime_size[0] > 0 and runtime_size[1] > 0 and runtime_size[0] * calib_size[1] == runtime_size[1] * calib_size[0]
    ok &= status(runtime_ok, "runtime stream", f"runtime={runtime_size[0]}x{runtime_size[1]} fps={runtime_stream.get('fps', '?')} jpeg={runtime_stream.get('jpeg_quality', '?')}")
    ok &= status(float(cfg.FUSION_PARAMS.get("mount_angle_deg", 0.0)) == 20.0, "mount angle", f"{cfg.FUSION_PARAMS.get('mount_angle_deg')} deg")
    z_scale = float(cfg.PREDICTION.get("z_scale", 1.0))
    ok &= status(0.65 <= z_scale <= 1.10, "z scale", f"{z_scale:.3f} calibrated")
    command_lead = float(cfg.PREDICTION.get("command_lead_ratio", 1.0))
    ok &= status(0.0 <= command_lead <= 1.0, "command lead ratio", f"{command_lead:.2f}")
    fusion = getattr(cfg, "FUSION_PARAMS", {})
    baseline_power = float(fusion.get("baseline_weight_power", 2.0))
    baseline_ref = float(fusion.get("baseline_weight_reference_m", getattr(cfg, "CAMERA_GEOMETRY", {}).get("camera_spacing_m", 0.15)))
    ok &= status(1.0 <= baseline_power <= 3.0, "baseline weight power", f"{baseline_power:.2f}")
    ok &= status(baseline_ref > 0.0, "baseline weight reference", f"{baseline_ref:.3f}m")
    sync_window = float(getattr(cfg, "SYNC", {}).get("pair_sync_window", 0.0))
    sync_soft = float(getattr(cfg, "SYNC", {}).get("pair_sync_soft_window", sync_window))
    sync_floor = float(getattr(cfg, "SYNC", {}).get("pair_sync_weight_floor", 0.2))
    sender_pair_max_dt = float(getattr(cfg, "SYNC", {}).get("sender_pair_max_dt", sync_window))
    sender_offset_alpha = float(getattr(cfg, "SYNC", {}).get("sender_offset_alpha", 0.1))
    sender_offset_max_step = float(getattr(cfg, "SYNC", {}).get("sender_offset_max_step", 0.2))
    ok &= status(0.04 <= sync_window <= 0.10, "pair sync window", f"{sync_window:.3f}s")
    ok &= status(sync_window <= sync_soft <= 0.14, "pair sync soft window", f"{sync_soft:.3f}s")
    ok &= status(0.02 <= sync_floor <= 0.50, "pair sync weight floor", f"{sync_floor:.2f}")
    ok &= status(0.01 <= sender_pair_max_dt <= 0.14, "sender pair warn dt", f"{sender_pair_max_dt:.3f}s")
    ok &= status(0.01 <= sender_offset_alpha <= 0.5, "sender offset alpha", f"{sender_offset_alpha:.2f}")
    ok &= status(0.05 <= sender_offset_max_step <= 0.5, "sender offset max step", f"{sender_offset_max_step:.2f}s")
    ok &= status(set(REQUIRED_PAIRS).issubset(set(LOADABLE_PAIRS)), "calib pair policy", f"required={','.join(REQUIRED_PAIRS)} loadable={','.join(LOADABLE_PAIRS)}")
    det = getattr(cfg, "DETECTION", {})
    task = str(det.get("yolo_task", "auto")).strip().lower()
    ok &= status(task in ("auto", "detect", "segment", "pose", "obb"), "yolo task", task or "auto")
    center_mode = str(det.get("yolo_center_mode", "auto"))
    center_alpha = float(det.get("yolo_center_smooth_alpha", 1.0))
    ok &= status(center_mode in ("auto", "box", "box_anchor", "anchor", "stable_box", "mask", "seg", "segment", "keypoint", "pose"), "yolo center mode", center_mode)
    ok &= status(0.05 <= center_alpha <= 1.0, "yolo center smoothing", f"{center_alpha:.2f}")
    hsv_full = bool(det.get("hsv_full_resolution", True))
    hsv_area = float(det.get("hsv_min_area", 0.0))
    hsv_circ = float(det.get("hsv_min_circularity", 0.0))
    ok &= status(True, "hsv full resolution", "enabled" if hsv_full else "disabled, low-latency half-resolution decode")
    ok &= status(hsv_area >= 0.0, "hsv min area", f"{hsv_area:.1f}px")
    ok &= status(0.0 <= hsv_circ <= 1.0, "hsv circularity gate", f"{hsv_circ:.2f}")
    servo = getattr(cfg, "SERVO_SMOOTH", {})
    min_send = float(servo.get("min_send_interval", 0.0))
    poll_ms = int(servo.get("poll_timeout_ms", 999))
    clear_latest = bool(servo.get("clear_output_before_write", False))
    ok &= status(0.015 <= min_send <= 0.040, "turret min send", f"{min_send:.3f}s")
    ok &= status(0 <= poll_ms <= 5, "turret poll timeout", f"{poll_ms}ms")
    ok &= status(clear_latest, "serial latest clear", "enabled")
    return ok


def check_model_selection():
    det = getattr(cfg, "DETECTION", {})
    model_dir = os.path.join(PROJECT_ROOT, str(det.get("yolo_model_dir", "models")))
    priority = (
        "best.engine", "best.pt", "custom.engine", "custom.pt",
        "model.engine", "model.pt", "yolo_custom.engine", "yolo_custom.pt",
    )
    priority += tuple(str(name) for name in det.get("yolo_pretrained_candidates", ()))
    found = None
    for name in priority:
        if os.path.isabs(name):
            path = name
        elif os.path.dirname(name):
            path = os.path.join(PROJECT_ROOT, name)
        else:
            path = os.path.join(model_dir, name)
        if os.path.exists(path):
            found = path
            break
    if found is None:
        fallback = os.path.join(PROJECT_ROOT, str(det.get("yolo_fallback_model_path", det.get("yolo_model_path", "models/yolo26n.engine"))))
        found = fallback if os.path.exists(fallback) else None
    ok = status(found is not None, "yolo model", found if found else "no .pt/.engine model found")
    if found and found.lower().endswith(".engine"):
        ok &= status(importlib.util.find_spec("tensorrt") is not None, "tensorrt", "installed for .engine inference")
    return ok


def check_calibration(allow_missing):
    data_dir = getattr(cfg, "DATA_DIR", os.path.join(PROJECT_ROOT, "data"))
    expected_size = tuple(int(v) for v in cfg.CALIB_RESOLUTION)
    single_rms_good = float(CALIBRATION_QUALITY.get("single_rms_good", 0.50))
    stereo_rms_good = float(CALIBRATION_QUALITY.get("stereo_rms_good", 0.75))
    ok = True
    missing_required = []

    for cam_id in range(4):
        path = os.path.join(data_dir, f"intrinsics_{cam_id}.npz")
        if not os.path.exists(path):
            missing_required.append(path)
            continue
        with np.load(path, allow_pickle=False) as z:
            keys_ok = REQUIRED_SINGLE_KEYS <= set(z.files)
            size_ok = "image_size" in z.files and read_size(z) == expected_size
            quality_ok = bool(np.asarray(z["quality_passed"]).reshape(-1)[0]) if "quality_passed" in z.files else False
            pose_ok = bool(np.asarray(z["pose_coverage_passed"]).reshape(-1)[0]) if "pose_coverage_passed" in z.files else False
            rms = float(np.asarray(z["rms"]).reshape(-1)[0]) if "rms" in z.files else float("nan")
        ok &= status(keys_ok and size_ok and quality_ok and pose_ok and rms <= single_rms_good, f"intrinsics_{cam_id}", f"rms={rms:.4f} size_ok={size_ok}")

    for pair in LOADABLE_PAIRS:
        path = os.path.join(data_dir, f"calib_{pair}.npz")
        if not os.path.exists(path):
            if pair in REQUIRED_PAIRS:
                missing_required.append(path)
            else:
                warn("optional calibration missing", path)
            continue
        with np.load(path, allow_pickle=False) as z:
            keys_ok = REQUIRED_STEREO_KEYS <= set(z.files)
            size_ok = "image_size" in z.files and read_size(z) == expected_size
            quality_ok = bool(np.asarray(z["quality_passed"]).reshape(-1)[0]) if "quality_passed" in z.files else False
            pose_ok = bool(np.asarray(z["pose_coverage_passed"]).reshape(-1)[0]) if "pose_coverage_passed" in z.files else False
            rms = float(np.asarray(z["rms"]).reshape(-1)[0]) if "rms" in z.files else float("nan")
            baseline = float(np.asarray(z["baseline_actual_m"]).reshape(-1)[0]) if "baseline_actual_m" in z.files else float("nan")
        pair_ok = keys_ok and size_ok and quality_ok and pose_ok and rms <= stereo_rms_good and baseline > 0
        if pair in REQUIRED_PAIRS:
            ok &= status(pair_ok, f"calib_{pair}", f"rms={rms:.4f} baseline={baseline:.4f}m")
        elif pair_ok:
            status(True, f"optional calib_{pair}", f"rms={rms:.4f} baseline={baseline:.4f}m")
        else:
            warn(f"optional calib_{pair}", f"invalid or low quality: rms={rms:.4f} baseline={baseline:.4f}m")

    if missing_required:
        for path in missing_required:
            warn("calibration missing", path)
        return bool(allow_missing)
    return ok


def hsv_synthetic_check():
    ok = True
    colors = getattr(cfg, "HSV_COLORS", {})
    for idx, (name, limits) in enumerate(colors.items(), 1):
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        color = (0, 255, 0) if idx == 1 else (255, 0, 0)
        cv2.circle(img, (640, 360), 22, color, -1)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower = np.asarray(limits["lower"], dtype=np.uint8)
        upper = np.asarray(limits["upper"], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower, upper)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            ok &= status(False, f"hsv {name}", "no contour")
            continue
        m = cv2.moments(max(cnts, key=cv2.contourArea))
        cx = m["m10"] / m["m00"] if m["m00"] else float("nan")
        cy = m["m01"] / m["m00"] if m["m00"] else float("nan")
        ok &= status(abs(cx - 640) < 1 and abs(cy - 360) < 1, f"hsv {name}", f"center=({cx:.1f},{cy:.1f})")
    return ok


def triangulation_noise_check():
    width, height = tuple(int(v) for v in cfg.CALIB_RESOLUTION)
    spacing = float(getattr(cfg, "CAMERA_GEOMETRY", {}).get("camera_spacing_m", 0.15))
    focal_px = 900.0
    rng = np.random.default_rng(7)
    ok = True

    print("[INFO] triangulation sensitivity: ideal pinhole, 1px center noise")
    for baseline in (spacing, spacing * 2, spacing * 3):
        z_errs = []
        z = 2.2
        x = np.array([0.02, 0.03, z], dtype=np.float64)
        p1 = np.array([focal_px * x[0] / x[2] + width / 2, focal_px * x[1] / x[2] + height / 2], dtype=np.float32)
        p2 = np.array([focal_px * (x[0] - baseline) / x[2] + width / 2, p1[1]], dtype=np.float32)
        k = np.array([[focal_px, 0, width / 2], [0, focal_px, height / 2], [0, 0, 1]], dtype=np.float64)
        d = np.zeros(5)
        pmat1 = np.array([[focal_px, 0, width / 2, 0], [0, focal_px, height / 2, 0], [0, 0, 1, 0]], dtype=np.float64)
        pmat2 = np.array([[focal_px, 0, width / 2, -focal_px * baseline], [0, focal_px, height / 2, 0], [0, 0, 1, 0]], dtype=np.float64)
        for _ in range(600):
            n1 = p1 + rng.normal(0, 1.0, 2).astype(np.float32)
            n2 = p2 + rng.normal(0, 1.0, 2).astype(np.float32)
            r1 = cv2.undistortPoints(np.array([[n1]], dtype=np.float32), k, d, R=np.eye(3), P=pmat1)
            r2 = cv2.undistortPoints(np.array([[n2]], dtype=np.float32), k, d, R=np.eye(3), P=pmat2)
            q = cv2.triangulatePoints(pmat1, pmat2, r1, r2)
            xyz = (q[:3] / q[3]).reshape(3)
            z_errs.append(abs(float(xyz[2]) - z))
        p95_mm = float(np.percentile(z_errs, 95) * 1000.0)
        ok &= status(p95_mm < 120.0, f"triangulation baseline {baseline:.2f}m", f"z p95={p95_mm:.1f}mm at 2.2m")
    return ok


def turret_math_check():
    spec = importlib.util.spec_from_file_location("turret_server", os.path.join(PROJECT_ROOT, "6_turret_server.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ok = True
    samples = (
        np.array([0.20, 0.15, 1.0]),
        np.array([0.20, 0.15, 1.7]),
        np.array([0.45, 0.10, 2.1]),
    )
    for target in samples:
        for name, pt in (("pt1", module.cfg.PT1_CONFIG), ("pt2", module.cfg.PT2_CONFIG)):
            pan, tilt, _ = module.calculate_precise_angles(target, pt)
            finite = np.all(np.isfinite([pan, tilt]))
            in_range = (
                module.cfg.SAFE_LIMITS["pan_min"] <= pan <= module.cfg.SAFE_LIMITS["pan_max"]
                and module.cfg.SAFE_LIMITS["tilt_min"] <= tilt <= module.cfg.SAFE_LIMITS["tilt_max"]
            )
            ok &= status(finite and in_range, f"turret {name}", f"target={target.tolist()} pan={pan:.2f} tilt={tilt:.2f}")
    return ok


def arduino_firmware_source_check():
    path = os.path.abspath(os.path.join(PROJECT_ROOT, "..", "..", "firmware", "arduino_uno", "turret_uno.ino"))
    if not os.path.exists(path):
        return status(False, "arduino firmware source", "missing")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    required = ("latest_buffer", "Serial.read()", "applyCommand", "strncpy", "COMMAND_TIMEOUT_MS")
    missing = [token for token in required if token not in text]
    return status(not missing, "arduino firmware source", "latest-command parser + watchdog" if not missing else f"missing {missing}")


def run_yolo_benchmark(args):
    cmd = [
        sys.executable,
        os.path.join(PROJECT_ROOT, "src", "5_benchmark_yolo.py"),
        "--loops", str(args.yolo_loops),
        "--batch",
        "--include-jpeg-decode",
        "--target-hz", str(args.target_hz),
    ]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True)
    return result.returncode == 0


def parse_args():
    parser = argparse.ArgumentParser(description="Read-only runtime validation for fusion/turret pipeline.")
    parser.add_argument("--allow-missing-calibration", action="store_true")
    parser.add_argument("--benchmark-yolo", action="store_true")
    parser.add_argument("--yolo-loops", type=int, default=10)
    parser.add_argument("--target-hz", type=float, default=15.0)
    return parser.parse_args()


def main():
    args = parse_args()
    ok = True
    ok &= check_environment()
    ok &= check_config()
    ok &= check_model_selection()
    ok &= check_calibration(args.allow_missing_calibration)
    ok &= hsv_synthetic_check()
    ok &= triangulation_noise_check()
    ok &= turret_math_check()
    ok &= arduino_firmware_source_check()
    if args.benchmark_yolo:
        ok &= run_yolo_benchmark(args)
    if not ok:
        raise SystemExit(1)
    print("[OK] runtime validation complete")


if __name__ == "__main__":
    main()
