# -*- coding: utf-8 -*-
import argparse
import datetime
import glob
import os
import re
import sys

import cv2
import numpy as np

import common
import calibration_utils as calib_meta


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import config_turret as cfg
except ImportError:
    cfg = None


DEFAULT_RESOLUTION = tuple(getattr(cfg, "CALIB_RESOLUTION", (1280, 720))) if cfg is not None else (1280, 720)
DATA_DIR = getattr(cfg, "DATA_DIR", os.path.join(PROJECT_ROOT, "data")) if cfg is not None else os.path.join(PROJECT_ROOT, "data")
CALIB_IMAGE_DIR = os.path.join(PROJECT_ROOT, "calibration_images")
CAMERA_GEOMETRY = getattr(cfg, "CAMERA_GEOMETRY", {}) if cfg is not None else {}
CALIBRATION_QUALITY = getattr(cfg, "CALIBRATION_QUALITY", {}) if cfg is not None else {}
DEFAULT_INTERACTIVE_SQUARE_SIZE_MM = 25.0


def image_paths(folder):
    paths = []
    for pattern in ("*.png", "*.jpg", "*.jpeg", "*.bmp"):
        paths.extend(glob.glob(os.path.join(folder, pattern)))
    return sorted(paths)


def index_key(path):
    name = os.path.splitext(os.path.basename(path))[0]
    match = re.search(r"(?:img|pair)_(\d+)", name)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)", name)
    if match:
        return int(match.group(1))
    return name


def pair_image_paths(left_dir, right_dir):
    left = {index_key(p): p for p in image_paths(left_dir)}
    right = {index_key(p): p for p in image_paths(right_dir)}
    keys = sorted(set(left) & set(right), key=lambda x: (isinstance(x, str), x))
    return [(left[k], right[k]) for k in keys]


def expected_baseline_for_pair(left, right, fallback_spacing_m):
    left_i, right_i = sorted((int(left), int(right)))
    pair_key = f"{left_i}{right_i}"
    direct = CAMERA_GEOMETRY.get("pair_baselines_m", {})
    if pair_key in direct:
        return float(direct[pair_key])

    adjacent = CAMERA_GEOMETRY.get("adjacent_baselines_m", {})
    total = 0.0
    for idx in range(left_i, right_i):
        edge_key = f"{idx}{idx + 1}"
        if edge_key not in adjacent:
            return abs(right_i - left_i) * float(fallback_spacing_m)
        total += float(adjacent[edge_key])
    return total

def config_pair_set(name):
    return {str(pair).strip().replace("cam", "") for pair in CALIBRATION_QUALITY.get(name, [])}


def is_distance_limited_pair(pair_key):
    return pair_key in config_pair_set("distance_limited_stereo_pairs")


def summary_count(summary, key):
    try:
        return int(summary.get(key, 0))
    except Exception:
        return 0


def pose_coverage_from_removed_indices(removed_indices, pose_left_records, pose_right_records):
    removed_set = {int(i) for i in np.asarray(removed_indices).reshape(-1)}
    pose_left_used = [p for i, p in enumerate(pose_left_records) if i not in removed_set]
    pose_right_used = [p for i, p in enumerate(pose_right_records) if i not in removed_set]
    pose_left_summary = calib_meta.summarize_pose_coverage(pose_left_used)
    pose_right_summary = calib_meta.summarize_pose_coverage(pose_right_used)
    pose_left_ok, pose_left_reasons = calib_meta.pose_coverage_pass(pose_left_summary)
    pose_right_ok, pose_right_reasons = calib_meta.pose_coverage_pass(pose_right_summary)
    pose_ok = pose_left_ok and pose_right_ok
    pose_reasons = [f"left:{r}" for r in pose_left_reasons] + [f"right:{r}" for r in pose_right_reasons]
    return pose_left_used, pose_right_used, pose_left_summary, pose_right_summary, pose_left_ok, pose_right_ok, pose_ok, pose_reasons


def distance_limited_pose_soft_pass(pair_key, left_summary, right_summary, pose_reasons, valid_count, rms, baseline_error_pct):
    if not is_distance_limited_pair(pair_key):
        return False, []

    allowed_pose_reasons = {"left:distance_buckets<2", "right:distance_buckets<2"}
    unexpected = [reason for reason in pose_reasons if reason not in allowed_pose_reasons]
    if unexpected:
        return False, ["unexpected pose failures: " + ", ".join(unexpected)]

    min_valid = int(CALIBRATION_QUALITY.get("distance_limited_min_valid_pairs", 35))
    min_grid = int(CALIBRATION_QUALITY.get("distance_limited_min_grid_cells", 8))
    min_roll = int(CALIBRATION_QUALITY.get("distance_limited_min_roll_buckets", 2))
    max_rms = float(CALIBRATION_QUALITY.get("distance_limited_max_rms", 0.45))
    max_baseline_err = float(CALIBRATION_QUALITY.get("distance_limited_max_baseline_error_percent", 1.0))

    failures = []
    if int(valid_count) < min_valid:
        failures.append(f"valid_pairs<{min_valid}")
    if float(rms) > max_rms:
        failures.append(f"rms>{max_rms:g}")
    if float(baseline_error_pct) > max_baseline_err:
        failures.append(f"baseline_error>{max_baseline_err:g}%")
    for side, summary in (("left", left_summary), ("right", right_summary)):
        if summary_count(summary, "grid_cell_count") < min_grid:
            failures.append(f"{side}:grid_cells<{min_grid}")
        if summary_count(summary, "roll_bucket_count") < min_roll:
            failures.append(f"{side}:roll_buckets<{min_roll}")

    if failures:
        return False, failures
    return True, [
        "distance bucket coverage is physically limited for this optional wide pair",
        f"valid_pairs>={min_valid}",
        f"rms<={max_rms:g}",
        f"baseline_error<={max_baseline_err:g}%",
        f"grid_cells>={min_grid}",
        f"roll_buckets>={min_roll}",
    ]

def managed_pair_image_paths(img_dir, include_flagged=False):
    left_dir = os.path.join(img_dir, "left")
    right_dir = os.path.join(img_dir, "right")
    pairs = []
    for record in calib_meta.stereo_records(img_dir, include_flagged=include_flagged):
        left_path = os.path.join(left_dir, record["left_file"])
        right_path = os.path.join(right_dir, record["right_file"])
        pairs.append((left_path, right_path, record))
    return pairs


def print_stereo_metadata_report(img_dir, physical_pairs, managed_pairs, include_flagged):
    if include_flagged:
        print(f">> Metadata filter: include-flagged enabled; {len(managed_pairs)} managed pairs will be considered")
        return
    try:
        data = calib_meta.load_metadata(img_dir)
    except Exception as exc:
        print(f">> [Warn] metadata read failed: {exc}")
        return

    physical_names = {
        (os.path.basename(left_path), os.path.basename(right_path))
        for left_path, right_path in physical_pairs
    }
    records = [
        r for r in data.get("records", [])
        if r.get("mode") == "stereo" and r.get("left_file") and r.get("right_file")
    ]
    rejected = []
    force_saved_usable = 0
    for record in records:
        key = (record.get("left_file"), record.get("right_file"))
        if key not in physical_names:
            continue
        reasons = calib_meta.record_rejection_reasons(record)
        if reasons:
            rejected.append((key, reasons))
        elif bool(record.get("force_saved", False)):
            force_saved_usable += 1

    print(f">> Metadata advisory: {len(physical_pairs)} physical pairs, {len(managed_pairs)} usable metadata records")
    if force_saved_usable:
        print(f">> Metadata note: {force_saved_usable} force_saved pairs have no hard quality flags.")
    if rejected:
        reason_counts = {}
        for _, reasons in rejected:
            key = ", ".join(reasons)
            reason_counts[key] = reason_counts.get(key, 0) + 1
        print(">> Metadata rejected stereo records:")
        for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0])):
            print(f"   - {count}: {reason}")
        print(">> First rejected stereo examples:")
        for (left_name, right_name), reasons in rejected[:8]:
            print(f"   - L={left_name} R={right_name}: {', '.join(reasons)}")

def make_objp(square_size_m):
    objp = np.zeros((common.CHECKERBOARD[0] * common.CHECKERBOARD[1], 3), np.float32)
    objp[:, :2] = (
        np.mgrid[0:common.CHECKERBOARD[0], 0:common.CHECKERBOARD[1]]
        .T.reshape(-1, 2)
        * float(square_size_m)
    )
    return objp

def resolve_square_size_m(args):
    if args.square_size_m is not None and args.square_size_mm is not None:
        raise SystemExit("Use only one of --square-size-m or --square-size-mm.")
    if args.square_size_mm is not None:
        return float(args.square_size_mm) / 1000.0
    if args.square_size_m is not None:
        return float(args.square_size_m)
    if getattr(args, "use_default_square_size", False):
        return float(common.SQUARE_SIZE)
    if sys.stdin.isatty():
        raw = input(f"Checkerboard square size in mm [{DEFAULT_INTERACTIVE_SQUARE_SIZE_MM:g}]: ").strip()
        if not raw:
            raw = str(DEFAULT_INTERACTIVE_SQUARE_SIZE_MM)
        try:
            square_mm = float(raw)
        except ValueError as exc:
            raise SystemExit("checkerboard square size must be a number in millimeters, e.g. 25.0") from exc
        if square_mm <= 0:
            raise SystemExit("checkerboard square size must be greater than 0 mm")
        print(f">> Checkerboard square size: {square_mm:.3f} mm")
        return square_mm / 1000.0
    raise SystemExit(
        "Missing checkerboard square size. Pass --square-size-mm with the measured printed square size "
        "or explicitly pass --use-default-square-size to use src/common.py."
    )

def atomic_savez_compressed(path, **payload):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "wb") as f:
        np.savez_compressed(f, **payload)
    os.replace(tmp_path, path)


def load_intrinsics(path, expected_size):
    if not os.path.exists(path):
        raise SystemExit(
            f"missing single calibration: {path}\n"
            "Run 1_single_calib.py for both cameras in this pair before stereo calibration."
        )
    with np.load(path, allow_pickle=False) as z:
        if "K" not in z.files or "D" not in z.files:
            raise SystemExit(f"{path} is missing K/D")
        if "image_size" not in z.files:
            raise SystemExit(f"{path} is missing image_size. Rebuild single calibration at {expected_size[0]}x{expected_size[1]}.")
        size = tuple(int(v) for v in np.asarray(z["image_size"]).reshape(-1)[:2])
        if size != tuple(expected_size):
            raise SystemExit(
                f"{path} resolution mismatch: got {size[0]}x{size[1]}, "
                f"expected {expected_size[0]}x{expected_size[1]}"
            )
        return z["K"].copy(), z["D"].copy()


def parse_pair(args):
    if args.pair:
        text = str(args.pair).replace("cam", "").replace("-", "").replace("_", "")
        if len(text) != 2 or not text.isdigit():
            raise SystemExit("--pair must look like 01, 12, cam23")
        left, right = text[0], text[1]
    else:
        left = args.left_camera or input("Left camera id (0-3): ").strip()
        right = args.right_camera or input("Right camera id (0-3): ").strip()
    if left not in {"0", "1", "2", "3"} or right not in {"0", "1", "2", "3"} or left == right:
        raise SystemExit("camera pair must use two different ids from 0,1,2,3")
    if int(left) > int(right):
        raise SystemExit("left camera id must be lower than right camera id, e.g. 01 not 10. Fusion loads sorted pair names.")
    return left, right



def parse_excluded_left_files(args):
    excluded = set()
    raw = getattr(args, "exclude_left_files", "") or ""
    for item in str(raw).split(","):
        item = item.strip()
        if item:
            excluded.add(os.path.basename(item))
    list_path = getattr(args, "exclude_left_file_list", None)
    if list_path:
        with open(list_path, "r", encoding="utf-8") as f:
            for line in f:
                item = line.strip()
                if item and not item.startswith("#"):
                    excluded.add(os.path.basename(item))
    return excluded


def stereo_calibrate_extended(obj_pts, img_l, img_r, K1, D1, K2, D2, size, flags, criteria):
    if hasattr(cv2, "stereoCalibrateExtended"):
        result = cv2.stereoCalibrateExtended(
            obj_pts, img_l, img_r,
            K1.copy(), D1.copy(), K2.copy(), D2.copy(),
            size,
            R=None, T=None, E=None, F=None,
            flags=flags,
            criteria=criteria,
        )
        per_view = np.asarray(result[-1], dtype=np.float64)
        if per_view.ndim == 0:
            per_view = per_view.reshape(1)
        return result[:9], per_view

    result = cv2.stereoCalibrate(
        obj_pts, img_l, img_r,
        K1.copy(), D1.copy(), K2.copy(), D2.copy(),
        size,
        flags=flags,
        criteria=criteria,
    )
    return result[:9], None


def per_view_scalar_errors(per_view_errors):
    if per_view_errors is None:
        return None
    arr = np.asarray(per_view_errors, dtype=np.float64)
    if arr.size == 0:
        return np.array([], dtype=np.float64)
    if arr.ndim == 1:
        return np.abs(arr)
    arr = arr.reshape(arr.shape[0], -1)
    return np.sqrt(np.sum(arr * arr, axis=1))


def _direction_dot(a, b):
    a = np.asarray(a, dtype=np.float64).reshape(2)
    b = np.asarray(b, dtype=np.float64).reshape(2)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 1e-9:
        return 1.0
    return float(np.dot(a, b) / denom)


def normalize_stereo_corner_order(left_corners, right_corners, pattern_size=None):
    """Keep left/right checkerboard indices tied to the same physical corners."""
    pattern = pattern_size or common.CHECKERBOARD
    cols, rows = int(pattern[0]), int(pattern[1])
    left = np.asarray(left_corners, dtype=np.float32).reshape(-1, 2)
    right = np.asarray(right_corners, dtype=np.float32).reshape(-1, 2)
    expected = cols * rows
    if left.shape[0] != expected or right.shape[0] != expected:
        return right_corners, None

    left_row = left[cols - 1] - left[0]
    right_row = right[cols - 1] - right[0]
    left_col = left[cols * (rows - 1)] - left[0]
    right_col = right[cols * (rows - 1)] - right[0]
    row_dot = _direction_dot(left_row, right_row)
    col_dot = _direction_dot(left_col, right_col)

    if row_dot < -0.5 and col_dot < -0.5:
        return right_corners[::-1].copy(), "rev_all"
    if row_dot < -0.5 or col_dot < -0.5:
        return right_corners, "suspect"
    return right_corners, None

def filter_outliers(obj_pts, img_l, img_r, per_view_errors, args):
    errors = per_view_scalar_errors(per_view_errors)
    if errors is None or len(errors) != len(obj_pts):
        return obj_pts, img_l, img_r, np.array([], dtype=np.int32), errors

    median = float(np.median(errors))
    mad = float(np.median(np.abs(errors - median)))
    std = float(np.std(errors))
    robust_scale = 1.4826 * mad if mad > 1e-9 else std
    if robust_scale > 1e-9:
        robust_limit = median + float(args.max_zscore) * robust_scale
    else:
        robust_limit = float(args.max_view_error)
    percentile_limit = float(np.percentile(errors, float(args.filter_percentile)))
    threshold = min(float(args.max_view_error), max(percentile_limit, robust_limit))

    kept_obj, kept_l, kept_r = [], [], []
    removed = []
    for idx, (obj, l, r, err) in enumerate(zip(obj_pts, img_l, img_r, errors)):
        if float(err) <= threshold:
            kept_obj.append(obj)
            kept_l.append(l)
            kept_r.append(r)
        else:
            removed.append(idx)
    if removed:
        print(f">> Stereo outlier filter: threshold={threshold:.6f}px kept={len(kept_obj)} removed={len(removed)}")
    return kept_obj, kept_l, kept_r, np.array(removed, dtype=np.int32), errors.astype(np.float32)


def quality_grade(rms, baseline, expected_baseline, args):
    baseline_error_pct = abs(float(baseline) - float(expected_baseline)) / max(float(expected_baseline), 1e-9) * 100.0
    reasons = []
    if rms > args.rms_good:
        reasons.append(f"rms>{args.rms_good:g}px")
    if baseline_error_pct > args.baseline_error_good_percent:
        reasons.append(f"baseline_error>{args.baseline_error_good_percent:g}%")

    if rms <= args.rms_excellent and baseline_error_pct <= args.baseline_error_excellent_percent:
        return "excellent", True, baseline_error_pct, reasons
    if not reasons:
        return "good", True, baseline_error_pct, reasons
    return "poor", False, baseline_error_pct, reasons


def parse_args():
    parser = argparse.ArgumentParser(description="Stereo calibration for 1280x720 runtime.")
    parser.add_argument("--pair", default=None, help="camera pair, e.g. 01, 12, cam23")
    parser.add_argument("--left-camera", default=None)
    parser.add_argument("--right-camera", default=None)
    parser.add_argument("--image-dir", default=None, help="override calibration_images/camXY")
    parser.add_argument("--output", default=None, help="override output npz path")
    parser.add_argument("--width", type=int, default=int(DEFAULT_RESOLUTION[0]))
    parser.add_argument("--height", type=int, default=int(DEFAULT_RESOLUTION[1]))
    parser.add_argument("--min-pairs", type=int, default=int(CALIBRATION_QUALITY.get("min_stereo_pairs", 15)))
    parser.add_argument("--max-selected-pairs", type=int, default=int(CALIBRATION_QUALITY.get("max_stereo_pairs", 50)),
                        help="Hard cap for diverse high-quality stereo pairs. Use 0 to keep all.")
    parser.add_argument("--disable-auto-selection", action="store_true",
                        help="Use every detected stereo pair instead of selecting a diverse subset.")
    parser.add_argument("--duplicate-pose-distance", type=float, default=float(CALIBRATION_QUALITY.get("stereo_duplicate_pose_distance", 0.16)),
                        help="Drop lower-quality stereo pairs only when both pose bucket and continuous pose are this close. Use 0 to disable duplicate pruning.")
    parser.add_argument("--camera-spacing-m", type=float, default=float(CAMERA_GEOMETRY.get("camera_spacing_m", 0.15)))
    parser.add_argument("--baseline-m", type=float, default=None)
    parser.add_argument("--max-view-error", type=float, default=0.75)
    parser.add_argument("--filter-percentile", type=float, default=80.0)
    parser.add_argument("--max-zscore", type=float, default=2.5)
    parser.add_argument("--rms-excellent", type=float, default=float(CALIBRATION_QUALITY.get("stereo_rms_excellent", 0.40)))
    parser.add_argument("--rms-good", type=float, default=float(CALIBRATION_QUALITY.get("stereo_rms_good", 0.75)))
    parser.add_argument("--baseline-error-excellent-percent", type=float, default=float(CALIBRATION_QUALITY.get("baseline_error_excellent_percent", 5.0)))
    parser.add_argument("--baseline-error-good-percent", type=float, default=float(CALIBRATION_QUALITY.get("baseline_error_good_percent", 7.0)))
    parser.add_argument("--square-size-m", type=float, default=None)
    parser.add_argument("--square-size-mm", type=float, default=None)
    parser.add_argument("--use-default-square-size", action="store_true",
                        help="Use src/common.py SQUARE_SIZE. Prefer --square-size-mm for real calibration.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-poor-quality", action="store_true")
    parser.add_argument("--allow-resolution-mismatch", action="store_true")
    parser.add_argument("--include-unmanaged-images", action="store_true",
                        help="Compatibility flag; stereo calibration scans all matched image pairs by default.")
    parser.add_argument("--use-metadata-filter", action="store_true",
                        help="Only scan stereo pairs accepted by capture metadata. Default scans every matched pair.")
    parser.add_argument("--include-flagged-pairs", action="store_true")
    parser.add_argument("--exclude-left-files", default="", help="Comma-separated left image basenames to exclude from this run.")
    parser.add_argument("--exclude-left-file-list", default=None, help="Text file with one left image basename to exclude per line.")
    parser.add_argument("--allow-incomplete-pose-coverage", action="store_true")
    parser.add_argument("--allow-auto-selection-for-distance-limited", action="store_true",
                        help="Do not force all-detected mode for configured distance-limited optional pairs.")
    return parser.parse_args()


def main():
    args = parse_args()
    left, right = parse_pair(args)
    pair_name = f"cam{left}{right}"
    pair_key = f"{left}{right}"
    distance_limited_pair = is_distance_limited_pair(pair_key)
    square_size_m = resolve_square_size_m(args)
    expected_size = (int(args.width), int(args.height))
    expected_baseline = (
        float(args.baseline_m)
        if args.baseline_m is not None
        else expected_baseline_for_pair(left, right, args.camera_spacing_m)
    )

    img_dir = args.image_dir or os.path.join(CALIB_IMAGE_DIR, pair_name)
    left_dir = os.path.join(img_dir, "left")
    right_dir = os.path.join(img_dir, "right")
    out_npz = args.output or os.path.join(DATA_DIR, f"calib_{pair_key}.npz")

    if os.path.exists(out_npz) and not args.overwrite:
        raise SystemExit(f"{out_npz} already exists. Use --overwrite to replace it.")

    K1_init, D1_init = load_intrinsics(os.path.join(DATA_DIR, f"intrinsics_{left}.npz"), expected_size)
    K2_init, D2_init = load_intrinsics(os.path.join(DATA_DIR, f"intrinsics_{right}.npz"), expected_size)

    physical_pairs = pair_image_paths(left_dir, right_dir)
    managed_pairs = managed_pair_image_paths(img_dir, include_flagged=args.include_flagged_pairs)
    if args.use_metadata_filter and not args.include_unmanaged_images:
        print_stereo_metadata_report(img_dir, physical_pairs, managed_pairs, args.include_flagged_pairs)
        pairs = managed_pairs
        input_source = "metadata-managed"
    else:
        print(f">> Image source: scanning all {len(physical_pairs)} matched left/right image pairs. Corner detection will reject unusable frames.")
        if managed_pairs:
            print_stereo_metadata_report(img_dir, physical_pairs, managed_pairs, args.include_flagged_pairs)
        pairs = [(l, r, None) for l, r in physical_pairs]
        input_source = "physical-files"
    excluded_left_files = parse_excluded_left_files(args)
    if excluded_left_files:
        before_exclude = len(pairs)
        pairs = [
            (l_path, r_path, record)
            for l_path, r_path, record in pairs
            if os.path.basename(l_path) not in excluded_left_files
        ]
        print(f">> Exclude list: skipped {before_exclude - len(pairs)} matched pairs by left filename")
    if not pairs:
        raise SystemExit(
            f"no matched left/right image pairs found under {img_dir}. "
            "Capture with 3_capture_tool first. If files exist, check left/right filenames have matching indexes."
        )

    objp = make_objp(square_size_m)
    obj_pts, img_l, img_r = [], [], []
    rejected_resolution = 0
    failed_checkerboard = 0
    pose_left_records = []
    pose_right_records = []
    detected_metadata_records = []
    detected_pair_names = []
    candidate_quality_scores = []
    corner_order_fixed = []
    corner_order_suspect = []
    shape = None

    print(f">> {pair_name}: scanning {len(pairs)} {input_source} pairs")
    print(f">> Required calibration resolution: {expected_size[0]}x{expected_size[1]}")

    for idx, (left_path, right_path, record) in enumerate(pairs, 1):
        il = common.imread_unicode(left_path, cv2.IMREAD_GRAYSCALE)
        ir = common.imread_unicode(right_path, cv2.IMREAD_GRAYSCALE)
        if il is None or ir is None:
            print(f"[{idx}/{len(pairs)}] READ_FAIL")
            continue

        l_size = il.shape[::-1]
        r_size = ir.shape[::-1]
        if (l_size != expected_size or r_size != expected_size) and not args.allow_resolution_mismatch:
            rejected_resolution += 1
            print(f"[{idx}/{len(pairs)}] SKIP_SIZE L={l_size} R={r_size}")
            continue
        if shape is None:
            shape = l_size
        elif l_size != shape or r_size != shape:
            rejected_resolution += 1
            print(f"[{idx}/{len(pairs)}] SKIP_MIXED_SIZE")
            continue

        rl, cl = common.find_checkerboard_corners(il)
        rr, cr = common.find_checkerboard_corners(ir)
        if not (rl and rr):
            failed_checkerboard += 1
            print(f"[{idx}/{len(pairs)}] FAIL_CB: {os.path.basename(left_path)}")
            continue

        cr, order_fix = normalize_stereo_corner_order(cl, cr)
        if order_fix == "rev_all":
            corner_order_fixed.append(os.path.basename(left_path))
        elif order_fix == "suspect":
            corner_order_suspect.append(os.path.basename(left_path))

        obj_pts.append(objp)
        img_l.append(cl)
        img_r.append(cr)
        pose_left_records.append(calib_meta.pose_from_corners(cl, il.shape))
        pose_right_records.append(calib_meta.pose_from_corners(cr, ir.shape))
        detected_metadata_records.append(record)
        detected_pair_names.append((os.path.basename(left_path), os.path.basename(right_path)))
        sharp_l = float(cv2.Laplacian(il, cv2.CV_64F).var())
        sharp_r = float(cv2.Laplacian(ir, cv2.CV_64F).var())
        candidate_quality_scores.append(float(np.log1p(max(min(sharp_l, sharp_r), 0.0))))
        print(f"[{idx}/{len(pairs)}] OK ({len(obj_pts)}): {os.path.basename(left_path)}")

    if corner_order_fixed:
        print(
            f">> Stereo corner order: reversed right-corner order in "
            f"{len(corner_order_fixed)} pairs to keep physical L/R corner correspondence"
        )
        for name in corner_order_fixed[:10]:
            print(f"   - corner order fixed: {name}")
        if len(corner_order_fixed) > 10:
            print(f"   - ... {len(corner_order_fixed) - 10} more")
    if corner_order_suspect:
        print(
            f">> [Warn] Stereo corner order has one-axis orientation mismatch in "
            f"{len(corner_order_suspect)} pairs; inspect these images if calibration remains poor"
        )
        for name in corner_order_suspect[:10]:
            print(f"   - suspect corner order: {name}")

    distance_bucket_policy = str(CALIBRATION_QUALITY.get("stereo_distance_bucket_mode", "relative")).strip().lower()
    relative_distance_left_summary = {}
    relative_distance_right_summary = {}
    if distance_bucket_policy == "relative":
        min_log_span = float(CALIBRATION_QUALITY.get("stereo_relative_distance_min_log_span", 0.35))
        far_quantile = float(CALIBRATION_QUALITY.get("stereo_relative_distance_far_quantile", 0.33))
        near_quantile = float(CALIBRATION_QUALITY.get("stereo_relative_distance_near_quantile", 0.67))
        pose_left_records, relative_distance_left_summary = calib_meta.assign_relative_distance_buckets(
            pose_left_records,
            min_log_area_span=min_log_span,
            far_quantile=far_quantile,
            near_quantile=near_quantile,
        )
        pose_right_records, relative_distance_right_summary = calib_meta.assign_relative_distance_buckets(
            pose_right_records,
            min_log_area_span=min_log_span,
            far_quantile=far_quantile,
            near_quantile=near_quantile,
        )
        left_span = float(relative_distance_left_summary.get("log_area_span", float("nan")))
        right_span = float(relative_distance_right_summary.get("log_area_span", float("nan")))
        print(
            ">> Distance buckets: relative board-size split "
            f"L policy={relative_distance_left_summary.get('policy', 'unknown')} "
            f"span={left_span:.3f} counts={relative_distance_left_summary.get('bucket_counts', {})}; "
            f"R policy={relative_distance_right_summary.get('policy', 'unknown')} "
            f"span={right_span:.3f} counts={relative_distance_right_summary.get('bucket_counts', {})}"
        )
    elif distance_bucket_policy in ("absolute", "fixed"):
        distance_bucket_policy = "absolute"
        print(">> Distance buckets: using fixed absolute board-size thresholds")
    else:
        print(f">> [Warn] Unknown stereo_distance_bucket_mode={distance_bucket_policy!r}; using relative")
        distance_bucket_policy = "relative"
        pose_left_records, relative_distance_left_summary = calib_meta.assign_relative_distance_buckets(pose_left_records)
        pose_right_records, relative_distance_right_summary = calib_meta.assign_relative_distance_buckets(pose_right_records)
    if distance_limited_pair and not args.disable_auto_selection and not args.allow_auto_selection_for_distance_limited:
        args.disable_auto_selection = True
        print(">> Distance-limited optional pair policy: using all detected pairs before outlier filtering")

    if len(obj_pts) < args.min_pairs:
        raise SystemExit(
            f"valid stereo pairs too few: {len(obj_pts)} < {args.min_pairs}\n"
            f"Capture more usable stereo pairs under: {img_dir}"
        )

    selected_indices = list(range(len(obj_pts)))
    detected_count_before_selection = len(obj_pts)
    if not args.disable_auto_selection:
        selection_limit = int(args.max_selected_pairs)
        token_sets = [
            calib_meta.pose_tokens(left_pose, "L") | calib_meta.pose_tokens(right_pose, "R")
            for left_pose, right_pose in zip(pose_left_records, pose_right_records)
        ]
        pair_pose_records = [
            {
                "center_x": (left_pose.get("center_x", 0.5) + right_pose.get("center_x", 0.5)) * 0.5,
                "center_y": (left_pose.get("center_y", 0.5) + right_pose.get("center_y", 0.5)) * 0.5,
                "area_ratio": min(left_pose.get("area_ratio", 0.0), right_pose.get("area_ratio", 0.0)),
                "roll_deg": (left_pose.get("roll_deg", 0.0) + right_pose.get("roll_deg", 0.0)) * 0.5,
            }
            for left_pose, right_pose in zip(pose_left_records, pose_right_records)
        ]
        selected_indices = calib_meta.select_diverse_indices(
            token_sets,
            candidate_quality_scores,
            max_count=selection_limit,
            min_count=int(args.min_pairs),
            pose_records=pair_pose_records,
            duplicate_distance=float(args.duplicate_pose_distance),
        )
        if len(selected_indices) < len(obj_pts):
            print(f">> Auto-select: using {len(selected_indices)}/{len(obj_pts)} diverse high-quality stereo pairs")
    if len(selected_indices) < args.min_pairs:
        raise SystemExit(f"selected stereo pairs too few: {len(selected_indices)} < {args.min_pairs}")
    if len(selected_indices) != len(obj_pts):
        obj_pts = [obj_pts[i] for i in selected_indices]
        img_l = [img_l[i] for i in selected_indices]
        img_r = [img_r[i] for i in selected_indices]
        pose_left_records = [pose_left_records[i] for i in selected_indices]
        pose_right_records = [pose_right_records[i] for i in selected_indices]
        detected_metadata_records = [detected_metadata_records[i] for i in selected_indices]
        detected_pair_names = [detected_pair_names[i] for i in selected_indices]
        candidate_quality_scores = [candidate_quality_scores[i] for i in selected_indices]

    candidate_pair_names_before_filter = list(detected_pair_names)
    candidate_quality_scores_before_filter = list(candidate_quality_scores)

    flags = cv2.CALIB_FIX_INTRINSIC
    criteria = (cv2.TERM_CRITERIA_MAX_ITER + cv2.TERM_CRITERIA_EPS, 100, 1e-6)

    print(">> first stereoCalibrate pass...")
    first_result, per_view = stereo_calibrate_extended(
        obj_pts, img_l, img_r,
        K1_init, D1_init, K2_init, D2_init,
        shape, flags, criteria,
    )
    print(f">> first RMS={float(first_result[0]):.6f}px")

    obj_f, img_l_f, img_r_f, removed_indices, per_view_errors = filter_outliers(
        obj_pts, img_l, img_r, per_view, args
    )
    if len(obj_f) < args.min_pairs:
        raise SystemExit(f"filtered stereo pairs too few: {len(obj_f)} < {args.min_pairs}")

    (
        pose_left_used,
        pose_right_used,
        pose_left_summary,
        pose_right_summary,
        pose_left_ok,
        pose_right_ok,
        pose_ok,
        pose_reasons,
    ) = pose_coverage_from_removed_indices(removed_indices, pose_left_records, pose_right_records)

    coverage_max_view_error = float(CALIBRATION_QUALITY.get("distance_limited_coverage_max_view_error", args.max_view_error))
    if distance_limited_pair and not pose_ok and coverage_max_view_error > float(args.max_view_error):
        relaxed_args = argparse.Namespace(**vars(args))
        relaxed_args.max_view_error = coverage_max_view_error
        obj_alt, img_l_alt, img_r_alt, removed_alt, per_view_errors_alt = filter_outliers(
            obj_pts, img_l, img_r, per_view, relaxed_args
        )
        if len(obj_alt) >= args.min_pairs:
            (
                pose_left_alt,
                pose_right_alt,
                pose_left_summary_alt,
                pose_right_summary_alt,
                pose_left_ok_alt,
                pose_right_ok_alt,
                pose_ok_alt,
                pose_reasons_alt,
            ) = pose_coverage_from_removed_indices(removed_alt, pose_left_records, pose_right_records)
            if pose_ok_alt:
                print(
                    ">> Distance-limited optional pair policy: relaxed outlier threshold "
                    f"from {float(args.max_view_error):.3f}px to {coverage_max_view_error:.3f}px "
                    "to preserve available distance coverage"
                )
                obj_f, img_l_f, img_r_f = obj_alt, img_l_alt, img_r_alt
                removed_indices = removed_alt
                per_view_errors = per_view_errors_alt
                pose_left_used = pose_left_alt
                pose_right_used = pose_right_alt
                pose_left_summary = pose_left_summary_alt
                pose_right_summary = pose_right_summary_alt
                pose_left_ok = pose_left_ok_alt
                pose_right_ok = pose_right_ok_alt
                pose_ok = pose_ok_alt
                pose_reasons = pose_reasons_alt

    removed_set = {int(i) for i in np.asarray(removed_indices).reshape(-1)}
    metadata_used = [r for i, r in enumerate(detected_metadata_records) if i not in removed_set]
    pair_names_used = [name for i, name in enumerate(detected_pair_names) if i not in removed_set]
    quality_scores_used = [score for i, score in enumerate(candidate_quality_scores) if i not in removed_set]

    pose_effective_ok = pose_ok
    pose_soft_passed = False
    pose_policy = "standard" if pose_ok else "standard_failed"
    pose_soft_reasons = []
    if not pose_ok:
        print(">> Pose coverage standard check did not pass")
        for reason in pose_reasons:
            print(f"   - {reason}")

    print(f">> outlier filter: kept={len(obj_f)} removed={len(removed_indices)}")
    print(">> final stereoCalibrate...")
    final_result = cv2.stereoCalibrate(
        obj_f, img_l_f, img_r_f,
        K1_init.copy(), D1_init.copy(),
        K2_init.copy(), D2_init.copy(),
        shape,
        flags=flags,
        criteria=criteria,
    )

    rms, K1, D1, K2, D2, R, T, E, F = final_result[:9]
    baseline = float(np.linalg.norm(T))
    R1, R2, P1, P2, Q, roi1, roi2 = cv2.stereoRectify(
        K1, D1, K2, D2, shape, R, T, alpha=0
    )

    grade, passed, baseline_error_pct, reasons = quality_grade(
        float(rms), baseline, expected_baseline, args
    )
    sync_dts = []
    for record in metadata_used:
        if record is None:
            continue
        pair_dt = record.get("pair_dt_s")
        if pair_dt is not None:
            sync_dts.append(float(pair_dt))
    sync_dts_arr = np.array(sync_dts, dtype=np.float32)

    if not passed and not args.allow_poor_quality:
        print(">> [Reject] poor stereo calibration quality")
        print(f">> RMS={float(rms):.6f}px baseline={baseline:.6f}m expected={expected_baseline:.6f}m")
        for reason in reasons:
            print(f"   - {reason}")
        print(">> Retake sharper, more varied 1280x720 stereo pairs.")
        raise SystemExit(1)

    if not pose_effective_ok:
        pose_soft_passed, pose_soft_reasons = distance_limited_pose_soft_pass(
            pair_key,
            pose_left_summary,
            pose_right_summary,
            pose_reasons,
            len(obj_f),
            float(rms),
            float(baseline_error_pct),
        )
        if pose_soft_passed:
            pose_effective_ok = True
            pose_policy = "distance_limited_optional"
            print(">> Distance-limited optional pair policy: pose coverage accepted with strict numeric checks")
            for reason in pose_soft_reasons:
                print(f"   - {reason}")

    if not pose_effective_ok and not args.allow_incomplete_pose_coverage:
        print(">> [Reject] incomplete stereo pose coverage")
        for reason in pose_reasons:
            print(f"   - {reason}")
        if pose_soft_reasons:
            print(">> Distance-limited soft-pass also failed:")
            for reason in pose_soft_reasons:
                print(f"   - {reason}")
        print(">> Retake pairs across center/edges, near/far, and rolled views.")
        raise SystemExit(1)
    if not pose_effective_ok:
        pose_policy = "incomplete_allowed"

    atomic_savez_compressed(
        out_npz,
        K1=K1, D1=D1, K2=K2, D2=D2,
        R=R, T=T, E=E, F=F,
        R1=R1, R2=R2, P1=P1, P2=P2, Q=Q,
        roi1=np.array(roi1, dtype=np.int32),
        roi2=np.array(roi2, dtype=np.int32),
        rms=float(rms),
        baseline=baseline,
        expected_baseline_m=float(expected_baseline),
        baseline_command_m=float(expected_baseline),
        baseline_actual_m=float(baseline),
        baseline_error_m=float(abs(baseline - expected_baseline)),
        baseline_error_percent=float(baseline_error_pct),
        image_size=np.array(shape, dtype=np.int32),
        image_width=int(shape[0]),
        image_height=int(shape[1]),
        checkerboard=np.array(common.CHECKERBOARD, dtype=np.int32),
        square_size_m=float(square_size_m),
        valid_pair_count=int(len(obj_f)),
        detected_pair_count_before_selection=int(detected_count_before_selection),
        total_matched_pair_count=int(len(pairs)),
        rejected_resolution_count=int(rejected_resolution),
        failed_checkerboard_count=int(failed_checkerboard),
        removed_outlier_indices=removed_indices,
        excluded_left_image_files=np.array(sorted(excluded_left_files), dtype=str),
        candidate_left_image_files=np.array([name[0] for name in candidate_pair_names_before_filter], dtype=str),
        candidate_right_image_files=np.array([name[1] for name in candidate_pair_names_before_filter], dtype=str),
        candidate_quality_scores=np.array(candidate_quality_scores_before_filter, dtype=np.float32),
        corner_order_fixed_files=np.array(corner_order_fixed, dtype=str),
        corner_order_suspect_files=np.array(corner_order_suspect, dtype=str),
        per_view_errors=per_view_errors if per_view_errors is not None else np.array([], dtype=np.float32),
        quality_grade=grade,
        quality_passed=bool(passed),
        quality_failure_reasons=np.array(reasons, dtype=str),
        distance_bucket_policy=np.array(distance_bucket_policy, dtype=str),
        relative_distance_left_summary=np.array(str(relative_distance_left_summary), dtype=str),
        relative_distance_right_summary=np.array(str(relative_distance_right_summary), dtype=str),
        pose_left_coverage_summary=np.array(str(pose_left_summary), dtype=str),
        pose_right_coverage_summary=np.array(str(pose_right_summary), dtype=str),
        pose_left_coverage_passed=bool(pose_left_ok),
        pose_right_coverage_passed=bool(pose_right_ok),
        pose_coverage_passed=bool(pose_effective_ok),
        pose_coverage_standard_passed=bool(pose_ok),
        pose_coverage_soft_passed=bool(pose_soft_passed),
        pose_coverage_policy=np.array(pose_policy, dtype=str),
        pose_coverage_soft_reasons=np.array(pose_soft_reasons, dtype=str),
        pose_coverage_failure_reasons=np.array(pose_reasons, dtype=str),
        selected_left_image_files=np.array([name[0] for name in pair_names_used], dtype=str),
        selected_right_image_files=np.array([name[1] for name in pair_names_used], dtype=str),
        selected_quality_scores=np.array(quality_scores_used, dtype=np.float32),
        auto_selection_enabled=bool(not args.disable_auto_selection and int(args.max_selected_pairs) > 0),
        max_selected_pairs=int(args.max_selected_pairs),
        duplicate_pose_distance=float(args.duplicate_pose_distance),
        metadata_managed_only=bool(args.use_metadata_filter and not args.include_unmanaged_images),
        managed_pair_count=int(len(managed_pairs)),
        sync_pair_dt_s=sync_dts_arr,
        sync_pair_dt_s_count=int(len(sync_dts_arr)),
        sync_pair_dt_s_mean=float(np.mean(sync_dts_arr)) if len(sync_dts_arr) else float("nan"),
        sync_pair_dt_s_max=float(np.max(sync_dts_arr)) if len(sync_dts_arr) else float("nan"),
        camera_left_index=int(left),
        camera_right_index=int(right),
        created_at_utc=np.array(datetime.datetime.now(datetime.timezone.utc).isoformat(), dtype=str),
        script_name=np.array(os.path.basename(__file__), dtype=str),
        source_image_dir=np.array(os.path.abspath(img_dir), dtype=str),
        opencv_version=np.array(cv2.__version__, dtype=str),
        calibration_schema_version=np.array("stereo_v2", dtype=str),
    )

    print(">> [Success] stereo calibration saved")
    print(f">> path={out_npz}")
    print(f">> RMS={float(rms):.6f}px grade={grade}")
    print(f">> baseline={baseline:.6f}m expected={expected_baseline:.6f}m error={baseline_error_pct:.2f}%")
    print(f">> pairs used={len(obj_f)} / detected={len(obj_pts)} / matched={len(pairs)}")


if __name__ == "__main__":
    main()
