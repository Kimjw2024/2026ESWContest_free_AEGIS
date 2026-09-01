# -*- coding: utf-8 -*-
"""
5_final_fusion_SYNC_PRED_FIXED.py

"""
import os
import sys


def _reexec_with_project_python():
    expected = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Programs",
        "Python",
        "Python311",
        "python.exe",
    )
    if not expected or not os.path.exists(expected):
        return
    if os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(os.path.abspath(expected)):
        return
    print(f"[PYTHON] Re-launching with project Python: {expected}", flush=True)
    import subprocess
    raise SystemExit(subprocess.call([expected, os.path.abspath(__file__), *sys.argv[1:]]))


_reexec_with_project_python()

if os.environ.get("AEGIS_REEXEC_TEST") == "1":
    print(f"[PYTHON] Re-exec test interpreter: {sys.executable}", flush=True)
    raise SystemExit(0)

import cv2
import zmq
import pickle
import numpy as np
import math
import time
import threading
import traceback
from collections import deque

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = SCRIPT_DIR

def resolve_project_path(path):
    if not path:
        return path
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)

YOLO_MODEL_EXTS = (".pt", ".engine", ".onnx", ".torchscript", ".xml")

def _path_exists(path):
    return bool(path) and os.path.exists(path)

def _model_candidates_from_dir(model_dir):
    if not model_dir or not os.path.isdir(model_dir):
        return []
    candidates = []
    priority_names = (
        "best.engine", "best.pt", "custom.engine", "custom.pt",
        "model.engine", "model.pt", "yolo_custom.engine", "yolo_custom.pt",
    )
    for name in priority_names:
        path = os.path.join(model_dir, name)
        if os.path.exists(path):
            candidates.append(path)
    for name in DETECTION_CFG.get("yolo_pretrained_candidates", ()):
        name_text = str(name)
        if os.path.isabs(name_text):
            path = name_text
        elif os.path.dirname(name_text):
            path = resolve_project_path(name_text)
        else:
            path = os.path.join(model_dir, name_text)
        if os.path.exists(path):
            candidates.append(path)
    discovered = []
    for name in os.listdir(model_dir):
        path = os.path.join(model_dir, name)
        if os.path.isfile(path) and name.lower().endswith(YOLO_MODEL_EXTS):
            discovered.append(path)
    discovered.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for path in discovered:
        if path not in candidates:
            candidates.append(path)
    return candidates

# UI toggle. If False, imshow/waitKey are disabled.
ENABLE_UI = True

# Detection mode. HSV is the low-latency color tracker; YOLO uses the bird detector.
# Press T at runtime to switch modes when command input is enabled.
DETECT_MODE = "HSV"

# YOLO is loaded lazily so HSV/calibration checks can run without torch.
_YOLO_MODEL = None
_YOLO_IMPORT_ERROR = None
_YOLO_DEVICE = "cpu"
_YOLO_HALF = False
_YOLO_IMGSZ = 320
_YOLO_MODEL_PATH = "models/yolo26n.engine"
_YOLO_TASK = "detect"

# ==========================================
# Config
# ==========================================
try:
    import config_turret as cfg
except ImportError:
    class cfg:
        PT1_CONFIG = {"pos_global": [0.075, 0, 0], "h_pivot": 0.03, "dx_laser": 0.0, "dz_laser": 0.05, "l_arm": 0.08, "pan_trim": 0, "tilt_trim": 0}
        PT2_CONFIG = {"pos_global": [0.375, 0, 0], "h_pivot": 0.03, "dx_laser": 0.0, "dz_laser": 0.05, "l_arm": 0.08, "pan_trim": 0, "tilt_trim": 0}
        FUSION_PARAMS = {"mount_angle_deg": 20, "max_y_diff": 50, "pred_k": 8, "max_pred_len": 2.0, "edge_margin": 50, "critical_dist_m": 1.0, "cam_height_m": 0.03, "max_laser_dist": 3.0}
        PREDICTION = {"system_delay": 0.14, "sonic_speed": 340.0, "max_lead_dist": 0.22, "command_lead_ratio": 0.55, "vel_deadzone": 0.06, "smooth_alpha": 0.35, "vel_lpf_beta": 0.35, "z_scale": 1.0}
        SERVO_CENTER = 90
        SAFE_LIMITS = {"pan_min": 30, "pan_max": 150, "tilt_min": 30, "tilt_max": 150}
        TRACK_HOLD = {"hold_sec": 0.30, "drop_sec": 1.00, "threat_decay": 0.5}
        SYNC = {"max_frame_age": 0.25, "max_show_age": 1.00, "pair_sync_window": 0.06, "pair_sync_soft_window": 0.09, "pair_sync_weight_floor": 0.08}
        CALIB_RESOLUTION = (1280, 720)
        RUNTIME_VALIDATION = {"strict_calibration": True, "required_calib_pairs": ["01", "12", "23"], "loadable_calib_pairs": ["01", "02", "03", "12", "13", "23"], "allow_poor_calibration": False, "strict_stream_resolution": True}
        DETECTION = {"default_mode": "HSV", "yolo_model_path": "models/yolo26n.engine", "yolo_imgsz_gpu": 1280, "yolo_imgsz_cpu": 640, "yolo_conf": 0.16, "yolo_max_det": 1, "yolo_classes": [14], "yolo_min_box_area": 80, "yolo_assignment": "confidence", "yolo_rect": True, "target_count": 1, "hsv_full_resolution": False}

for attr, default in [
    ('PREDICTION', {"system_delay": 0.14, "sonic_speed": 340.0, "max_lead_dist": 0.22, "command_lead_ratio": 0.55, "vel_deadzone": 0.06, "smooth_alpha": 0.35, "vel_lpf_beta": 0.35, "z_scale": 1.0}),
    ('TRACK_HOLD', {"hold_sec": 0.30, "drop_sec": 1.00, "threat_decay": 0.5}),
    ('SYNC', {"max_frame_age": 0.25, "max_show_age": 1.00, "pair_sync_window": 0.06, "pair_sync_soft_window": 0.09, "pair_sync_weight_floor": 0.08}),
    ('RUNTIME_VALIDATION', {"strict_calibration": True, "required_calib_pairs": ["01", "12", "23"], "loadable_calib_pairs": ["01", "02", "03", "12", "13", "23"], "allow_poor_calibration": False, "strict_stream_resolution": True}),
    ('CAMERA_STREAM', {"width": 1280, "height": 720, "fps": 20, "jpeg_quality": 76, "sensor_mode": "2304:1296", "rotation": 180}),
    ('RUNTIME_STREAM', {"width": 640, "height": 360, "fps": 30, "jpeg_quality": 75, "sensor_mode": "2304:1296", "rotation": 180}),
    ('DETECTION', {"default_mode": "HSV", "yolo_model_path": "models/yolo26n.engine", "yolo_imgsz_gpu": 1280, "yolo_imgsz_cpu": 640, "yolo_conf": 0.16, "yolo_max_det": 1, "yolo_classes": [14], "yolo_min_box_area": 80, "yolo_assignment": "confidence", "yolo_rect": True, "target_count": 1, "hsv_full_resolution": False}),
    ('UI', {"enabled": True, "target_fps": 12, "draw_yolo_overlay": True}),
]:
    if not hasattr(cfg, attr):
        setattr(cfg, attr, default)

DETECTION_CFG = getattr(cfg, "DETECTION", {})
NETWORK_CFG = getattr(cfg, "NETWORK", {})
RUNTIME_VALIDATION_CFG = getattr(cfg, "RUNTIME_VALIDATION", {})
UI_CFG = getattr(cfg, "UI", {})
_YOLO_CONFIG_MODEL_PATH = resolve_project_path(str(DETECTION_CFG.get("yolo_model_path", _YOLO_MODEL_PATH)))
YOLO_MODEL_DIR = resolve_project_path(str(DETECTION_CFG.get("yolo_model_dir", "models")))
YOLO_FALLBACK_MODEL_PATH = resolve_project_path(str(DETECTION_CFG.get("yolo_fallback_model_path", _YOLO_CONFIG_MODEL_PATH)))
_YOLO_MODEL_PATH = _YOLO_CONFIG_MODEL_PATH
YOLO_CLASSES_CFG = DETECTION_CFG.get("yolo_classes", "auto")
YOLO_CUSTOM_CLASSES_CFG = DETECTION_CFG.get("yolo_custom_classes", "auto")
YOLO_FALLBACK_CLASSES = DETECTION_CFG.get("yolo_fallback_classes", [14])
YOLO_CLASSES = None
YOLO_CONF = float(DETECTION_CFG.get("yolo_conf", 0.16))
YOLO_MAX_DET = int(DETECTION_CFG.get("yolo_max_det", 1))
YOLO_MIN_BOX_AREA = float(DETECTION_CFG.get("yolo_min_box_area", 80))
YOLO_ASSIGNMENT = str(DETECTION_CFG.get("yolo_assignment", "confidence")).lower()
YOLO_RECT = bool(DETECTION_CFG.get("yolo_rect", True))
YOLO_CENTER_MODE = str(DETECTION_CFG.get("yolo_center_mode", "auto")).lower()
YOLO_BOX_ANCHOR = DETECTION_CFG.get("yolo_box_anchor", [0.5, 0.5])
try:
    YOLO_BOX_ANCHOR_X = float(YOLO_BOX_ANCHOR[0])
    YOLO_BOX_ANCHOR_Y = float(YOLO_BOX_ANCHOR[1])
except (TypeError, ValueError, IndexError):
    YOLO_BOX_ANCHOR_X, YOLO_BOX_ANCHOR_Y = 0.5, 0.5
YOLO_BOX_ANCHOR_X = float(np.clip(YOLO_BOX_ANCHOR_X, 0.0, 1.0))
YOLO_BOX_ANCHOR_Y = float(np.clip(YOLO_BOX_ANCHOR_Y, 0.0, 1.0))
YOLO_CENTER_SMOOTH_ALPHA = float(DETECTION_CFG.get("yolo_center_smooth_alpha", 1.0))
if not np.isfinite(YOLO_CENTER_SMOOTH_ALPHA):
    YOLO_CENTER_SMOOTH_ALPHA = 1.0
YOLO_CENTER_SMOOTH_ALPHA = float(np.clip(YOLO_CENTER_SMOOTH_ALPHA, 0.05, 1.0))
YOLO_CENTER_MAX_JUMP_PX = float(DETECTION_CFG.get("yolo_center_max_jump_px", 220.0))
if not np.isfinite(YOLO_CENTER_MAX_JUMP_PX) or YOLO_CENTER_MAX_JUMP_PX <= 0:
    YOLO_CENTER_MAX_JUMP_PX = 220.0
YOLO_ALLOW_MONO_AIM = bool(DETECTION_CFG.get("yolo_allow_mono_aim", False))
YOLO_KEYPOINT_INDEX = DETECTION_CFG.get("yolo_keypoint_index", None)
AIM_STATIC_TARGETS = bool(DETECTION_CFG.get("aim_static_targets", False))
if YOLO_KEYPOINT_INDEX is not None:
    try:
        YOLO_KEYPOINT_INDEX = int(YOLO_KEYPOINT_INDEX)
    except (TypeError, ValueError):
        YOLO_KEYPOINT_INDEX = None
MAX_RECTIFIED_Y_DIFF = float(getattr(cfg, "FUSION_PARAMS", {}).get("max_rectified_y_diff", cfg.FUSION_PARAMS["max_y_diff"]))
TARGET_COUNT = max(1, min(2, int(DETECTION_CFG.get("target_count", 1))))
VIDEO_PORT = int(NETWORK_CFG.get("video_port", 5555))
RESULT_PORT = int(NETWORK_CFG.get("result_port", 5556))
UI_PORT = int(NETWORK_CFG.get("ui_port", 5557))
UI_CMD_PORT = int(NETWORK_CFG.get("ui_cmd_port", 5558))
VIDEO_RCVHWM = max(1, int(NETWORK_CFG.get("video_rcvhwm", 64)))
VIDEO_CONFLATE = bool(NETWORK_CFG.get("video_conflate", False))
DETECT_MODE = str(DETECTION_CFG.get("default_mode", DETECT_MODE)).upper()
STRICT_CALIBRATION = bool(RUNTIME_VALIDATION_CFG.get("strict_calibration", True))
ALLOW_POOR_CALIBRATION = bool(RUNTIME_VALIDATION_CFG.get("allow_poor_calibration", False))
STRICT_STREAM_RESOLUTION = bool(RUNTIME_VALIDATION_CFG.get("strict_stream_resolution", True))
ENABLE_UI = bool(UI_CFG.get("enabled", ENABLE_UI))
UI_TARGET_FPS = float(UI_CFG.get("target_fps", 12))
UI_RENDER_INTERVAL = 0.0 if UI_TARGET_FPS <= 0 else 1.0 / UI_TARGET_FPS
DRAW_YOLO_OVERLAY = bool(UI_CFG.get("draw_yolo_overlay", True))
ENABLE_DASHBOARD = bool(UI_CFG.get("dashboard_enabled", True))
STORE_VISUAL_FEEDS = ENABLE_UI or ENABLE_DASHBOARD
DASHBOARD_FPS = float(UI_CFG.get("dashboard_fps", 15))
DASHBOARD_INTERVAL = 0.0 if DASHBOARD_FPS <= 0 else 1.0 / DASHBOARD_FPS
DASHBOARD_JPEG_QUALITY = int(UI_CFG.get("dashboard_jpeg_quality", 78))
DASHBOARD_COMMAND_MAX_AGE = float(UI_CFG.get("dashboard_command_max_age", 0.5))
MAX_DASHBOARD_COMMANDS_PER_LOOP = 32

def _normalize_pair_text(pair):
    text = str(pair).replace("cam", "").replace("-", "").replace("_", "")
    if len(text) != 2 or not text.isdigit() or text[0] == text[1]:
        return None
    return "".join(sorted(text))

ALL_CALIB_PAIRS = ["01", "02", "03", "12", "13", "23"]

def _normalize_pair_list(pairs, fallback):
    out = []
    for _pair in pairs or []:
        _norm_pair = _normalize_pair_text(_pair)
        if _norm_pair is not None and _norm_pair not in out:
            out.append(_norm_pair)
    return out or list(fallback)

REQUIRED_CALIB_PAIRS = _normalize_pair_list(
    RUNTIME_VALIDATION_CFG.get("required_calib_pairs"),
    ["01", "12", "23"],
)
if not REQUIRED_CALIB_PAIRS:
    REQUIRED_CALIB_PAIRS = ["01", "12", "23"]
LOADABLE_CALIB_PAIRS = _normalize_pair_list(
    RUNTIME_VALIDATION_CFG.get("loadable_calib_pairs"),
    ALL_CALIB_PAIRS,
)
for _pair in REQUIRED_CALIB_PAIRS:
    if _pair not in LOADABLE_CALIB_PAIRS:
        LOADABLE_CALIB_PAIRS.append(_pair)

def select_yolo_model_path():
    candidates = []
    candidates.extend(_model_candidates_from_dir(YOLO_MODEL_DIR))
    if _path_exists(_YOLO_CONFIG_MODEL_PATH):
        candidates.append(_YOLO_CONFIG_MODEL_PATH)
    if _path_exists(YOLO_FALLBACK_MODEL_PATH):
        candidates.append(YOLO_FALLBACK_MODEL_PATH)
    fallback_root = resolve_project_path("models/yolo26n.engine")
    if _path_exists(fallback_root):
        candidates.append(fallback_root)

    seen = set()
    for path in candidates:
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.exists(path):
            return path
    return _YOLO_CONFIG_MODEL_PATH

def is_custom_yolo_model(path):
    if not path:
        return False
    basename = os.path.basename(str(path)).lower()
    standard_names = {
        os.path.basename(str(name)).lower()
        for name in DETECTION_CFG.get("yolo_pretrained_candidates", ())
    }
    if basename in standard_names:
        return False
    try:
        model_dir = os.path.normcase(os.path.abspath(YOLO_MODEL_DIR))
        model_path = os.path.normcase(os.path.abspath(path))
        return os.path.commonpath([model_dir, model_path]) == model_dir
    except Exception:
        return False

def _parse_yolo_classes(value, model_path):
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("", "none", "all"):
            return None
        if text == "auto":
            return None if is_custom_yolo_model(model_path) else YOLO_FALLBACK_CLASSES
        try:
            return [int(x.strip()) for x in text.split(",") if x.strip()]
        except ValueError:
            return None
    try:
        return [int(x) for x in value]
    except TypeError:
        return None

def resolve_yolo_classes(model_path):
    class_cfg = YOLO_CUSTOM_CLASSES_CFG if is_custom_yolo_model(model_path) else YOLO_CLASSES_CFG
    return _parse_yolo_classes(class_cfg, model_path)

def resolve_yolo_task(model_path):
    task_cfg = str(DETECTION_CFG.get("yolo_task", "auto")).strip().lower()
    if task_cfg in ("detect", "segment", "pose", "obb"):
        return task_cfg
    if task_cfg not in ("", "auto", "none"):
        return "detect"

    basename = os.path.basename(str(model_path)).lower()
    if any(token in basename for token in ("-seg", "_seg", "seg.")):
        return "segment"
    if any(token in basename for token in ("-pose", "_pose", "pose.")):
        return "pose"
    if is_custom_yolo_model(model_path):
        return None
    return "detect"

def load_yolo_model(cls, model_path, task):
    return cls(model_path) if task is None else cls(model_path, task=task)

def warmup_yolo_model():
    if not bool(DETECTION_CFG.get("yolo_warmup", True)):
        return
    if _YOLO_MODEL is None:
        return
    try:
        dummy = np.zeros((SRC_H, SRC_W, 3), dtype=np.uint8)
        warmup_batch = [dummy.copy() for _ in range(4)]
        kwargs = {
            "conf": YOLO_CONF,
            "imgsz": _YOLO_IMGSZ,
            "max_det": YOLO_MAX_DET,
            "device": _YOLO_DEVICE,
            "half": _YOLO_HALF,
            "rect": YOLO_RECT,
            "verbose": False,
        }
        if YOLO_CLASSES is not None:
            kwargs["classes"] = YOLO_CLASSES
        _YOLO_MODEL(warmup_batch, **kwargs)
        try:
            import torch
            if _YOLO_DEVICE != "cpu" and torch.cuda.is_available():
                torch.cuda.synchronize()
        except Exception:
            pass
        print(">> YOLO warmup complete")
    except Exception as e:
        print(f"!! YOLO warmup skipped: {type(e).__name__}: {e}")

def ensure_yolo_ready():
    global _YOLO_MODEL, _YOLO_IMPORT_ERROR, _YOLO_DEVICE, _YOLO_HALF, _YOLO_IMGSZ, _YOLO_MODEL_PATH, _YOLO_TASK, YOLO_CLASSES

    if _YOLO_MODEL is not None:
        return True

    try:
        import torch
        from ultralytics import YOLO as YOLO

        cuda_ok = torch.cuda.is_available()
        _YOLO_DEVICE = "0" if cuda_ok else "cpu"
        _YOLO_HALF = bool(cuda_ok)
        if cuda_ok:
            _YOLO_IMGSZ = int(DETECTION_CFG.get("yolo_imgsz_gpu", DETECTION_CFG.get("yolo_imgsz", 640)))
            print(f">> GPU detected: {torch.cuda.get_device_name(0)} / YOLO device=0, half=True")
        else:
            _YOLO_IMGSZ = int(DETECTION_CFG.get("yolo_imgsz_cpu", DETECTION_CFG.get("yolo_imgsz", 320)))
            print(">> GPU not detected: YOLO CPU mode")

        _YOLO_MODEL_PATH = select_yolo_model_path()
        YOLO_CLASSES = resolve_yolo_classes(_YOLO_MODEL_PATH)
        _YOLO_TASK = resolve_yolo_task(_YOLO_MODEL_PATH)
        _YOLO_MODEL = load_yolo_model(YOLO, _YOLO_MODEL_PATH, _YOLO_TASK)
        _YOLO_IMPORT_ERROR = None
        class_text = "all/custom" if YOLO_CLASSES is None else ",".join(str(x) for x in YOLO_CLASSES)
        task_text = "auto" if _YOLO_TASK is None else _YOLO_TASK
        print(f">> YOLO model loaded: {_YOLO_MODEL_PATH}, task={task_text}, imgsz={_YOLO_IMGSZ}, classes={class_text}, device={_YOLO_DEVICE}")
        warmup_yolo_model()
        return True
    except Exception as e:
        _YOLO_IMPORT_ERROR = e
        print(f"!! YOLO unavailable: {type(e).__name__}: {e}")
        return False

# ==========================================
# Runtime image geometry
# ==========================================
_calib_resolution = getattr(cfg, "CALIB_RESOLUTION", (1280, 720))
SRC_W, SRC_H = int(_calib_resolution[0]), int(_calib_resolution[1])
RUNTIME_STREAM_CFG = getattr(cfg, "RUNTIME_STREAM", getattr(cfg, "CAMERA_STREAM", {}))
try:
    RUNTIME_STREAM_SIZE = (
        int(RUNTIME_STREAM_CFG.get("width", SRC_W)),
        int(RUNTIME_STREAM_CFG.get("height", SRC_H)),
    )
except Exception:
    RUNTIME_STREAM_SIZE = (SRC_W, SRC_H)
SUPPORTED_STREAM_SIZES = {(SRC_W, SRC_H)}
if (
    RUNTIME_STREAM_SIZE[0] > 0
    and RUNTIME_STREAM_SIZE[1] > 0
    and RUNTIME_STREAM_SIZE[0] * SRC_H == RUNTIME_STREAM_SIZE[1] * SRC_W
):
    SUPPORTED_STREAM_SIZES.add(RUNTIME_STREAM_SIZE)

# ==========================================
# Calibration Load
# ==========================================
CANDIDATE_ROOTS = [
    SCRIPT_DIR,
    os.path.join(SCRIPT_DIR, "data"),
    getattr(cfg, 'DATA_DIR', os.path.join(SCRIPT_DIR, "data")),
]
CALIB_DATA = {}
RUNTIME_CALIB_REQUIRED_KEYS = {
    "K1", "D1", "K2", "D2", "R", "T", "R1", "R2", "P1", "P2", "Q", "image_size"
}
RUNTIME_CALIB_SAFETY_KEYS = {
    "quality_passed", "pose_coverage_passed", "calibration_schema_version",
    "baseline_actual_m", "baseline_command_m",
}

def _calibration_image_size(npz):
    if "image_size" in npz.files:
        vals = np.asarray(npz["image_size"]).reshape(-1)
        if len(vals) >= 2:
            return int(vals[0]), int(vals[1])
    if "image_width" in npz.files and "image_height" in npz.files:
        return int(npz["image_width"]), int(npz["image_height"])
    return None

def _npz_bool(npz, key, default=True):
    if key not in npz.files:
        return default
    return bool(np.asarray(npz[key]).reshape(-1)[0])

def _npz_finite(npz, key):
    arr = np.asarray(npz[key])
    return np.all(np.isfinite(arr))

def _runtime_calibration_issues(npz, p_str):
    files = set(npz.files)
    required = set(RUNTIME_CALIB_REQUIRED_KEYS)
    if STRICT_CALIBRATION:
        required |= RUNTIME_CALIB_SAFETY_KEYS

    issues = []
    missing = sorted(required - files)
    if missing:
        issues.append(f"missing keys: {', '.join(missing)}")

    image_size = _calibration_image_size(npz)
    if image_size != (SRC_W, SRC_H):
        if image_size is None:
            issues.append(f"missing image_size; rebuild at {SRC_W}x{SRC_H}")
        else:
            issues.append(f"resolution {image_size[0]}x{image_size[1]} != runtime {SRC_W}x{SRC_H}")

    for key in ("K1", "D1", "K2", "D2", "R", "T", "R1", "R2", "P1", "P2", "Q"):
        if key in files and not _npz_finite(npz, key):
            issues.append(f"{key} contains non-finite values")

    if "baseline_actual_m" in files:
        baseline = float(np.asarray(npz["baseline_actual_m"]).reshape(-1)[0])
    elif "baseline" in files:
        baseline = float(np.asarray(npz["baseline"]).reshape(-1)[0])
    else:
        baseline = None
    if baseline is not None and (not np.isfinite(baseline) or baseline <= 0):
        issues.append(f"invalid baseline {baseline}")

    if not ALLOW_POOR_CALIBRATION:
        if "quality_passed" in files and not _npz_bool(npz, "quality_passed"):
            issues.append("quality_passed is false")
        if "pose_coverage_passed" in files and not _npz_bool(npz, "pose_coverage_passed"):
            issues.append("pose_coverage_passed is false")

    return issues

def _calibration_baseline_m(cal):
    for key in ("baseline_actual_m", "baseline"):
        if key in cal:
            val = float(np.asarray(cal[key]).reshape(-1)[0])
            if np.isfinite(val) and val > 0:
                return val
    if "T" in cal:
        val = float(np.linalg.norm(cal["T"]))
        if np.isfinite(val) and val > 0:
            return val
    return None

def pair_baseline_m(idx_a, idx_b):
    ca, cb = sorted((int(idx_a), int(idx_b)))
    if ca == cb:
        return None
    cal = CALIB_DATA.get((ca, cb))
    if cal is not None:
        baseline = _calibration_baseline_m(cal)
        if baseline is not None:
            return baseline
    return CAMERA_SPACING_M * abs(cb - ca)

def pair_baseline_weight(idx_a, idx_b):
    baseline = pair_baseline_m(idx_a, idx_b)
    if baseline is None:
        baseline = CAMERA_SPACING_M * max(1, abs(int(idx_b) - int(idx_a)))
    ref = BASELINE_WEIGHT_REFERENCE_M if BASELINE_WEIGHT_REFERENCE_M > 0 else CAMERA_SPACING_M
    normalized = max(0.01, baseline / max(ref, 1e-6))
    return normalized ** BASELINE_WEIGHT_POWER

def pair_reliability_weight(idx_a, idx_b):
    rel_cfg = cfg.FUSION_PARAMS.get("pair_reliability", {})
    if not isinstance(rel_cfg, dict):
        return 1.0
    ca, cb = sorted((int(idx_a), int(idx_b)))
    key = f"{ca}{cb}"
    try:
        val = float(rel_cfg.get(key, 1.0))
    except (TypeError, ValueError):
        val = 1.0
    if not np.isfinite(val):
        return 1.0
    return float(np.clip(val, 0.0, 2.0))

def pair_sync_weight(ts_a, ts_b):
    if ts_a is None or ts_b is None:
        return 1.0
    dt = abs(float(ts_a) - float(ts_b))
    if dt <= PAIR_SYNC_WINDOW:
        return 1.0
    if dt > PAIR_SYNC_SOFT_WINDOW:
        return 0.0
    span = max(PAIR_SYNC_SOFT_WINDOW - PAIR_SYNC_WINDOW, 1e-6)
    ratio = (dt - PAIR_SYNC_WINDOW) / span
    return max(PAIR_SYNC_WEIGHT_FLOOR, 1.0 - ratio * (1.0 - PAIR_SYNC_WEIGHT_FLOOR))

_CAMERA_TO_CAM0_POSE_CACHE = {}

def _rt_from_calibration(cal):
    try:
        r = np.asarray(cal["R"], dtype=np.float64).reshape(3, 3)
        t = np.asarray(cal["T"], dtype=np.float64).reshape(3, 1)
    except Exception:
        return None, None
    if not np.all(np.isfinite(r)) or not np.all(np.isfinite(t)):
        return None, None
    return r, t

def camera_to_cam0_pose(cam_idx):
    cam_idx = int(cam_idx)
    if cam_idx == 0:
        return np.eye(3, dtype=np.float64), np.zeros((3, 1), dtype=np.float64)
    if cam_idx in _CAMERA_TO_CAM0_POSE_CACHE:
        return _CAMERA_TO_CAM0_POSE_CACHE[cam_idx]

    direct = CALIB_DATA.get((0, cam_idx))
    if direct is not None:
        r_0i, t_0i = _rt_from_calibration(direct)
        if r_0i is not None:
            r_i0 = r_0i.T
            t_i0 = -r_0i.T @ t_0i
            _CAMERA_TO_CAM0_POSE_CACHE[cam_idx] = (r_i0, t_i0)
            return r_i0, t_i0

    pose_prev = camera_to_cam0_pose(cam_idx - 1) if cam_idx > 0 else None
    adjacent = CALIB_DATA.get((cam_idx - 1, cam_idx)) if cam_idx > 0 else None
    if pose_prev is None or adjacent is None:
        return None
    r_prev0, t_prev0 = pose_prev
    r_prev_i, t_prev_i = _rt_from_calibration(adjacent)
    if r_prev_i is None:
        return None
    r_i0 = r_prev0 @ r_prev_i.T
    t_i0 = t_prev0 - r_prev0 @ r_prev_i.T @ t_prev_i
    _CAMERA_TO_CAM0_POSE_CACHE[cam_idx] = (r_i0, t_i0)
    return r_i0, t_i0

def triangulate_in_base_camera(cal, pts_1, pts_2):
    r, t = _rt_from_calibration(cal)
    if r is None:
        return None
    p1 = np.array([[float(pts_1[0]), float(pts_1[1])]], dtype=np.float64).reshape(1, 1, 2)
    p2 = np.array([[float(pts_2[0]), float(pts_2[1])]], dtype=np.float64).reshape(1, 1, 2)
    try:
        n1 = cv2.undistortPoints(p1, cal["K1"], cal["D1"]).reshape(2, 1)
        n2 = cv2.undistortPoints(p2, cal["K2"], cal["D2"]).reshape(2, 1)
    except Exception:
        return None
    pmat1 = np.hstack([np.eye(3, dtype=np.float64), np.zeros((3, 1), dtype=np.float64)])
    pmat2 = np.hstack([r, t])
    point4d = cv2.triangulatePoints(pmat1, pmat2, n1, n2)
    w = float(point4d[3, 0])
    if not np.isfinite(w) or abs(w) < 1e-6:
        return None
    point3d = (point4d[:3] / w).reshape(3, 1)
    if not np.all(np.isfinite(point3d)):
        return None
    return point3d

def camera0_to_world(point_cam0):
    x_cam, y_cam, z_cam = [float(v) for v in np.asarray(point_cam0, dtype=np.float64).reshape(3)]
    theta = math.radians(MOUNT_ANGLE_DEG)
    y_world = (-y_cam) * math.cos(theta) + z_cam * math.sin(theta)
    z_world = -(-y_cam) * math.sin(theta) + z_cam * math.cos(theta)
    return np.array([x_cam, y_world, z_world], dtype=np.float64)

print(">> Calibration loading...")
required_pairs = list(REQUIRED_CALIB_PAIRS)
load_pairs = list(LOADABLE_CALIB_PAIRS)
best_root, best_cnt = None, -1
best_required_cnt = -1
for r in CANDIDATE_ROOTS:
    required_cnt = sum(1 for p in required_pairs if os.path.exists(os.path.join(r, f"calib_{p}.npz")))
    cnt = sum(1 for p in load_pairs if os.path.exists(os.path.join(r, f"calib_{p}.npz")))
    if (required_cnt, cnt) > (best_required_cnt, best_cnt):
        best_required_cnt, best_cnt, best_root = required_cnt, cnt, r

if best_cnt <= 0:
    print("!! No calib files found")
else:
    print(f"   ROOT = {best_root} (required {best_required_cnt}/{len(required_pairs)}, loaded candidates {best_cnt}/{len(load_pairs)})")
    for p_str in load_pairs:
        path = os.path.join(best_root, f"calib_{p_str}.npz")
        if not os.path.exists(path):
            continue
        key = tuple(map(int, list(p_str)))
        npz = np.load(path, allow_pickle=False)
        issues = _runtime_calibration_issues(npz, p_str)
        if issues:
            print(f"!! skip calib_{p_str}.npz:")
            for issue in issues:
                print(f"   - {issue}")
            npz.close()
            continue
        CALIB_DATA[key] = {k: npz[k] for k in npz.files}
        npz.close()

loaded_pair_text = ["".join(map(str, key)) for key in sorted(CALIB_DATA)]
missing_pair_text = [p for p in required_pairs if tuple(map(int, list(p))) not in CALIB_DATA]
missing_optional_pair_text = [p for p in load_pairs if p not in required_pairs and tuple(map(int, list(p))) not in CALIB_DATA]
if loaded_pair_text:
    print(f"   Loaded pairs: {', '.join(loaded_pair_text)}")
if missing_optional_pair_text:
    print(f"   Optional pairs not loaded: {', '.join(missing_optional_pair_text)}")
if missing_pair_text:
    msg = (
        "Runtime calibration validation failed. Missing/invalid required pairs: "
        + ", ".join(missing_pair_text)
        + f". Run src\\4_run_calibration_pipeline.py at {SRC_W}x{SRC_H} and pass src\\4_check_calibration_results.py before fusion."
    )
    if STRICT_CALIBRATION:
        raise SystemExit("!! " + msg)
    print("!! " + msg)
if not CALIB_DATA:
    raise SystemExit("!! No usable runtime calibration loaded; fusion cannot produce 3D targets.")

if DETECT_MODE == "YOLO" and not ensure_yolo_ready():
    print("!! Falling back to HSV mode. Install torch/ultralytics and provide the model file to use YOLO.")
    DETECT_MODE = "HSV"
print(f">> Detect mode={DETECT_MODE}, YOLO imgsz={_YOLO_IMGSZ}, max_det={YOLO_MAX_DET}, targets={TARGET_COUNT}, rect={YOLO_RECT}, device={_YOLO_DEVICE}")

# ==========================================
# Target Color (HSV)
# ==========================================
ALL_TARGET_COLORS = {
    "Target_1": {"lower": np.array([40, 100, 100]), "upper": np.array([80, 255, 255])},
    "Target_2": {"lower": np.array([105, 85, 70]), "upper": np.array([130, 255, 255])}
}
HSV_COLORS_CFG = getattr(cfg, "HSV_COLORS", DETECTION_CFG.get("hsv_colors", {}))
if isinstance(HSV_COLORS_CFG, dict):
    for _name, _lims in HSV_COLORS_CFG.items():
        if not isinstance(_lims, dict):
            continue
        try:
            _lower = np.asarray(_lims["lower"], dtype=np.uint8).reshape(3)
            _upper = np.asarray(_lims["upper"], dtype=np.uint8).reshape(3)
        except Exception:
            continue
        ALL_TARGET_COLORS[str(_name)] = {"lower": _lower, "upper": _upper}
TARGET_NAMES = [f"Target_{idx + 1}" for idx in range(TARGET_COUNT)]
TARGET_COLORS = {name: ALL_TARGET_COLORS[name] for name in TARGET_NAMES}
VISUAL_COLORS = {"Target_1": (0, 255, 0), "Target_2": (255, 0, 255)}

calib_trims = {
    "pt1": [cfg.PT1_CONFIG["pan_trim"], cfg.PT1_CONFIG["tilt_trim"]],
    "pt2": [cfg.PT2_CONFIG["pan_trim"], cfg.PT2_CONFIG["tilt_trim"]]
}

# Load runtime parameters from config_turret.py.
MOUNT_ANGLE_DEG = cfg.FUSION_PARAMS["mount_angle_deg"]
MAX_Y_DIFF      = cfg.FUSION_PARAMS["max_y_diff"]
EDGE_MARGIN     = cfg.FUSION_PARAMS["edge_margin"]
CRITICAL_DIST_M = cfg.FUSION_PARAMS["critical_dist_m"]
CAM_HEIGHT_M    = cfg.FUSION_PARAMS["cam_height_m"]
CAMERA_GEOMETRY_CFG = getattr(cfg, "CAMERA_GEOMETRY", {})
CAMERA_SPACING_M = float(CAMERA_GEOMETRY_CFG.get("camera_spacing_m", 0.15))
BASELINE_WEIGHT_POWER = float(cfg.FUSION_PARAMS.get("baseline_weight_power", 2.0))
BASELINE_WEIGHT_REFERENCE_M = float(cfg.FUSION_PARAMS.get("baseline_weight_reference_m", CAMERA_SPACING_M))
if not np.isfinite(BASELINE_WEIGHT_POWER) or BASELINE_WEIGHT_POWER <= 0:
    BASELINE_WEIGHT_POWER = 2.0
if not np.isfinite(BASELINE_WEIGHT_REFERENCE_M) or BASELINE_WEIGHT_REFERENCE_M <= 0:
    BASELINE_WEIGHT_REFERENCE_M = CAMERA_SPACING_M
HSV_FULL_RESOLUTION = bool(DETECTION_CFG.get("hsv_full_resolution", True))
HSV_MIN_AREA = max(0.0, float(DETECTION_CFG.get("hsv_min_area", 0.0)))
HSV_MIN_CIRCULARITY = max(0.0, float(DETECTION_CFG.get("hsv_min_circularity", 0.0)))
HSV_MORPH_CLOSE = bool(DETECTION_CFG.get("hsv_morph_close", True))

SYSTEM_DELAY  = cfg.PREDICTION["system_delay"]
SONIC_SPEED   = cfg.PREDICTION["sonic_speed"]
MAX_LEAD_DIST = cfg.PREDICTION["max_lead_dist"]
COMMAND_LEAD_RATIO = float(cfg.PREDICTION.get("command_lead_ratio", 1.0))
if not np.isfinite(COMMAND_LEAD_RATIO):
    COMMAND_LEAD_RATIO = 1.0
COMMAND_LEAD_RATIO = float(np.clip(COMMAND_LEAD_RATIO, 0.0, 1.0))
VEL_DEADZONE  = cfg.PREDICTION["vel_deadzone"]
SMOOTH_ALPHA  = cfg.PREDICTION["smooth_alpha"]
Z_SCALE       = cfg.PREDICTION.get("z_scale", 1.0)
VEL_LPF_BETA  = cfg.PREDICTION.get("vel_lpf_beta", 0.5)

TRACK_HOLD_SEC  = cfg.TRACK_HOLD["hold_sec"]
TRACK_DROP_SEC  = cfg.TRACK_HOLD["drop_sec"]
THREAT_DECAY    = cfg.TRACK_HOLD.get("threat_decay", 0.5)
TRACK_AIM_HOLD_SEC = float(cfg.TRACK_HOLD.get("aim_hold_sec", TRACK_HOLD_SEC))
if not np.isfinite(TRACK_AIM_HOLD_SEC) or TRACK_AIM_HOLD_SEC < 0:
    TRACK_AIM_HOLD_SEC = 0.0
TRACK_AIM_HOLD_SEC = min(TRACK_AIM_HOLD_SEC, TRACK_HOLD_SEC)

MAX_FRAME_AGE    = cfg.SYNC["max_frame_age"]
MAX_SHOW_AGE     = cfg.SYNC["max_show_age"]
PAIR_SYNC_WINDOW = cfg.SYNC["pair_sync_window"]
PAIR_SYNC_SOFT_WINDOW = max(PAIR_SYNC_WINDOW, float(cfg.SYNC.get("pair_sync_soft_window", PAIR_SYNC_WINDOW)))
PAIR_SYNC_WEIGHT_FLOOR = float(cfg.SYNC.get("pair_sync_weight_floor", 0.2))
if not np.isfinite(PAIR_SYNC_WEIGHT_FLOOR):
    PAIR_SYNC_WEIGHT_FLOOR = 0.2
PAIR_SYNC_WEIGHT_FLOOR = float(np.clip(PAIR_SYNC_WEIGHT_FLOOR, 0.02, 1.0))
SENDER_PAIR_MAX_DT = float(cfg.SYNC.get("sender_pair_max_dt", PAIR_SYNC_WINDOW))
if not np.isfinite(SENDER_PAIR_MAX_DT) or SENDER_PAIR_MAX_DT <= 0:
    SENDER_PAIR_MAX_DT = PAIR_SYNC_WINDOW
OFFSET_ALPHA = float(cfg.SYNC.get("sender_offset_alpha", 0.1))
if not np.isfinite(OFFSET_ALPHA):
    OFFSET_ALPHA = 0.1
OFFSET_ALPHA = float(np.clip(OFFSET_ALPHA, 0.01, 0.5))
OFFSET_MAX_STEP = float(cfg.SYNC.get("sender_offset_max_step", 0.20))
if not np.isfinite(OFFSET_MAX_STEP) or OFFSET_MAX_STEP <= 0:
    OFFSET_MAX_STEP = 0.20
SYNC_DIAGNOSTIC_INTERVAL = float(cfg.SYNC.get("diagnostic_interval_sec", 0.0))
if not np.isfinite(SYNC_DIAGNOSTIC_INTERVAL) or SYNC_DIAGNOSTIC_INTERVAL < 0:
    SYNC_DIAGNOSTIC_INTERVAL = 0.0
fire_mode = "LASER"
KALMAN_CFG = getattr(cfg, "KALMAN", {})
TRACKING_CFG = getattr(cfg, "TRACKING", {})
MAX_TARGET_SPEED_MPS = float(TRACKING_CFG.get("max_target_speed_mps", 3.5))
POSITION_GATE_MARGIN_M = float(TRACKING_CFG.get("position_gate_margin_m", 0.12))
POSITION_GATE_MIN_DT = float(TRACKING_CFG.get("position_gate_min_dt", 0.01))

# ==========================================
# Filters
# ==========================================
class SimpleKalman:
    def __init__(self, q=5e-3, r=2e-2):
        self.q, self.r = q, r
        self.x, self.p = None, 1.0
    def update(self, measurement):
        if self.x is None:
            self.x = measurement
            return self.x
        p_prior = self.p + self.q
        k_gain = p_prior / (p_prior + self.r)
        self.x = self.x + k_gain * (measurement - self.x)
        self.p = (1 - k_gain) * p_prior
        return self.x

def kalman_params(axis, default_q, default_r):
    axis_cfg = KALMAN_CFG.get(axis, {}) if isinstance(KALMAN_CFG, dict) else {}
    try:
        return float(axis_cfg.get("q", default_q)), float(axis_cfg.get("r", default_r))
    except (TypeError, ValueError):
        return default_q, default_r

def make_kalman_filters():
    x_q, x_r = kalman_params("x", 4e-3, 3e-2)
    y_q, y_r = kalman_params("y", 2e-3, 8e-2)
    z_q, z_r = kalman_params("z", 1.5e-3, 6e-2)
    return {
        "x": SimpleKalman(q=x_q, r=x_r),
        "y": SimpleKalman(q=y_q, r=y_r),
        "z": SimpleKalman(q=z_q, r=z_r),
    }

KF_DICT = {name: make_kalman_filters() for name in TARGET_NAMES}
smooth_pred = {name: None for name in TARGET_NAMES}

# ==========================================
# UI layout
# ==========================================
TOTAL_W, TOTAL_H = 1280, 850
FEED_W, FEED_H = 320, 240
MAP_H = TOTAL_H - FEED_H
PANEL_H = TOTAL_H - FEED_H
PANEL_W = 450
MAP_W = TOTAL_W - PANEL_W
MAP_MARGIN = 30
MAP_DRAW_W = MAP_W - (MAP_MARGIN * 2)
MAP_DRAW_H = MAP_H - MAP_MARGIN - 60
SCALE = 200
MAP_BTM_Y = MAP_MARGIN + MAP_DRAW_H
START_X = MAP_MARGIN + (MAP_DRAW_W // 2) - int((CAMERA_SPACING_M * 3) * SCALE // 2)
TURRET_POS = [cfg.PT1_CONFIG["pos_global"][0], cfg.PT2_CONFIG["pos_global"][0]]

# Preallocated canvas
combined_canvas = np.zeros((TOTAL_H, TOTAL_W, 3), dtype=np.uint8)

# Build static top-view background once.
def build_map_bg():
    bg = np.zeros((MAP_H, MAP_W, 3), dtype=np.uint8)
    bg[:] = (25, 25, 25)
    for r in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        y = MAP_BTM_Y - int(r * SCALE)
        if MAP_MARGIN < y < MAP_BTM_Y:
            cv2.line(bg, (MAP_MARGIN, y), (MAP_W - MAP_MARGIN, y), (50, 50, 50), 1)
            cv2.putText(bg, f"{r}m", (MAP_MARGIN + 5, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 100, 100), 1)
    crit_y = MAP_BTM_Y - int(CRITICAL_DIST_M * SCALE)
    if MAP_MARGIN < crit_y < MAP_BTM_Y:
        cv2.line(bg, (MAP_MARGIN, crit_y), (MAP_W - MAP_MARGIN, crit_y), (0, 80, 200), 2)
        cv2.putText(bg, "CRITICAL", (MAP_W - MAP_MARGIN - 80, crit_y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 120, 255), 1)
    cam_y = MAP_BTM_Y
    for i in range(4):
        cx = int(START_X + (i * CAMERA_SPACING_M * SCALE))
        cv2.circle(bg, (cx, cam_y), 5, (0, 180, 80), -1)
        cv2.putText(bg, f"C{i}", (cx - 8, cam_y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (60, 120, 80), 1)
    turret_colors = [(0, 255, 255), (255, 150, 0)]
    for ti in range(2):
        tx = int(START_X + TURRET_POS[ti] * SCALE)
        cv2.circle(bg, (tx, cam_y), 9, turret_colors[ti], 2)
        cv2.circle(bg, (tx, cam_y), 4, turret_colors[ti], -1)
    return bg

def build_panel_bg():
    bg = np.zeros((PANEL_H, PANEL_W, 3), dtype=np.uint8)
    bg[:] = (30, 30, 30)
    cv2.rectangle(bg, (0, 0), (PANEL_W, 40), (45, 45, 45), -1)
    cv2.putText(bg, "TACTICAL CONTROL", (12, 28), cv2.FONT_HERSHEY_DUPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.line(bg, (0, 40), (PANEL_W, 40), (80, 80, 80), 1)
    return bg

map_bg = build_map_bg()
panel_bg = build_panel_bg()

# ==========================================
# ZMQ
# ==========================================
print(">> ZMQ init...")
ctx = zmq.Context()
VIDEO_ENDPOINT = f"tcp://*:{VIDEO_PORT}"
RESULT_ENDPOINT = f"tcp://*:{RESULT_PORT}"
UI_CMD_ENDPOINT = f"tcp://*:{UI_CMD_PORT}"
SENDER_FRAME_KEYS = {
    # rpi1 may operate any logical stereo pair in one-Pi demo mode:
    # 01, 02, 03, 12, 13, or 23.
    "rpi1": {"img0", "img1", "img2", "img3"},
    "rpi2": {"img2", "img3"},
}
try:
    sA = None

    sT = ctx.socket(zmq.PUB)
    sT.setsockopt(zmq.LINGER, 0)
    sT.bind(RESULT_ENDPOINT)
    sT.setsockopt(zmq.SNDHWM, 1)

    sCMD = None
    if ENABLE_DASHBOARD:
        sCMD = ctx.socket(zmq.PULL)
        sCMD.setsockopt(zmq.LINGER, 0)
        sCMD.setsockopt(zmq.RCVHWM, 32)
        sCMD.bind(UI_CMD_ENDPOINT)
    print("   OK")
except zmq.ZMQError as e:
    print(f"   FAIL: {e}")
    ctx.destroy()
    raise SystemExit(1)

def decode_jpeg_frame(raw_frame, flag):
    if isinstance(raw_frame, np.ndarray):
        arr = raw_frame
    else:
        arr = np.frombuffer(raw_frame, dtype=np.uint8)
    return cv2.imdecode(arr, flag)

def encode_dashboard_frame(frame):
    if frame is None:
        return None
    params = [int(cv2.IMWRITE_JPEG_QUALITY), int(np.clip(DASHBOARD_JPEG_QUALITY, 30, 95))]
    ok, encoded = cv2.imencode(".jpg", frame, params)
    if not ok:
        return None
    return encoded.tobytes()

def list_or_none(value):
    if value is None:
        return None
    arr = np.asarray(value, dtype=np.float32).reshape(-1)
    if not np.all(np.isfinite(arr)):
        return None
    return arr.tolist()

def float_or_default(value, default=0.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if np.isfinite(value) else default

def _finite_xy(point):
    if point is None:
        return None
    arr = np.asarray(point, dtype=np.float32).reshape(-1)
    if arr.size < 2 or not np.all(np.isfinite(arr[:2])):
        return None
    return float(arr[0]), float(arr[1])

def _mask_center(results, idx):
    masks = getattr(results, "masks", None)
    polys = getattr(masks, "xy", None)
    if polys is None or idx >= len(polys):
        return None
    poly = np.asarray(polys[idx], dtype=np.float32)
    if poly.ndim != 2 or poly.shape[0] < 3 or poly.shape[1] < 2:
        return None
    try:
        moments = cv2.moments(poly)
    except Exception:
        try:
            moments = cv2.moments(poly.reshape(-1, 1, 2))
        except Exception:
            return _finite_xy(np.mean(poly[:, :2], axis=0))
    if abs(moments["m00"]) > 1e-6:
        return float(moments["m10"] / moments["m00"]), float(moments["m01"] / moments["m00"])
    return _finite_xy(np.mean(poly[:, :2], axis=0))

def _keypoint_center(results, idx):
    keypoints = getattr(results, "keypoints", None)
    xy = getattr(keypoints, "xy", None)
    if xy is None:
        return None
    try:
        pts = xy[idx].detach().cpu().numpy()
    except AttributeError:
        pts = np.asarray(xy[idx], dtype=np.float32)
    except Exception:
        return None
    if pts.ndim != 2 or pts.shape[0] <= 0:
        return None

    conf = getattr(keypoints, "conf", None)
    conf_arr = None
    if conf is not None:
        try:
            conf_arr = conf[idx].detach().cpu().numpy()
        except AttributeError:
            conf_arr = np.asarray(conf[idx], dtype=np.float32)
        except Exception:
            conf_arr = None

    if YOLO_KEYPOINT_INDEX is not None:
        if YOLO_KEYPOINT_INDEX < 0 or YOLO_KEYPOINT_INDEX >= pts.shape[0]:
            return None
        if conf_arr is not None and YOLO_KEYPOINT_INDEX < len(conf_arr) and conf_arr[YOLO_KEYPOINT_INDEX] <= 0.05:
            return None
        return _finite_xy(pts[YOLO_KEYPOINT_INDEX])

    valid = np.all(np.isfinite(pts[:, :2]), axis=1)
    if conf_arr is not None and len(conf_arr) == len(valid):
        valid &= conf_arr > 0.05
    if not np.any(valid):
        return None
    return _finite_xy(np.mean(pts[valid, :2], axis=0))

def yolo_detection_center(results, box, idx):
    if YOLO_CENTER_MODE in ("auto", "keypoint", "pose"):
        center = _keypoint_center(results, idx)
        if center is not None:
            return center[0], center[1], "keypoint"
    if YOLO_CENTER_MODE in ("auto", "mask", "seg", "segment"):
        center = _mask_center(results, idx)
        if center is not None:
            return center[0], center[1], "mask"
    bx, by, bw, bh = [float(v) for v in box.xywh[0].tolist()]
    if YOLO_CENTER_MODE in ("auto", "box_anchor", "anchor", "stable_box"):
        x1 = bx - bw / 2.0
        y1 = by - bh / 2.0
        return x1 + bw * YOLO_BOX_ANCHOR_X, y1 + bh * YOLO_BOX_ANCHOR_Y, "anchor"
    return float(bx), float(by), "box"

def smooth_yolo_centers(cam_idx, centers):
    if not centers:
        return {}
    if YOLO_CENTER_SMOOTH_ALPHA >= 0.999:
        return centers
    state = center_2d_state.setdefault(cam_idx, {})
    out = {}
    for lbl, point in centers.items():
        curr = np.asarray(point, dtype=np.float32)
        prev = state.get(lbl)
        if prev is not None and np.all(np.isfinite(prev)):
            jump = float(np.linalg.norm(curr - prev))
            if jump > YOLO_CENTER_MAX_JUMP_PX:
                curr = prev.copy()
            else:
                curr = prev * (1.0 - YOLO_CENTER_SMOOTH_ALPHA) + curr * YOLO_CENTER_SMOOTH_ALPHA
        state[lbl] = curr
        out[lbl] = (float(curr[0]), float(curr[1]))
    for lbl in list(state):
        if lbl not in centers:
            state.pop(lbl, None)
    return out

def assign_yolo_detections(detections, previous_centers=None):
    if not detections:
        return {}
    if YOLO_ASSIGNMENT == "confidence":
        ranked = sorted(detections, key=lambda d: d[3], reverse=True)
        return {TARGET_NAMES[idx]: (det[0], det[1]) for idx, det in enumerate(ranked[:len(TARGET_NAMES)])}
    if YOLO_ASSIGNMENT == "area":
        ranked = sorted(detections, key=lambda d: d[2], reverse=True)
        return {TARGET_NAMES[idx]: (det[0], det[1]) for idx, det in enumerate(ranked[:len(TARGET_NAMES)])}
    if YOLO_ASSIGNMENT == "tracking":
        remaining = list(detections)
        assigned = {}
        previous = previous_centers if isinstance(previous_centers, dict) else {}
        for lbl in TARGET_NAMES:
            if not remaining:
                break
            prev = previous.get(lbl)
            if prev is not None:
                best_idx = min(
                    range(len(remaining)),
                    key=lambda idx: (remaining[idx][0] - prev[0]) ** 2 + (remaining[idx][1] - prev[1]) ** 2
                )
            else:
                best_idx = max(range(len(remaining)), key=lambda idx: remaining[idx][3])
            det = remaining.pop(best_idx)
            assigned[lbl] = (det[0], det[1])
        return assigned

    ranked = sorted(detections, key=lambda d: d[0])
    return {TARGET_NAMES[idx]: (det[0], det[1]) for idx, det in enumerate(ranked[:len(TARGET_NAMES)])}

def command_to_key(command):
    if isinstance(command, dict):
        key = command.get("key")
        cmd_ts = command.get("ts")
    else:
        key = command
        cmd_ts = None
    if cmd_ts is not None:
        try:
            if time.time() - float(cmd_ts) > DASHBOARD_COMMAND_MAX_AGE:
                return None
        except (TypeError, ValueError):
            return None
    if key is None:
        return None
    key = str(key).strip()
    if not key:
        return None
    if key.lower() in ("esc", "escape"):
        return 27
    if len(key) == 1:
        return ord(key)
    return None

def build_dashboard_packet(cam_feeds, cam_ages, pts_data, t_scores, t_assignments, fps_v, load_v, loop_ms, encode_frames=True, command_targets=None, include_frames=True):
    command_targets = command_targets if isinstance(command_targets, dict) else {}
    frames = {}
    raw_frames = None
    if include_frames:
        if encode_frames:
            for cam_idx, feed in enumerate(cam_feeds):
                frames[f"cam{cam_idx}"] = encode_dashboard_frame(feed)
        else:
            raw_frames = [feed.copy() if feed is not None else None for feed in cam_feeds]

    targets = {}
    for lbl in TARGET_NAMES:
        curr, pred = pts_data.get(lbl, (None, None))
        command_info = command_targets.get(lbl) if isinstance(command_targets.get(lbl), dict) else {}
        raw_pos = list_or_none(curr)
        raw_pred = list_or_none(pred)
        aim_requested = bool(command_info.get("aim", False)) if command_info else False
        command_pos = list_or_none(command_info.get("pos")) if command_info and aim_requested else None
        aim = aim_requested and command_pos is not None
        status = command_info.get("status", target_status.get(lbl, "IDLE")) if command_info else target_status.get(lbl, "IDLE")
        threat = command_info.get("threat", t_scores.get(lbl, 0.0)) if command_info else t_scores.get(lbl, 0.0)
        targets[lbl] = {
            "status": status,
            "pos": raw_pos,
            "pred": raw_pred,
            "raw_pos": raw_pos,
            "raw_pred": raw_pred,
            "command_pos": command_pos,
            "aim": aim,
            "stale_age": float_or_default(command_info.get("stale_age", 0.0), 0.0) if command_info else 0.0,
            "threat": float_or_default(threat, 0.0),
        }

    packet = {
        "schema": "aegis_dashboard_v1",
        "ts": time.time(),
        "mode": DETECT_MODE,
        "fire_mode": fire_mode,
        "target_count": TARGET_COUNT,
        "targets": targets,
        "stats": {
            "fps": float_or_default(fps_v, 0.0),
            "load": float_or_default(load_v, 0.0),
            "loop_ms": float_or_default(loop_ms, 0.0),
            "cam_ages": [float_or_default(x, 1e9) for x in cam_ages],
            "imgsz": int(_YOLO_IMGSZ),
            "max_det": int(YOLO_MAX_DET),
            "task": "auto" if _YOLO_TASK is None else str(_YOLO_TASK),
        },
        "turrets": {
            "pt1_target": t_assignments.get(0),
            "pt2_target": t_assignments.get(1),
            "trims": {name: values[:] for name, values in calib_trims.items()},
        },
        "frames": frames,
    }
    if raw_frames is not None:
        packet["_raw_frames"] = raw_frames
    return packet

def encode_dashboard_snapshot(packet):
    raw_frames = packet.pop("_raw_frames", None)
    if raw_frames is not None:
        packet["frames"] = {
            f"cam{cam_idx}": encode_dashboard_frame(feed)
            for cam_idx, feed in enumerate(raw_frames)
        }
    return packet

class DashboardPublisher:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.pending = None
        self.lock = threading.Lock()
        self.event = threading.Event()
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, name="dashboard-publisher", daemon=True)
        self.thread.start()

    def submit(self, packet):
        with self.lock:
            self.pending = packet
        self.event.set()

    def stop(self):
        self.running = False
        self.event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)

    def _run(self):
        pub_ctx = zmq.Context.instance()
        sock = pub_ctx.socket(zmq.PUB)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.SNDHWM, 1)
        try:
            sock.bind(self.endpoint)
        except zmq.ZMQError as e:
            print(f"!! dashboard publisher disabled: {e}")
            self.running = False
            sock.close()
            return

        while self.running:
            self.event.wait(0.05)
            self.event.clear()
            with self.lock:
                packet = self.pending
                self.pending = None
            if packet is None:
                continue
            try:
                encoded = encode_dashboard_snapshot(packet)
                sock.send(pickle.dumps(encoded, protocol=pickle.HIGHEST_PROTOCOL), zmq.NOBLOCK)
            except zmq.Again:
                pass
            except Exception as e:
                print(f"!! dashboard publish skipped: {type(e).__name__}: {e}")
        sock.close()

dashboard_pub = None
if ENABLE_DASHBOARD:
    dashboard_pub = DashboardPublisher(f"tcp://*:{UI_PORT}")
    dashboard_pub.start()

_runtime_resolution_warned = set()
_sender_pair_dt_warned = {}

def packet_stream_size(pkt, sender_id="unknown"):
    width = pkt.get("width")
    height = pkt.get("height")
    if width is None or height is None:
        key = (sender_id, "missing")
        if key not in _runtime_resolution_warned:
            print(f"!! drop packet from {sender_id}: missing stream width/height metadata")
            _runtime_resolution_warned.add(key)
        return None
    try:
        size = (int(width), int(height))
    except (TypeError, ValueError):
        key = (sender_id, "invalid", str(width), str(height))
        if key not in _runtime_resolution_warned:
            print(f"!! drop packet from {sender_id}: invalid stream size {width}x{height}")
            _runtime_resolution_warned.add(key)
        return None
    return size


def runtime_packet_resolution_ok(pkt, sender_id):
    if not STRICT_STREAM_RESOLUTION:
        return True

    size = packet_stream_size(pkt, sender_id)
    if size is None:
        return False

    if size not in SUPPORTED_STREAM_SIZES:
        key = (sender_id, size)
        if key not in _runtime_resolution_warned:
            supported = ", ".join(f"{w}x{h}" for w, h in sorted(SUPPORTED_STREAM_SIZES))
            print(
                f"!! drop packet from {sender_id}: stream {size[0]}x{size[1]} "
                f"is not in supported stream sizes [{supported}] for calibration {SRC_W}x{SRC_H}"
            )
            _runtime_resolution_warned.add(key)
        return False
    return True


def runtime_packet_pair_dt_ok(pkt, sender_id):
    raw_dt = pkt.get("pair_dt_s", pkt.get("pair_dt"))
    if raw_dt is None:
        return True
    try:
        pair_dt = float(raw_dt)
    except (TypeError, ValueError):
        return False
    if not np.isfinite(pair_dt) or pair_dt < 0:
        return False
    if pair_dt <= SENDER_PAIR_MAX_DT:
        return True

    # Same-sender CSI slips should not freeze both video feeds. Keep the packet
    # and let per-camera timestamps plus pair_sync_weight reject or down-weight
    # bad triangulation pairs later.
    now = time.time()
    last_warn = _sender_pair_dt_warned.get(sender_id, 0.0)
    if now - last_warn > 2.0:
        print(
            f"!! warn packet from {sender_id}: same-sender pair_dt "
            f"{pair_dt:.3f}s > {SENDER_PAIR_MAX_DT:.3f}s; keeping frames"
        )
        _sender_pair_dt_warned[sender_id] = now
    return True


def decoded_frame_resolution_ok(decoded, sender_id, frame_key, decode_flag, stream_size=None):
    if decoded is None or not STRICT_STREAM_RESOLUTION:
        return True
    dec_h, dec_w = decoded.shape[:2]
    src_size = stream_size if stream_size in SUPPORTED_STREAM_SIZES else (SRC_W, SRC_H)
    src_w, src_h = int(src_size[0]), int(src_size[1])
    if decode_flag == cv2.IMREAD_REDUCED_COLOR_2:
        exp_w = (src_w + 1) // 2
        exp_h = (src_h + 1) // 2
    else:
        exp_w, exp_h = src_w, src_h
    if (dec_w, dec_h) == (exp_w, exp_h):
        return True
    key = (sender_id, frame_key, "decoded", dec_w, dec_h, "stream", src_w, src_h)
    if key not in _runtime_resolution_warned:
        print(
            f"!! drop {frame_key} from {sender_id}: decoded frame {dec_w}x{dec_h} "
            f"but expected {exp_w}x{exp_h} from stream {src_w}x{src_h} for calibration {SRC_W}x{SRC_H}"
        )
        _runtime_resolution_warned.add(key)
    return False

# ==========================================
# Stereo triangulation helpers
# ==========================================
def get_3d_global_corrected(ptL, ptR, idxL, idxR):
    if idxL < idxR:
        pair_key, pts_1, pts_2 = (idxL, idxR), ptL, ptR
    else:
        pair_key, pts_1, pts_2 = (idxR, idxL), ptR, ptL
    if pair_key not in CALIB_DATA:
        return None
    cal = CALIB_DATA[pair_key]

    point_base = triangulate_in_base_camera(cal, pts_1, pts_2)
    pose = camera_to_cam0_pose(pair_key[0])
    if point_base is not None and pose is not None:
        r_base0, t_base0 = pose
        point_cam0 = r_base0 @ point_base + t_base0
        return camera0_to_world(point_cam0)

    p1_in = np.array([[[pts_1[0], pts_1[1]]]], dtype=np.float32)
    p2_in = np.array([[[pts_2[0], pts_2[1]]]], dtype=np.float32)
    try:
        rect_p1 = cv2.undistortPoints(p1_in, cal['K1'], cal['D1'], R=cal['R1'], P=cal['P1'])
        rect_p2 = cv2.undistortPoints(p2_in, cal['K2'], cal['D2'], R=cal['R2'], P=cal['P2'])
    except Exception:
        return None
    point4D = cv2.triangulatePoints(cal['P1'], cal['P2'], rect_p1, rect_p2)
    w = float(point4D[3, 0])
    if not np.isfinite(w) or abs(w) < 1e-6:
        return None
    point3D = point4D[:3] / w
    if not np.all(np.isfinite(point3D)):
        return None
    x_cam, y_cam, z_cam = point3D[0][0], point3D[1][0], point3D[2][0]
    base_cam = pair_key[0]
    offset_x = 0.0
    if base_cam > 0:
        pair_to_origin = (0, base_cam)
        if pair_to_origin in CALIB_DATA:
            baseline = _calibration_baseline_m(CALIB_DATA[pair_to_origin])
            offset_x = baseline if baseline is not None else CAMERA_SPACING_M * base_cam
        else:
            for b in range(base_cam):
                pk = (b, b + 1)
                if pk in CALIB_DATA:
                    baseline = _calibration_baseline_m(CALIB_DATA[pk])
                    offset_x += baseline if baseline is not None else CAMERA_SPACING_M
                else:
                    offset_x += CAMERA_SPACING_M
    return camera0_to_world([x_cam + offset_x, y_cam, z_cam])


# =========================================================
# Single-camera fallback tracking
#
# When only one camera sees the target, true stereo depth is
# unavailable. Keep the last valid stereo Z and intersect the
# current camera ray with that constant-Z plane.
#
# If no stereo lock has ever existed, use 0.55 m as the
# temporary demo depth.
# =========================================================
MONO_FALLBACK_DEFAULT_Z = 0.55
MONO_FALLBACK_MIN_Z = 0.25
MONO_FALLBACK_MAX_Z = 2.20


def _camera_intrinsics_for_index(cam_idx):
    cam_idx = int(cam_idx)

    for (a, b), cal in CALIB_DATA.items():
        if cam_idx == a:
            try:
                return (
                    np.asarray(cal["K1"], dtype=np.float64),
                    np.asarray(cal["D1"], dtype=np.float64),
                )
            except Exception:
                pass

        if cam_idx == b:
            try:
                return (
                    np.asarray(cal["K2"], dtype=np.float64),
                    np.asarray(cal["D2"], dtype=np.float64),
                )
            except Exception:
                pass

    return None, None


def single_camera_world_at_depth(cam_idx, pixel_xy, z_world):
    """
    Back-project one image point into a world-space ray and
    intersect it with the plane world-Z = z_world.

    This is a fallback, not true stereo depth estimation.
    """
    k, d = _camera_intrinsics_for_index(cam_idx)
    if k is None:
        return None

    pose = camera_to_cam0_pose(cam_idx)
    if pose is None:
        return None

    try:
        px = np.array(
            [[[float(pixel_xy[0]), float(pixel_xy[1])]]],
            dtype=np.float64
        )

        und = cv2.undistortPoints(px, k, d).reshape(2)

        ray_cam = np.array(
            [float(und[0]), float(und[1]), 1.0],
            dtype=np.float64
        )

        r_cam0, t_cam0 = pose

        origin_cam0 = np.asarray(
            t_cam0, dtype=np.float64
        ).reshape(3)

        direction_cam0 = (
            np.asarray(r_cam0, dtype=np.float64) @ ray_cam
        ).reshape(3)

        # camera0_to_world is a linear orientation transform.
        origin_world = camera0_to_world(origin_cam0)
        direction_world = camera0_to_world(direction_cam0)

        dz = float(direction_world[2])
        if not np.isfinite(dz) or abs(dz) < 1e-8:
            return None

        z_world = float(np.clip(
            z_world,
            MONO_FALLBACK_MIN_Z,
            MONO_FALLBACK_MAX_Z
        ))

        ray_t = (
            z_world - float(origin_world[2])
        ) / dz

        if not np.isfinite(ray_t) or ray_t <= 0.0:
            return None

        point = origin_world + direction_world * ray_t

        if not np.all(np.isfinite(point)):
            return None

        return np.asarray(point, dtype=np.float64)

    except Exception:
        return None


def rectified_y_residual(ptL, ptR, idxL, idxR):
    if idxL < idxR:
        pair_key, pts_1, pts_2 = (idxL, idxR), ptL, ptR
    else:
        pair_key, pts_1, pts_2 = (idxR, idxL), ptR, ptL
    if pair_key not in CALIB_DATA:
        return None
    cal = CALIB_DATA[pair_key]
    p1_in = np.array([[[pts_1[0], pts_1[1]]]], dtype=np.float32)
    p2_in = np.array([[[pts_2[0], pts_2[1]]]], dtype=np.float32)
    try:
        rect_p1 = cv2.undistortPoints(p1_in, cal["K1"], cal["D1"], R=cal["R1"], P=cal["P1"])
        rect_p2 = cv2.undistortPoints(p2_in, cal["K2"], cal["D2"], R=cal["R2"], P=cal["P2"])
        residual = abs(float(rect_p1[0, 0, 1]) - float(rect_p2[0, 0, 1]))
    except Exception:
        return None
    return residual if np.isfinite(residual) else None

def calculate_threat_level(pos, vel):
    distance = max(pos[2], 0.3)
    velocity = np.linalg.norm(vel) if vel is not None else 0.0
    return (1.0 / distance) * (1.0 + velocity * 2.0) * (2.0 if distance < CRITICAL_DIST_M else 1.0)

def compute_lead_shot(curr_3d, velocity_mps, distance_m):
    speed = float(np.linalg.norm(velocity_mps))
    if fire_mode == "LASER":
        speed_factor = min(1.35, 1.0 + speed * 0.08)
        t_total = SYSTEM_DELAY * speed_factor
    else:
        t_total = SYSTEM_DELAY + distance_m / SONIC_SPEED
    lead = velocity_mps * t_total
    lead_dist = np.linalg.norm(lead)
    if lead_dist > MAX_LEAD_DIST:
        lead = (lead / lead_dist) * MAX_LEAD_DIST
    return curr_3d + lead

def build_target_output(curr_3d, pred_3d, threat, status, stale_age, aim):
    if curr_3d is not None and pred_3d is not None:
        final_target = np.asarray(curr_3d, dtype=np.float32) + (
            np.asarray(pred_3d, dtype=np.float32) - np.asarray(curr_3d, dtype=np.float32)
        ) * COMMAND_LEAD_RATIO
    else:
        final_target = pred_3d if pred_3d is not None else curr_3d
    command_pos = None
    if final_target is not None:
        command_pos = np.asarray(final_target, dtype=np.float32).copy()
        command_pos[1] += CAM_HEIGHT_M
        command_pos[2] *= Z_SCALE
    command_pos_list = list_or_none(command_pos)
    return {
        "pos": command_pos_list,
        "raw_pos": list_or_none(curr_3d),
        "raw_pred": list_or_none(pred_3d),
        "threat": float_or_default(threat, 0.0),
        "status": status,
        "stale_age": float_or_default(stale_age, 0.0),
        "aim": bool(aim) and command_pos_list is not None,
    }

# ==========================================
# Top-view UI drawing
# ==========================================
def draw_topview_dynamic(pts_data, threat_scores, t_assignments):
    top = map_bg.copy()
    cam_y = MAP_BTM_Y
    turret_colors = [(0, 255, 255), (255, 150, 0)]

    for lbl, (curr, pred) in pts_data.items():
        if curr is None:
            continue
        status = target_status.get(lbl, "IDLE")
        color = VISUAL_COLORS.get(lbl, (255, 255, 255))
        if status == "CRITICAL":
            color = (0, 0, 255)
        mx = int(START_X + curr[0] * SCALE)
        my = int(MAP_BTM_Y - curr[2] * SCALE)
        dist = curr[2]
        sz = max(6, min(20, int(50 / max(dist, 0.5))))
        cv2.circle(top, (mx, my), sz, color, -1)
        cv2.circle(top, (mx, my), sz + 3, (255, 255, 255), 2)
        if pred is not None:
            px = int(START_X + pred[0] * SCALE)
            py = int(MAP_BTM_Y - pred[2] * SCALE)
            cv2.arrowedLine(top, (mx, my), (px, py), color, 2, tipLength=0.3)
        tnum = lbl.split('_')[1]
        # Mark targets that are currently held by Track Hold.
        if status == "HELD":
            cv2.putText(top, f"T{tnum}(H)", (mx - 12, my - sz - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 255), 1)
        else:
            cv2.putText(top, f"T{tnum}", (mx - 8, my - sz - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    for ti, tgt in t_assignments.items():
        if tgt is None or tgt not in pts_data:
            continue
        curr, pred = pts_data[tgt]
        if curr is None:
            continue
        tx = int(START_X + TURRET_POS[ti] * SCALE)
        tp = pred if pred is not None else curr
        tgx = int(START_X + tp[0] * SCALE)
        tgy = int(MAP_BTM_Y - tp[2] * SCALE)
        cv2.line(top, (tx, cam_y), (tgx, tgy), turret_colors[ti], 1)
        cv2.circle(top, (tgx, tgy), 15, turret_colors[ti], 1)

    return top


def draw_panel_dynamic(pts_data, t_scores, fps_v, load_v, cam_ages, loop_ms):
    p = panel_bg.copy()
    y = 55
    lg = 20
    fs = 0.38  # Compact font scale

    # System status
    cv2.putText(p, "SYSTEM", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1); y += 22
    cv2.putText(p, f"FPS:{fps_v:.0f} Load:{load_v:.0f}% Loop:{loop_ms:.0f}ms", (20, y), cv2.FONT_HERSHEY_SIMPLEX, fs, (200, 200, 200), 1); y += lg
    uptime = time.time() - system_stats['start_time']
    cv2.putText(p, f"Up:{int(uptime//60)}:{int(uptime%60):02d}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, fs, (180, 180, 180), 1); y += lg

    mode_c = (0, 255, 0) if fire_mode == "LASER" else (0, 180, 255)
    mode_t = "LASER" if fire_mode == "LASER" else f"SONIC({SONIC_SPEED:.0f})"
    cv2.putText(p, f"Mode: {mode_t}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, fs, mode_c, 1); y += lg
    detect_c = (0, 255, 80) if DETECT_MODE == "YOLO" else (200, 200, 0)
    cv2.putText(p, f"Detect: {DETECT_MODE}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, fs, detect_c, 1); y += 5
    cv2.line(p, (12, y), (PANEL_W - 12, y), (60, 60, 60), 1); y += 18

    # Cam ages
    cv2.putText(p, "CAM AGE", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1); y += 18
    age_txt = " ".join([f"C{i}:{cam_ages[i]*1000:.0f}ms" if cam_ages[i] < 10 else f"C{i}:--" for i in range(4)])
    age_color = (100, 255, 100)          # Fresh frames: green
    if any(0.25 < a < 10 for a in cam_ages):
        age_color = (0, 0, 255)          # Stale frames: red (>250 ms)
    elif any(0.1 < a < 10 for a in cam_ages):
        age_color = (0, 200, 255)        # Aging frames: amber (100-250 ms)
    cv2.putText(p, age_txt, (20, y), cv2.FONT_HERSHEY_SIMPLEX, fs, age_color, 1); y += 5
    cv2.line(p, (12, y), (PANEL_W - 12, y), (60, 60, 60), 1); y += 18

    # Targets
    cv2.putText(p, "TARGETS", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1); y += 22
    for idx, (lbl, st) in enumerate(target_status.items()):
        cy = y + idx * 60
        tnum = lbl.split('_')[1]
        color = VISUAL_COLORS.get(lbl, (255, 255, 255))
        threat = t_scores.get(lbl, 0.0)
        cv2.circle(p, (22, cy - 4), 5, color, -1)
        cv2.putText(p, f"T{tnum}", (35, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1)
        tc = (0, 0, 255) if threat > 1.0 else (100, 255, 100)
        cv2.putText(p, f"Thr:{threat:.1f}", (75, cy), cv2.FONT_HERSHEY_SIMPLEX, fs, tc, 1)
        sc = (0, 200, 255) if st == "HELD" else ((0, 0, 255) if st == "CRITICAL" else (150, 255, 150))
        cv2.putText(p, st, (155, cy), cv2.FONT_HERSHEY_SIMPLEX, fs, sc, 1)
        if lbl in pts_data and pts_data[lbl][0] is not None:
            pos = pts_data[lbl][0]
            cv2.putText(p, f"X:{pos[0]:.2f} Z:{pos[2]:.2f}m", (35, cy + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 150, 150), 1)
        else:
            cv2.putText(p, "NO SIGNAL", (35, cy + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80, 80, 80), 1)

    y += 130
    cv2.line(p, (12, y), (PANEL_W - 12, y), (60, 60, 60), 1); y += 18
    cv2.putText(p, "TURRETS", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1); y += 22
    tc = [(0, 255, 255), (255, 150, 0)]
    cv2.circle(p, (22, y), 5, tc[0], -1)
    cv2.putText(p, f"T1->{turret_assignments.get(0,'--')}", (32, y+4), cv2.FONT_HERSHEY_SIMPLEX, fs, tc[0], 1)
    cv2.circle(p, (195, y), 5, tc[1], -1)
    cv2.putText(p, f"T2->{turret_assignments.get(1,'--')}", (205, y+4), cv2.FONT_HERSHEY_SIMPLEX, fs, tc[1], 1)
    y += 22
    cv2.line(p, (12, y), (PANEL_W - 12, y), (60, 60, 60), 1); y += 18

    cv2.putText(p, "TRIM", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 200, 0), 1); y += 20
    cv2.putText(p, f"T1:P{calib_trims['pt1'][0]:+.0f} T{calib_trims['pt1'][1]:+.0f} | T2:P{calib_trims['pt2'][0]:+.0f} T{calib_trims['pt2'][1]:+.0f}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, fs, (200, 200, 200), 1)
    y += 22
    cv2.line(p, (12, y), (PANEL_W - 12, y), (60, 60, 60), 1); y += 18
    cv2.putText(p, "[WASD]T1 [IJKL]T2 [M]Mode [T]HSV/YOLO", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (160, 160, 160), 1); y += 16
    cv2.putText(p, "[0]Reset [R]Track [ESC]Exit", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (160, 160, 160), 1)

    return p

# ==========================================
# Modern UI drawing
# ==========================================
# Modern single-target UI override. Control math keeps using the filtered
# tracking state above; this layer only stabilizes and simplifies what is drawn.
UI_BG = (27, 22, 18)
UI_SURFACE = (40, 33, 27)
UI_SURFACE_2 = (49, 41, 34)
UI_LINE = (76, 64, 54)
UI_TEXT = (244, 238, 232)
UI_MUTED = (166, 152, 139)
UI_ACCENT = (176, 215, 32)
UI_ACCENT_2 = (210, 170, 54)
UI_WARN = (45, 171, 245)
UI_DANGER = (72, 86, 245)
UI_GREEN = (112, 220, 128)
UI_SMOOTH_ALPHA = float(UI_CFG.get("smooth_alpha", 0.75))
UI_PRED_ALPHA = float(UI_CFG.get("pred_alpha", 0.55))
UI_DEADBAND_M = float(UI_CFG.get("deadband_m", 0.003))
UI_SNAP_M = float(UI_CFG.get("snap_m", 0.25))
ui_display_state = {name: {"curr": None, "pred": None} for name in TARGET_NAMES}

def rounded_rect(img, x1, y1, x2, y2, color, radius=8, thickness=-1, border=None):
    radius = int(max(1, min(radius, (x2 - x1) // 2, (y2 - y1) // 2)))
    if thickness < 0:
        cv2.rectangle(img, (x1 + radius, y1), (x2 - radius, y2), color, -1)
        cv2.rectangle(img, (x1, y1 + radius), (x2, y2 - radius), color, -1)
        cv2.circle(img, (x1 + radius, y1 + radius), radius, color, -1)
        cv2.circle(img, (x2 - radius, y1 + radius), radius, color, -1)
        cv2.circle(img, (x1 + radius, y2 - radius), radius, color, -1)
        cv2.circle(img, (x2 - radius, y2 - radius), radius, color, -1)
    else:
        cv2.rectangle(img, (x1 + radius, y1), (x2 - radius, y2), color, thickness)
        cv2.rectangle(img, (x1, y1 + radius), (x2, y2 - radius), color, thickness)
        cv2.circle(img, (x1 + radius, y1 + radius), radius, color, thickness)
        cv2.circle(img, (x2 - radius, y1 + radius), radius, color, thickness)
        cv2.circle(img, (x1 + radius, y2 - radius), radius, color, thickness)
        cv2.circle(img, (x2 - radius, y2 - radius), radius, color, thickness)
    if border is not None:
        cv2.rectangle(img, (x1, y1), (x2, y2), border, 1)

def soft_box(img, x1, y1, x2, y2, color):
    cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), color, -1)

def put_text(img, text, x, y, scale=0.45, color=UI_TEXT, thickness=1):
    cv2.putText(img, str(text), (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, thickness, cv2.LINE_AA)

def status_color(status):
    if status == "LOCKED":
        return UI_GREEN
    if status == "HELD":
        return UI_WARN
    if status == "CRITICAL":
        return UI_DANGER
    return UI_MUTED

def smooth_vec(prev, current, alpha):
    if current is None:
        return None
    curr = np.asarray(current, dtype=np.float32)
    if prev is None:
        return curr.copy()
    delta = float(np.linalg.norm(curr - prev))
    if delta < UI_DEADBAND_M:
        return prev.copy()
    if delta > UI_SNAP_M:
        return curr.copy()
    return prev + (curr - prev) * alpha

def smooth_ui_points(pts_data, state_store=None):
    if state_store is None:
        state_store = ui_display_state
    out = {}
    for lbl, pair in pts_data.items():
        curr, pred = pair
        state = state_store.setdefault(lbl, {"curr": None, "pred": None})
        state["curr"] = smooth_vec(state["curr"], curr, UI_SMOOTH_ALPHA)
        state["pred"] = smooth_vec(state["pred"], pred, UI_PRED_ALPHA)
        out[lbl] = (state["curr"], state["pred"])
    for lbl in list(state_store.keys()):
        if lbl not in pts_data:
            state_store[lbl] = {"curr": None, "pred": None}
    return out

def build_map_bg():
    bg = np.zeros((MAP_H, MAP_W, 3), dtype=np.uint8)
    bg[:] = UI_BG
    rounded_rect(bg, 18, 18, MAP_W - 18, MAP_H - 18, UI_SURFACE, radius=10, border=UI_LINE)
    put_text(bg, "FIELD VIEW", 38, 50, 0.58, UI_TEXT, 1)
    put_text(bg, "3D triangulation | single target", 158, 50, 0.38, UI_MUTED, 1)

    plot_l, plot_r = 42, MAP_W - 42
    plot_t, plot_b = 76, MAP_BTM_Y
    cv2.rectangle(bg, (plot_l, plot_t), (plot_r, plot_b), (33, 27, 22), -1)
    cv2.rectangle(bg, (plot_l, plot_t), (plot_r, plot_b), UI_LINE, 1)

    for r in [0.5, 1.0, 1.5, 2.0, 2.5]:
        y = MAP_BTM_Y - int(r * SCALE)
        if plot_t < y < plot_b:
            cv2.line(bg, (plot_l, y), (plot_r, y), (61, 51, 42), 1)
            put_text(bg, f"{r:.1f}m", plot_l + 10, y - 7, 0.34, UI_MUTED, 1)

    center_x = int(START_X + (CAMERA_SPACING_M * 1.5) * SCALE)
    cv2.line(bg, (center_x, plot_t), (center_x, plot_b), (67, 58, 45), 1)
    crit_y = MAP_BTM_Y - int(CRITICAL_DIST_M * SCALE)
    if plot_t < crit_y < plot_b:
        cv2.line(bg, (plot_l, crit_y), (plot_r, crit_y), UI_WARN, 1)
        put_text(bg, "critical range", plot_r - 118, crit_y - 8, 0.34, UI_WARN, 1)

    cam_y = MAP_BTM_Y
    for i in range(4):
        cx = int(START_X + (i * CAMERA_SPACING_M * SCALE))
        rounded_rect(bg, cx - 13, cam_y - 18, cx + 13, cam_y + 8, (48, 42, 32), radius=6)
        cv2.circle(bg, (cx, cam_y - 5), 4, UI_ACCENT, -1)
        put_text(bg, f"C{i}", cx - 10, cam_y + 28, 0.34, UI_MUTED, 1)

    for ti, col in enumerate([UI_ACCENT, UI_ACCENT_2]):
        tx = int(START_X + TURRET_POS[ti] * SCALE)
        cv2.circle(bg, (tx, cam_y - 5), 12, col, 1)
        cv2.circle(bg, (tx, cam_y - 5), 4, col, -1)
        put_text(bg, f"PT{ti + 1}", tx - 15, cam_y - 26, 0.34, col, 1)
    return bg

def build_panel_bg():
    bg = np.zeros((PANEL_H, PANEL_W, 3), dtype=np.uint8)
    bg[:] = UI_BG
    rounded_rect(bg, 14, 18, PANEL_W - 14, PANEL_H - 18, UI_SURFACE, radius=10, border=UI_LINE)
    put_text(bg, "AEGIS CONTROL", 32, 50, 0.62, UI_TEXT, 1)
    put_text(bg, "AI bird tracking | decision support", 32, 73, 0.38, UI_MUTED, 1)
    return bg

map_bg = build_map_bg()
panel_bg = build_panel_bg()

def draw_topview_dynamic(pts_data, threat_scores, t_assignments, t_status=None):
    if t_status is None:
        t_status = target_status  # fallback for dashboard
    top = map_bg.copy()
    cam_y = MAP_BTM_Y - 5

    for ti, tgt in t_assignments.items():
        if tgt is None or tgt not in pts_data:
            continue
        curr, pred = pts_data[tgt]
        if curr is None:
            continue
        col = [UI_ACCENT, UI_ACCENT_2][ti]
        tx = int(START_X + TURRET_POS[ti] * SCALE)
        tp = pred if pred is not None else curr
        tgx = int(START_X + float(tp[0]) * SCALE)
        tgy = int(MAP_BTM_Y - float(tp[2]) * SCALE)
        cv2.line(top, (tx, cam_y), (tgx, tgy),
                 (int(col[0] * 0.65), int(col[1] * 0.65), int(col[2] * 0.65)), 1, cv2.LINE_AA)

    for lbl, (curr, pred) in pts_data.items():
        if curr is None:
            continue
        status = t_status.get(lbl, "IDLE")
        col = status_color(status)
        mx = int(START_X + float(curr[0]) * SCALE)
        my = int(MAP_BTM_Y - float(curr[2]) * SCALE)
        mx = int(np.clip(mx, 48, MAP_W - 48))
        my = int(np.clip(my, 82, MAP_BTM_Y - 10))
        dist = max(float(curr[2]), 0.3)
        radius = max(8, min(18, int(42 / dist)))

        cv2.circle(top, (mx, my), radius + 9, (55, 47, 37), -1, cv2.LINE_AA)
        cv2.circle(top, (mx, my), radius + 9, col, 1, cv2.LINE_AA)
        cv2.circle(top, (mx, my), radius, col, -1, cv2.LINE_AA)
        cv2.circle(top, (mx, my), 3, (255, 255, 255), -1, cv2.LINE_AA)

        if pred is not None:
            lead = float(np.linalg.norm(np.asarray(pred) - np.asarray(curr)))
            if lead > 0.04:
                px = int(START_X + float(pred[0]) * SCALE)
                py = int(MAP_BTM_Y - float(pred[2]) * SCALE)
                px = int(np.clip(px, 48, MAP_W - 48))
                py = int(np.clip(py, 82, MAP_BTM_Y - 10))
                cv2.arrowedLine(top, (mx, my), (px, py), (82, 146, 154), 1, cv2.LINE_AA, tipLength=0.18)
                cv2.circle(top, (px, py), 7, (82, 146, 154), 1, cv2.LINE_AA)

        badge_w = 118 if status != "IDLE" else 92
        soft_box(top, mx + 16, my - 30, mx + 16 + badge_w, my + 4, (43, 36, 29))
        put_text(top, status, mx + 28, my - 11, 0.38, col, 1)
        put_text(top, f"{dist:.2f}m", mx + 28, my + 18, 0.36, UI_TEXT, 1)
    return top

def draw_metric_card(img, x, y, w, h, title, value, sub="", color=UI_TEXT):
    rounded_rect(img, x, y, x + w, y + h, UI_SURFACE_2, radius=8)
    put_text(img, title, x + 12, y + 22, 0.34, UI_MUTED, 1)
    put_text(img, value, x + 12, y + 52, 0.68, color, 1)
    if sub:
        put_text(img, sub, x + 12, y + h - 13, 0.32, UI_MUTED, 1)

def draw_panel_dynamic(pts_data, t_scores, fps_v, load_v, cam_ages, loop_ms, t_status=None, t_assignments=None):
    if t_status is None:
        t_status = target_status
    if t_assignments is None:
        t_assignments = turret_assignments

    p = panel_bg.copy()

    # -----------------------------------------------------
    # Runtime metrics
    # -----------------------------------------------------
    y = 90
    draw_metric_card(
        p, 32, y, 118, 72,
        "FPS", f"{fps_v:.0f}", "camera stream", UI_ACCENT
    )
    draw_metric_card(
        p, 164, y, 118, 72,
        "LOOP", f"{loop_ms:.0f}ms", "fusion loop", UI_TEXT
    )
    draw_metric_card(
        p, 296, y, 118, 72,
        "MODE", DETECT_MODE, f"{_YOLO_IMGSZ}px",
        UI_GREEN if DETECT_MODE == "YOLO" else UI_WARN
    )

    # -----------------------------------------------------
    # Target lock
    # -----------------------------------------------------
    y = 176
    rounded_rect(
        p, 32, y, PANEL_W - 32, y + 116,
        UI_SURFACE_2, radius=9
    )

    lbl = TARGET_NAMES[0] if TARGET_NAMES else "Target_1"
    curr, pred = pts_data.get(lbl, (None, None))
    status = t_status.get(lbl, "IDLE")
    status_col = status_color(status)
    threat = float(t_scores.get(lbl, 0.0))

    put_text(p, "TARGET LOCK", 48, y + 27, 0.40, UI_MUTED, 1)

    soft_box(
        p,
        PANEL_W - 142, y + 13,
        PANEL_W - 48, y + 40,
        (42, 35, 28)
    )
    put_text(
        p, status,
        PANEL_W - 124, y + 33,
        0.38, status_col, 1
    )

    if curr is not None:
        put_text(
            p, f"{float(curr[2]):.2f} m",
            48, y + 67,
            0.82, UI_TEXT, 1
        )
        put_text(
            p,
            f"X {float(curr[0]):+.2f} m   Y {float(curr[1]):+.2f} m",
            50, y + 94,
            0.39, UI_MUTED, 1
        )
        put_text(
            p, f"threat {threat:.2f}",
            50, y + 112,
            0.35,
            UI_WARN if threat > 1.0 else UI_GREEN,
            1
        )
    else:
        put_text(
            p, "NO SIGNAL",
            48, y + 68,
            0.68, UI_MUTED, 1
        )
        put_text(
            p, "waiting for calibrated 3D lock",
            50, y + 96,
            0.36, UI_MUTED, 1
        )

    # -----------------------------------------------------
    # AI decision support
    #
    # IMPORTANT:
    # TRACK RISK v0 = current distance/velocity based prototype.
    # Species / acoustic / RC car are intentionally marked NEXT.
    # -----------------------------------------------------
    y = 304
    rounded_rect(
        p, 32, y, PANEL_W - 32, y + 150,
        UI_SURFACE_2, radius=9
    )

    put_text(
        p, "AI DECISION SUPPORT",
        48, y + 25,
        0.40, UI_MUTED, 1
    )

    has_target = curr is not None

    if status == "CRITICAL" or threat >= 3.0:
        risk_text = "CRITICAL"
        risk_col = UI_DANGER
    elif threat >= 1.5:
        risk_text = "HIGH"
        risk_col = UI_WARN
    elif threat >= 0.8:
        risk_text = "ELEVATED"
        risk_col = UI_ACCENT_2
    else:
        risk_text = "LOW"
        risk_col = UI_GREEN

    if not has_target:
        risk_text = "--"
        risk_col = UI_MUTED

    assigned = any(
        target_name == lbl
        for target_name in t_assignments.values()
    )

    object_text = (
        "BIRD"
        if DETECT_MODE == "YOLO" and has_target
        else "HSV TARGET"
        if DETECT_MODE == "HSV" and has_target
        else "--"
    )

    response_text = (
        "TURRET TRACK"
        if has_target and assigned
        else "MONITOR"
        if has_target
        else "--"
    )

    # OBJECT
    put_text(p, "OBJECT", 48, y + 52, 0.33, UI_MUTED, 1)
    put_text(
        p, object_text,
        130, y + 52,
        0.42,
        UI_GREEN if has_target else UI_MUTED,
        1
    )
    put_text(
        p,
        "YOLO LIVE" if DETECT_MODE == "YOLO" else "BASELINE",
        306, y + 52,
        0.30,
        UI_GREEN if DETECT_MODE == "YOLO" else UI_WARN,
        1
    )

    # CURRENT TRACK RISK
    put_text(p, "TRACK RISK", 48, y + 76, 0.33, UI_MUTED, 1)
    put_text(p, risk_text, 150, y + 76, 0.42, risk_col, 1)
    put_text(
        p,
        f"v0  {threat:.2f}" if has_target else "v0",
        306, y + 76,
        0.30, UI_MUTED, 1
    )

    # FUTURE SPECIES CLASSIFIER
    put_text(p, "SPECIES", 48, y + 100, 0.33, UI_MUTED, 1)
    put_text(
        p,
        "UNKNOWN" if has_target else "--",
        130, y + 100,
        0.40, UI_TEXT if has_target else UI_MUTED, 1
    )
    put_text(
        p, "ResNet NEXT",
        292, y + 100,
        0.30, UI_ACCENT_2, 1
    )

    # RESPONSE
    put_text(p, "RESPONSE", 48, y + 124, 0.33, UI_MUTED, 1)
    put_text(
        p, response_text,
        140, y + 124,
        0.40,
        UI_ACCENT if assigned else UI_TEXT,
        1
    )
    put_text(
        p, "SOUND NEXT",
        302, y + 124,
        0.30, UI_ACCENT_2, 1
    )

    # Roadmap footer
    put_text(
        p,
        "NEXT  ResNet species | Speaker | RC Car",
        48, y + 145,
        0.29, UI_MUTED, 1
    )

    # -----------------------------------------------------
    # Turret assignment
    # -----------------------------------------------------
    y = 466
    rounded_rect(
        p, 32, y, PANEL_W - 32, y + 58,
        UI_SURFACE_2, radius=9
    )

    put_text(p, "TURRETS", 48, y + 24, 0.36, UI_MUTED, 1)

    for ti, turret_col in enumerate([UI_ACCENT, UI_ACCENT_2]):
        x = 48 + ti * 172
        tgt = t_assignments.get(ti) or "--"

        cv2.circle(
            p, (x + 8, y + 42),
            5, turret_col, -1, cv2.LINE_AA
        )

        put_text(
            p, f"PT{ti + 1}",
            x + 22, y + 47,
            0.40, UI_TEXT, 1
        )

        put_text(
            p,
            tgt.replace("Target_", "T"),
            x + 70, y + 47,
            0.36, turret_col, 1
        )

    # -----------------------------------------------------
    # Compact camera health
    # -----------------------------------------------------
    y = 536
    rounded_rect(
        p, 32, y, PANEL_W - 32, y + 36,
        UI_SURFACE_2, radius=7
    )

    parts = []
    for i in range(4):
        age = cam_ages[i]
        if age < 10:
            parts.append(f"C{i} {age * 1000:.0f}")
        else:
            parts.append(f"C{i} --")

    put_text(
        p,
        "CAM  " + "   ".join(parts),
        48, y + 23,
        0.28, UI_MUTED, 1
    )

    put_text(
        p,
        "T HSV/YOLO   M response   R reset   ESC exit",
        32, PANEL_H - 23,
        0.29, UI_MUTED, 1
    )

    return p


def decorate_feed_frame(feed, cam_idx, age):
    out = feed.copy()
    stale = age > MAX_FRAME_AGE
    lost = age > MAX_SHOW_AGE or age >= 10
    col = UI_GREEN if not stale else (UI_WARN if not lost else UI_DANGER)
    cv2.rectangle(out, (0, 0), (FEED_W - 1, FEED_H - 1), col, 1)
    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (FEED_W, 30), (12, 16, 20), -1)
    cv2.addWeighted(overlay, 0.72, out, 0.28, 0, out)
    put_text(out, f"CAM {cam_idx}", 12, 21, 0.44, UI_TEXT, 1)
    age_txt = f"{age * 1000:.0f} ms" if age < 10 else "NO SIGNAL"
    put_text(out, age_txt, FEED_W - 88, 21, 0.36, col, 1)
    return out

kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))


# (threading/traceback already imported at top)

class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.frames = {f"img{i}": None for i in range(4)}
        self.frame_ts = {f"img{i}": None for i in range(4)}
        self.frame_stream_size = {f"img{i}": None for i in range(4)}
        self.corrected_ts = {f"img{i}": None for i in range(4)}
        self.frame_sender_id = {f"img{i}": None for i in range(4)}
        self.frame_version = {f"img{i}": 0 for i in range(4)}

        self.ui_cam_feeds = None
        self.ui_final_pts_data = {}
        self.ui_cam_ages = [1e9]*4
        self.ui_threat_scores = {}
        self.ui_turret_assignments = {}
        self.ui_target_status = {}
        self.ui_fps = 0.0
        self.ui_load = 0.0
        self.ui_loop_ms = 0.0
        self.ready_canvas = None
        self.rx_frame_count = 0
        self.rx_packet_count = 0
        self.last_rx_time = 0.0
        self.receiver_error = None
        self.sender_stats = {}

shared_state = SharedState()
shutdown_event = threading.Event()
sender_offsets = {}
first_frame_received = False
_fps_frame_count_rx = 0

class ZmqReceiverThread(threading.Thread):
    def __init__(self, context, endpoint, stop_event):
        super().__init__(daemon=True, name="ZmqReceiver")
        self.context = context
        self.endpoint = endpoint
        self.stop_event = stop_event

    def run(self):
        global first_frame_received, _fps_frame_count_rx
        sock = self.context.socket(zmq.SUB)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVHWM, VIDEO_RCVHWM)
        if VIDEO_CONFLATE:
            sock.setsockopt(zmq.CONFLATE, 1)
        try:
            sock.bind(self.endpoint)
            sock.setsockopt_string(zmq.SUBSCRIBE, "")
            print(f">> Video receiver bound: {self.endpoint}")
        except zmq.ZMQError as e:
            with shared_state.lock:
                shared_state.receiver_error = f"video receiver bind failed on {self.endpoint}: {e}"
            sock.close()
            return

        try:
            while not self.stop_event.is_set():
                try:
                    try:
                        raw = sock.recv(zmq.NOBLOCK)
                        rx_ts = time.time()
                    except zmq.Again:
                        self.stop_event.wait(0.001)
                        continue
                    except zmq.ZMQError as e:
                        if self.stop_event.is_set():
                            break
                        print(f"!! ReceiverThread ZMQ error: {e}")
                        self.stop_event.wait(0.05)
                        continue
                    except Exception as e:
                        if self.stop_event.is_set():
                            break
                        print(f"!! ReceiverThread recv error: {type(e).__name__}: {e}")
                        self.stop_event.wait(0.01)
                        continue

                    try:
                        pkt = pickle.loads(raw)
                    except Exception:
                        continue
                    if not isinstance(pkt, dict):
                        continue
                    if pkt.get("id") != "stereo":
                        continue

                    pkt_ts = pkt.get("ts")
                    sender_id = pkt.get("sender_id", "unknown")
                    if not runtime_packet_resolution_ok(pkt, sender_id):
                        continue
                    if not runtime_packet_pair_dt_ok(pkt, sender_id):
                        continue
                    pkt_stream_size = packet_stream_size(pkt, sender_id)
                    pair_dt = float_or_default(pkt.get("pair_dt_s", pkt.get("pair_dt")), None)
                    packet_ts = float_or_default(pkt_ts, None)
                    if pkt_ts is not None:
                        try:
                            offset = rx_ts - float(pkt_ts)
                        except (TypeError, ValueError):
                            offset = None
                        if offset is not None and np.isfinite(offset):
                            prev_offset = sender_offsets.get(sender_id)
                            if prev_offset is not None:
                                delta = offset - prev_offset
                                if abs(delta) > OFFSET_MAX_STEP:
                                    offset = prev_offset + math.copysign(OFFSET_MAX_STEP, delta)
                                sender_offsets[sender_id] = prev_offset * (1 - OFFSET_ALPHA) + offset * OFFSET_ALPHA
                            else:
                                sender_offsets[sender_id] = offset

                    allowed_keys = SENDER_FRAME_KEYS.get(sender_id)
                    if allowed_keys is None:
                        continue
                    frame_items = [
                        (k2, pkt[k2], pkt.get(f"{k2}_ts"))
                        for k2 in pkt.keys()
                        if k2 in shared_state.frames and k2 in allowed_keys
                    ]
                    if not frame_items and "left" in pkt and "right" in pkt:
                        base_idx = {"rpi1": 0, "rpi2": 2}.get(sender_id)
                        if base_idx is None:
                            continue
                        frame_items = [
                            (f"img{base_idx}", pkt["left"], pkt.get("left_ts")),
                            (f"img{base_idx + 1}", pkt["right"], pkt.get("right_ts")),
                        ]
                    if not frame_items:
                        continue

                    with shared_state.lock:
                        shared_state.sender_stats[sender_id] = {
                            "rx_ts": rx_ts,
                            "packet_ts": packet_ts,
                            "offset": sender_offsets.get(sender_id),
                            "pair_dt": pair_dt,
                            "frame_keys": [k for k, _, _ in frame_items],
                        }
                        for k, frame_payload, frame_sender_ts in frame_items:
                            shared_state.frames[k] = frame_payload
                            shared_state.frame_ts[k] = rx_ts
                            shared_state.frame_stream_size[k] = pkt_stream_size
                            shared_state.frame_sender_id[k] = sender_id
                            shared_state.frame_version[k] += 1

                            ts_for_offset = frame_sender_ts if frame_sender_ts is not None else pkt_ts
                            if ts_for_offset is not None and sender_id in sender_offsets:
                                shared_state.corrected_ts[k] = ts_for_offset + sender_offsets[sender_id]
                            else:
                                shared_state.corrected_ts[k] = rx_ts
                        shared_state.rx_frame_count += len(frame_items)
                        shared_state.rx_packet_count += 1
                        shared_state.last_rx_time = rx_ts

                    if not first_frame_received:
                        first_frame_received = True
                        print(">> Connected!\n")
                    _fps_frame_count_rx += len(frame_items)

                except Exception as e:
                    print(f"!! ReceiverThread Error: {e}")
                    traceback.print_exc()
                    self.stop_event.wait(1.0)
        finally:
            sock.close()


all_frames = {f"img{i}": None for i in range(4)}
frame_ts = {f"img{i}": None for i in range(4)}
frame_stream_size = {f"img{i}": None for i in range(4)}
corrected_ts = {f"img{i}": None for i in range(4)}
frame_sender_id = {f"img{i}": None for i in range(4)}
frame_version = {f"img{i}": 0 for i in range(4)}

# Sender timestamp offset state for clock correction.

decoded_cache = [None for _ in range(4)]
decoded_cache_ts = [None for _ in range(4)]
decoded_cache_version = [0 for _ in range(4)]
processed_frame_version = [0 for _ in range(4)]

global_centers = {i: {} for i in range(4)}
center_2d_state = {i: {} for i in range(4)}
pos_3d_history = {name: None for name in TARGET_NAMES}
vel_buffer = {name: None for name in TARGET_NAMES}
last_detect_time = {name: None for name in TARGET_NAMES}

# Track Hold state
last_good_3d = {name: None for name in TARGET_NAMES}
last_good_pred = {name: None for name in TARGET_NAMES}
last_good_threat = {name: 0.0 for name in TARGET_NAMES}

target_status = {name: "IDLE" for name in TARGET_NAMES}
threat_scores = {name: 0.0 for name in TARGET_NAMES}
turret_assignments = {0: None, 1: None}

fps_timer = {}
processing_time = {'times': deque(maxlen=10), 'avg': 0}
system_stats = {'start_time': time.time(), 'frame_count': 0, 'detection_count': 0}

frame_loss_count = 0
# first_frame_received is set by ReceiverThread after the first valid packet.
selected_turret = 1

display_fps = 0.0
_fps_frame_count = 0      # Frames counted inside the current FPS window
_fps_window_start = 0.0   # Start timestamp for the current FPS window
display_load = 0.0
panel_fps_fixed = 0.0
panel_load_fixed = 0.0
panel_loop_ms = 0.0
panel_cam_ages = [1e9] * 4
last_panel_update = 0
PANEL_UPDATE_INTERVAL = 0.3
last_ui_render_time = 0.0
last_imshow_time = 0.0
last_sync_diag_time = 0.0
last_dashboard_send_time = 0.0

def camera_ages_from_ts(now_ts, ts_snapshot):
    ages = [1e9] * 4
    for i in range(4):
        ts_k = ts_snapshot.get(f"img{i}")
        ages[i] = (now_ts - ts_k) if ts_k is not None else 1e9
    return ages


def _sync_delta_seconds(a, b):
    if a is None or b is None:
        return None
    try:
        delta = abs(float(a) - float(b))
    except (TypeError, ValueError):
        return None
    return delta if np.isfinite(delta) else None


def _sync_ms_text(seconds):
    if seconds is None:
        return "--"
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "--"
    if not np.isfinite(seconds):
        return "--"
    return f"{seconds * 1000:.0f}"


def _sender_corrected_stamp(stats, ts_snapshot, sender_id):
    default_keys = {"rpi1": ["img0", "img1"], "rpi2": ["img2", "img3"]}.get(sender_id, [])
    keys = stats.get(sender_id, {}).get("frame_keys") or default_keys
    vals = []
    for key in keys:
        ts = ts_snapshot.get(key)
        if ts is not None:
            try:
                ts_val = float(ts)
            except (TypeError, ValueError):
                continue
            if np.isfinite(ts_val):
                vals.append(ts_val)
    if not vals:
        return None
    return sum(vals) / len(vals)


def build_sender_sync_diagnostic(now_ts):
    with shared_state.lock:
        stats = {sender: dict(values) for sender, values in shared_state.sender_stats.items()}
        ts_snapshot = dict(shared_state.corrected_ts)
    r1 = stats.get("rpi1")
    r2 = stats.get("rpi2")
    if not r1 and not r2:
        return None
    if not r1 or not r2:
        return f">> SYNC waiting: rpi1={'OK' if r1 else '--'} rpi2={'OK' if r2 else '--'}"

    rx_delta = _sync_delta_seconds(r1.get("rx_ts"), r2.get("rx_ts"))
    corr_delta = _sync_delta_seconds(
        _sender_corrected_stamp(stats, ts_snapshot, "rpi1"),
        _sender_corrected_stamp(stats, ts_snapshot, "rpi2"),
    )
    offset_delta = _sync_delta_seconds(r1.get("offset"), r2.get("offset"))
    r1_age = _sync_delta_seconds(now_ts, r1.get("rx_ts"))
    r2_age = _sync_delta_seconds(now_ts, r2.get("rx_ts"))
    return (
        ">> SYNC rpi1-rpi2 "
        f"rx_delta={_sync_ms_text(rx_delta)}ms "
        f"corr_delta={_sync_ms_text(corr_delta)}ms "
        f"offset_delta={_sync_ms_text(offset_delta)}ms "
        f"pair_dt={_sync_ms_text(r1.get('pair_dt'))}/{_sync_ms_text(r2.get('pair_dt'))}ms "
        f"age={_sync_ms_text(r1_age)}/{_sync_ms_text(r2_age)}ms"
    )


def maybe_print_sender_sync(now_ts):
    global last_sync_diag_time
    if SYNC_DIAGNOSTIC_INTERVAL <= 0:
        return
    if now_ts - last_sync_diag_time < SYNC_DIAGNOSTIC_INTERVAL:
        return
    last_sync_diag_time = now_ts
    msg = build_sender_sync_diagnostic(now_ts)
    if msg:
        print(msg)

def build_display_feeds_from_cache(now_ts, ts_snapshot):
    feeds = []
    ages = [1e9] * 4
    for i in range(4):
        ts_k = ts_snapshot.get(f"img{i}")
        age = (now_ts - ts_k) if ts_k is not None else 1e9
        ages[i] = age
        if decoded_cache[i] is None:
            feed = np.zeros((FEED_H, FEED_W, 3), np.uint8)
        else:
            feed = decoded_cache[i].copy()

        if ts_k is None or age > MAX_SHOW_AGE:
            feed = np.zeros((FEED_H, FEED_W, 3), np.uint8)
        elif age > MAX_FRAME_AGE:
            cv2.rectangle(feed, (0, 0), (FEED_W - 1, FEED_H - 1), (0, 0, 255), 2)
            cv2.putText(feed, f"STALE {age:.2f}s", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        feeds.append(feed)
    return feeds, ages

def coast_targets_without_measurement(now):
    display_pts = {}
    display_targets = {}
    fresh_display_sec = min(MAX_FRAME_AGE, TRACK_HOLD_SEC)
    for lbl in TARGET_NAMES:
        curr_3d, pred_3d = None, None
        if last_detect_time[lbl] is not None and last_good_3d[lbl] is not None:
            hold_age = now - last_detect_time[lbl]
            if hold_age <= fresh_display_sec:
                curr_3d = last_good_3d[lbl]
                pred_3d = last_good_pred[lbl]
                threat_scores[lbl] = last_good_threat[lbl]
                display_targets[lbl] = build_target_output(
                    curr_3d,
                    pred_3d,
                    threat_scores[lbl],
                    target_status.get(lbl, "IDLE"),
                    hold_age,
                    target_status.get(lbl) in ("LOCKED", "CRITICAL") or hold_age <= TRACK_AIM_HOLD_SEC,
                )
            elif hold_age <= TRACK_HOLD_SEC:
                curr_3d = last_good_3d[lbl]
                pred_3d = last_good_pred[lbl]
                target_status[lbl] = "HELD"
                threat_scores[lbl] = last_good_threat[lbl] * THREAT_DECAY
                display_targets[lbl] = build_target_output(curr_3d, pred_3d, threat_scores[lbl], target_status[lbl], hold_age, False)
            elif hold_age > TRACK_DROP_SEC:
                target_status[lbl] = "IDLE"
                threat_scores[lbl] = 0.0
                pos_3d_history[lbl] = None
                vel_buffer[lbl] = None
                smooth_pred[lbl] = None
                last_detect_time[lbl] = None
                last_good_3d[lbl] = None
                last_good_pred[lbl] = None
            else:
                curr_3d = last_good_3d[lbl]
                pred_3d = last_good_pred[lbl]
                fade = 1.0 - (hold_age - TRACK_HOLD_SEC) / (TRACK_DROP_SEC - TRACK_HOLD_SEC)
                target_status[lbl] = "HELD"
                threat_scores[lbl] = last_good_threat[lbl] * THREAT_DECAY * fade
                if fade > 0.1:
                    display_targets[lbl] = build_target_output(curr_3d, pred_3d, threat_scores[lbl], target_status[lbl], hold_age, False)
        else:
            target_status[lbl] = "IDLE"
            threat_scores[lbl] = 0.0
        display_pts[lbl] = (curr_3d, pred_3d)
    return display_pts, display_targets

def handle_control_key(key):
    global selected_turret, fire_mode, DETECT_MODE
    if key in (-1, 255, None):
        return False
    if key == ord('1'): selected_turret = 1
    elif key == ord('2'): selected_turret = 2
    elif key == ord('0'): calib_trims["pt1"] = [0, 0]; calib_trims["pt2"] = [0, 0]
    elif key == ord('p') or key == ord('P'):
        print(f"T1: P{calib_trims['pt1'][0]} T{calib_trims['pt1'][1]} | T2: P{calib_trims['pt2'][0]} T{calib_trims['pt2'][1]}")
    elif key == ord('w'): calib_trims['pt1'][1] -= 1
    elif key == ord('s'): calib_trims['pt1'][1] += 1
    elif key == ord('a'): calib_trims['pt1'][0] += 1
    elif key == ord('d'): calib_trims['pt1'][0] -= 1
    elif key == ord('i'): calib_trims['pt2'][1] -= 1
    elif key == ord('k'): calib_trims['pt2'][1] += 1
    elif key == ord('j'): calib_trims['pt2'][0] += 1
    elif key == ord('l'): calib_trims['pt2'][0] -= 1
    elif key == ord('m') or key == ord('M'):
        fire_mode = "SONIC" if fire_mode == "LASER" else "LASER"
        print(f">> Mode: {fire_mode}")
    elif key == ord('t') or key == ord('T'):
        if DETECT_MODE == "HSV":
            if ensure_yolo_ready():
                DETECT_MODE = "YOLO"
            else:
                print("!! YOLO mode unavailable; staying in HSV mode")
        else:
            DETECT_MODE = "HSV"
        print(f">> DETECT MODE: {DETECT_MODE}")

    if key == 27:
        return True
    if key == ord('r') or key == ord('R'):
        for state in center_2d_state.values():
            state.clear()
        for name in TARGET_NAMES:
            KF_DICT[name] = make_kalman_filters()
            pos_3d_history[name] = None
            vel_buffer[name] = None
            smooth_pred[name] = None
            last_detect_time[name] = None
            last_good_3d[name] = None
            last_good_pred[name] = None
        print(">> Track reset")
    return False

print("\n" + "="*55)
print("  FUSION + Track Hold + Timestamp Sync")
print("="*55)
print("  [M] LASER/SONIC  [T] HSV/YOLO  [WASD] T1  [IJKL] T2")
print("  [0] Trim Reset  [R] Track Reset  [ESC] Exit")
print("="*55 + "\n")


class UIRenderThread(threading.Thread):
    def __init__(self, stop_event):
        super().__init__(daemon=True, name="UIRenderer")
        self.stop_event = stop_event
        self.ui_smooth_state = {}

    def run(self):
        interval = 1.0 / UI_TARGET_FPS if UI_TARGET_FPS > 0 else 0.05
        while not self.stop_event.is_set():
            try:
                # Skip rendering until at least one camera feed is available.
                has_data = False
                with shared_state.lock:
                    if shared_state.ui_cam_feeds is not None:
                        has_data = True
                        cam_feeds_raw = list(shared_state.ui_cam_feeds)
                        final_pts = dict(shared_state.ui_final_pts_data)
                        cam_ages = list(shared_state.ui_cam_ages)
                        ui_threat = dict(shared_state.ui_threat_scores)
                        ui_turret = dict(shared_state.ui_turret_assignments)
                        ui_status = dict(shared_state.ui_target_status)
                        fps_fixed = shared_state.ui_fps
                        load_fixed = shared_state.ui_load
                        loop_ms = shared_state.ui_loop_ms

                if not has_data:
                    self.stop_event.wait(0.01)
                    continue

                # Copy shared frames before drawing so the UI thread never mutates shared state.
                cam_feeds = [f.copy() if f is not None else np.zeros((FEED_H, FEED_W, 3), np.uint8) for f in cam_feeds_raw]
                display_pts = smooth_ui_points(final_pts, self.ui_smooth_state)
                top_map = draw_topview_dynamic(display_pts, ui_threat, ui_turret, t_status=ui_status)
                panel = draw_panel_dynamic(display_pts, ui_threat, fps_fixed, load_fixed, cam_ages, loop_ms, t_status=ui_status, t_assignments=ui_turret)

                canvas = np.zeros((FEED_H + MAP_H, FEED_W * 4, 3), dtype=np.uint8)
                for ci in range(4):
                    x0 = ci * FEED_W
                    canvas[0:FEED_H, x0:x0+FEED_W] = decorate_feed_frame(cam_feeds[ci], ci, cam_ages[ci])
                canvas[FEED_H:FEED_H+MAP_H, 0:MAP_W] = top_map
                canvas[FEED_H:FEED_H+PANEL_H, MAP_W:MAP_W+PANEL_W] = panel

                # Publish the completed canvas atomically for the main UI loop.
                with shared_state.lock:
                    shared_state.ready_canvas = canvas

                self.stop_event.wait(interval)
            except Exception as e:
                print(f"!! UIRenderThread Error: {e}")
                traceback.print_exc()
                self.stop_event.wait(1.0)

rx_thread = ZmqReceiverThread(ctx, VIDEO_ENDPOINT, shutdown_event)
rx_thread.start()
ui_thread = None
if ENABLE_UI:
    ui_thread = UIRenderThread(shutdown_event)
    ui_thread.start()


try:
    while True:
        loop_start = time.time()
        system_stats['frame_count'] += 1

        control_keys = []
        # pollKey if available (non-blocking), else waitKey(1)
        if ENABLE_UI:
            try:
                key = cv2.pollKey() & 0xFF
            except AttributeError:
                key = cv2.waitKey(1) & 0xFF
        else:
            key = -1
            # Headless mode: keep command polling active without stdin blocking.
        if 'sCMD' in globals() and sCMD is not None:
            try:
                raw_cmd = sCMD.recv(zmq.NOBLOCK)
            except zmq.Again:
                raw_cmd = None
            if raw_cmd is not None:
                try:
                    cmd_key = command_to_key(pickle.loads(raw_cmd))
                except Exception:
                    cmd_key = None
                if cmd_key is not None:
                    key = cmd_key

        if key not in (-1, 255):
            control_keys.append(key)
        if 'sCMD' in globals() and sCMD is not None:
            for _ in range(MAX_DASHBOARD_COMMANDS_PER_LOOP - 1):
                try:
                    raw_cmd = sCMD.recv(zmq.NOBLOCK)
                except zmq.Again:
                    break
                try:
                    cmd_key = command_to_key(pickle.loads(raw_cmd))
                except Exception:
                    cmd_key = None
                if cmd_key is not None:
                    control_keys.append(cmd_key)
        if any(handle_control_key(cmd_key) for cmd_key in control_keys):
            break
        # ==========================
        # Drain latest video packets
        # ==========================

        has_new_frame = False
        with shared_state.lock:
            receiver_error = shared_state.receiver_error
            next_frame_version = dict(shared_state.frame_version)
            for k_str, version in next_frame_version.items():
                if version != frame_version.get(k_str, 0):
                    has_new_frame = True

            # Shallow copy and reference assignment
            all_frames = dict(shared_state.frames)
            frame_ts = dict(shared_state.frame_ts)
            frame_stream_size = dict(shared_state.frame_stream_size)
            corrected_ts = dict(shared_state.corrected_ts)
            frame_sender_id = dict(shared_state.frame_sender_id)
            frame_version = next_frame_version

        if receiver_error:
            raise RuntimeError(receiver_error)

        now_ts = time.time()

        if has_new_frame:
            frame_loss_count = 0
        else:
            frame_loss_count += 1
            if frame_loss_count > 30 and first_frame_received:
                time.sleep(0.001)
            elif not first_frame_received:
                time.sleep(0.005)
            else:
                time.sleep(0.0005)

            current_time = time.time()
            maybe_print_sender_sync(current_time)
            if _fps_window_start == 0.0:
                _fps_window_start = current_time
            elapsed_fps = current_time - _fps_window_start
            if elapsed_fps >= 1.0:
                with shared_state.lock:
                    rx_frames = shared_state.rx_frame_count
                    shared_state.rx_frame_count = 0
                display_fps = rx_frames / elapsed_fps
                _fps_window_start = current_time

            loop_ms_now = (current_time - loop_start) * 1000
            display_load = min(loop_ms_now / (100.0 if DETECT_MODE == "YOLO" else 33.3) * 100, 999)
            cam_ages_now = camera_ages_from_ts(current_time, corrected_ts)
            final_pts_data, dashboard_targets = coast_targets_without_measurement(current_time)
            heartbeat_assignments = {
                idx: tgt if tgt in dashboard_targets and dashboard_targets[tgt].get("aim", False) else None
                for idx, tgt in turret_assignments.items()
            }

            if current_time - last_panel_update > PANEL_UPDATE_INTERVAL:
                panel_fps_fixed = display_fps
                panel_load_fixed = display_load
                panel_loop_ms = loop_ms_now
                panel_cam_ages = cam_ages_now[:]
                last_panel_update = current_time

            render_ui = ENABLE_UI and ((UI_RENDER_INTERVAL <= 0.0) or (current_time - last_ui_render_time >= UI_RENDER_INTERVAL))
            dashboard_due = ENABLE_DASHBOARD and dashboard_pub is not None and ((DASHBOARD_INTERVAL <= 0.0) or (current_time - last_dashboard_send_time >= DASHBOARD_INTERVAL))
            cam_feeds = None

            if render_ui:
                if cam_feeds is None:
                    cam_feeds, _ = build_display_feeds_from_cache(current_time, corrected_ts)
                with shared_state.lock:
                    shared_state.ui_cam_feeds = list(cam_feeds)
                    shared_state.ui_final_pts_data = dict(final_pts_data)
                    shared_state.ui_cam_ages = list(panel_cam_ages)
                    shared_state.ui_threat_scores = dict(threat_scores)
                    shared_state.ui_turret_assignments = dict(heartbeat_assignments)
                    shared_state.ui_target_status = dict(target_status)
                    shared_state.ui_fps = panel_fps_fixed
                    shared_state.ui_load = panel_load_fixed
                    shared_state.ui_loop_ms = panel_loop_ms
                last_ui_render_time = current_time

            imshow_due = ENABLE_UI and (
                (UI_RENDER_INTERVAL <= 0.0)
                or (current_time - last_imshow_time >= UI_RENDER_INTERVAL)
            )
            if imshow_due:
                with shared_state.lock:
                    canvas_to_show = shared_state.ready_canvas
                if canvas_to_show is not None:
                    cv2.imshow("FUSION", canvas_to_show)
                    last_imshow_time = current_time

            if dashboard_due:
                last_dashboard_send_time = current_time
                if cam_feeds is None:
                    cam_feeds, _ = build_display_feeds_from_cache(current_time, corrected_ts)
                dashboard_pts_data = smooth_ui_points(final_pts_data)
                dashboard_packet = build_dashboard_packet(
                    cam_feeds,
                    cam_ages_now,
                    dashboard_pts_data,
                    threat_scores,
                    heartbeat_assignments,
                    panel_fps_fixed,
                    panel_load_fixed,
                    panel_loop_ms,
                    encode_frames=False,
                    command_targets=dashboard_targets,
                )
                dashboard_pub.submit(dashboard_packet)

            processing_time['times'].append(time.time() - loop_start)
            processing_time['avg'] = float(np.mean(processing_time['times']))
            continue


        # ==========================
        # Decode and detect camera frames
        # ==========================
        cam_feeds = None
        cam_ages_now = [1e9] * 4
        yolo_jobs = []
        for i in range(4):
            k = f"img{i}"
            ts_k = corrected_ts.get(k)
            age = (now_ts - ts_k) if ts_k is not None else 1e9
            cam_ages_now[i] = age

            raw_frame = all_frames.get(k)
            current_frame_version = frame_version.get(k, 0)
            has_new = (raw_frame is not None) and (ts_k is not None) and (processed_frame_version[i] != current_frame_version)
            if has_new:
                try:
                    # HSV can decode reduced frames when full-resolution HSV is disabled.
                    # YOLO keeps full-resolution decode before model preprocessing.
                    flag = cv2.IMREAD_COLOR if (DETECT_MODE != "HSV" or HSV_FULL_RESOLUTION) else cv2.IMREAD_REDUCED_COLOR_2
                    orig = decode_jpeg_frame(raw_frame, flag)
                except Exception:
                    orig = None

                if orig is not None:
                    if not decoded_frame_resolution_ok(orig, frame_sender_id.get(k, "unknown"), k, flag, frame_stream_size.get(k)):
                        global_centers[i] = {}
                        if STORE_VISUAL_FEEDS:
                            decoded_cache[i] = None
                            decoded_cache_ts[i] = frame_ts.get(k)
                            decoded_cache_version[i] = current_frame_version
                        processed_frame_version[i] = current_frame_version
                        continue
                    dec_h, dec_w = orig.shape[0], orig.shape[1]
                    sx = SRC_W / float(dec_w)
                    sy = SRC_H / float(dec_h)
                    centers = {}

                    if DETECT_MODE == "HSV":
                        # HSV detection path
                        hsv = cv2.cvtColor(orig, cv2.COLOR_BGR2HSV)
                        for name, lims in TARGET_COLORS.items():
                            mask = cv2.inRange(hsv, lims['lower'], lims['upper'])
                            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
                            if HSV_MORPH_CLOSE:
                                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
                            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                            if not cnts:
                                continue
                            best = max(cnts, key=cv2.contourArea)
                            area = float(cv2.contourArea(best))
                            if area < HSV_MIN_AREA:
                                continue
                            if HSV_MIN_CIRCULARITY > 0.0:
                                perimeter = float(cv2.arcLength(best, True))
                                circularity = 0.0 if perimeter <= 1e-6 else (4.0 * math.pi * area) / (perimeter * perimeter)
                                if circularity < HSV_MIN_CIRCULARITY:
                                    continue
                            M = cv2.moments(best)
                            if M["m00"] <= 0:
                                continue
                            cx_dec = M["m10"] / M["m00"]
                            cy_dec = M["m01"] / M["m00"]
                            cx = float(cx_dec * sx)
                            cy = float(cy_dec * sy)
                            centers[name] = (cx, cy)
                            if STORE_VISUAL_FEEDS:
                                cv2.drawMarker(orig, (int(cx_dec), int(cy_dec)),
                                               VISUAL_COLORS[name], cv2.MARKER_CROSS, 25, 2)

                    else:
                        # YOLO detection path: batch all available camera frames together.
                        if not ensure_yolo_ready():
                            DETECT_MODE = "HSV"
                            global_centers[i] = {}
                            continue
                        yolo_jobs.append((i, k, orig, age))
                        continue

                    if STORE_VISUAL_FEEDS:
                        decoded_cache[i] = cv2.resize(orig, (FEED_W, FEED_H))
                        decoded_cache_ts[i] = frame_ts.get(k)
                        decoded_cache_version[i] = current_frame_version
                    processed_frame_version[i] = current_frame_version

                    if age <= MAX_FRAME_AGE:
                        global_centers[i] = centers
                    else:
                        global_centers[i] = {}
                else:
                    global_centers[i] = {}
                    processed_frame_version[i] = current_frame_version
            else:
                if age > MAX_FRAME_AGE:
                    global_centers[i] = {}

        if DETECT_MODE == "YOLO" and yolo_jobs:
            if ensure_yolo_ready():
                try:
                    yolo_kwargs = {
                        "conf": YOLO_CONF,
                        "imgsz": _YOLO_IMGSZ,
                        "max_det": YOLO_MAX_DET,
                        "device": _YOLO_DEVICE,
                        "half": _YOLO_HALF,
                        "rect": YOLO_RECT,
                        "verbose": False,
                    }
                    if YOLO_CLASSES is not None:
                        yolo_kwargs["classes"] = YOLO_CLASSES
                    yolo_results = _YOLO_MODEL([job[2] for job in yolo_jobs], **yolo_kwargs)
                except Exception as e:
                    print(f"!! YOLO batch failed: {type(e).__name__}: {e}")
                    for i, _, _, _ in yolo_jobs:
                        global_centers[i] = {}
                    yolo_results = [None] * len(yolo_jobs)

                for (i, k, orig, age), results in zip(yolo_jobs, yolo_results):
                    centers = {}
                    dec_h, dec_w = orig.shape[:2]
                    detections = []
                    boxes = getattr(results, "boxes", None)
                    if boxes is None:
                        if STORE_VISUAL_FEEDS:
                            decoded_cache[i] = cv2.resize(orig, (FEED_W, FEED_H))
                            decoded_cache_ts[i] = frame_ts.get(k)
                            decoded_cache_version[i] = frame_version.get(k, 0)
                        processed_frame_version[i] = frame_version.get(k, 0)
                        global_centers[i] = {}
                        continue
                    for idx, box in enumerate(boxes):
                        try:
                            bx, by, bw, bh = [float(v) for v in box.xywh[0].tolist()]
                        except Exception:
                            continue
                        if not np.all(np.isfinite([bx, by, bw, bh])) or bw <= 0 or bh <= 0:
                            continue
                        area = float(bw * bh)
                        if area < YOLO_MIN_BOX_AREA:
                            continue
                        try:
                            conf_val = float(box.conf[0])
                        except Exception:
                            conf_val = 0.0
                        if not np.isfinite(conf_val):
                            continue
                        try:
                            center_x, center_y, center_src = yolo_detection_center(results, box, idx)
                        except Exception:
                            continue
                        if not np.isfinite(center_x) or not np.isfinite(center_y):
                            continue
                        if not (0.0 <= center_x < dec_w and 0.0 <= center_y < dec_h):
                            continue
                        cx = float(center_x * (SRC_W / dec_w))
                        cy = float(center_y * (SRC_H / dec_h))
                        detections.append((cx, cy, area, conf_val, bx, by, bw, bh, center_x, center_y, center_src))
                        if DRAW_YOLO_OVERLAY:
                            cv2.rectangle(orig,
                                (int(bx - bw / 2), int(by - bh / 2)),
                                (int(bx + bw / 2), int(by + bh / 2)),
                                (0, 255, 80), 2)
                            cv2.putText(orig, f"bird {conf_val:.2f}",
                                (int(bx - bw / 2), max(0, int(by - bh / 2) - 5)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 80), 1)
                            cv2.drawMarker(orig, (int(center_x), int(center_y)),
                                (0, 255, 80), cv2.MARKER_CROSS, 25, 2)

                    centers = assign_yolo_detections(detections, global_centers.get(i, {}))
                    centers = smooth_yolo_centers(i, centers)

                    if STORE_VISUAL_FEEDS:
                        decoded_cache[i] = cv2.resize(orig, (FEED_W, FEED_H))
                        decoded_cache_ts[i] = frame_ts.get(k)
                        decoded_cache_version[i] = frame_version.get(k, 0)
                    processed_frame_version[i] = frame_version.get(k, 0)
                    if age <= MAX_FRAME_AGE:
                        global_centers[i] = centers
                    else:
                        global_centers[i] = {}

        # Visual feed cache is refreshed on every processed frame; UI canvas is built only when due.
        final_pts_data = {}
        targets_to_send = {}
        now = time.time()

        # ==========================
        # Fuse detections and apply Track Hold
        # ==========================
        for lbl in TARGET_NAMES:
            valid = [idx for idx in range(4) if lbl in global_centers[idx]]

            # ---- Phase 1: triangulate all valid camera pairs ----
            pair_results = []
            if len(valid) >= 2:
                for i in range(len(valid)):
                    for j in range(i + 1, len(valid)):
                        ca, cb = valid[i], valid[j]
                        ta = corrected_ts.get(f"img{ca}")
                        tb = corrected_ts.get(f"img{cb}")
                        sync_w = pair_sync_weight(ta, tb)
                        if sync_w <= 0.0:
                            system_stats["sync_reject_count"] = system_stats.get("sync_reject_count", 0) + 1
                            continue
                        pL, pR = global_centers[ca][lbl], global_centers[cb][lbl]
                        y_residual = rectified_y_residual(pL, pR, ca, cb)
                        if y_residual is not None:
                            if y_residual > MAX_RECTIFIED_Y_DIFF:
                                continue
                        elif abs(pL[1] - pR[1]) > MAX_Y_DIFF:
                            continue
                        r_3d = get_3d_global_corrected(pL, pR, ca, cb)
                        if r_3d is not None:
                            # Z gate removes impossible depth or non-finite triangulation results.
                            _Z_MIN = 0.10
                            _Z_MAX = cfg.FUSION_PARAMS["max_laser_dist"] * 1.2
                            if not np.all(np.isfinite(r_3d)):
                                continue
                            if not (_Z_MIN <= r_3d[2] <= _Z_MAX):
                                continue
                            dist_c = (abs(pL[0] - (SRC_W / 2)) + abs(pR[0] - (SRC_W / 2))) / float(SRC_W)
                            # Down-weight detections close to image edges.
                            min_x = min(pL[0], pR[0])
                            max_x = max(pL[0], pR[0])
                            edge_dist = min(min_x, SRC_W - max_x)
                            if edge_dist < EDGE_MARGIN:
                                edge_w = max(0.02, edge_dist / EDGE_MARGIN)
                            else:
                                edge_w = 1.0
                            epi_w = 1.0
                            if y_residual is not None and MAX_RECTIFIED_Y_DIFF > 0:
                                epi_w = max(0.10, 1.0 - (y_residual / MAX_RECTIFIED_Y_DIFF))
                            weight = pair_baseline_weight(ca, cb) * pair_reliability_weight(ca, cb) * sync_w * (1.0 - dist_c) * edge_w * epi_w
                            pair_results.append((r_3d, weight))

            # ---- Phase 2: reject pairwise Y/Z outliers around the median ----
            if len(pair_results) >= 3:
                positions = np.array([r[0] for r in pair_results])
                median_pos = np.median(positions, axis=0)
                pair_results = [(p, w) for p, w in pair_results
                                if abs(p[1] - median_pos[1]) < 0.10   # Y outlier gate
                                and abs(p[2] - median_pos[2]) < 0.15]  # Z outlier gate

            if pair_results and pos_3d_history[lbl] is not None and last_detect_time[lbl] is not None:
                dt_gate = now - last_detect_time[lbl]
                if dt_gate >= POSITION_GATE_MIN_DT and dt_gate < 0.5:
                    allowed_jump = MAX_TARGET_SPEED_MPS * dt_gate + POSITION_GATE_MARGIN_M
                    before_count = len(pair_results)
                    pair_results = [
                        (p, w) for p, w in pair_results
                        if float(np.linalg.norm(p - pos_3d_history[lbl])) <= allowed_jump
                    ]
                    if len(pair_results) < before_count:
                        system_stats["outlier_reject_count"] = system_stats.get("outlier_reject_count", 0) + (before_count - len(pair_results))

            # ---- Phase 3: weighted fusion ----
            f_sum, t_weight = np.zeros(3), 0.0
            for r_3d, weight in pair_results:
                f_sum += r_3d * weight
                t_weight += weight

            curr_3d, pred_3d = None, None

            if t_weight > 0:
                # Filter fused 3D position per axis.
                fused = f_sum / t_weight
                curr_3d = np.array([
                    KF_DICT[lbl]["x"].update(fused[0]),
                    KF_DICT[lbl]["y"].update(fused[1]),
                    KF_DICT[lbl]["z"].update(fused[2])
                ])

                # Position-level clamp limits physically impossible frame-to-frame jumps.
                if pos_3d_history[lbl] is not None and last_detect_time[lbl] is not None:
                    dt_clamp = now - last_detect_time[lbl]
                    if dt_clamp > 0.001 and dt_clamp < 0.5:
                        max_move = MAX_TARGET_SPEED_MPS * dt_clamp
                        delta = curr_3d - pos_3d_history[lbl]
                        move_dist = float(np.linalg.norm(delta))
                        if move_dist > max_move:
                            curr_3d = pos_3d_history[lbl] + delta * (max_move / move_dist)

                system_stats['detection_count'] += 1

                filtered_vel = np.zeros(3)
                if (pos_3d_history[lbl] is not None) and (last_detect_time[lbl] is not None):
                    dt_v = now - last_detect_time[lbl]
                    if dt_v > 0.001:
                        raw_vel = (curr_3d - pos_3d_history[lbl]) / dt_v
                        if vel_buffer[lbl] is None:
                            vel_buffer[lbl] = raw_vel
                        vel_buffer[lbl] = VEL_LPF_BETA * raw_vel + (1 - VEL_LPF_BETA) * vel_buffer[lbl]
                        filtered_vel = vel_buffer[lbl]
                else:
                    vel_buffer[lbl] = None

                speed = float(np.linalg.norm(filtered_vel))
                dist_m = max(float(curr_3d[2]), 0.3)

                if speed < VEL_DEADZONE:
                    filtered_vel = np.zeros(3)
                    speed = 0.0
                    smooth_pred[lbl] = None

                raw_pred = compute_lead_shot(curr_3d, filtered_vel, dist_m)
                alpha = SMOOTH_ALPHA
                if speed > 0.0 and smooth_pred[lbl] is not None:
                    pred_3d = smooth_pred[lbl] * (1 - alpha) + raw_pred * alpha
                else:
                    pred_3d = raw_pred
                smooth_pred[lbl] = pred_3d

                can_aim = AIM_STATIC_TARGETS or speed > 0.0
                target_status[lbl] = (
                    "CRITICAL" if can_aim and float(curr_3d[2]) < CRITICAL_DIST_M
                    else "LOCKED" if can_aim
                    else "IDLE"
                )
                threat_scores[lbl] = calculate_threat_level(curr_3d, filtered_vel)

                # Cache the last usable target state for Track Hold.
                last_good_3d[lbl] = curr_3d.copy()
                last_good_pred[lbl] = pred_3d.copy() if pred_3d is not None else curr_3d.copy()
                last_good_threat[lbl] = threat_scores[lbl]
                last_detect_time[lbl] = now
                pos_3d_history[lbl] = curr_3d

                targets_to_send[lbl] = build_target_output(
                    curr_3d, pred_3d, threat_scores[lbl], target_status[lbl], 0.0, can_aim
                )

            else:
                # -------------------------------------------------
                # SINGLE-CAMERA FALLBACK
                #
                # If exactly one camera still detects the target,
                # keep the latest stereo depth and update X/Y from
                # that camera's calibrated image ray.
                #
                # Status is HELD to make it clear that this is an
                # approximate monocular continuation, not fresh
                # stereo triangulation.
                # -------------------------------------------------
                if len(valid) == 1 and (DETECT_MODE != "YOLO" or YOLO_ALLOW_MONO_AIM):
                    mono_cam = valid[0]
                    mono_pixel = global_centers[mono_cam].get(lbl)

                    if last_good_3d[lbl] is not None:
                        mono_z = float(last_good_3d[lbl][2])
                    else:
                        mono_z = MONO_FALLBACK_DEFAULT_Z

                    mono_point = single_camera_world_at_depth(
                        mono_cam,
                        mono_pixel,
                        mono_z
                    )

                    if mono_point is not None:
                        # Light smoothing reduces one-camera jitter.
                        if pos_3d_history[lbl] is not None:
                            mono_point = (
                                0.72 * mono_point
                                + 0.28 * np.asarray(
                                    pos_3d_history[lbl],
                                    dtype=np.float64
                                )
                            )

                        curr_3d = mono_point
                        pred_3d = mono_point.copy()

                        filtered_vel = np.zeros(3, dtype=np.float64)

                        target_status[lbl] = "HELD"
                        threat_scores[lbl] = calculate_threat_level(
                            curr_3d,
                            filtered_vel
                        )

                        # Keep the fallback alive while one camera
                        # continues to see the object.
                        last_good_3d[lbl] = curr_3d.copy()
                        last_good_pred[lbl] = pred_3d.copy()
                        last_good_threat[lbl] = threat_scores[lbl]
                        last_detect_time[lbl] = now
                        pos_3d_history[lbl] = curr_3d.copy()

                        targets_to_send[lbl] = build_target_output(
                            curr_3d,
                            pred_3d,
                            threat_scores[lbl],
                            target_status[lbl],
                            0.0,
                            True
                        )

                        final_pts_data[lbl] = (
                            curr_3d,
                            pred_3d
                        )

                        # One-camera fallback completed for this
                        # target; skip normal Track Hold below.
                        continue

                # No valid pair / no usable mono detection:
                # fall back to the original Track Hold logic.
                # No valid pair this frame; try Track Hold.
                if last_detect_time[lbl] is not None and last_good_3d[lbl] is not None:
                    hold_age = now - last_detect_time[lbl]

                    if hold_age <= TRACK_HOLD_SEC:
                        # HOLD: coast using the last good position/prediction.
                        curr_3d = last_good_3d[lbl]
                        pred_3d = last_good_pred[lbl]
                        target_status[lbl] = "HELD"
                        threat_scores[lbl] = last_good_threat[lbl] * THREAT_DECAY

                        targets_to_send[lbl] = build_target_output(
                            curr_3d, pred_3d, threat_scores[lbl], target_status[lbl], hold_age, hold_age <= TRACK_AIM_HOLD_SEC
                        )

                    elif hold_age > TRACK_DROP_SEC:
                        # DROP: clear stale target state.
                        target_status[lbl] = "IDLE"
                        threat_scores[lbl] = 0.0
                        pos_3d_history[lbl] = None
                        vel_buffer[lbl] = None
                        smooth_pred[lbl] = None
                        last_detect_time[lbl] = None
                        last_good_3d[lbl] = None
                        last_good_pred[lbl] = None
                    else:
                        # HOLD_SEC < age <= DROP_SEC: fading hold
                        curr_3d = last_good_3d[lbl]
                        pred_3d = last_good_pred[lbl]
                        fade = 1.0 - (hold_age - TRACK_HOLD_SEC) / (TRACK_DROP_SEC - TRACK_HOLD_SEC)
                        target_status[lbl] = "HELD"
                        threat_scores[lbl] = last_good_threat[lbl] * THREAT_DECAY * fade
                        # Keep sending while fade is meaningful; otherwise turret should idle.
                        if fade > 0.1:
                            targets_to_send[lbl] = build_target_output(
                                curr_3d, pred_3d, threat_scores[lbl], target_status[lbl], hold_age, False
                            )
                else:
                    target_status[lbl] = "IDLE"
                    threat_scores[lbl] = 0.0

            final_pts_data[lbl] = (curr_3d, pred_3d)

        # ==========================
        # Assign turrets and publish targets
        # ==========================
        turret_assignments = {0: None, 1: None}
        aimable_targets = {
            name: info for name, info in targets_to_send.items()
            if info.get("aim", False) and info.get("pos") is not None
        }
        if aimable_targets:
            sorted_tgts = sorted(aimable_targets.items(), key=lambda x: x[1]["threat"], reverse=True)
            if len(sorted_tgts) >= 1:
                turret_assignments[0] = sorted_tgts[0][0]
            if len(sorted_tgts) >= 2:
                turret_assignments[1] = sorted_tgts[1][0]
            elif len(sorted_tgts) == 1:
                turret_assignments[1] = sorted_tgts[0][0]

        try:
            sT.send(pickle.dumps({"targets": targets_to_send, "trims": calib_trims, "mode": fire_mode, "fusion_ts": time.time()}), zmq.NOBLOCK)
        except zmq.Again:
            pass

        current_time = time.time()
        maybe_print_sender_sync(current_time)
        if _fps_window_start == 0.0:
            _fps_window_start = current_time
        elapsed_fps = current_time - _fps_window_start
        if elapsed_fps >= 1.0:
            with shared_state.lock:
                rx_frames = shared_state.rx_frame_count
                shared_state.rx_frame_count = 0
            display_fps = rx_frames / elapsed_fps
            _fps_frame_count = 0
            _fps_window_start = current_time
        loop_ms_now = (current_time - loop_start) * 1000
        display_load = min(loop_ms_now / (100.0 if DETECT_MODE == "YOLO" else 33.3) * 100, 999)

        if current_time - last_panel_update > PANEL_UPDATE_INTERVAL:
            panel_fps_fixed = display_fps
            panel_load_fixed = display_load
            panel_loop_ms = loop_ms_now
            panel_cam_ages = cam_ages_now[:]
            last_panel_update = current_time
        # ==========================
        # UI/dashboard output: canvas/packet output is built only when actually due.
        # ==========================
        render_ui = ENABLE_UI and ((UI_RENDER_INTERVAL <= 0.0) or (current_time - last_ui_render_time >= UI_RENDER_INTERVAL))
        dashboard_due = ENABLE_DASHBOARD and dashboard_pub is not None and ((DASHBOARD_INTERVAL <= 0.0) or (current_time - last_dashboard_send_time >= DASHBOARD_INTERVAL))

        if render_ui:
            if cam_feeds is None:
                cam_feeds, _ = build_display_feeds_from_cache(current_time, corrected_ts)
            with shared_state.lock:
                shared_state.ui_cam_feeds = list(cam_feeds)
                shared_state.ui_final_pts_data = dict(final_pts_data)
                shared_state.ui_cam_ages = list(panel_cam_ages)
                shared_state.ui_threat_scores = dict(threat_scores)
                shared_state.ui_turret_assignments = dict(turret_assignments)
                shared_state.ui_target_status = dict(target_status)
                shared_state.ui_fps = panel_fps_fixed
                shared_state.ui_load = panel_load_fixed
                shared_state.ui_loop_ms = panel_loop_ms
            last_ui_render_time = current_time

        imshow_due = ENABLE_UI and (
            (UI_RENDER_INTERVAL <= 0.0)
            or (current_time - last_imshow_time >= UI_RENDER_INTERVAL)
        )
        if imshow_due:
            with shared_state.lock:
                canvas_to_show = shared_state.ready_canvas
            if canvas_to_show is not None:
                cv2.imshow("FUSION", canvas_to_show)
                last_imshow_time = current_time

        if dashboard_due:
            last_dashboard_send_time = current_time
            if cam_feeds is None:
                cam_feeds, _ = build_display_feeds_from_cache(current_time, corrected_ts)
            dashboard_pts_data = smooth_ui_points(final_pts_data)
            dashboard_packet = build_dashboard_packet(
                cam_feeds,
                cam_ages_now,
                dashboard_pts_data,
                threat_scores,
                turret_assignments,
                panel_fps_fixed,
                panel_load_fixed,
                panel_loop_ms,
                encode_frames=False,
                command_targets=targets_to_send,
            )
            dashboard_pub.submit(dashboard_packet)

        processing_time['times'].append(time.time() - loop_start)
        processing_time['avg'] = float(np.mean(processing_time['times']))

except KeyboardInterrupt:
    print("\n>> Exit")
except Exception as e:
    print(f"\n!! Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    shutdown_event.set()
    if 'dashboard_pub' in globals() and dashboard_pub is not None:
        dashboard_pub.stop()
    for thread_name in ("ui_thread", "rx_thread"):
        thread = globals().get(thread_name)
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
    for sock_name in ("sA", "sT", "sCMD"):
        sock = globals().get(sock_name)
        if sock is not None:
            sock.close()
    ctx.destroy()
    cv2.destroyAllWindows()
    print(">> Done")
