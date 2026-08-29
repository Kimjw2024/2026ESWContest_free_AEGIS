# -*- coding: utf-8 -*-
import argparse
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import config_turret as cfg
except ImportError:
    cfg = None


DEFAULT_RESOLUTION = tuple(getattr(cfg, "CALIB_RESOLUTION", (1280, 720))) if cfg is not None else (1280, 720)
CAMERAS = ("0", "1", "2", "3")
PAIRS = ("01", "02", "03", "12", "13", "23")
RUNTIME_VALIDATION = getattr(cfg, "RUNTIME_VALIDATION", {}) if cfg is not None else {}


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
LOADABLE_PAIRS = list(normalize_pair_list(RUNTIME_VALIDATION.get("loadable_calib_pairs"), PAIRS))
for pair in REQUIRED_PAIRS:
    if pair not in LOADABLE_PAIRS:
        LOADABLE_PAIRS.append(pair)
LOADABLE_PAIRS = tuple(LOADABLE_PAIRS)


def default_pairs_for_cameras(cameras):
    cams = set(cameras)
    return tuple(pair for pair in REQUIRED_PAIRS if pair[0] in cams and pair[1] in cams)


def run_step(cmd, required=True):
    print("\n>> " + " ".join(f'"{x}"' if " " in x else x for x in cmd))
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)
    if result.returncode != 0:
        if required:
            raise SystemExit(
                "\n>> [STOP] Calibration step failed. See the message above for the exact reason.\n"
                ">> Common causes: not enough usable captures, missing single intrinsics before stereo, "
                "wrong square size, or incomplete pose coverage."
            )
        print(f">> [WARN] optional step failed; continuing: returncode={result.returncode}")
        return False
    return True


def parse_args():
    parser = argparse.ArgumentParser(description="Run full or selected-camera calibration pipeline.")
    parser.add_argument("--width", type=int, default=int(DEFAULT_RESOLUTION[0]))
    parser.add_argument("--height", type=int, default=int(DEFAULT_RESOLUTION[1]))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-poor-quality", action="store_true")
    parser.add_argument("--allow-incomplete-pose-coverage", action="store_true")
    parser.add_argument("--include-unmanaged-images", action="store_true")
    parser.add_argument("--include-flagged-images", action="store_true")
    parser.add_argument("--no-preview", action="store_true")
    parser.add_argument("--skip-single", action="store_true")
    parser.add_argument("--skip-stereo", action="store_true")
    parser.add_argument("--cameras", nargs="+", default=list(CAMERAS), help="Camera ids to calibrate, e.g. 0 1")
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=None,
        help="Stereo pairs to calibrate, e.g. 01 12 23. Defaults to required pairs inside --cameras.",
    )
    parser.add_argument("--square-size-m", type=float, default=None)
    parser.add_argument("--square-size-mm", type=float, default=None)
    parser.add_argument(
        "--use-default-square-size",
        action="store_true",
        help="Use src/common.py SQUARE_SIZE. Prefer --square-size-mm for real calibration.",
    )
    return parser.parse_args()


def add_common_args(cmd, args):
    cmd += ["--width", str(args.width), "--height", str(args.height)]
    if args.overwrite:
        cmd.append("--overwrite")
    if args.allow_poor_quality:
        cmd.append("--allow-poor-quality")
    if args.allow_incomplete_pose_coverage:
        cmd.append("--allow-incomplete-pose-coverage")
    if args.include_unmanaged_images:
        cmd.append("--include-unmanaged-images")
    if args.square_size_m is not None:
        cmd += ["--square-size-m", str(args.square_size_m)]
    if args.square_size_mm is not None:
        cmd += ["--square-size-mm", str(args.square_size_mm)]
    if args.use_default_square_size:
        cmd.append("--use-default-square-size")
    return cmd


def main():
    args = parse_args()
    if args.square_size_m is not None and args.square_size_mm is not None:
        raise SystemExit("Use only one of --square-size-m or --square-size-mm.")
    if args.square_size_m is None and args.square_size_mm is None and not args.use_default_square_size:
        raise SystemExit(
            "Missing checkerboard square size. Pass --square-size-mm with the measured printed square size "
            "or explicitly pass --use-default-square-size."
        )

    cameras = normalize_camera_list(args.cameras, CAMERAS)
    pair_list = normalize_pair_list(args.pairs, default_pairs_for_cameras(cameras))
    if not args.skip_stereo and not pair_list:
        raise SystemExit("No stereo pair selected. Pass --pairs, e.g. --pairs 01.")

    py = sys.executable

    if not args.skip_single:
        for cam_id in cameras:
            cmd = [py, os.path.join(SCRIPT_DIR, "1_single_calib.py"), "--camera", str(cam_id)]
            add_common_args(cmd, args)
            if args.include_flagged_images:
                cmd.append("--include-flagged-images")
            if args.no_preview:
                cmd.append("--no-preview")
            run_step(cmd)

    if not args.skip_stereo:
        for pair in pair_list:
            pair_text = normalize_pair_text(pair)
            if pair_text not in PAIRS:
                raise SystemExit(f"unsupported pair: {pair}. Use one of: {' '.join(PAIRS)}")
            cmd = [py, os.path.join(SCRIPT_DIR, "2_stereo_calib ver.2.py"), "--pair", pair_text]
            add_common_args(cmd, args)
            if args.include_flagged_images:
                cmd.append("--include-flagged-pairs")
            run_step(cmd, required=pair_text in REQUIRED_PAIRS or pair_text in pair_list)

    check_cmd = [
        py,
        os.path.join(SCRIPT_DIR, "4_check_calibration_results.py"),
        "--width", str(args.width),
        "--height", str(args.height),
        "--cameras", *cameras,
    ]
    if args.skip_stereo:
        check_cmd.append("--skip-stereo")
    else:
        check_cmd += ["--pairs", *pair_list]
    run_step(check_cmd)


if __name__ == "__main__":
    main()