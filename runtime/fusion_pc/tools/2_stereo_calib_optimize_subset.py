# -*- coding: utf-8 -*-
"""Search practical stereo-calibration subset settings.

Default strategy is refine: start from all detected stereo pairs, then test
removing high per-view-error images one at a time. A removal is accepted only
when the calibration score improves while quality and pose coverage still pass.

By default this wrapper writes only to calibration_candidates/. If
--install-to-data is passed, it installs the best candidate into data/ only
after comparing it with the current data file and passing the calibration
checker. Existing data files are backed up before replacement.

VS Code Run-button use is supported: run this file without arguments and
answer the terminal prompts for pair and square size. After the best result is
shown, the script asks whether to install it into data/.
"""

import argparse
import csv
import datetime
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

import numpy as np


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
STEREO_SCRIPT = os.path.join(SRC_DIR, "2_stereo_calib ver.2.py")

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import config_turret as cfg
except ImportError:
    cfg = None


CAMERA_GEOMETRY = getattr(cfg, "CAMERA_GEOMETRY", {}) if cfg is not None else {}


@dataclass(frozen=True)
class Candidate:
    name: str
    args: tuple


def parse_csv_ints(text):
    result = []
    for item in str(text).split(","):
        item = item.strip()
        if item:
            result.append(int(item))
    return result


def parse_csv_floats(text):
    result = []
    for item in str(text).split(","):
        item = item.strip()
        if item:
            result.append(float(item))
    return result


def expected_baseline_for_pair(pair, fallback_spacing_m):
    left_i, right_i = sorted((int(pair[0]), int(pair[1])))
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


def build_candidates(max_pairs_grid, duplicate_grid, include_default, include_all):
    candidates = []
    if include_default:
        candidates.append(Candidate("default", tuple()))
    if include_all:
        candidates.append(Candidate("all_detected", ("--disable-auto-selection",)))

    seen = {c.name for c in candidates}
    for max_pairs in max_pairs_grid:
        for duplicate in duplicate_grid:
            name = f"max{max_pairs}_dup{duplicate:g}".replace(".", "p")
            if name in seen:
                continue
            seen.add(name)
            candidates.append(
                Candidate(
                    name,
                    (
                        "--max-selected-pairs",
                        str(max_pairs),
                        "--duplicate-pose-distance",
                        f"{duplicate:g}",
                    ),
                )
            )
    return candidates


def scalar_from_npz(z, key, default=None):
    if key not in z.files:
        return default
    value = np.asarray(z[key])
    if value.size == 0:
        return default
    return value.reshape(-1)[0].item()


def count_from_npz(z, key):
    if key not in z.files:
        return 0
    return int(np.asarray(z[key]).reshape(-1).shape[0])


def load_metrics(path, pair, fallback_spacing_m):
    expected = expected_baseline_for_pair(pair, fallback_spacing_m)
    with np.load(path, allow_pickle=True) as z:
        rms = float(scalar_from_npz(z, "rms", float("inf")))
        baseline = float(scalar_from_npz(z, "baseline_actual_m", scalar_from_npz(z, "baseline", float("inf"))))
        baseline_error_pct = abs(baseline - expected) / max(expected, 1e-9) * 100.0
        quality_passed = bool(scalar_from_npz(z, "quality_passed", False))
        pose_passed = bool(scalar_from_npz(z, "pose_coverage_passed", False))
        grade = str(scalar_from_npz(z, "quality_grade", "unknown"))
        detected = int(
            scalar_from_npz(
                z,
                "detected_pair_count",
                scalar_from_npz(z, "detected_pair_count_before_selection", 0),
            )
            or 0
        )
        selected = int(
            scalar_from_npz(
                z,
                "selected_pair_count",
                count_from_npz(z, "selected_left_image_files"),
            )
            or 0
        )
        valid = int(scalar_from_npz(z, "valid_pair_count", 0) or 0)
        removed = count_from_npz(z, "removed_outlier_indices")
    return {
        "rms": rms,
        "baseline_m": baseline,
        "expected_baseline_m": expected,
        "baseline_error_percent": baseline_error_pct,
        "quality_passed": quality_passed,
        "pose_coverage_passed": pose_passed,
        "quality_grade": grade,
        "detected_pair_count": detected,
        "selected_pair_count": selected,
        "valid_pair_count": valid,
        "removed_outlier_count": removed,
    }


def score_metrics(metrics, min_preferred_pairs, baseline_weight, low_count_penalty):
    score = float(metrics["rms"]) + float(metrics["baseline_error_percent"]) * baseline_weight
    if not metrics["quality_passed"]:
        score += 100.0
    if not metrics["pose_coverage_passed"]:
        score += 50.0
    missing = max(0, int(min_preferred_pairs) - int(metrics["valid_pair_count"]))
    score += missing * low_count_penalty
    return score


def run_candidate(args, candidate, output_path):
    cmd = [
        sys.executable,
        STEREO_SCRIPT,
        "--pair",
        args.pair,
        "--square-size-mm",
        f"{args.square_size_mm:g}",
        "--output",
        output_path,
        "--overwrite",
        "--allow-poor-quality",
        "--allow-incomplete-pose-coverage",
    ]
    cmd.extend(candidate.args)
    if args.image_dir:
        cmd.extend(["--image-dir", args.image_dir])
    if args.min_pairs is not None:
        cmd.extend(["--min-pairs", str(args.min_pairs)])
    if args.max_view_error is not None:
        cmd.extend(["--max-view-error", f"{args.max_view_error:g}"])
    if args.filter_percentile is not None:
        cmd.extend(["--filter-percentile", f"{args.filter_percentile:g}"])
    if args.max_zscore is not None:
        cmd.extend(["--max-zscore", f"{args.max_zscore:g}"])

    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.returncode, result.stdout


def safe_name(text):
    allowed = []
    for ch in str(text):
        if ch.isalnum() or ch in {"-", "_"}:
            allowed.append(ch)
        else:
            allowed.append("_")
    return "".join(allowed).strip("_") or "candidate"


def write_exclude_file(output_dir, candidate_name, excluded_left_files):
    path = os.path.join(output_dir, f"{safe_name(candidate_name)}_exclude_left.txt")
    with open(path, "w", encoding="utf-8") as f:
        for name in sorted(set(excluded_left_files)):
            f.write(f"{name}\n")
    return path


def run_candidate_row(args, candidate, output_dir, pair, fallback_spacing_m):
    out_npz = os.path.join(output_dir, f"calib_{pair}_{safe_name(candidate.name)}.npz")
    code, log = run_candidate(args, candidate, out_npz)
    log_path = os.path.join(output_dir, f"{safe_name(candidate.name)}.log")
    if code != 0 or not os.path.exists(out_npz):
        if args.keep_failed_logs:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(log)
        print(f"   FAIL code={code}")
        return None

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(log)
    metrics = load_metrics(out_npz, pair, fallback_spacing_m)
    score = score_metrics(
        metrics,
        min_preferred_pairs=args.min_preferred_pairs,
        baseline_weight=args.baseline_score_weight,
        low_count_penalty=args.low_count_penalty,
    )
    return {
        "candidate": candidate.name,
        "score": score,
        "npz_path": out_npz,
        "strategy": "",
        "dropped_left_files": "",
        "new_drop_left_file": "",
        **metrics,
    }


def print_candidate_row(row):
    print(
        f"   score={row['score']:.6f} rms={row['rms']:.6f}px "
        f"baseline_err={row['baseline_error_percent']:.3f}% "
        f"valid={row['valid_pair_count']} selected={row['selected_pair_count']} "
        f"grade={row['quality_grade']}"
    )


def ranked_per_view_left_files(npz_path):
    with np.load(npz_path, allow_pickle=True) as z:
        if "candidate_left_image_files" in z.files:
            names = [str(v) for v in np.asarray(z["candidate_left_image_files"]).reshape(-1)]
        elif "selected_left_image_files" in z.files:
            names = [str(v) for v in np.asarray(z["selected_left_image_files"]).reshape(-1)]
        else:
            return []
        if "per_view_errors" not in z.files:
            return []
        errors = np.asarray(z["per_view_errors"], dtype=np.float64).reshape(-1)
    n = min(len(names), len(errors))
    ranked = [(names[i], float(errors[i])) for i in range(n)]
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


def run_sweep(args, output_dir, pair, fallback_spacing_m):
    max_pairs_grid = parse_csv_ints(args.max_pairs_grid)
    duplicate_grid = parse_csv_floats(args.duplicate_grid)
    candidates = build_candidates(
        max_pairs_grid,
        duplicate_grid,
        include_default=not args.no_default,
        include_all=not args.no_all,
    )
    rows = []
    failures = []
    print(f">> Sweep candidates: {len(candidates)}")
    for idx, candidate in enumerate(candidates, 1):
        print(f">> [sweep {idx}/{len(candidates)}] {candidate.name}")
        row = run_candidate_row(args, candidate, output_dir, pair, fallback_spacing_m)
        if row is None:
            failures.append((candidate.name, 1))
            continue
        row["strategy"] = "sweep"
        rows.append(row)
        print_candidate_row(row)
    return rows, failures


def run_refine_from_all(args, output_dir, pair, fallback_spacing_m):
    rows = []
    failures = []
    excluded = []
    base = Candidate("refine00_all_detected", ("--disable-auto-selection",))
    print(">> Refine: starting from all detected pairs")
    current = run_candidate_row(args, base, output_dir, pair, fallback_spacing_m)
    if current is None:
        return rows, [(base.name, 1)]
    current["strategy"] = "refine"
    rows.append(current)
    print_candidate_row(current)

    for step in range(1, int(args.refine_max_removals) + 1):
        ranked = ranked_per_view_left_files(current["npz_path"])
        if not ranked:
            print(">> Refine: no per-view error list available; stopping")
            break
        best_trial = None
        tested = 0
        for left_name, view_error in ranked:
            if left_name in excluded:
                continue
            trial_excluded = sorted(set(excluded + [left_name]))
            exclude_file = write_exclude_file(output_dir, f"refine{step:02d}_{left_name}", trial_excluded)
            candidate = Candidate(
                f"refine{step:02d}_drop_{safe_name(left_name)}",
                ("--disable-auto-selection", "--exclude-left-file-list", exclude_file),
            )
            print(f">> [refine step {step}] try dropping {left_name} per_view={view_error:.6f}px")
            row = run_candidate_row(args, candidate, output_dir, pair, fallback_spacing_m)
            tested += 1
            if row is None:
                failures.append((candidate.name, 1))
            else:
                row["strategy"] = "refine"
                row["dropped_left_files"] = ";".join(trial_excluded)
                row["new_drop_left_file"] = left_name
                rows.append(row)
                print_candidate_row(row)
                improves = float(row["score"]) <= float(current["score"]) - float(args.refine_min_score_improvement)
                if row["quality_passed"] and row["pose_coverage_passed"] and improves:
                    if best_trial is None or float(row["score"]) < float(best_trial["score"]):
                        best_trial = row
            if tested >= int(args.refine_top_k):
                break
        if best_trial is None:
            print(">> Refine: no tested removal improved the score while preserving quality/coverage")
            break
        excluded = [name for name in str(best_trial["dropped_left_files"]).split(";") if name]
        current = best_trial
        print(
            f">> Refine: accepted removal {best_trial['new_drop_left_file']} "
            f"new_score={best_trial['score']:.6f} dropped={len(excluded)}"
        )
    return rows, failures


def write_summary_csv(path, rows):
    fieldnames = [
        "rank",
        "candidate",
        "score",
        "rms",
        "baseline_m",
        "expected_baseline_m",
        "baseline_error_percent",
        "valid_pair_count",
        "selected_pair_count",
        "detected_pair_count",
        "removed_outlier_count",
        "quality_grade",
        "quality_passed",
        "pose_coverage_passed",
        "npz_path",
        "strategy",
        "dropped_left_files",
        "new_drop_left_file",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rank, row in enumerate(rows, 1):
            out = {key: row.get(key, "") for key in fieldnames}
            out["rank"] = rank
            writer.writerow(out)


def run_post_install_check(pair, output_dir):
    check_script = os.path.join(SRC_DIR, "4_check_calibration_results.py")
    cmd = [
        sys.executable,
        check_script,
        "--cameras",
        pair[0],
        pair[1],
        "--pairs",
        pair,
    ]
    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log_path = os.path.join(output_dir, "post_install_check.log")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(result.stdout)
    return result.returncode, log_path, result.stdout


def install_best_to_data(args, data_dir, output_dir, pair, best, best_copy, fallback_spacing_m):
    if not best.get("quality_passed"):
        raise SystemExit("Refusing to install: best candidate did not pass quality checks.")
    if not best.get("pose_coverage_passed"):
        raise SystemExit("Refusing to install: best candidate did not pass pose coverage checks.")

    data_path = os.path.join(data_dir, f"calib_{pair}.npz")
    best_score = float(best["score"])
    backup_path = None

    if os.path.exists(data_path):
        current_metrics = load_metrics(data_path, pair, fallback_spacing_m)
        current_score = score_metrics(
            current_metrics,
            min_preferred_pairs=args.min_preferred_pairs,
            baseline_weight=args.baseline_score_weight,
            low_count_penalty=args.low_count_penalty,
        )
        print(
            f">> Current data score={current_score:.6f} rms={current_metrics['rms']:.6f}px "
            f"baseline_err={current_metrics['baseline_error_percent']:.3f}% "
            f"valid={current_metrics['valid_pair_count']}"
        )
        if not args.force_install and best_score >= current_score - float(args.min_score_improvement):
            print(
                ">> Install skipped: best candidate is not better than current data "
                f"by min_score_improvement={args.min_score_improvement:g}."
            )
            return False

        backup_dir = os.path.join(output_dir, "data_backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"calib_{pair}_{stamp}.npz")
        shutil.copy2(data_path, backup_path)
        print(f">> Backed up current data file: {backup_path}")

    shutil.copy2(best_copy, data_path)
    print(f">> Installed best candidate to data: {data_path}")

    code, log_path, _ = run_post_install_check(pair, output_dir)
    if code != 0:
        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, data_path)
            print(f">> Restored previous data file from backup: {backup_path}")
        elif os.path.exists(data_path):
            os.remove(data_path)
            print(">> Removed installed data file because post-install check failed and no previous backup existed.")
        raise SystemExit(f"Post-install calibration check failed. See {log_path}")

    print(f">> Post-install calibration check passed. Log: {log_path}")
    return True


def prompt_text(label, default):
    raw = input(f"{label} [{default}]: ").strip()
    return raw or str(default)


def prompt_bool(label, default=True):
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} ({hint}): ").strip().lower()
        if not raw:
            return bool(default)
        if raw in {"y", "yes", "1", "true"}:
            return True
        if raw in {"n", "no", "0", "false"}:
            return False
        print("Please answer y or n.")


def normalize_pair_text(pair_text):
    text = str(pair_text).strip().lower().replace("cam", "").replace("-", "").replace("_", "")
    if text == "all":
        return "all"
    if len(text) != 2 or not text.isdigit() or text[0] == text[1]:
        raise SystemExit("--pair must look like 01, 02, 03, 12, 13, 23, or all")
    if text[0] not in "0123" or text[1] not in "0123":
        raise SystemExit("camera pair must use camera ids 0, 1, 2, 3")
    if int(text[0]) > int(text[1]):
        raise SystemExit("left camera id must be lower than right camera id, e.g. 01 not 10")
    return text


def apply_run_button_prompts(args):
    if args.pair is not None:
        return args
    print(">> VS Code run-button mode: no --pair argument was provided.")
    print(">> Type one pair, or type all to run 12, 23, then 01. Optional pairs like 02, 13, 03 also work.")
    args.pair = prompt_text("Stereo pair (01, 02, 03, 12, 13, 23, all)", "12")
    args.square_size_mm = float(prompt_text("Checkerboard square size in mm", f"{args.square_size_mm:g}"))
    args.prompt_install_after = True
    args.install_to_data = False
    print(">> Install decision will be asked after the best candidate is shown.")
    return args


def child_command_for_pair(args, pair):
    if args.image_dir:
        raise SystemExit("--pair all cannot be used with --image-dir because each pair has a different image folder.")
    cmd = [
        sys.executable,
        os.path.abspath(__file__),
        "--pair",
        pair,
        "--square-size-mm",
        f"{args.square_size_mm:g}",
        "--output-dir",
        args.output_dir,
        "--strategy",
        args.strategy,
        "--max-pairs-grid",
        args.max_pairs_grid,
        "--duplicate-grid",
        args.duplicate_grid,
        "--min-preferred-pairs",
        str(args.min_preferred_pairs),
        "--baseline-score-weight",
        f"{args.baseline_score_weight:g}",
        "--low-count-penalty",
        f"{args.low_count_penalty:g}",
        "--min-score-improvement",
        f"{args.min_score_improvement:g}",
        "--refine-top-k",
        str(args.refine_top_k),
        "--refine-max-removals",
        str(args.refine_max_removals),
        "--refine-min-score-improvement",
        f"{args.refine_min_score_improvement:g}",
    ]
    if args.min_pairs is not None:
        cmd.extend(["--min-pairs", str(args.min_pairs)])
    if args.max_view_error is not None:
        cmd.extend(["--max-view-error", f"{args.max_view_error:g}"])
    if args.filter_percentile is not None:
        cmd.extend(["--filter-percentile", f"{args.filter_percentile:g}"])
    if args.max_zscore is not None:
        cmd.extend(["--max-zscore", f"{args.max_zscore:g}"])
    if args.no_default:
        cmd.append("--no-default")
    if args.no_all:
        cmd.append("--no-all")
    if args.keep_failed_logs:
        cmd.append("--keep-failed-logs")
    if args.install_to_data:
        cmd.append("--install-to-data")
    if args.prompt_install_after:
        cmd.append("--prompt-install-after")
    if args.force_install:
        cmd.append("--force-install")
    return cmd


def run_all_pairs(args):
    for pair in ("12", "23", "01"):
        print("\n" + "=" * 72)
        print(f">> Running optimized stereo calibration for pair {pair}")
        print("=" * 72)
        result = subprocess.run(child_command_for_pair(args, pair), cwd=PROJECT_ROOT)
        if result.returncode != 0:
            raise SystemExit(f"pair {pair} failed with exit code {result.returncode}")
    print("\n>> Finished all requested stereo pairs.")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run stereo-calibration optimization and optionally install the best result."
    )
    parser.add_argument("--pair", default=None, help="camera pair, e.g. 01, 02, 03, 12, 13, 23, or all")
    parser.add_argument("--square-size-mm", type=float, default=25.0)
    parser.add_argument("--image-dir", default=None)
    parser.add_argument(
        "--output-dir",
        default=os.path.join(PROJECT_ROOT, "calibration_candidates"),
        help="candidate output folder. Do not point this at data/.",
    )
    parser.add_argument("--strategy", choices=("refine", "sweep", "both"), default="refine")
    parser.add_argument("--max-pairs-grid", default="50,60,70,80,90,0")
    parser.add_argument("--duplicate-grid", default="0,0.08,0.12,0.16,0.20")
    parser.add_argument("--no-default", action="store_true")
    parser.add_argument("--no-all", action="store_true")
    parser.add_argument("--min-pairs", type=int, default=None)
    parser.add_argument("--min-preferred-pairs", type=int, default=40)
    parser.add_argument("--baseline-score-weight", type=float, default=0.02)
    parser.add_argument("--low-count-penalty", type=float, default=0.002)
    parser.add_argument("--max-view-error", type=float, default=None)
    parser.add_argument("--filter-percentile", type=float, default=None)
    parser.add_argument("--max-zscore", type=float, default=None)
    parser.add_argument("--keep-failed-logs", action="store_true")
    parser.add_argument(
        "--install-to-data",
        action="store_true",
        help="Install the best candidate into data/calib_XX.npz if it improves current data and post-check passes.",
    )
    parser.add_argument(
        "--prompt-install-after",
        action="store_true",
        help="After showing the best candidate and current data comparison, ask whether to install.",
    )
    parser.add_argument(
        "--force-install",
        action="store_true",
        help="With --install-to-data, install even if the current data score is not worse.",
    )
    parser.add_argument(
        "--min-score-improvement",
        type=float,
        default=0.0,
        help="Required score improvement over current data before installing. Lower score is better.",
    )
    parser.add_argument(
        "--refine-top-k",
        type=int,
        default=8,
        help="At each refine step, test this many highest per-view-error removals.",
    )
    parser.add_argument(
        "--refine-max-removals",
        type=int,
        default=8,
        help="Maximum accepted image removals in refine mode.",
    )
    parser.add_argument(
        "--refine-min-score-improvement",
        type=float,
        default=0.001,
        help="Minimum score improvement required to accept a removal.",
    )
    return parser.parse_args()


def main():
    args = apply_run_button_prompts(parse_args())
    pair = normalize_pair_text(args.pair)
    if pair == "all":
        run_all_pairs(args)
        return
    args.pair = pair

    data_dir = os.path.realpath(getattr(cfg, "DATA_DIR", os.path.join(PROJECT_ROOT, "data")) if cfg is not None else os.path.join(PROJECT_ROOT, "data"))
    output_dir = os.path.realpath(os.path.join(args.output_dir, f"cam{pair}"))
    if output_dir == data_dir or output_dir.startswith(data_dir + os.sep):
        raise SystemExit("Refusing to write candidates under data/. Choose a different --output-dir.")
    os.makedirs(output_dir, exist_ok=True)

    fallback_spacing_m = float(CAMERA_GEOMETRY.get("camera_spacing_m", 0.15))
    rows = []
    failures = []
    print(f">> Optimizing cam{pair} strategy={args.strategy}")
    print(f">> Candidate output dir: {output_dir}")

    if args.strategy in {"refine", "both"}:
        refine_rows, refine_failures = run_refine_from_all(args, output_dir, pair, fallback_spacing_m)
        rows.extend(refine_rows)
        failures.extend(refine_failures)
    if args.strategy in {"sweep", "both"}:
        sweep_rows, sweep_failures = run_sweep(args, output_dir, pair, fallback_spacing_m)
        rows.extend(sweep_rows)
        failures.extend(sweep_failures)

    if not rows:
        raise SystemExit(f"No successful candidates. Failures: {failures}")

    rows.sort(key=lambda row: (float(row["score"]), float(row["rms"]), -int(row["valid_pair_count"])))
    summary_csv = os.path.join(output_dir, f"summary_cam{pair}.csv")
    write_summary_csv(summary_csv, rows)

    best = rows[0]
    best_copy = os.path.join(output_dir, f"best_calib_{pair}.npz")
    shutil.copy2(best["npz_path"], best_copy)

    print("\n>> Best candidate")
    print(f"   name={best['candidate']}")
    print(f"   strategy={best.get('strategy', '')}")
    if best.get("dropped_left_files"):
        print(f"   dropped_left_files={best['dropped_left_files']}")
    print(f"   source={best['npz_path']}")
    print(f"   best_copy={best_copy}")
    print(
        f"   score={best['score']:.6f} rms={best['rms']:.6f}px "
        f"baseline={best['baseline_m']:.6f}m expected={best['expected_baseline_m']:.6f}m "
        f"baseline_err={best['baseline_error_percent']:.3f}% valid={best['valid_pair_count']}"
    )
    print(f"   summary={summary_csv}")
    if failures:
        print(f">> Failed candidates: {', '.join(name for name, _ in failures)}")

    if args.prompt_install_after and not args.install_to_data:
        data_path = os.path.join(data_dir, f"calib_{pair}.npz")
        print("\n>> Current data comparison")
        if os.path.exists(data_path):
            current_metrics = load_metrics(data_path, pair, fallback_spacing_m)
            current_score = score_metrics(
                current_metrics,
                min_preferred_pairs=args.min_preferred_pairs,
                baseline_weight=args.baseline_score_weight,
                low_count_penalty=args.low_count_penalty,
            )
            print(
                "   current_score={:.6f} rms={:.6f}px baseline_err={:.3f}% valid={}".format(
                    current_score,
                    float(current_metrics["rms"]),
                    float(current_metrics["baseline_error_percent"]),
                    int(current_metrics["valid_pair_count"]),
                )
            )
            print("   best_score={:.6f}".format(float(best["score"])))
        else:
            print("   no current data file exists for this pair")
        args.install_to_data = prompt_bool("Install this best result to data now", False)

    installed = False
    if args.install_to_data:
        installed = install_best_to_data(
            args,
            data_dir,
            output_dir,
            pair,
            best,
            best_copy,
            fallback_spacing_m,
        )
    if not installed:
        print(">> data/ was not modified.")


if __name__ == "__main__":
    main()