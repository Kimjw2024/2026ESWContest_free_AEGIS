# -*- coding: utf-8 -*-
import datetime
import json
import os

import numpy as np


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")
METADATA_FILENAME = "metadata.json"
METADATA_SCHEMA_VERSION = "aegis_calib_metadata_v1"
MIN_USABLE_SHARPNESS = 200.0

try:
    import common as _common
    CHECKERBOARD_COLS = int(getattr(_common, "CHECKERBOARD", (9, 6))[0])
except Exception:
    CHECKERBOARD_COLS = 9


def normalize_roll_deg(angle_deg):
    while angle_deg <= -90.0:
        angle_deg += 180.0
    while angle_deg > 90.0:
        angle_deg -= 180.0
    return float(angle_deg)


def roll_from_corners(pts):
    if len(pts) >= CHECKERBOARD_COLS:
        vec = pts[CHECKERBOARD_COLS - 1] - pts[0]
    else:
        vec = pts[-1] - pts[0]
    return normalize_roll_deg(float(np.degrees(np.arctan2(vec[1], vec[0]))))


def utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def metadata_path(folder):
    return os.path.join(folder, METADATA_FILENAME)


def load_metadata(folder):
    path = metadata_path(folder)
    if not os.path.exists(path):
        return {
            "schema_version": METADATA_SCHEMA_VERSION,
            "created_at_utc": utc_now_iso(),
            "updated_at_utc": utc_now_iso(),
            "records": [],
        }
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("schema_version", METADATA_SCHEMA_VERSION)
    data.setdefault("records", [])
    return data


def save_metadata(folder, data):
    os.makedirs(folder, exist_ok=True)
    data["updated_at_utc"] = utc_now_iso()
    path = metadata_path(folder)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def upsert_record(folder, record):
    data = load_metadata(folder)
    key = record_key(record)
    records = []
    replaced = False
    for old in data.get("records", []):
        if record_key(old) == key:
            records.append(record)
            replaced = True
        else:
            records.append(old)
    if not replaced:
        records.append(record)
    data["records"] = records
    save_metadata(folder, data)


def record_key(record):
    if record.get("mode") == "stereo":
        return ("stereo", record.get("left_file"), record.get("right_file"))
    return ("single", record.get("file"))


def list_images(folder):
    if not os.path.isdir(folder):
        return []
    out = []
    for name in os.listdir(folder):
        if name.lower().endswith(IMAGE_EXTS):
            out.append(os.path.join(folder, name))
    return sorted(out)


HARD_REJECT_FLAGS = (
    "quality_failed",
    "checkerboard_failed",
    "resolution_failed",
    "sync_failed",
    "baseline_mismatch",
)


def record_rejection_reasons(record):
    reasons = []
    for flag in HARD_REJECT_FLAGS:
        if bool(record.get(flag, False)):
            reasons.append(flag)
    return reasons


def is_record_usable(record, include_flagged=False):
    if include_flagged:
        return True
    return not record_rejection_reasons(record)


def single_records_by_file(folder, include_flagged=False):
    data = load_metadata(folder)
    result = {}
    for record in data.get("records", []):
        if record.get("mode") != "single":
            continue
        fname = record.get("file")
        if not fname:
            continue
        if not os.path.exists(os.path.join(folder, fname)):
            continue
        if not is_record_usable(record, include_flagged=include_flagged):
            continue
        result[fname] = record
    return result


def stereo_records(folder, include_flagged=False):
    data = load_metadata(folder)
    left_dir = os.path.join(folder, "left")
    right_dir = os.path.join(folder, "right")
    result = []
    for record in data.get("records", []):
        if record.get("mode") != "stereo":
            continue
        left_file = record.get("left_file")
        right_file = record.get("right_file")
        if not left_file or not right_file:
            continue
        if not os.path.exists(os.path.join(left_dir, left_file)):
            continue
        if not os.path.exists(os.path.join(right_dir, right_file)):
            continue
        if not is_record_usable(record, include_flagged=include_flagged):
            continue
        result.append(record)
    return result


def pose_from_corners(corners, image_shape):
    pts = np.asarray(corners, dtype=np.float32).reshape(-1, 2)
    h, w = image_shape[:2]
    x0, y0 = np.min(pts, axis=0)
    x1, y1 = np.max(pts, axis=0)
    center_x = float((x0 + x1) * 0.5 / max(w, 1))
    center_y = float((y0 + y1) * 0.5 / max(h, 1))
    area_ratio = float(max((x1 - x0) * (y1 - y0), 0.0) / max(w * h, 1))
    roll_deg = roll_from_corners(pts)
    grid_x = int(np.clip(center_x * 3.0, 0, 2))
    grid_y = int(np.clip(center_y * 3.0, 0, 2))
    if area_ratio >= 0.32:
        distance_bucket = "near"
    elif area_ratio <= 0.15:
        distance_bucket = "far"
    else:
        distance_bucket = "mid"
    if roll_deg < -12:
        roll_bucket = "roll_left"
    elif roll_deg > 12:
        roll_bucket = "roll_right"
    else:
        roll_bucket = "roll_center"
    return {
        "center_x": center_x,
        "center_y": center_y,
        "area_ratio": area_ratio,
        "roll_deg": roll_deg,
        "grid_cell": f"{grid_x},{grid_y}",
        "distance_bucket": distance_bucket,
        "roll_bucket": roll_bucket,
    }


def assign_relative_distance_buckets(
    pose_records,
    min_log_area_span=0.35,
    far_quantile=0.33,
    near_quantile=0.67,
):
    """Assign far/mid/near after seeing the full capture distribution.

    The fixed thresholds in pose_from_corners are useful as a rough diagnostic,
    but calibration coverage should be judged relative to the images captured
    for that pair. If the board-size spread is too small, keep one distance
    bucket so coverage is not falsely inflated.
    """
    updated = [dict(p) if p else p for p in pose_records]
    valid = []
    for idx, pose in enumerate(updated):
        if not pose:
            continue
        area = float(pose.get("area_ratio", 0.0))
        if np.isfinite(area) and area > 0.0:
            valid.append((idx, area))

    info = {
        "mode": "relative",
        "sample_count": len(valid),
        "min_log_area_span": float(min_log_area_span),
        "far_quantile": float(far_quantile),
        "near_quantile": float(near_quantile),
    }
    if len(valid) < 3:
        for pose in updated:
            if pose:
                pose["absolute_distance_bucket"] = pose.get("distance_bucket")
                pose["distance_bucket"] = "mid"
                pose["distance_bucket_policy"] = "relative_insufficient_samples"
        info.update({"policy": "relative_insufficient_samples"})
        return updated, info

    areas = np.array([area for _, area in valid], dtype=np.float64)
    log_areas = np.log(np.maximum(areas, 1e-12))
    log_span = float(np.max(log_areas) - np.min(log_areas))
    info.update({
        "min_area_ratio": float(np.min(areas)),
        "max_area_ratio": float(np.max(areas)),
        "log_area_span": log_span,
    })

    if log_span < float(min_log_area_span):
        for pose in updated:
            if pose:
                pose["absolute_distance_bucket"] = pose.get("distance_bucket")
                pose["distance_bucket"] = "mid"
                pose["distance_bucket_policy"] = "relative_insufficient_span"
        info.update({"policy": "relative_insufficient_span"})
        return updated, info

    far_q = float(np.clip(far_quantile, 0.01, 0.49))
    near_q = float(np.clip(near_quantile, 0.51, 0.99))
    if far_q >= near_q:
        far_q, near_q = 0.33, 0.67
    far_threshold = float(np.quantile(log_areas, far_q))
    near_threshold = float(np.quantile(log_areas, near_q))

    counts = {"far": 0, "mid": 0, "near": 0}
    for idx, area in valid:
        pose = updated[idx]
        pose["absolute_distance_bucket"] = pose.get("distance_bucket")
        log_area = float(np.log(max(area, 1e-12)))
        if log_area <= far_threshold:
            bucket = "far"
        elif log_area >= near_threshold:
            bucket = "near"
        else:
            bucket = "mid"
        pose["distance_bucket"] = bucket
        pose["distance_bucket_policy"] = "relative"
        counts[bucket] += 1

    info.update({
        "policy": "relative",
        "far_log_area_threshold": far_threshold,
        "near_log_area_threshold": near_threshold,
        "bucket_counts": counts,
    })
    return updated, info

def summarize_pose_coverage(pose_records):
    poses = [p for p in pose_records if p]
    grid = sorted({p.get("grid_cell") for p in poses if p.get("grid_cell")})
    distance = sorted({p.get("distance_bucket") for p in poses if p.get("distance_bucket")})
    roll = sorted({p.get("roll_bucket") for p in poses if p.get("roll_bucket")})
    return {
        "sample_count": len(poses),
        "grid_cells": grid,
        "grid_cell_count": len(grid),
        "distance_buckets": distance,
        "distance_bucket_count": len(distance),
        "roll_buckets": roll,
        "roll_bucket_count": len(roll),
    }


def pose_coverage_pass(summary, min_grid_cells=5, min_distance_buckets=2, min_roll_buckets=2):
    reasons = []
    if summary.get("grid_cell_count", 0) < min_grid_cells:
        reasons.append(f"grid_cells<{min_grid_cells}")
    if summary.get("distance_bucket_count", 0) < min_distance_buckets:
        reasons.append(f"distance_buckets<{min_distance_buckets}")
    if summary.get("roll_bucket_count", 0) < min_roll_buckets:
        reasons.append(f"roll_buckets<{min_roll_buckets}")
    return not reasons, reasons

def pose_tokens(pose, prefix=""):
    if not pose:
        return set()
    pfx = f"{prefix}:" if prefix else ""
    tokens = set()
    for key in ("grid_cell", "distance_bucket", "roll_bucket"):
        value = pose.get(key)
        if value:
            tokens.add(f"{pfx}{key}:{value}")
    return tokens


def _normalised_scores(quality_scores, n):
    if quality_scores is None:
        return np.zeros(n, dtype=np.float64)
    scores = np.asarray(quality_scores, dtype=np.float64).reshape(-1)
    if scores.size != n:
        scores = np.resize(scores, n)
    scores = np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0)
    if np.max(scores) > np.min(scores):
        return (scores - np.min(scores)) / (np.max(scores) - np.min(scores))
    return np.zeros(n, dtype=np.float64)


def _pose_vector(pose):
    if not pose:
        return None
    cx = float(pose.get("center_x", 0.5))
    cy = float(pose.get("center_y", 0.5))
    area = float(max(pose.get("area_ratio", 0.0), 1e-6))
    roll = np.radians(float(pose.get("roll_deg", 0.0)))
    # Area is logarithmic because near/far board sizes span a large range.
    return np.array([
        cx * 2.0,
        cy * 2.0,
        np.log(area) / 4.0,
        np.sin(roll),
        np.cos(roll),
    ], dtype=np.float64)


def _pose_distance(a, b):
    if a is None or b is None:
        return float("inf")
    return float(np.linalg.norm(a - b))


def _signature(tokens):
    return tuple(sorted(set(tokens)))


def _best_per_signature(signatures, scores):
    best = {}
    for idx, sig in enumerate(signatures):
        current = best.get(sig)
        if current is None or (float(scores[idx]), -idx) > (float(scores[current]), -current):
            best[sig] = idx
    return set(best.values())


def _prune_to_max(selected, token_sets, scores, max_count, min_count):
    selected = set(selected)
    if max_count is None or int(max_count) <= 0 or len(selected) <= int(max_count):
        return selected
    max_count = max(int(max_count), int(min_count), 1)
    while len(selected) > max_count:
        token_counts = {}
        for idx in selected:
            for token in token_sets[idx]:
                token_counts[token] = token_counts.get(token, 0) + 1
        removable = []
        for idx in selected:
            if all(token_counts.get(token, 0) > 1 for token in token_sets[idx]):
                removable.append(idx)
        if not removable:
            break
        remove_idx = min(removable, key=lambda i: (float(scores[i]), -i))
        selected.remove(remove_idx)
    return selected


def select_diverse_indices(
    token_sets,
    quality_scores=None,
    max_count=0,
    min_count=0,
    pose_records=None,
    duplicate_distance=0.16,
):
    """Remove only harmful duplicates while preserving calibration coverage.

    This is intentionally not a fixed-count downsampler. It keeps the best frame
    for every observed pose bucket, then keeps additional views only when their
    continuous pose is sufficiently different from already-kept views with the
    same bucket signature. Very large sets may still be capped by max_count as a
    safety limit, but coverage tokens are protected during that cap.
    """
    n = len(token_sets)
    if n == 0:
        return []
    token_sets = [set(t) for t in token_sets]
    scores = _normalised_scores(quality_scores, n)
    signatures = [_signature(tokens) for tokens in token_sets]
    pose_vectors = None
    if pose_records is not None:
        pose_vectors = [_pose_vector(pose) for pose in pose_records]
        if len(pose_vectors) != n:
            pose_vectors = None

    if pose_vectors is None or duplicate_distance is None or float(duplicate_distance) <= 0.0:
        selected = set(range(n))
        selected = _prune_to_max(selected, token_sets, scores, max_count, min_count)
        return sorted(selected)

    selected = _best_per_signature(signatures, scores)
    ordered = sorted(range(n), key=lambda i: (float(scores[i]), -i), reverse=True)
    for idx in ordered:
        if idx in selected:
            continue
        duplicate = False
        for kept_idx in selected:
            if signatures[idx] != signatures[kept_idx]:
                continue
            if _pose_distance(pose_vectors[idx], pose_vectors[kept_idx]) < float(duplicate_distance):
                duplicate = True
                break
        if not duplicate:
            selected.add(idx)

    if len(selected) < int(min_count):
        for idx in ordered:
            selected.add(idx)
            if len(selected) >= int(min_count):
                break

    selected = _prune_to_max(selected, token_sets, scores, max_count, min_count)
    return sorted(selected)
