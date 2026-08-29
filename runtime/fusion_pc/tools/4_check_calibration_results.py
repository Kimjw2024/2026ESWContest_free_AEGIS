# -*- coding: utf-8 -*-
import argparse
import os
import sys

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import config_turret as cfg
except ImportError:
    cfg = None


DEFAULT_RESOLUTION = tuple(getattr(cfg, "CALIB_RESOLUTION", (1280, 720))) if cfg is not None else (1280, 720)
DATA_DIR = getattr(cfg, "DATA_DIR", os.path.join(PROJECT_ROOT, "data")) if cfg is not None else os.path.join(PROJECT_ROOT, "data")
CAMERA_GEOMETRY = getattr(cfg, "CAMERA_GEOMETRY", {}) if cfg is not None else {}
CALIBRATION_QUALITY = getattr(cfg, "CALIBRATION_QUALITY", {}) if cfg is not None else {}
RUNTIME_VALIDATION = getattr(cfg, "RUNTIME_VALIDATION", {}) if cfg is not None else {}


SINGLE_REQUIRED = {
    "K", "D", "image_size", "rms", "checkerboard", "square_size_m",
    "quality_passed", "pose_coverage_passed", "calibration_schema_version",
}
STEREO_REQUIRED = {
    "K1", "D1", "K2", "D2", "R", "T", "R1", "R2", "P1", "P2", "Q",
    "image_size", "rms", "baseline", "baseline_command_m", "baseline_actual_m",
    "quality_passed", "pose_coverage_passed", "calibration_schema_version",
}
CAMERAS = ("0", "1", "2", "3")
ALL_PAIRS = ("01", "02", "03", "12", "13", "23")


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


def expected_baseline_for_pair(pair, fallback_spacing_m):
    norm = normalize_pair_text(pair)
    if norm is None:
        return None
    direct = CAMERA_GEOMETRY.get("pair_baselines_m", {})
    if norm in direct:
        return float(direct[norm])

    adjacent = CAMERA_GEOMETRY.get("adjacent_baselines_m", {})
    left_i, right_i = int(norm[0]), int(norm[1])
    total = 0.0
    for idx in range(left_i, right_i):
        edge_key = f"{idx}{idx + 1}"
        if edge_key not in adjacent:
            return abs(right_i - left_i) * float(fallback_spacing_m)
        total += float(adjacent[edge_key])
    return total

def normalize_camera_list(cameras, fallback):
    out = []
    for cam in cameras or []:
        text = str(cam).strip().lower().replace("cam", "")
        if text not in CAMERAS:
            raise SystemExit(f"unsupported camera: {cam}. Use one of: {' '.join(CAMERAS)}")
        if text not in out:
            out.append(text)
    return tuple(out or fallback)


REQUIRED_PAIRS = normalize_pair_list(RUNTIME_VALIDATION.get("required_calib_pairs"), ("01", "12", "23"))
LOADABLE_PAIRS = list(normalize_pair_list(RUNTIME_VALIDATION.get("loadable_calib_pairs"), ALL_PAIRS))
for pair in REQUIRED_PAIRS:
    if pair not in LOADABLE_PAIRS:
        LOADABLE_PAIRS.append(pair)
LOADABLE_PAIRS = tuple(LOADABLE_PAIRS)


def read_size(z):
    vals = np.asarray(z["image_size"]).reshape(-1)
    return int(vals[0]), int(vals[1])


def check_single(cam_id, expected_size, args):
    path = os.path.join(DATA_DIR, f"intrinsics_{cam_id}.npz")
    issues = []
    if not os.path.exists(path):
        return False, [f"missing {path}"]

    with np.load(path, allow_pickle=False) as z:
        missing = sorted(SINGLE_REQUIRED - set(z.files))
        if missing:
            issues.append(f"missing keys: {', '.join(missing)}")
        if "image_size" in z.files:
            size = read_size(z)
            if size != expected_size:
                issues.append(f"image_size {size[0]}x{size[1]} != expected {expected_size[0]}x{expected_size[1]}")
        if "rms" in z.files:
            rms = float(np.asarray(z["rms"]).reshape(-1)[0])
            if rms > args.single_rms_good:
                issues.append(f"rms {rms:.4f}px > {args.single_rms_good:.4f}px")
        if "valid_image_count" in z.files:
            count = int(np.asarray(z["valid_image_count"]).reshape(-1)[0])
            if count < args.min_single_images:
                issues.append(f"valid_image_count {count} < {args.min_single_images}")
        if "quality_passed" in z.files and not bool(np.asarray(z["quality_passed"]).reshape(-1)[0]):
            issues.append("quality_passed is false")
        if "pose_coverage_passed" in z.files and not bool(np.asarray(z["pose_coverage_passed"]).reshape(-1)[0]):
            issues.append("pose_coverage_passed is false")

    return not issues, [f"intrinsics_{cam_id}.npz: {msg}" for msg in issues]


def check_stereo(pair, expected_size, args):
    path = os.path.join(DATA_DIR, f"calib_{pair}.npz")
    issues = []
    if not os.path.exists(path):
        return False, [f"missing {path}"]

    with np.load(path, allow_pickle=False) as z:
        missing = sorted(STEREO_REQUIRED - set(z.files))
        if missing:
            issues.append(f"missing keys: {', '.join(missing)}")
        if "image_size" in z.files:
            size = read_size(z)
            if size != expected_size:
                issues.append(f"image_size {size[0]}x{size[1]} != expected {expected_size[0]}x{expected_size[1]}")
        if "rms" in z.files:
            rms = float(np.asarray(z["rms"]).reshape(-1)[0])
            if rms > args.stereo_rms_good:
                issues.append(f"rms {rms:.4f}px > {args.stereo_rms_good:.4f}px")
        if "baseline" in z.files:
            baseline = float(np.asarray(z["baseline"]).reshape(-1)[0])
            expected = expected_baseline_for_pair(pair, args.camera_spacing_m)
            err_pct = abs(baseline - expected) / max(expected, 1e-9) * 100.0
            if err_pct > args.baseline_error_good_percent:
                issues.append(f"baseline {baseline:.4f}m expected {expected:.4f}m error {err_pct:.1f}%")
        if "valid_pair_count" in z.files:
            count = int(np.asarray(z["valid_pair_count"]).reshape(-1)[0])
            if count < args.min_stereo_pairs:
                issues.append(f"valid_pair_count {count} < {args.min_stereo_pairs}")
        if "quality_passed" in z.files and not bool(np.asarray(z["quality_passed"]).reshape(-1)[0]):
            issues.append("quality_passed is false")
        if "pose_coverage_passed" in z.files and not bool(np.asarray(z["pose_coverage_passed"]).reshape(-1)[0]):
            issues.append("pose_coverage_passed is false")

    return not issues, [f"calib_{pair}.npz: {msg}" for msg in issues]


def parse_args():
    parser = argparse.ArgumentParser(description="Validate calibration result files before running fusion.")
    parser.add_argument("--width", type=int, default=int(DEFAULT_RESOLUTION[0]))
    parser.add_argument("--height", type=int, default=int(DEFAULT_RESOLUTION[1]))
    parser.add_argument("--cameras", nargs="+", default=list(CAMERAS), help="Camera ids to validate, e.g. 0 1")
    parser.add_argument("--pairs", nargs="+", default=None, help="Stereo pairs to validate, e.g. 01")
    parser.add_argument("--skip-stereo", action="store_true", help="Validate only selected single-camera intrinsics.")
    parser.add_argument("--single-rms-good", type=float, default=float(CALIBRATION_QUALITY.get("single_rms_good", 0.50)))
    parser.add_argument("--stereo-rms-good", type=float, default=float(CALIBRATION_QUALITY.get("stereo_rms_good", 0.75)))
    parser.add_argument("--min-single-images", type=int, default=int(CALIBRATION_QUALITY.get("min_single_images", 15)))
    parser.add_argument("--min-stereo-pairs", type=int, default=int(CALIBRATION_QUALITY.get("min_stereo_pairs", 15)))
    parser.add_argument("--camera-spacing-m", type=float, default=float(CAMERA_GEOMETRY.get("camera_spacing_m", 0.15)))
    parser.add_argument("--baseline-error-good-percent", type=float, default=float(CALIBRATION_QUALITY.get("baseline_error_good_percent", 7.0)))
    return parser.parse_args()


def main():
    args = parse_args()
    expected_size = (args.width, args.height)
    cameras = normalize_camera_list(args.cameras, CAMERAS)
    camera_set = set(cameras)
    default_pairs = tuple(pair for pair in LOADABLE_PAIRS if pair[0] in camera_set and pair[1] in camera_set)
    pairs = normalize_pair_list(args.pairs, default_pairs)
    required_pairs = set(pairs) if args.pairs is not None else {pair for pair in REQUIRED_PAIRS if pair in pairs}

    all_ok = True
    all_issues = []
    warnings = []

    for cam_id in cameras:
        ok, issues = check_single(cam_id, expected_size, args)
        all_ok = ok and all_ok
        all_issues.extend(issues)

    if args.skip_stereo:
        pairs = ()
        required_pairs = set()

    for pair in pairs:
        pair_path = os.path.join(DATA_DIR, f"calib_{pair}.npz")
        if not os.path.exists(pair_path):
            msg = f"missing {pair_path}"
            if pair in required_pairs:
                all_ok = False
                all_issues.append(msg)
            else:
                warnings.append(f"optional {msg}")
            continue
        ok, issues = check_stereo(pair, expected_size, args)
        if pair in required_pairs:
            all_ok = ok and all_ok
            all_issues.extend(issues)
        elif not ok:
            warnings.extend(f"optional {issue}" for issue in issues)

    if all_ok:
        print(f">> OK: selected calibration files match {expected_size[0]}x{expected_size[1]}")
        print(f">> Cameras: {', '.join(cameras)}")
        print(f">> Required pairs: {', '.join(pair for pair in pairs if pair in required_pairs)}")
        print(f">> Checked pairs: {', '.join(pairs)}")
        if warnings:
            print(">> Optional calibration warnings:")
            for warning in warnings:
                print(f"   - {warning}")
        return

    print(">> Calibration check failed:")
    for issue in all_issues:
        print(f"   - {issue}")
    if warnings:
        print(">> Optional calibration warnings:")
        for warning in warnings:
            print(f"   - {warning}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()