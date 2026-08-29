# -*- coding: utf-8 -*-
import argparse
import datetime
import glob
import os
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
CALIBRATION_QUALITY = getattr(cfg, "CALIBRATION_QUALITY", {}) if cfg is not None else {}
DEFAULT_INTERACTIVE_SQUARE_SIZE_MM = 25.0


def image_paths(folder):
    paths = []
    for pattern in ("*.png", "*.jpg", "*.jpeg", "*.bmp"):
        paths.extend(glob.glob(os.path.join(folder, pattern)))
    return sorted(paths)


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


def per_view_errors(objpts, imgpts, rvecs, tvecs, K, D):
    errors = []
    for objp, imgp, rvec, tvec in zip(objpts, imgpts, rvecs, tvecs):
        projected, _ = cv2.projectPoints(objp, rvec, tvec, K, D)
        err = cv2.norm(imgp, projected, cv2.NORM_L2) / len(projected)
        errors.append(float(err))
    return np.array(errors, dtype=np.float32)


def quality_grade(rms, rms_excellent, rms_good):
    if rms <= rms_excellent:
        return "excellent", True
    if rms <= rms_good:
        return "good", True
    return "poor", False


def filter_view_outliers(objpts, imgpts, view_errors, names, args):
    errors = np.asarray(view_errors, dtype=np.float64).reshape(-1)
    if len(errors) != len(objpts) or len(objpts) <= int(args.min_images):
        return objpts, imgpts, np.array([], dtype=np.int32), errors.astype(np.float32)

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

    keep = []
    removed = []
    for idx, err in enumerate(errors):
        if float(err) <= threshold:
            keep.append(idx)
        else:
            removed.append(idx)

    if len(keep) < int(args.min_images):
        print(">> Outlier filter skipped: keeping all views to satisfy min-images")
        return objpts, imgpts, np.array([], dtype=np.int32), errors.astype(np.float32)

    if removed:
        print(f">> Single outlier filter: threshold={threshold:.6f}px kept={len(keep)} removed={len(removed)}")
        for idx in removed[:12]:
            label = names[idx] if idx < len(names) else f"#{idx}"
            print(f"   - remove {label}: view_error={errors[idx]:.6f}px")

    return (
        [objpts[i] for i in keep],
        [imgpts[i] for i in keep],
        np.array(removed, dtype=np.int32),
        errors.astype(np.float32),
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Single-camera calibration for 1280x720 runtime.")
    parser.add_argument("--camera", default=None, help="camera id: 0, 1, 2, 3, or all")
    parser.add_argument("--image-dir", default=None, help="override input image directory")
    parser.add_argument("--output", default=None, help="override output npz path")
    parser.add_argument("--width", type=int, default=int(DEFAULT_RESOLUTION[0]))
    parser.add_argument("--height", type=int, default=int(DEFAULT_RESOLUTION[1]))
    parser.add_argument("--min-images", type=int, default=int(CALIBRATION_QUALITY.get("min_single_images", 15)))
    parser.add_argument("--max-selected-images", type=int, default=int(CALIBRATION_QUALITY.get("max_single_images", 60)),
                        help="Hard cap for diverse high-quality images. Use 0 to keep all detected images.")
    parser.add_argument("--disable-auto-selection", action="store_true",
                        help="Use every detected image instead of selecting a diverse subset.")
    parser.add_argument("--duplicate-pose-distance", type=float, default=float(CALIBRATION_QUALITY.get("single_duplicate_pose_distance", 0.16)),
                        help="Drop lower-quality views only when pose bucket and continuous pose are this close. Use 0 to disable duplicate pruning.")
    parser.add_argument("--max-view-error", type=float, default=float(CALIBRATION_QUALITY.get("single_max_view_error", 0.35)),
                        help="Single-view reprojection error cap for the post-calibration outlier pass.")
    parser.add_argument("--filter-percentile", type=float, default=float(CALIBRATION_QUALITY.get("single_filter_percentile", 90.0)),
                        help="Single-view outlier percentile used with robust z-score filtering.")
    parser.add_argument("--max-zscore", type=float, default=float(CALIBRATION_QUALITY.get("single_max_zscore", 3.0)),
                        help="Robust z-score limit for single-view outlier filtering.")
    parser.add_argument("--rms-excellent", type=float, default=float(CALIBRATION_QUALITY.get("single_rms_excellent", 0.30)))
    parser.add_argument("--rms-good", type=float, default=float(CALIBRATION_QUALITY.get("single_rms_good", 0.50)))
    parser.add_argument("--square-size-m", type=float, default=None)
    parser.add_argument("--square-size-mm", type=float, default=None)
    parser.add_argument("--use-default-square-size", action="store_true",
                        help="Use src/common.py SQUARE_SIZE. Prefer --square-size-mm for real calibration.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-poor-quality", action="store_true")
    parser.add_argument("--allow-resolution-mismatch", action="store_true")
    parser.add_argument("--include-unmanaged-images", action="store_true",
                        help="Compatibility flag; single calibration scans all image files by default.")
    parser.add_argument("--use-metadata-filter", action="store_true",
                        help="Only scan images accepted by capture metadata. Default scans every image file and lets corner detection decide.")
    parser.add_argument("--include-flagged-images", action="store_true")
    parser.add_argument("--allow-incomplete-pose-coverage", action="store_true")
    parser.add_argument("--no-preview", action="store_true")
    return parser.parse_args()


def camera_list(camera_arg):
    if camera_arg is None:
        camera_arg = input("Camera id (0, 1, 2, 3, all): ").strip()
    if str(camera_arg).lower() == "all":
        return ["0", "1", "2", "3"]
    cam = str(camera_arg).strip()
    if cam not in {"0", "1", "2", "3"}:
        raise SystemExit("camera must be 0, 1, 2, 3, or all")
    return [cam]


def print_metadata_filter_report(img_dir, all_paths, records_by_file, include_flagged):
    image_names = {os.path.basename(p) for p in all_paths}
    try:
        data = calib_meta.load_metadata(img_dir)
    except Exception as exc:
        print(f">> [Warn] metadata read failed: {exc}")
        return

    records = [r for r in data.get("records", []) if r.get("mode") == "single" and r.get("file")]
    metadata_names = {r.get("file") for r in records if r.get("file")}
    if include_flagged:
        print(f">> Metadata filter: include-flagged enabled; {len(all_paths)} image files will be considered")
        return

    rejected = []
    force_saved_usable = 0
    for record in records:
        fname = record.get("file")
        if fname not in image_names:
            continue
        reasons = calib_meta.record_rejection_reasons(record)
        if reasons:
            rejected.append((fname, reasons))
        elif bool(record.get("force_saved", False)):
            force_saved_usable += 1

    unmanaged = sorted(image_names - metadata_names)
    print(f">> Metadata filter: {len(all_paths)} image files, {len(records_by_file)} usable metadata records")
    if force_saved_usable:
        print(f">> Metadata note: {force_saved_usable} force_saved records have no hard quality flags and will be used.")
    if rejected:
        reason_counts = {}
        for _, reasons in rejected:
            key = ", ".join(reasons)
            reason_counts[key] = reason_counts.get(key, 0) + 1
        print(">> Metadata rejected records:")
        for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0])):
            print(f"   - {count}: {reason}")
        print(">> First rejected examples:")
        for fname, reasons in rejected[:8]:
            print(f"   - {fname}: {', '.join(reasons)}")
    if unmanaged:
        print(f">> Unmanaged image files without metadata: {len(unmanaged)}")
        print(">> Use --include-unmanaged-images only for diagnostics or manual recovery.")


def calibrate_camera(cam_id, args, square_size_m):
    img_dir = args.image_dir or os.path.join(CALIB_IMAGE_DIR, "single", f"cam{cam_id}")
    out_npz = args.output or os.path.join(DATA_DIR, f"intrinsics_{cam_id}.npz")
    expected_size = (int(args.width), int(args.height))

    if os.path.exists(out_npz) and not args.overwrite:
        raise SystemExit(f"{out_npz} already exists. Use --overwrite to replace it.")

    all_paths = image_paths(img_dir)
    paths = list(all_paths)
    records_by_file = calib_meta.single_records_by_file(img_dir, include_flagged=args.include_flagged_images)
    if args.use_metadata_filter and not args.include_unmanaged_images:
        print_metadata_filter_report(img_dir, all_paths, records_by_file, args.include_flagged_images)
        paths = [p for p in paths if os.path.basename(p) in records_by_file]
    else:
        print(f">> Image source: scanning all {len(paths)} image files. Corner detection will reject unusable frames.")
        if records_by_file:
            print(f">> Metadata advisory: {len(records_by_file)} files have usable capture metadata.")
    if not paths:
        print(f">> [Error] no managed usable images found: {img_dir}")
        print(">> Capture with 3_capture_tool first, or use --include-unmanaged-images for diagnostics.")
        return False

    objp = make_objp(square_size_m)
    imgpts, objpts = [], []
    shape = None
    rejected_resolution = 0
    failed_corners = 0
    pose_records = []
    detected_names = []
    candidate_quality_scores = []

    print(f">> Cam{cam_id}: scanning {len(paths)} files from {img_dir}")
    print(f">> Required calibration resolution: {expected_size[0]}x{expected_size[1]}")

    for idx, path in enumerate(paths, 1):
        img = common.imread_unicode(path, cv2.IMREAD_COLOR)
        if img is None:
            print(f"[{idx}/{len(paths)}] READ_FAIL: {os.path.basename(path)}")
            continue

        h, w = img.shape[:2]
        current_size = (w, h)
        if current_size != expected_size and not args.allow_resolution_mismatch:
            rejected_resolution += 1
            print(f"[{idx}/{len(paths)}] SKIP_SIZE {w}x{h}: {os.path.basename(path)}")
            continue

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if shape is None:
            shape = gray.shape[::-1]
        elif gray.shape[::-1] != shape:
            rejected_resolution += 1
            print(f"[{idx}/{len(paths)}] SKIP_MIXED_SIZE: {os.path.basename(path)}")
            continue

        ret, corners = common.find_checkerboard_corners(gray)
        if not ret:
            failed_corners += 1
            print(f"[{idx}/{len(paths)}] FAIL_CB: {os.path.basename(path)}")
            continue

        imgpts.append(corners)
        objpts.append(objp)
        pose_records.append(calib_meta.pose_from_corners(corners, gray.shape))
        detected_names.append(os.path.basename(path))
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        candidate_quality_scores.append(float(np.log1p(max(sharpness, 0.0))))
        print(f"[{idx}/{len(paths)}] OK ({len(imgpts)}): {os.path.basename(path)}")

        if not args.no_preview:
            vis = img.copy()
            cv2.drawChessboardCorners(vis, common.CHECKERBOARD, corners, ret)
            preview = cv2.resize(vis, (960, 540))
            cv2.putText(preview, f"cam{cam_id} OK {len(imgpts)}/{len(paths)}", (20, 42),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
            cv2.imshow("single calibration", preview)
            cv2.waitKey(30)

    cv2.destroyAllWindows()

    if len(objpts) < args.min_images:
        print(f">> [Error] valid images too few: {len(objpts)} < {args.min_images}")
        print(f">> Capture more usable cam{cam_id} images in: {img_dir}")
        print(" >> For final calibration, capture more usable and diverse quality images instead of forcing a low-count run.")
        return False

    selected_indices = list(range(len(objpts)))
    detected_count_before_selection = len(objpts)
    if not args.disable_auto_selection:
        selection_limit = int(args.max_selected_images)
        token_sets = [calib_meta.pose_tokens(pose) for pose in pose_records]
        selected_indices = calib_meta.select_diverse_indices(
            token_sets,
            candidate_quality_scores,
            max_count=selection_limit,
            min_count=int(args.min_images),
            pose_records=pose_records,
            duplicate_distance=float(args.duplicate_pose_distance),
        )
        if len(selected_indices) < len(objpts):
            print(f">> Auto-select: using {len(selected_indices)}/{len(objpts)} diverse high-quality images")
    if len(selected_indices) < args.min_images:
        print(f">> [Error] selected images too few: {len(selected_indices)} < {args.min_images}")
        return False
    if len(selected_indices) != len(objpts):
        imgpts = [imgpts[i] for i in selected_indices]
        objpts = [objpts[i] for i in selected_indices]
        pose_records = [pose_records[i] for i in selected_indices]
        detected_names = [detected_names[i] for i in selected_indices]
        candidate_quality_scores = [candidate_quality_scores[i] for i in selected_indices]

    print(">> first calibrateCamera pass...")
    initial_rms, initial_K, initial_D, initial_rvecs, initial_tvecs = cv2.calibrateCamera(objpts, imgpts, shape, None, None)
    initial_view_errors = per_view_errors(objpts, imgpts, initial_rvecs, initial_tvecs, initial_K, initial_D)
    print(f">> first RMS={initial_rms:.4f}px")

    objpts_f, imgpts_f, removed_indices, initial_view_errors = filter_view_outliers(
        objpts, imgpts, initial_view_errors, detected_names, args
    )
    removed_set = {int(i) for i in np.asarray(removed_indices).reshape(-1)}
    removed_outlier_names = [detected_names[i] for i in sorted(removed_set) if i < len(detected_names)]
    if len(objpts_f) < args.min_images:
        print(f">> [Error] filtered images too few: {len(objpts_f)} < {args.min_images}")
        return False

    if removed_set:
        pose_records = [p for i, p in enumerate(pose_records) if i not in removed_set]
        detected_names = [name for i, name in enumerate(detected_names) if i not in removed_set]
        candidate_quality_scores = [score for i, score in enumerate(candidate_quality_scores) if i not in removed_set]
        objpts = objpts_f
        imgpts = imgpts_f
        print(">> final calibrateCamera pass...")
        rms, K, D, rvecs, tvecs = cv2.calibrateCamera(objpts, imgpts, shape, None, None)
    else:
        rms, K, D, rvecs, tvecs = initial_rms, initial_K, initial_D, initial_rvecs, initial_tvecs

    view_errors = per_view_errors(objpts, imgpts, rvecs, tvecs, K, D)
    grade, passed = quality_grade(float(rms), args.rms_excellent, args.rms_good)
    pose_summary = calib_meta.summarize_pose_coverage(pose_records)
    pose_ok, pose_reasons = calib_meta.pose_coverage_pass(pose_summary)

    if not pose_ok and not args.allow_incomplete_pose_coverage:
        print(">> [Reject] incomplete pose coverage")
        for reason in pose_reasons:
            print(f"   - {reason}")
        print(">> Retake images across center/edges, near/far, and rolled views.")
        return False

    if not passed and not args.allow_poor_quality:
        print(f">> [Reject] poor RMS {rms:.4f}px > {args.rms_good:.4f}px")
        print(">> Retake sharper, more varied 1280x720 checkerboard images.")
        return False
    atomic_savez_compressed(
        out_npz,
        K=K,
        D=D,
        image_size=np.array(shape, dtype=np.int32),
        image_width=int(shape[0]),
        image_height=int(shape[1]),
        rms=float(rms),
        initial_rms=float(initial_rms),
        per_view_errors=view_errors,
        initial_per_view_errors=initial_view_errors,
        removed_outlier_indices=removed_indices,
        removed_outlier_image_files=np.array(removed_outlier_names, dtype=str),
        valid_image_count=int(len(objpts)),
        detected_image_count_before_selection=int(detected_count_before_selection),
        total_file_count=int(len(paths)),
        rejected_resolution_count=int(rejected_resolution),
        failed_checkerboard_count=int(failed_corners),
        checkerboard=np.array(common.CHECKERBOARD, dtype=np.int32),
        square_size_m=float(square_size_m),
        quality_grade=grade,
        quality_passed=bool(passed),
        pose_coverage_summary=np.array(str(pose_summary), dtype=str),
        pose_coverage_passed=bool(pose_ok),
        pose_coverage_failure_reasons=np.array(pose_reasons, dtype=str),
        selected_source_image_files=np.array(detected_names, dtype=str),
        selected_quality_scores=np.array(candidate_quality_scores, dtype=np.float32),
        auto_selection_enabled=bool(not args.disable_auto_selection and int(args.max_selected_images) > 0),
        max_selected_images=int(args.max_selected_images),
        duplicate_pose_distance=float(args.duplicate_pose_distance),
        created_at_utc=np.array(datetime.datetime.now(datetime.timezone.utc).isoformat(), dtype=str),
        script_name=np.array(os.path.basename(__file__), dtype=str),
        source_image_dir=np.array(os.path.abspath(img_dir), dtype=str),
        opencv_version=np.array(cv2.__version__, dtype=str),
        calibration_schema_version=np.array("single_v2", dtype=str),
    )

    print(f">> [Success] cam{cam_id} intrinsics saved: {out_npz}")
    print(f">> RMS={rms:.4f}px grade={grade} valid={len(objpts)} size={shape[0]}x{shape[1]}")
    return True


def main():
    args = parse_args()
    square_size_m = resolve_square_size_m(args)
    ok = True
    for cam_id in camera_list(args.camera):
        ok = calibrate_camera(cam_id, args, square_size_m) and ok
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
