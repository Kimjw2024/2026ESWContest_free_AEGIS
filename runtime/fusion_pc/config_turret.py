# config_turret.py
import numpy as np
import os
import json

# [프로젝트 루트 / 데이터 경로]
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# [시스템]
CAM_HEIGHT_M = 0.073
CALIB_RESOLUTION = (1280, 720)

CAMERA_GEOMETRY = {
    "camera_count": 4,
    # Measured adjacent spacings: 0-1=149mm, 1-2=151mm, 2-3=149mm.
    # Calibration T vectors remain authoritative; these are expected/check values.
    "adjacent_baselines_m": {"01": 0.149, "12": 0.151, "23": 0.149},
    # Average fallback for UI drawing and any code path that cannot identify a pair.
    "camera_spacing_m": 0.1496666667,
}

RUNTIME_VALIDATION = {
    "strict_calibration": True,
    # Adjacent pairs are the minimum needed to connect all 4 cameras into cam0 frame.
    "required_calib_pairs": ["01", "12", "23"],
    # Load every valid pair that exists; non-required pairs improve robustness/precision.
    "loadable_calib_pairs": ["01", "02", "03", "12", "13", "23"],
    "allow_poor_calibration": False,
    "strict_stream_resolution": True,
}

CALIBRATION_QUALITY = {
    "min_single_images": 15,
    "min_stereo_pairs": 15,
    # Calibration selection is not a fixed-count downsample. It preserves
    # required pose coverage and only drops near-duplicate/weak/outlier views.
    "max_single_images": 60,
    "max_stereo_pairs": 50,
    "single_duplicate_pose_distance": 0.16,
    "stereo_duplicate_pose_distance": 0.16,
    # Stereo distance coverage is bucketed after all detected board sizes are known.
    # This avoids judging near/mid/far by fixed thresholds that can be wrong for a specific pair.
    "stereo_distance_bucket_mode": "relative",
    "stereo_relative_distance_min_log_span": 0.35,
    "stereo_relative_distance_far_quantile": 0.33,
    "stereo_relative_distance_near_quantile": 0.67,
    # Pair 13 is physically hard to capture close with the current camera spacing and board size.
    # For these optional wide-baseline pairs, calibration may accept broad grid/roll coverage
    # with only one distance bucket, but only when RMS/baseline/valid-pair checks are still strong.
    "distance_limited_stereo_pairs": ["13"],
    "distance_limited_min_valid_pairs": 35,
    "distance_limited_min_grid_cells": 8,
    "distance_limited_min_roll_buckets": 2,
    "distance_limited_max_rms": 0.45,
    "distance_limited_max_baseline_error_percent": 1.0,
    "distance_limited_coverage_max_view_error": 1.15,
    "single_rms_excellent": 0.30,
    "single_rms_good": 0.50,
    "single_max_view_error": 0.35,
    "single_filter_percentile": 90.0,
    "single_max_zscore": 3.0,
    "stereo_rms_excellent": 0.40,
    "stereo_rms_good": 0.75,
    "baseline_error_excellent_percent": 5.0,
    "baseline_error_good_percent": 7.0,
}

# Calibration/default stream profile for wired Raspberry Pi senders.
# Keep this matched to CALIB_RESOLUTION for calibration image capture.
CAMERA_STREAM = {
    "width": 1280,
    "height": 720,
    "fps": 20,
    "jpeg_quality": 76,
    "sensor_mode": "2304:1296",
    "rotation": 180,
}

# Low-latency runtime stream profile. Fusion scales 2D detections back to
# CALIB_RESOLUTION before triangulation, so calibration stays 1280x720.
RUNTIME_STREAM = {
    "width": 640,
    "height": 360,
    "fps": 30,
    "jpeg_quality": 70,
    "sensor_mode": "2304:1296",
    "rotation": 180,
}

NETWORK = {
    "laptop_ip": os.environ.get("AEGIS_LAPTOP_IP", os.environ.get("LAPTOP_IP", "192.0.2.10")),
    "video_port": 5555,
    "result_port": 5556,
    "ui_port": 5557,
    "ui_cmd_port": 5558,
    "transport": "wired_ethernet_zmq_jpeg",
    "video_rcvhwm": 2,
    "sender_sndhwm": 1,
    "video_conflate": False,
}

ARDUINO = {
    "port": "COM4",
    "baud": 115200,
    "use_microseconds": True,
}

DETECTION = {
    "default_mode": "YOLO",
    "yolo_model_path": "models/yolo26n.pt",
    "yolo_model_dir": "models",
    "yolo_fallback_model_path": "models/yolo26n.pt",
    "yolo_task": "auto",
    "yolo_pretrained_candidates": [
        "yolo26n.pt", "yolo26n.engine",
    ],
    "yolo_imgsz_gpu": 1280,
    "yolo_imgsz_cpu": 480,
    "yolo_conf": 0.25,
    "yolo_max_det": 1,
    "yolo_classes": [14],
    "yolo_custom_classes": "auto",
    "yolo_fallback_classes": [14],
    "yolo_center_mode": "box_anchor",
    "yolo_box_anchor": [0.50, 0.50],
    "yolo_keypoint_index": None,
    "yolo_min_box_area": 80,
    "yolo_assignment": "tracking",
    "yolo_rect": True,
    "yolo_warmup": True,
    "yolo_center_smooth_alpha": 0.25,
    "yolo_center_max_jump_px": 120,
    "yolo_allow_mono_aim": False,
    "hsv_full_resolution": False,
    "hsv_min_area": 25,
    "hsv_min_circularity": 0.0,
    "hsv_morph_close": True,
    "aim_static_targets": True,
    "target_count": 1,
}

HSV_COLORS = {
    "Target_1": {"lower": [100, 75, 60], "upper": [125, 255, 255]},
    "Target_2": {"lower": [105, 85, 70], "upper": [130, 255, 255]},
}

UI = {
    "enabled": True,
    "target_fps": 30,
    "draw_yolo_overlay": True,
    "dashboard_enabled": True,
    "dashboard_fps": 4,
    "dashboard_jpeg_quality": 65,
    "dashboard_command_max_age": 0.5,
    "smooth_alpha": 0.75,
    "pred_alpha": 0.55,
    "deadband_m": 0.003,
    "snap_m": 0.25,
}

# [퓨전]
FUSION_PARAMS = {
    "mount_angle_deg": 20.0,
    "max_y_diff": 40,
    "max_rectified_y_diff": 25,
    "pred_k": 35,
    "max_pred_len": 1.3,
    "edge_margin": 45,
    "critical_dist_m": 1.5,
    "cam_height_m": 0.073,
    "baseline_weight_power": 2.0,
    "baseline_weight_reference_m": 0.15,
    "pair_reliability": {"01": 1.0, "02": 1.0, "03": 1.0, "12": 1.0, "13": 1.0, "23": 1.0},
    "max_laser_dist": 2.2
}

# [예측]
PREDICTION = {
    "system_delay": 0.14,      # 과예측 방지를 위해 실제 지연보다 약간 보수적으로 둔다.
    "sonic_speed": 340.0,
    "max_lead_dist": 0.0,
    "command_lead_ratio": 0.0,
    "vel_deadzone": 0.035,
    "smooth_alpha": 0.78,
    "z_scale": 1.0,
    "vel_lpf_beta": 0.70,
}

# [Track Hold - Fusion 측: 유실 시 즉시 리셋 방지]
TRACKING = {
    "max_target_speed_mps": 3.5,
    "position_gate_margin_m": 0.12,
    "position_gate_min_dt": 0.01,
}

KALMAN = {
    "x": {"q": 4e-3, "r": 3e-2},
    "y": {"q": 5e-3, "r": 5e-2},
    "z": {"q": 1.5e-3, "r": 6e-2},
}

TRACK_HOLD = {
    "hold_sec": 0.30,     # 유실 후 이 시간까지 마지막 좌표 유지 (coast)
    "drop_sec": 1.00,     # 이 시간 이후 완전 드랍
    "threat_decay": 0.5,  # hold 중 threat 감쇠 계수
    "aim_hold_sec": 0.20, # 짧은 검출 유실 동안 레이저/터렛 명령 유지
}

# [Turret Hold - 서버 측: 빈 패킷에 즉시 홈 금지]
TURRET_HOLD = {
    "hold_sec": 0.30,         # 마지막 타겟 각도 유지 (레이저 OFF)
    "return_home_sec": 1.0,   # 이 시간에 걸쳐 홈으로 서서히 복귀
}

# [서보 스무딩]
SERVO_SMOOTH = {
    # 정지 상태에서는 노이즈 억제
    "alpha": 0.40,

    # MG995 / MG996R 기준 약 50Hz
    "min_send_interval": 0.020,
    "tick_hz": 50,
    "poll_timeout_ms": 2,

    "clear_output_before_write": True,

    # 비정상적인 순간 좌표 점프 방지
    "max_deg_per_frame": 18.0,

    # threat에 의한 과격한 움직임 완화
    "threat_motion_boost": 0.15,

    # 큰 오차에서는 빠르게 따라감
    "max_alpha": 0.90,

    # Pan / Tilt 미세 떨림 억제
    "pan_deadband": 0.08,
    "tilt_deadband": 0.10,

    # 실제 Arduino에 보내는 각도도 아주 작은 변화는 무시
    "output_deadband_deg": 0.12,

    "tilt_alpha_scale": 1.00,

    "laser_keepalive_interval": 0.10,

    # 비정상 tilt jump 제한
    "tilt_max_deg_scale": 0.90,

    # 1도 이상 오차가 생기면 빠르게 추종
    "error_boost_deg": 1.0,
    "error_boost_alpha": 0.15,
}


# [Tilt 방향성 / Servo Backlash 보상]
TURRET_DIRECTION_COMP = {
    # 이보다 작은 각도 변화는 방향 전환으로 보지 않음
    # HSV 좌표 흔들림으로 UP/DOWN이 계속 바뀌는 것 방지
    "direction_epsilon_deg": 0.18,

    # 2프레임 연속 같은 방향이어야 방향 전환 확정
    "direction_confirm_frames": 2,

    # 위 -> 아래 이동 시 실제 서보가 덜 내려오는 현상 보상
    # 최종 실물 튜닝값
    "pt1_down_deg": 0.80,
    "pt2_down_deg": 0.80,

    # 아래 -> 위는 현재 정확하므로 추가 보상 없음
    "pt1_up_deg": 0.00,
    "pt2_up_deg": 0.00,

    # 하강할 때 tilt EMA 응답속도 증가
    "down_alpha_mult": 1.18,
}

# [서보 PWM]
SERVO_PWM = {
    "us_min": 544,
    "us_max": 2400,
}

# [서보 안전 범위]
SAFE_LIMITS = {
    "pan_min": 20, "pan_max": 160,
    "tilt_min": 45, "tilt_max": 150
}

# [프레임 동기화]
SYNC = {
    "max_frame_age": 0.25,
    "max_show_age": 1.00,
    "pair_sync_window": 0.06,
    "pair_sync_soft_window": 0.09,
    "pair_sync_weight_floor": 0.08,
    # Same-sender CSI streams are not hardware synchronized. Warn on slips,
    # but do not drop the whole sender packet; pair-level sync weights reject
    # or down-weight bad triangulation combinations later.
    "sender_pair_max_dt": 0.12,
    "sender_offset_alpha": 0.08,
    "sender_offset_max_step": 0.20,
    "diagnostic_interval_sec": 1.0,
}

# Camera geometry is expected to stay fixed for the next calibration pass.
# Re-measure turret geometry after any pan/tilt mount relocation before final tests.
TURRET_GEOMETRY_REMEASURE = {
    "pt1_fields": ["pos_global", "pan_trim", "tilt_trim", "axis_tilt", "axis_lean"],
    "pt2_fields": ["pos_global", "pan_trim", "tilt_trim", "axis_tilt", "axis_lean"],
    "fixed_fields": ["dx_laser", "dz_laser", "h_pivot", "l_arm"],
}

PT1_CONFIG = {
    "pos_global": np.array([0.0750, 0.0, -0.0900]),
    "dx_laser": 0.000,
    "dz_laser": 0.012,
    "h_pivot": 0.1280,
    "l_arm": 0.0410,
    "pan_trim": 0.0, "tilt_trim": 0.0,
    "axis_tilt": 0.0, "axis_lean": 0.0
}

PT2_CONFIG = {
    "pos_global": np.array([0.3750, 0.0, -0.0900]),
    "dx_laser": 0.000,
    "dz_laser": 0.012,
    "h_pivot": 0.1280,
    "l_arm": 0.0410,
    "pan_trim": 0.0, "tilt_trim": 0.0,
    "axis_tilt": 0.0, "axis_lean": 0.0
}

def _apply_turret_overrides():
    path = os.path.join(PROJECT_ROOT, "turret_calibration_overrides.json")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"!! turret override ignored: {type(exc).__name__}: {exc}")
        return

    for name, target in (("pt1", PT1_CONFIG), ("pt2", PT2_CONFIG)):
        values = payload.get(name)
        if not isinstance(values, dict):
            continue
        for key in ("dx_laser", "dz_laser", "h_pivot", "l_arm", "pan_trim", "tilt_trim", "axis_tilt", "axis_lean"):
            if key in values:
                try:
                    target[key] = float(values[key])
                except (TypeError, ValueError):
                    pass
        if "pos_global" in values:
            try:
                arr = np.asarray(values["pos_global"], dtype=np.float64).reshape(3)
                target["pos_global"] = arr
            except Exception:
                pass

    pred_values = payload.get("prediction")
    if isinstance(pred_values, dict) and "z_scale" in pred_values:
        try:
            z_scale = float(pred_values["z_scale"])
            if np.isfinite(z_scale) and 0.50 <= z_scale <= 1.20:
                PREDICTION["z_scale"] = z_scale
        except (TypeError, ValueError):
            pass

_apply_turret_overrides()

SERVO_CENTER = 90
