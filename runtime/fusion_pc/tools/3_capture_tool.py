1# -*- coding: utf-8 -*-
"""
3_capture_tool_ULTIMATE.py
완전 재설계 (검증 완료):
- 진행 바를 텍스트 아래로 이동
- 박스 높이 증가 (300 → 320)
- 모든 요소 간격 재계산
- 텍스트 절대 안 잘림
"""
import os
os.environ.setdefault("OPENCV_OPENCL_RUNTIME", "disabled")
import cv2
try:
    cv2.ocl.setUseOpenCL(False)
except cv2.error:
    pass
import zmq
import pickle
import re
import sys
import math
import numpy as np
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import config_turret as cfg
except ImportError:
    cfg = None

import common
import calibration_utils as calib_meta

BASE_DIR = os.path.join(PROJECT_ROOT, "calibration_images")
IMAGE_EXT = ".png"
NETWORK_CFG = getattr(cfg, "NETWORK", {}) if cfg is not None else {}
VIDEO_PORT = int(NETWORK_CFG.get("video_port", 5555))
EXPECTED_CAPTURE_SIZE = tuple(getattr(cfg, "CALIB_RESOLUTION", (1280, 720))) if cfg is not None else (1280, 720)
MOUNT_ANGLE_DEG = float(getattr(cfg, "FUSION_PARAMS", {}).get("mount_angle_deg", 20.0)) if cfg is not None else 20.0

MIN_CAPTURE_QUALITY = 60
MIN_CAPTURE_SHARPNESS = float(getattr(calib_meta, "MIN_USABLE_SHARPNESS", 200.0))
MIN_AUTO_SIGNATURE_DELTA = 0.075
AUTO_CAPTURE_COOLDOWN_S = 1.5
SYNC_CFG = getattr(cfg, "SYNC", {}) if cfg is not None else {}
PAIR_SYNC_WINDOW = float(SYNC_CFG.get("pair_sync_window", 0.14))
PREVIEW_EVAL_INTERVAL = 0.35
STEREO_PREVIEW_EVAL_INTERVAL = 0.75
STEREO_LIVE_CHECK_ENABLED = False
ZMQ_DRAIN_LIMIT = 8
DISPLAY_MARGIN_W = 120
DISPLAY_MARGIN_H = 180
DISPLAY_FALLBACK_MAX_W = 1700
DISPLAY_FALLBACK_MAX_H = 920
DISPLAY_PANEL_H = 300
_DISPLAY_LIMIT_CACHE = None

CAPTURE_PROTOCOL = {
    "single": [
        {"name": "free", "desc": "Free Quality Capture", "count": 40, "repeat": True}
    ],
    "stereo": [
        {"name": "free", "desc": "Free Stereo Capture", "count": 30, "repeat": True}
    ]
}

DETAILED_GUIDE = {"single": {}, "stereo": {}}

def get_next_file_number(folder_path):
    if not os.path.exists(folder_path):
        return 1
    files = os.listdir(folder_path)
    max_num = 0
    for file in files:
        if file.lower().endswith((".jpg", ".jpeg", ".png")):
            match = re.search(r'img_(\d+)', file)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num
    return max_num + 1

def board_roi(gray, corners, pad=12):
    if corners is None:
        return gray
    pts = np.asarray(corners, dtype=np.float32).reshape(-1, 2)
    x0, y0 = np.floor(np.min(pts, axis=0)).astype(int)
    x1, y1 = np.ceil(np.max(pts, axis=0)).astype(int)
    h, w = gray.shape[:2]
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(w, x1 + pad)
    y1 = min(h, y1 + pad)
    if x1 <= x0 or y1 <= y0:
        return gray
    return gray[y0:y1, x0:x1]


def calculate_sharpness(image, corners=None):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = board_roi(gray, corners)
    return cv2.Laplacian(gray, cv2.CV_64F).var()

def evaluate_image_quality(image, corners=None):
    sharpness = calculate_sharpness(image, corners)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    brightness = np.mean(gray)
    contrast = np.std(gray)

    feedback = []
    quality_score = 0

    if sharpness > 500:
        feedback.append("Sharp:Excellent")
        quality_score += 40
    elif sharpness > 200:
        feedback.append("Sharp:Good")
        quality_score += 25
    else:
        feedback.append("Sharp:Poor")
        quality_score += 10

    if 80 < brightness < 180:
        feedback.append("Light:OK")
        quality_score += 30
    elif brightness <= 80:
        feedback.append("Light:Dark")
        quality_score += 10
    else:
        feedback.append("Light:Bright")
        quality_score += 10

    if contrast > 40:
        feedback.append("Contrast:Good")
        quality_score += 30
    else:
        feedback.append("Contrast:Fair")
        quality_score += 15

    return quality_score, feedback, sharpness

def checkerboard_diagnostics(image, robust=True):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    found, corners = common.find_checkerboard_corners(gray, robust=robust)
    if not found:
        return False, ["Board:Missing"], None

    pts = corners.reshape(-1, 2)
    h, w = gray.shape[:2]
    x0, y0 = np.min(pts, axis=0)
    x1, y1 = np.max(pts, axis=0)
    bw = max(float(x1 - x0), 1.0)
    bh = max(float(y1 - y0), 1.0)
    coverage = (bw * bh) / float(w * h)
    cx = float((x0 + x1) * 0.5 / w)
    cy = float((y0 + y1) * 0.5 / h)

    feedback = ["Board:OK"]
    ok = True
    margin_px = 8.0

    # Far/edge board poses are valuable for calibration. Size is advisory only;
    # hard reject only missing checkerboards, clipped boards, bad sharpness, or wrong resolution.
    if coverage < 0.035:
        feedback.append("Board:TooSmall")
    elif coverage < 0.08:
        feedback.append("Board:Small")
    elif coverage > 0.75:
        feedback.append("Board:TooClose")
    else:
        feedback.append(f"Area:{coverage*100:.0f}%")

    if x0 < margin_px or y0 < margin_px or x1 > (w - margin_px) or y1 > (h - margin_px):
        feedback.append("Board:Clipped")
        ok = False
    elif not (0.10 <= cx <= 0.90 and 0.10 <= cy <= 0.90):
        feedback.append("Board:Edge")

    return ok, feedback, corners

def evaluate_capture_frame(image, robust=True):
    h, w = image.shape[:2]
    board_ok, board_feedback, corners = checkerboard_diagnostics(image, robust=robust)
    quality, feedback, sharpness = evaluate_image_quality(image, corners)
    size_ok = (w, h) == EXPECTED_CAPTURE_SIZE
    sharp_ok = sharpness >= MIN_CAPTURE_SHARPNESS
    ok = quality >= MIN_CAPTURE_QUALITY and sharp_ok and board_ok and size_ok
    if not size_ok:
        feedback.append(f"Size:{w}x{h}")
    if not sharp_ok:
        feedback.append(f"SharpGate:{sharpness:.0f}<{MIN_CAPTURE_SHARPNESS:.0f}")
    feedback.extend(board_feedback)
    return ok, quality, feedback, sharpness, corners


def evaluate_single_state(image, robust=True):
    ok, quality, feedback, sharpness, corners = evaluate_capture_frame(image, robust=robust)
    signature = checkerboard_signature(corners, image.shape)
    return ok, quality, feedback, sharpness, corners, signature


def evaluate_stereo_state(left_image, right_image, left_info, right_info, robust=True):
    ok_l, quality_l, feedback_l, sharpness_l, corners_l = evaluate_capture_frame(left_image, robust=robust)
    ok_r, quality_r, feedback_r, sharpness_r, corners_r = evaluate_capture_frame(right_image, robust=robust)
    capture_ok = ok_l and ok_r
    quality = min(quality_l, quality_r)
    feedback = [f"L:{x}" for x in feedback_l] + [f"R:{x}" for x in feedback_r]
    sharpness = min(sharpness_l, sharpness_r)
    sig_l = checkerboard_signature(corners_l, left_image.shape)
    sig_r = checkerboard_signature(corners_r, right_image.shape)
    signature = np.concatenate([sig_l, sig_r]) if sig_l is not None and sig_r is not None else None
    sync_ok, pair_dt_s, sync_source = pair_sync_status(left_info, right_info)
    if not sync_ok:
        if pair_dt_s is None:
            feedback.append("SYNC:missing")
        else:
            feedback.append(f"SYNC:{pair_dt_s:.3f}s>{PAIR_SYNC_WINDOW:.3f}s")
    else:
        feedback.append(f"SYNC:{pair_dt_s:.3f}s/{sync_source}")
    capture_ok = capture_ok and sync_ok
    return capture_ok, quality, feedback, sharpness, corners_l, corners_r, signature

def draw_checkerboard_preview(image, corners, ok):
    if corners is None:
        return
    color = (0, 255, 0) if ok else (0, 180, 255)
    cv2.drawChessboardCorners(image, common.CHECKERBOARD, corners, True)
    pts = corners.reshape(-1, 2)
    x0, y0 = np.min(pts, axis=0).astype(int)
    x1, y1 = np.max(pts, axis=0).astype(int)
    cv2.rectangle(image, (x0, y0), (x1, y1), color, 2)

def checkerboard_signature(corners, image_shape):
    if corners is None:
        return None
    pts = corners.reshape(-1, 2)
    h, w = image_shape[:2]
    x0, y0 = np.min(pts, axis=0)
    x1, y1 = np.max(pts, axis=0)
    center_x = float((x0 + x1) * 0.5 / w)
    center_y = float((y0 + y1) * 0.5 / h)
    area = float((x1 - x0) * (y1 - y0) / max(w * h, 1))
    angle = calib_meta.roll_from_corners(pts) / 90.0
    return np.array([center_x, center_y, area, angle], dtype=np.float32)

def signature_changed(sig, last_sig, min_delta=0.035):
    if sig is None or last_sig is None:
        return True
    a = np.asarray(sig, dtype=np.float32)
    b = np.asarray(last_sig, dtype=np.float32)
    if a.shape != b.shape:
        return True
    return float(np.linalg.norm(a - b)) >= min_delta



def _as_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pair_sync_status(left_info, right_info):
    same_packet = (
        left_info.get("sender_id") == right_info.get("sender_id")
        and left_info.get("seq") is not None
        and left_info.get("seq") == right_info.get("seq")
    )
    if same_packet:
        for key in ("pair_dt_s", "pair_dt"):
            dt = _as_float_or_none(left_info.get(key))
            if dt is None:
                dt = _as_float_or_none(right_info.get(key))
            if dt is not None:
                return dt <= PAIR_SYNC_WINDOW, dt, key

    for key in ("frame_ts", "packet_ts", "recv_local_ts"):
        left_ts = _as_float_or_none(left_info.get(key))
        right_ts = _as_float_or_none(right_info.get(key))
        if left_ts is None or right_ts is None:
            continue
        dt = abs(left_ts - right_ts)
        return dt <= PAIR_SYNC_WINDOW, dt, key

    return False, None, "missing"


def count_existing_progress(target_dir, protocol, mode_type):
    counts = {step["name"]: 0 for step in protocol}
    scores = []
    free_repeat = len(protocol) == 1 and protocol[0].get("repeat") and protocol[0].get("name") == "free"
    if mode_type == "stereo":
        records = calib_meta.stereo_records(target_dir, include_flagged=False)
    else:
        records = calib_meta.single_records_by_file(target_dir, include_flagged=False).values()
    for record in records:
        step_name = record.get("step")
        if free_repeat:
            counts["free"] += 1
        elif step_name in counts:
            counts[step_name] += 1
        else:
            continue
        if "quality_score" in record:
            scores.append(float(record["quality_score"]))

    if free_repeat:
        total = counts.get("free", 0)
        return 0, total, total, scores

    total = sum(min(counts[step["name"]], step["count"]) for step in protocol)
    step_index = 0
    step_count = 0
    for idx, step in enumerate(protocol):
        have = counts.get(step["name"], 0)
        if have < step["count"]:
            step_index = idx
            step_count = have
            break
    else:
        step_index = len(protocol)
    return step_index, step_count, total, scores

def make_single_record(cam_id, filename, step, quality, feedback, sharpness, corners, image):
    pose = calib_meta.pose_from_corners(corners, image.shape) if corners is not None else None
    h, w = image.shape[:2]
    return {
        "schema_version": calib_meta.METADATA_SCHEMA_VERSION,
        "mode": "single",
        "camera_id": int(cam_id),
        "file": filename,
        "step": step["name"],
        "captured_at_utc": calib_meta.utc_now_iso(),
        "width": int(w),
        "height": int(h),
        "quality_score": int(quality),
        "quality_feedback": list(feedback),
        "sharpness": float(sharpness),
        "force_saved": False,
        "quality_failed": bool(quality < MIN_CAPTURE_QUALITY),
        "checkerboard_failed": bool(corners is None),
        "resolution_failed": bool((w, h) != EXPECTED_CAPTURE_SIZE),
        "pose": pose,
    }

def make_stereo_record(pair_name, left_file, right_file, step, quality, feedback, sharpness,
                       left_corners, right_corners, left_image, right_image, left_info, right_info):
    lh, lw = left_image.shape[:2]
    rh, rw = right_image.shape[:2]
    left_ts = left_info.get("frame_ts")
    right_ts = right_info.get("frame_ts")
    sync_ok, pair_dt, sync_source = pair_sync_status(left_info, right_info)
    return {
        "schema_version": calib_meta.METADATA_SCHEMA_VERSION,
        "mode": "stereo",
        "pair": pair_name,
        "left_file": left_file,
        "right_file": right_file,
        "step": step["name"],
        "captured_at_utc": calib_meta.utc_now_iso(),
        "left_width": int(lw),
        "left_height": int(lh),
        "right_width": int(rw),
        "right_height": int(rh),
        "left_ts": left_ts,
        "right_ts": right_ts,
        "left_recv_local_ts": left_info.get("recv_local_ts"),
        "right_recv_local_ts": right_info.get("recv_local_ts"),
        "pair_dt_s": pair_dt,
        "sync_source": sync_source,
        "sync_ok": bool(sync_ok),
        "sync_failed": bool(not sync_ok),
        "sender_left": left_info.get("sender_id"),
        "sender_right": right_info.get("sender_id"),
        "seq_left": left_info.get("seq"),
        "seq_right": right_info.get("seq"),
        "quality_score": int(quality),
        "quality_feedback": list(feedback),
        "sharpness": float(sharpness),
        "force_saved": False,
        "quality_failed": bool(quality < MIN_CAPTURE_QUALITY),
        "checkerboard_failed": bool(left_corners is None or right_corners is None),
        "resolution_failed": bool((lw, lh) != EXPECTED_CAPTURE_SIZE or (rw, rh) != EXPECTED_CAPTURE_SIZE),
        "pose_left": calib_meta.pose_from_corners(left_corners, left_image.shape) if left_corners is not None else None,
        "pose_right": calib_meta.pose_from_corners(right_corners, right_image.shape) if right_corners is not None else None,
    }

def decode_frame(payload):
    arr = payload if isinstance(payload, np.ndarray) else np.frombuffer(payload, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)

def screen_limited_display_size():
    global _DISPLAY_LIMIT_CACHE
    if _DISPLAY_LIMIT_CACHE is not None:
        return _DISPLAY_LIMIT_CACHE
    max_w = DISPLAY_FALLBACK_MAX_W
    max_h = DISPLAY_FALLBACK_MAX_H
    try:
        import ctypes
        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
        screen_w = int(user32.GetSystemMetrics(0))
        screen_h = int(user32.GetSystemMetrics(1))
        if screen_w > 0 and screen_h > 0:
            max_w = min(DISPLAY_FALLBACK_MAX_W, max(640, screen_w - DISPLAY_MARGIN_W))
            max_h = min(DISPLAY_FALLBACK_MAX_H, max(480, screen_h - DISPLAY_MARGIN_H))
    except Exception:
        pass
    _DISPLAY_LIMIT_CACHE = (max_w, max_h)
    return _DISPLAY_LIMIT_CACHE


def resize_keep_aspect_with_scale(image, max_w, max_h):
    h, w = image.shape[:2]
    scale = min(1.0, max_w / max(float(w), 1.0), max_h / max(float(h), 1.0))
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    if new_w == w and new_h == h:
        return image.copy(), 1.0
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA), scale


def resize_keep_aspect(image, max_w, max_h):
    resized, _ = resize_keep_aspect_with_scale(image, max_w, max_h)
    return resized


def fit_camera_to_layout(camera_display):
    max_w, max_h = screen_limited_display_size()
    max_camera_h = max(220, max_h - DISPLAY_PANEL_H)
    return resize_keep_aspect(camera_display, max_w, max_camera_h)


def scaled_corners(corners, scale):
    if corners is None:
        return None
    if abs(float(scale) - 1.0) < 1e-6:
        return corners
    return (corners.astype(np.float32) * float(scale)).astype(np.float32)


def pad_to_height(image, target_h):
    h, w = image.shape[:2]
    if h >= target_h:
        return image
    padded = np.zeros((target_h, w, 3), dtype=image.dtype)
    padded[:] = (20, 20, 20)
    padded[:h, :w] = image
    return padded


def build_stereo_display(left_image, right_image, left_corners, right_corners,
                         capture_ok, left_label, right_label):
    max_w, max_h = screen_limited_display_size()
    max_camera_h = max(220, max_h - DISPLAY_PANEL_H)
    per_cam_w = max(320, max_w // 2)
    left_disp, left_scale = resize_keep_aspect_with_scale(left_image, per_cam_w, max_camera_h)
    right_disp, right_scale = resize_keep_aspect_with_scale(right_image, per_cam_w, max_camera_h)

    draw_checkerboard_preview(left_disp, scaled_corners(left_corners, left_scale), capture_ok)
    draw_checkerboard_preview(right_disp, scaled_corners(right_corners, right_scale), capture_ok)
    cv2.putText(left_disp, left_label, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(right_disp, right_label, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    if left_disp.shape[0] != right_disp.shape[0]:
        target_h = max(left_disp.shape[0], right_disp.shape[0])
        left_disp = pad_to_height(left_disp, target_h)
        right_disp = pad_to_height(right_disp, target_h)
    return np.hstack([left_disp, right_disp])


def drain_latest_packet(socket):
    """Return the newest waiting packet so display never works through old frames."""
    raw_data = socket.recv(zmq.NOBLOCK)
    recv_ts = time.time()
    drained = 0
    while drained < ZMQ_DRAIN_LIMIT:
        try:
            raw_data = socket.recv(zmq.NOBLOCK)
            recv_ts = time.time()
            drained += 1
        except zmq.Again:
            break
    return raw_data, recv_ts, drained


def create_bottom_panel(step, current_count, total_count, total_captured,
                        quality_score, feedback, last_sharpness, mode_type,
                        step_guides, overall_step, panel_width):
    """완전 재설계된 하단 패널"""
    panel_height = DISPLAY_PANEL_H
    panel = np.zeros((panel_height, panel_width, 3), dtype=np.uint8)
    panel[:] = (35, 35, 35)

    # 상단 구분선
    cv2.line(panel, (0, 0), (panel_width, 0), (100, 100, 100), 4)

    margin = 12
    box_y = 12
    box_height = panel_height - 24

    # 박스 너비 계산 (5개)
    total_margin = margin * 6
    available_width = panel_width - total_margin
    box_widths = [
        int(available_width * 0.16),  # OVERALL (작게)
        int(available_width * 0.24),  # CURRENT STEP
        int(available_width * 0.24),  # QUALITY RULES
        int(available_width * 0.20),  # QUALITY
        int(available_width * 0.16)   # CONTROLS (작게)
    ]

    current_x = margin

    # ========== BOX 1: OVERALL ==========
    box_x = current_x
    box_w = box_widths[0]

    # 박스 배경 및 테두리
    cv2.rectangle(panel, (box_x, box_y), (box_x + box_w, box_y + box_height),
                  (45, 45, 45), -1)
    cv2.rectangle(panel, (box_x, box_y), (box_x + box_w, box_y + box_height),
                  (70, 70, 70), 2)

    # 제목
    y = box_y + 30
    cv2.putText(panel, "OVERALL", (box_x + 15, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 2)
    cv2.line(panel, (box_x + 10, y + 8), (box_x + box_w - 10, y + 8),
             (70, 70, 70), 1)

    # 진행률 텍스트 (진행 바 위에)
    y += 40
    actual_captured = max(int(total_captured), 0)
    progress = actual_captured / total_count if total_count > 0 else 0
    progress = float(np.clip(progress, 0.0, 1.0))
    count_text = f"{actual_captured}/{total_count}" if actual_captured <= total_count else f"{actual_captured}/{total_count}+"
    cv2.putText(panel, count_text, (box_x + 15, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # 진행 바 (텍스트 아래)
    y += 25
    bar_w = box_w - 30
    bar_x = box_x + 15
    cv2.rectangle(panel, (bar_x, y), (bar_x + bar_w, y + 30), (60, 60, 60), -1)
    cv2.rectangle(panel, (bar_x, y), (bar_x + int(bar_w * progress), y + 30),
                  (0, 200, 0), -1)

    # 퍼센트 (진행 바 아래)
    y += 55
    cv2.putText(panel, f"{int(progress*100)}%", (box_x + 20, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    current_x += box_w + margin

    # ========== BOX 2: CURRENT STEP ==========
    box_x = current_x
    box_w = box_widths[1]

    cv2.rectangle(panel, (box_x, box_y), (box_x + box_w, box_y + box_height),
                  (45, 45, 45), -1)
    cv2.rectangle(panel, (box_x, box_y), (box_x + box_w, box_y + box_height),
                  (70, 70, 70), 2)

    # 제목
    y = box_y + 30
    cv2.putText(panel, "CAPTURE", (box_x + 15, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 2)
    cv2.line(panel, (box_x + 10, y + 8), (box_x + box_w - 10, y + 8),
             (70, 70, 70), 1)

    # 단계 이름
    y += 35
    cv2.putText(panel, step['desc'], (box_x + 15, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    # 자유 촬영 안내
    y += 28
    cv2.putText(panel, 'manual pose / quality gate', (box_x + 15, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 180, 180), 1)

    # 단계 진행 텍스트
    y += 30
    step_progress = current_count / step['count'] if step['count'] > 0 else 0
    step_progress = float(np.clip(step_progress, 0.0, 1.0))
    cv2.putText(panel, f"{current_count}/{step['count']}", (box_x + 15, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    # 단계 진행 바
    y += 20
    bar_w = box_w - 30
    bar_x = box_x + 15
    cv2.rectangle(panel, (bar_x, y), (bar_x + bar_w, y + 25), (60, 60, 60), -1)
    cv2.rectangle(panel, (bar_x, y), (bar_x + int(bar_w * step_progress), y + 25),
                  (255, 200, 0), -1)

    # 단계 퍼센트
    y += 45
    cv2.putText(panel, f"{int(step_progress*100)}%", (box_x + 15, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 200, 0), 1)

    current_x += box_w + margin

    # ========== BOX 3: QUALITY RULES ==========
    box_x = current_x
    box_w = box_widths[2]

    cv2.rectangle(panel, (box_x, box_y), (box_x + box_w, box_y + box_height),
                  (45, 45, 45), -1)
    cv2.rectangle(panel, (box_x, box_y), (box_x + box_w, box_y + box_height),
                  (70, 70, 70), 2)

    # 제목
    y = box_y + 30
    cv2.putText(panel, "QUALITY ONLY", (box_x + 15, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 2)
    cv2.line(panel, (box_x + 10, y + 8), (box_x + box_w - 10, y + 8),
             (70, 70, 70), 1)

    # 품질 전용 안내
    y += 40
    guide_lines = [
        "No pose/distance lock",
        "Move board freely",
        "Checkerboard required",
        "Q >= 60 required",
        "Sharp >= 200 required",
        "No confirmation prompts",
    ]
    for line in guide_lines:
        cv2.putText(panel, line, (box_x + 15, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)
        y += 22
    current_x += box_w + margin

    # ========== BOX 4: QUALITY ==========
    box_x = current_x
    box_w = box_widths[3]

    cv2.rectangle(panel, (box_x, box_y), (box_x + box_w, box_y + box_height),
                  (45, 45, 45), -1)
    cv2.rectangle(panel, (box_x, box_y), (box_x + box_w, box_y + box_height),
                  (70, 70, 70), 2)

    # 제목
    y = box_y + 30
    cv2.putText(panel, "QUALITY", (box_x + 15, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 2)
    cv2.line(panel, (box_x + 10, y + 8), (box_x + box_w - 10, y + 8),
             (70, 70, 70), 1)

    # 품질 정보
    y += 40
    if quality_score > 0:
        if quality_score >= 70:
            score_color = (0, 255, 0)
            grade = "GOOD"
        elif quality_score >= 60:
            score_color = (0, 200, 255)
            grade = "OK"
        else:
            score_color = (0, 100, 255)
            grade = "RETAKE"

        cv2.putText(panel, f"{quality_score}/100", (box_x + 15, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, score_color, 2)
        y += 30
        cv2.putText(panel, f"({grade})", (box_x + 15, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, score_color, 1)
        y += 30

        shown_feedback = list(feedback[:6])
        if len(feedback) > 6:
            shown_feedback.append(f"+{len(feedback) - 6} more")
        for fb in shown_feedback:
            cv2.putText(panel, fb, (box_x + 15, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            y += 22

        y += 10
        cv2.putText(panel, f"Sharp:{last_sharpness:.0f}", (box_x + 15, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (150, 150, 150), 1)
    else:
        cv2.putText(panel, "No capture", (box_x + 15, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (150, 150, 150), 1)
        y += 25
        cv2.putText(panel, "yet", (box_x + 15, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (150, 150, 150), 1)

    current_x += box_w + margin

    # ========== BOX 5: CONTROLS ==========
    box_x = current_x
    box_w = box_widths[4]

    cv2.rectangle(panel, (box_x, box_y), (box_x + box_w, box_y + box_height),
                  (45, 45, 45), -1)
    cv2.rectangle(panel, (box_x, box_y), (box_x + box_w, box_y + box_height),
                  (70, 70, 70), 2)

    # 제목
    y = box_y + 30
    cv2.putText(panel, "CONTROLS", (box_x + 15, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 200, 255), 2)
    cv2.line(panel, (box_x + 10, y + 8), (box_x + box_w - 10, y + 8),
             (70, 70, 70), 1)

    # 조작키
    y += 30
    cv2.putText(panel, "[S]/Click Save", (box_x + 12, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1)
    y += 25
    cv2.putText(panel, "[N] Finish", (box_x + 12, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1)
    y += 25
    cv2.putText(panel, "[ESC] Exit", (box_x + 12, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1)

    # 팁
    y += 35
    cv2.putText(panel, "TIPS:", (box_x + 12, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 200, 0), 1)
    y += 22
    cv2.putText(panel, f"{EXPECTED_CAPTURE_SIZE[0]}x{EXPECTED_CAPTURE_SIZE[1]}", (box_x + 12, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1)
    y += 20
    cv2.putText(panel, "same focus/exposure", (box_x + 12, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1)
    y += 20
    cv2.putText(panel, "manual varied poses", (box_x + 12, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1)

    return panel

def main():
    print("=" * 80)
    print(f"  CALIBRATION TOOL - {EXPECTED_CAPTURE_SIZE[0]}x{EXPECTED_CAPTURE_SIZE[1]} RUNTIME")
    print(f"  Camera mount angle in config: {MOUNT_ANGLE_DEG:.1f} deg")
    print("  Keep focus/exposure/stream resolution identical to the final runtime.")
    print("  Move the board freely; this tool only accepts/rejects by image quality.")
    print("=" * 80)

    mode = input("Mode (1:Single, 2:Stereo): ")

    if mode == "1":
        cam_id = input("Camera (0-3): ")
        if cam_id not in {"0", "1", "2", "3"}:
            raise SystemExit("Camera must be 0, 1, 2, or 3")
        single_cam_idx = int(cam_id)
        target_dir = os.path.join(BASE_DIR, "single", f"cam{cam_id}")
        protocol = CAPTURE_PROTOCOL["single"]
        pair_name = None
        mode_type = "single"
    else:
        c1 = input("Left Cam (0-3): ")
        c2 = input("Right Cam (0-3): ")
        if c1 not in {"0", "1", "2", "3"} or c2 not in {"0", "1", "2", "3"}:
            raise SystemExit("Camera must be 0, 1, 2, or 3")
        left_cam_idx = int(c1)
        right_cam_idx = int(c2)
        if left_cam_idx >= right_cam_idx:
            raise SystemExit("Use lower camera id as Left Cam. Fusion expects pairs like cam01, cam12, cam23.")
        pair_name = f"cam{c1}{c2}"
        target_dir = os.path.join(BASE_DIR, pair_name)
        protocol = CAPTURE_PROTOCOL["stereo"]
        mode_type = "stereo"

    if pair_name:
        os.makedirs(os.path.join(target_dir, "left"), exist_ok=True)
        os.makedirs(os.path.join(target_dir, "right"), exist_ok=True)
    else:
        os.makedirs(target_dir, exist_ok=True)

    context = zmq.Context()
    sA = context.socket(zmq.SUB)
    sA.setsockopt(zmq.LINGER, 0)
    sA.setsockopt(zmq.RCVHWM, 1)
    sA.bind(f"tcp://*:{VIDEO_PORT}")
    sA.setsockopt_string(zmq.SUBSCRIBE, "")
    sA.setsockopt(zmq.CONFLATE, 1)
    poller = zmq.Poller()
    poller.register(sA, zmq.POLLIN)
    print(f">> Listening on tcp://*:{VIDEO_PORT}")
    print(f">> Expected calibration frame size: {EXPECTED_CAPTURE_SIZE[0]}x{EXPECTED_CAPTURE_SIZE[1]}")

    total_count = sum(s['count'] for s in protocol)
    print(f"\nRecommended minimum: {total_count} accepted shots")
    print("Press [S] or left-click the preview to save a quality-passed frame, [N] to finish, [ESC] to exit.\n")

    buf = {}
    buf_info = {}
    warned_size = set()
    current_step, current_step_count, total_captured, quality_scores = count_existing_progress(target_dir, protocol, mode_type)
    if current_step >= len(protocol):
        print(">> Existing metadata already satisfies this capture protocol.")
        return
    if total_captured > 0:
        print(f">> Resumed from metadata: {total_captured}/{total_count} usable captures")
    last_quality = 0
    last_feedback = []
    last_sharpness = 0
    auto_capture = False
    last_auto_time = 0.0
    last_saved_signature = None
    last_wait_report = 0.0
    last_missing_report = 0.0
    last_sender_id = None
    last_eval_time = 0.0
    current_guide_feedback = "QualityOnly"
    current_capture_ok = False
    current_quality = 0
    current_feedback = ["Preview: waiting"]
    current_sharpness = 0.0
    current_signature = None
    current_corners = None
    current_left_corners = None
    current_right_corners = None

    window_name = "Calibration Tool ULTIMATE"
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
    mouse_capture_request = {"pending": False}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            mouse_capture_request["pending"] = True

    cv2.setMouseCallback(window_name, on_mouse)

    while current_step < len(protocol):
        step = protocol[current_step]
        step_guides = None

        try:
            events = dict(poller.poll(100))
            if sA not in events:
                now = time.time()
                if now - last_wait_report >= 2.0:
                    print(
                        "[WAIT] No video packets on tcp://*:5555. "
                        "Check sender --laptop-ip, Ethernet IP, firewall, and rpicam camera status.",
                        flush=True,
                    )
                    last_wait_report = now
                cv2.waitKey(1)
                continue

            raw_data, recv_local_ts, _drained_packets = drain_latest_packet(sA)
            d = pickle.loads(raw_data)
            last_sender_id = d.get("sender_id")

            if d.get("id") == "stereo":
                for key, payload in d.items():
                    if key.startswith("img") and key[3:].isdigit():
                        frame = decode_frame(payload)
                        if frame is not None:
                            cam_idx = int(key[3:])
                            h, w = frame.shape[:2]
                            if (w, h) != EXPECTED_CAPTURE_SIZE and cam_idx not in warned_size:
                                print(
                                    f"\n[WARN] Cam {cam_idx} frame is {w}x{h}, "
                                    f"but CALIB_RESOLUTION is {EXPECTED_CAPTURE_SIZE[0]}x{EXPECTED_CAPTURE_SIZE[1]}."
                                )
                                print("       Calibration capture must match CALIB_RESOLUTION. Runtime low-latency streams are handled separately by RUNTIME_STREAM.\n")
                                warned_size.add(cam_idx)
                            buf[cam_idx] = frame
                            buf_info[cam_idx] = {
                                "frame_ts": d.get(f"{key}_ts"),
                                "packet_ts": d.get("ts"),
                                "pair_dt_s": d.get("pair_dt_s", d.get("pair_dt")),
                                "recv_local_ts": recv_local_ts,
                                "sender_id": d.get("sender_id"),
                                "seq": d.get("seq"),
                            }
            else:
                continue

            if pair_name:
                if left_cam_idx not in buf or right_cam_idx not in buf:
                    now = time.time()
                    if now - last_missing_report >= 2.0:
                        missing = [
                            str(cam) for cam in (left_cam_idx, right_cam_idx)
                            if cam not in buf
                        ]
                        print(
                            f"[WAIT] Receiving cams {sorted(buf.keys())} "
                            f"from sender={last_sender_id}, but pair {left_cam_idx}{right_cam_idx} "
                            f"is missing cam(s): {', '.join(missing)}.",
                            flush=True,
                        )
                        last_missing_report = now
                    continue

                now_eval = time.time()
                if STEREO_LIVE_CHECK_ENABLED and now_eval - last_eval_time >= STEREO_PREVIEW_EVAL_INTERVAL:
                    (
                        current_capture_ok,
                        current_quality,
                        current_feedback,
                        current_sharpness,
                        current_left_corners,
                        current_right_corners,
                        current_signature,
                    ) = evaluate_stereo_state(
                        buf[left_cam_idx],
                        buf[right_cam_idx],
                        buf_info.get(left_cam_idx, {}),
                        buf_info.get(right_cam_idx, {}),
                        robust=False,
                    )
                    last_eval_time = now_eval
                elif not STEREO_LIVE_CHECK_ENABLED:
                    current_capture_ok = False
                    current_quality = 0
                    current_feedback = ["PreviewOnly", "Press S/click to check/save"]
                    current_sharpness = 0.0
                    current_left_corners = None
                    current_right_corners = None
                    current_signature = None
                current_guide_feedback = 'QualityOnly'
                camera_display = build_stereo_display(
                    buf[left_cam_idx],
                    buf[right_cam_idx],
                    current_left_corners,
                    current_right_corners,
                    current_capture_ok,
                    f"Cam {left_cam_idx} REF",
                    f"Cam {right_cam_idx} visible",
                )
            else:
                if single_cam_idx not in buf:
                    now = time.time()
                    if now - last_missing_report >= 2.0:
                        print(
                            f"[WAIT] Receiving cams {sorted(buf.keys())} "
                            f"from sender={last_sender_id}, but selected cam{single_cam_idx} is missing. "
                            "For cam0/cam1 use sender_FIXED_2.py; for cam2/cam3 use sender2_FIXED_2.py.",
                            flush=True,
                        )
                        last_missing_report = now
                    continue

                camera_display = buf[single_cam_idx].copy()
                now_eval = time.time()
                if now_eval - last_eval_time >= PREVIEW_EVAL_INTERVAL:
                    (
                        current_capture_ok,
                        current_quality,
                        current_feedback,
                        current_sharpness,
                        current_corners,
                        current_signature,
                    ) = evaluate_single_state(buf[single_cam_idx], robust=False)
                    last_eval_time = now_eval
                current_guide_feedback = 'QualityOnly'
                draw_checkerboard_preview(camera_display, current_corners, current_capture_ok)

                cv2.putText(camera_display, f"Cam {cam_id}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            panel_feedback = list(current_feedback)
            panel_feedback.append("QualityOnly")

            if pair_name:
                camera_preview = camera_display
            else:
                camera_preview = fit_camera_to_layout(camera_display)
            panel_width = camera_preview.shape[1]
            bottom_panel = create_bottom_panel(
                step, current_step_count, total_count, total_captured,
                current_quality, panel_feedback, current_sharpness, mode_type,
                step_guides, current_step + 1, panel_width
            )

            combined = np.vstack([camera_preview, bottom_panel])
            if pair_name and not STEREO_LIVE_CHECK_ENABLED:
                status_color = (0, 180, 255)
                status_label = "PREVIEW ONLY - S/CLICK"
            else:
                status_color = (0, 255, 0) if current_capture_ok else (0, 180, 255)
                status_label = "QUALITY OK" if current_capture_ok else "WAIT QUALITY"
            cv2.putText(combined, status_label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)

            cv2.imshow(window_name, combined)

            key = cv2.waitKey(1) & 0xFF
            mouse_trigger = bool(mouse_capture_request.get("pending"))
            if mouse_trigger:
                mouse_capture_request["pending"] = False

            if key == 27:
                break

            if key == ord('a') or key == ord('A'):
                print("\n>> Auto-capture is disabled in quality-only mode. Use S or left-click after moving the board.")

            auto_trigger = False

            if key == ord('s') or key == ord('S') or mouse_trigger or auto_trigger:
                if pair_name:
                    (
                        current_capture_ok,
                        current_quality,
                        current_feedback,
                        current_sharpness,
                        current_left_corners,
                        current_right_corners,
                        current_signature,
                    ) = evaluate_stereo_state(
                        buf[left_cam_idx],
                        buf[right_cam_idx],
                        buf_info.get(left_cam_idx, {}),
                        buf_info.get(right_cam_idx, {}),
                    )
                else:
                    (
                        current_capture_ok,
                        current_quality,
                        current_feedback,
                        current_sharpness,
                        current_corners,
                        current_signature,
                    ) = evaluate_single_state(buf[single_cam_idx])
                last_eval_time = time.time()
                capture_ok = current_capture_ok
                quality = current_quality
                feedback = current_feedback
                sharpness = current_sharpness
                last_quality = quality
                last_feedback = feedback
                last_sharpness = sharpness
                save_as_flagged = False

                if not capture_ok:
                    print(f"\n*** CAPTURE REJECTED: Q={quality}/100 ***")
                    print(f"    {' | '.join(feedback)}")
                    print("    Not saved. Move/steady/refocus the board and press S or click again.\n")
                    continue

                if pair_name:
                    left_dir = os.path.join(target_dir, "left")
                    right_dir = os.path.join(target_dir, "right")
                    next_idx = max(get_next_file_number(left_dir), get_next_file_number(right_dir))
                    fname = f"img_{next_idx:03d}_{step['name']}{IMAGE_EXT}"
                    left_path = os.path.join(left_dir, fname)
                    right_path = os.path.join(right_dir, fname)
                    if not common.imwrite_unicode(left_path, buf[left_cam_idx]):
                        print(f"[ERROR] failed to save left image: {left_path}")
                        continue
                    if not common.imwrite_unicode(right_path, buf[right_cam_idx]):
                        print(f"[ERROR] failed to save right image: {right_path}")
                        continue
                    record = make_stereo_record(
                        pair_name, fname, fname, step, quality, feedback, sharpness,
                        current_left_corners, current_right_corners,
                        buf[left_cam_idx], buf[right_cam_idx],
                        buf_info.get(left_cam_idx, {}), buf_info.get(right_cam_idx, {}),
                    )
                    record["force_saved"] = bool(save_as_flagged)
                    calib_meta.upsert_record(target_dir, record)
                    print(f"[OK] [{total_captured+1}/{total_count}] {fname} Q:{quality}")
                else:
                    next_idx = get_next_file_number(target_dir)
                    fname = f"img_{next_idx:03d}_{step['name']}{IMAGE_EXT}"
                    image_path = os.path.join(target_dir, fname)
                    if not common.imwrite_unicode(image_path, buf[single_cam_idx]):
                        print(f"[ERROR] failed to save image: {image_path}")
                        continue
                    record = make_single_record(cam_id, fname, step, quality, feedback, sharpness, current_corners, buf[single_cam_idx])
                    record["force_saved"] = bool(save_as_flagged)
                    calib_meta.upsert_record(target_dir, record)
                    print(f"[OK] [{total_captured+1}/{total_count}] {fname} Q:{quality}")

                last_saved_signature = np.copy(current_signature) if current_signature is not None else None
                last_auto_time = time.time()
                if save_as_flagged:
                    print("    Saved as flagged diagnostic image; it will not count toward calibration progress.")
                    continue
                quality_scores.append(quality)
                current_step_count += 1
                total_captured += 1

                if current_step_count == step['count']:
                    avg = np.mean(quality_scores[-step['count']:])
                    print(f"\n{'='*60}")
                    print(f"  Recommended minimum reached: {current_step_count}/{step['count']} accepted, Avg Q: {avg:.1f}")
                    print("  You can keep shooting freely, or press N/ESC to finish.")
                    print(f"{'='*60}\n")
                elif current_step_count > step['count'] and current_step_count % 10 == 0:
                    print(f">> Accepted {current_step_count} images. Continue or press N/ESC to finish.")

            elif key == ord('n') or key == ord('N'):
                print("\n>> Finished by user.")
                break
        except KeyboardInterrupt:
            print("\n>> Interrupted by user.")
            break
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            break

    print("\n" + "=" * 80)
    print("  COMPLETE")
    print("=" * 80)
    print(f"Captured: {total_captured}/{total_count}")
    if quality_scores:
        print(f"Avg Q: {np.mean(quality_scores):.1f}")
        print(f"Best: {max(quality_scores)} / Worst: {min(quality_scores)}")

    if total_captured < total_count * 0.8:
        print(f"\nWARNING: Low count ({total_captured}/{total_count})")
    else:
        print(f"\nSUCCESS!")

    context.destroy()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
