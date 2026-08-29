# -*- coding: utf-8 -*-
"""
calibration_turret.py - 카메라 자동 측정 + 레이저 수동 조준 보정

★ fusion(5번 코드)이 실행 중이어야 합니다!
  카메라가 타겟 3D 좌표를 자동 감지 → 사람이 자로 잴 필요 없음

사용법:
  1. fusion(5번 코드) 먼저 실행
  2. 이 스크립트 실행
  3. 타겟을 벽에 갖다 대기 → 좌표 자동 캡처 (Enter로 확정)
  4. PT1 레이저를 키보드로 타겟에 맞춤 → Enter
  5. PT2 레이저를 키보드로 타겟에 맞춤 → Enter
  6. 최소 3개 포인트 반복 → 자동 최적화 → turret_calibration_overrides.json 생성

조작:
  ←→ : pan (좌/우)
  ↑↓ : tilt (상/하)
  F  : 미세(0.1°) / 거친(0.5°) 전환
  Enter : 확정
  ESC   : 중단
"""
import serial
import time
import math
import sys
import json
import os
import zmq
import pickle
import numpy as np

try:
    from scipy.optimize import minimize
except ImportError:
    print("scipy 필요: pip install scipy")
    sys.exit(1)

try:
    import config_turret as cfg
except ImportError:
    print("config_turret.py가 같은 폴더에 필요합니다")
    sys.exit(1)

ARDUINO_CFG = getattr(cfg, "ARDUINO", {})
NETWORK_CFG = getattr(cfg, "NETWORK", {})
ARDUINO_PORT = str(ARDUINO_CFG.get("port", "COM3"))
ARDUINO_BAUD = int(ARDUINO_CFG.get("baud", 115200))
RESULT_PORT = int(NETWORK_CFG.get("result_port", 5556))
PREDICTION_CFG = getattr(cfg, "PREDICTION", {})
FUSION_PARAMS_CFG = getattr(cfg, "FUSION_PARAMS", {})
CAM_HEIGHT_M = float(getattr(cfg, "CAM_HEIGHT_M", FUSION_PARAMS_CFG.get("cam_height_m", 0.0)))
Z_SCALE_INIT = float(PREDICTION_CFG.get("z_scale", 1.0))
Z_SCALE_BOUNDS = (0.65, 1.10)
USE_MICROSECONDS = bool(ARDUINO_CFG.get("use_microseconds", True))
SERVO_CENTER = float(getattr(cfg, "SERVO_CENTER", 90))
SAFE_LIMITS = getattr(cfg, "SAFE_LIMITS", {"pan_min": 20, "pan_max": 160, "tilt_min": 45, "tilt_max": 150})
SERVO_PWM = getattr(cfg, "SERVO_PWM", {"us_min": 544, "us_max": 2400})
SERVO_SMOOTH = getattr(cfg, "SERVO_SMOOTH", {})
LASER_KEEPALIVE_INTERVAL = max(0.05, min(0.25, float(SERVO_SMOOTH.get("laser_keepalive_interval", 0.10))))
MANUAL_FINE_STEP_DEG = 0.25
MANUAL_COARSE_STEP_DEG = 1.0
MANUAL_KEY_DEBOUNCE_SEC = 0.06
MANUAL_MOVE_SETTLE_SEC = 0.05

import msvcrt

# ==========================================
# Arduino
# ==========================================
def connect_arduino(port='COM3', baud=115200):
    try:
        ser = serial.Serial(port, baud, timeout=0.1)
        time.sleep(2)
        print(f"  Arduino {port} connected")
        return ser
    except Exception as e:
        print(f"  Arduino 연결 실패: {e}")
        sys.exit(1)

# ==========================================
# 서보 변환
# ==========================================
US_MIN = int(SERVO_PWM.get("us_min", 544))
US_MAX = int(SERVO_PWM.get("us_max", 2400))
US_RANGE = US_MAX - US_MIN

def deg_to_us(deg):
    us = US_MIN + (deg / 180.0) * US_RANGE
    return max(US_MIN, min(US_MAX, int(round(us))))

def clamp_pan_tilt(pan, tilt):
    pan = max(float(SAFE_LIMITS["pan_min"]), min(float(SAFE_LIMITS["pan_max"]), float(pan)))
    tilt = max(float(SAFE_LIMITS["tilt_min"]), min(float(SAFE_LIMITS["tilt_max"]), float(tilt)))
    return pan, tilt

def build_command(p1, t1, p2, t2, l1, l2):
    if USE_MICROSECONDS:
        return f"U{deg_to_us(p1)},{deg_to_us(t1)},{deg_to_us(p2)},{deg_to_us(t2)},{l1},{l2}\n"
    return f"P1{int(round(p1))}T1{int(round(t1))}P2{int(round(p2))}T2{int(round(t2))}L1{l1}L2{l2}\n"

def send_cmd(ser, p1, t1, p2, t2, l1, l2, settle=0.0):
    """Send the protocol selected by config_turret.ARDUINO."""
    cmd = build_command(p1, t1, p2, t2, l1, l2)
    try:
        ser.reset_output_buffer()
    except Exception:
        pass
    ser.write(cmd.encode())
    ser.flush()   # OS 버퍼 즉시 비움 → Arduino에 바로 전달
    if settle > 0:
        time.sleep(settle)


def hold_cmd(ser, p1, t1, p2, t2, l1, l2, duration):
    """Keep laser-on commands alive while waiting for a visual check."""
    end = time.time() + max(0.0, float(duration))
    while True:
        send_cmd(ser, p1, t1, p2, t2, l1, l2)
        remaining = end - time.time()
        if remaining <= 0:
            break
        time.sleep(min(LASER_KEEPALIVE_INTERVAL, remaining))

# ==========================================
# ZMQ Fusion 수신
# ==========================================
class FusionReceiver:
    def __init__(self, port=5556):
        self.ctx = zmq.Context()
        self.sub = self.ctx.socket(zmq.SUB)
        self.sub.setsockopt(zmq.LINGER, 0)
        self.sub.setsockopt(zmq.CONFLATE, 1)
        self.sub.connect(f"tcp://localhost:{port}")
        self.sub.setsockopt_string(zmq.SUBSCRIBE, "")
        print(f"  Fusion ZMQ connected (port {port})")

    def get_target(self):
        try:
            raw = self.sub.recv(flags=zmq.NOBLOCK)
            packet = pickle.loads(raw)
            targets = packet.get("targets", {})
            if targets:
                best = max(targets.items(), key=lambda x: x[1].get("threat", 0))
                info = best[1] if isinstance(best[1], dict) else {}
                raw_pos = info.get("raw_pos")
                if raw_pos is not None:
                    pos = np.asarray(raw_pos, dtype=np.float64).reshape(3).copy()
                    # Fusion raw_pos is camera-height-relative. Turret geometry uses ground-frame Y.
                    pos[1] += CAM_HEIGHT_M
                    return pos, best[0]
                pos = info.get("pos")
                if pos is not None:
                    return np.asarray(pos, dtype=np.float64).reshape(3), best[0]
            return None, None
        except zmq.Again:
            return None, None
        except Exception:
            return None, None

    def get_stable_target(self, duration=1.0, interval=0.05):
        samples = []
        t_start = time.time()
        while time.time() - t_start < duration:
            pos, name = self.get_target()
            if pos is not None:
                samples.append(pos)
            time.sleep(interval)
        if len(samples) < 3:
            return None, 0
        arr = np.array(samples)
        mean = np.mean(arr, axis=0)
        return mean, len(samples)

    def close(self):
        self.sub.close()
        self.ctx.destroy()

# ==========================================
# Keyboard (Windows)
# ==========================================
def get_key():
    if not msvcrt.kbhit():
        return None
    ch = msvcrt.getch()
    if ch in (b'\xe0', b'\x00'):
        ch2 = msvcrt.getch()
        return {b'H': 'up', b'P': 'down', b'K': 'left', b'M': 'right'}.get(ch2)
    if ch == b'\r':
        return 'enter'
    if ch == b'\x1b':
        return 'esc'
    return ch.decode('utf-8', errors='ignore').lower()

# ==========================================
# 각도 계산 (turret_server와 동일)
# ==========================================
def calc_angles(target, px, pz, h_piv, l_arm, dx_l, dz_l, pan_tr, tilt_tr, axis_tilt=0.0, axis_lean=0.0, z_scale=1.0):
    target = np.asarray(target, dtype=np.float64).reshape(3).copy()
    target[2] *= float(z_scale)
    x_rel = target[0] - px
    z_rel = target[2] - pz
    y_rel = target[1] - h_piv

    pan_rad = math.atan2(x_rel - dx_l, z_rel - dz_l)
    pan_deg = SERVO_CENTER - math.degrees(pan_rad) + pan_tr

    dist_h = math.sqrt((x_rel - dx_l)**2 + (z_rel - dz_l)**2)
    dist_PT = math.sqrt(dist_h**2 + y_rel**2)

    if dist_PT > l_arm and l_arm > 0:
        beta = math.asin(min(1.0, l_arm / dist_PT))
        alpha_a = math.atan2(y_rel, dist_h)
        tilt_deg = SERVO_CENTER + math.degrees(alpha_a - beta) + tilt_tr
    else:
        tilt_deg = SERVO_CENTER + tilt_tr

    # ★ 2축 기울기 보정
    sin_pan = math.sin(math.radians(pan_deg - SERVO_CENTER))
    pan_deg  += sin_pan * axis_lean   # 좌우 기울기 → pan 오차
    tilt_deg += sin_pan * axis_tilt   # 앞뒤 기울기 → tilt 오차

    return pan_deg, tilt_deg

# ==========================================
# 최적화
# ==========================================
def optimize_turret(calib_points, init_cfg, name):
    """
    최적화 대상: pos_x, pos_z, pan_trim, tilt_trim, axis_tilt, axis_lean (6개)
    고정: h_pivot, l_arm, dx_laser, dz_laser
    """
    orig_px = init_cfg["pos_global"][0]
    orig_pz = init_cfg["pos_global"][2]
    orig_pan = float(init_cfg["pan_trim"])
    orig_tilt = float(init_cfg["tilt_trim"])
    orig_axis_tilt = 0.0
    orig_axis_lean = 0.0

    x0 = np.array([orig_px, orig_pz, orig_pan, orig_tilt, orig_axis_tilt, orig_axis_lean])

    dx_l = init_cfg["dx_laser"]
    dz_l = init_cfg["dz_laser"]
    h_piv = init_cfg["h_pivot"]
    l_arm = init_cfg["l_arm"]

    bounds = [
        (orig_px - 0.006, orig_px + 0.006),
        (orig_pz - 0.006, orig_pz + 0.006),
        (orig_pan - 5.0,  orig_pan + 5.0),
        (orig_tilt - 5.0, orig_tilt + 5.0),
        (-12.0, 12.0),
        (-12.0, 12.0),
    ]

    REG_WEIGHT = 0.15
    reg_center = x0.copy()
    reg_scale = np.array([0.006, 0.006, 4.0, 4.0, 8.0, 8.0])

    def cost(params):
        px, pz, pan_tr, tilt_tr, ax_tilt, ax_lean = params
        total = 0.0
        for tgt, m_pan, m_tilt in calib_points:
            c_pan, c_tilt = calc_angles(tgt, px, pz, h_piv, l_arm, dx_l, dz_l,
                                        pan_tr, tilt_tr, ax_tilt, ax_lean, z_scale=Z_SCALE_INIT)
            for err, weight in ((c_pan - m_pan, 1.0), (c_tilt - m_tilt, 1.25)):
                a = abs(float(err))
                delta = 2.5
                total += weight * (0.5 * a * a if a <= delta else delta * (a - 0.5 * delta))
        deviation = (params - reg_center) / reg_scale
        total += REG_WEIGHT * len(calib_points) * np.sum(deviation ** 2)
        return total

    result = minimize(cost, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': 200000, 'ftol': 1e-12})
    opt = result.x

    errors = []
    for tgt, m_pan, m_tilt in calib_points:
        c_pan, c_tilt = calc_angles(tgt, opt[0], opt[1], h_piv, l_arm, dx_l, dz_l,
                                    opt[2], opt[3], opt[4], opt[5], z_scale=Z_SCALE_INIT)
        errors.append((c_pan - m_pan, c_tilt - m_tilt))

    return {
        "pos_x": opt[0], "pos_z": opt[1],
        "h_pivot": h_piv, "l_arm": l_arm,
        "pan_trim": opt[2], "tilt_trim": opt[3],
        "axis_tilt": opt[4], "axis_lean": opt[5],
        "z_scale": Z_SCALE_INIT,
        "residual": result.fun,
        "errors": errors,
    }

# ==========================================
# 레이저 조준 UI
# ==========================================
def aim_turret(ser, turret_id, init_pan, init_tilt, other_pan, other_tilt):
    p, t = init_pan, init_tilt
    step = MANUAL_COARSE_STEP_DEG
    fine = False
    last_key_time = 0.0
    last_send_time = 0.0
    KEY_DEBOUNCE = MANUAL_KEY_DEBOUNCE_SEC  # 키 입력 최소 간격(초) - 너무 빠른 반복 방지

    def send_current(settle=0.0):
        nonlocal last_send_time
        if turret_id == 1:
            send_cmd(ser, p, t, other_pan, other_tilt, 1, 0, settle=settle)
        else:
            send_cmd(ser, other_pan, other_tilt, p, t, 0, 1, settle=settle)
        last_send_time = time.time()

    # 초기 위치로 이동
    send_current(settle=0.3)

    while True:
        k = get_key()
        if k is None:
            if time.time() - last_send_time >= LASER_KEEPALIVE_INTERVAL:
                send_current()
            time.sleep(0.01)
            continue

        now = time.time()

        if k == 'enter':
            # ★ 확정 전: 마지막 명령 재전송 + 서보 완전 안착 대기
            send_current(settle=0.45)
            return p, t

        if k == 'esc':
            return None

        if k == 'f':
            fine = not fine
            step = MANUAL_FINE_STEP_DEG if fine else MANUAL_COARSE_STEP_DEG
            mode = f"FINE({MANUAL_FINE_STEP_DEG:g} deg)" if fine else f"COARSE({MANUAL_COARSE_STEP_DEG:g} deg)"
            print(f"    [{mode} 전환]                        ")
            continue

        # ★ 키 디바운스: 너무 빠른 연속 입력 차단
        if now - last_key_time < KEY_DEBOUNCE:
            continue
        last_key_time = now

        moved = False
        if k == 'left':
            p += step; moved = True
        elif k == 'right':
            p -= step; moved = True
        elif k == 'up':
            t -= step; moved = True
        elif k == 'down':
            t += step; moved = True

        p, t = clamp_pan_tilt(p, t)

        if moved:
            send_current(settle=MANUAL_MOVE_SETTLE_SEC)
            mode = "FINE" if fine else "COARSE"
            # μs 값 표시: 숫자가 바뀌면 명령은 정상 전송됨
            us_p, us_t = deg_to_us(p), deg_to_us(t)
            print(f"    PT{turret_id}: pan={p:.1f}({us_p}us)  tilt={t:.1f}({us_t}us)  [{mode} {step:g} deg]      ", end='\r')

# ==========================================
# 타겟 캡처 UI
# ==========================================
def capture_target(fusion_rx):
    print("    타겟을 벽에 갖다 대세요. 좌표가 안정되면 Enter")
    print("    (감지 안 되면 X 표시)")

    while True:
        pos, name = fusion_rx.get_target()
        if pos is not None:
            print(f"    [{name}] X={pos[0]:.3f}  Y={pos[1]:.3f}  Z={pos[2]:.3f}      ", end='\r')
        else:
            print(f"    감지 안 됨 (X)                              ", end='\r')

        k = get_key()
        if k == 'enter':
            print(f"\n    안정화 측정 중 (1초)...", end='')
            mean_pos, count = fusion_rx.get_stable_target(duration=1.0)
            if mean_pos is not None and count >= 3:
                print(f" OK ({count}샘플)")
                print(f"    ★ 확정: X={mean_pos[0]:.4f}  Y={mean_pos[1]:.4f}  Z={mean_pos[2]:.4f}")
                return mean_pos
            else:
                print(f" 실패 (샘플 부족: {count}개). 다시 시도하세요.")
        elif k == 'esc':
            return None
        time.sleep(0.03)

# ==========================================
# 결과 출력
# ==========================================

def _huber_loss(err, delta=2.5):
    a = abs(float(err))
    return 0.5 * a * a if a <= delta else delta * (a - 0.5 * delta)


def optimize_turrets_joint(pt1_points, pt1_init, pt2_points, pt2_init):
    """Jointly fit both turrets and one command Z scale.

    Fusion raw_pos is camera-height-relative. calibration_turret converts it to
    ground-frame Y, then this optimizer estimates the command-side Z scale so
    tilt error is not incorrectly absorbed into trim/axis terms.
    """
    def init_vec(init_cfg):
        return np.array([
            float(init_cfg["pos_global"][0]),
            float(init_cfg["pos_global"][2]),
            float(init_cfg["pan_trim"]),
            float(init_cfg["tilt_trim"]),
            0.0,
            0.0,
        ], dtype=np.float64)

    x1 = init_vec(pt1_init)
    x2 = init_vec(pt2_init)
    z0 = float(np.clip(Z_SCALE_INIT, Z_SCALE_BOUNDS[0], Z_SCALE_BOUNDS[1]))
    x0 = np.concatenate([x1, x2, np.array([z0], dtype=np.float64)])

    def bounds_for(v):
        return [
            (v[0] - 0.006, v[0] + 0.006),
            (v[1] - 0.006, v[1] + 0.006),
            (v[2] - 8.0, v[2] + 8.0),
            (v[3] - 8.0, v[3] + 8.0),
            (-12.0, 12.0),
            (-12.0, 12.0),
        ]

    bounds = bounds_for(x1) + bounds_for(x2) + [Z_SCALE_BOUNDS]
    reg_scale = np.array([0.006, 0.006, 4.0, 4.0, 8.0, 8.0,
                          0.006, 0.006, 4.0, 4.0, 8.0, 8.0,
                          0.18], dtype=np.float64)
    reg_weight = 0.05

    def add_cost(points, init_cfg, params, z_scale):
        total = 0.0
        for tgt, m_pan, m_tilt in points:
            c_pan, c_tilt = calc_angles(
                tgt,
                params[0], params[1],
                init_cfg["h_pivot"], init_cfg["l_arm"],
                init_cfg["dx_laser"], init_cfg["dz_laser"],
                params[2], params[3], params[4], params[5],
                z_scale=z_scale,
            )
            total += 1.0 * _huber_loss(c_pan - m_pan)
            total += 1.25 * _huber_loss(c_tilt - m_tilt)
        return total

    def cost(params):
        z_scale = float(params[12])
        total = add_cost(pt1_points, pt1_init, params[0:6], z_scale)
        total += add_cost(pt2_points, pt2_init, params[6:12], z_scale)
        deviation = (params - x0) / reg_scale
        total += reg_weight * (len(pt1_points) + len(pt2_points)) * np.sum(deviation ** 2)
        return total

    result = minimize(cost, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': 200000, 'ftol': 1e-12})
    opt = result.x
    z_scale = float(opt[12])

    def pack(points, init_cfg, params, residual):
        errors = []
        for tgt, m_pan, m_tilt in points:
            c_pan, c_tilt = calc_angles(
                tgt,
                params[0], params[1],
                init_cfg["h_pivot"], init_cfg["l_arm"],
                init_cfg["dx_laser"], init_cfg["dz_laser"],
                params[2], params[3], params[4], params[5],
                z_scale=z_scale,
            )
            errors.append((c_pan - m_pan, c_tilt - m_tilt))
        return {
            "pos_x": float(params[0]), "pos_z": float(params[1]),
            "h_pivot": float(init_cfg["h_pivot"]), "l_arm": float(init_cfg["l_arm"]),
            "pan_trim": float(params[2]), "tilt_trim": float(params[3]),
            "axis_tilt": float(params[4]), "axis_lean": float(params[5]),
            "z_scale": z_scale,
            "residual": float(residual),
            "errors": errors,
        }

    return pack(pt1_points, pt1_init, opt[0:6], result.fun), pack(pt2_points, pt2_init, opt[6:12], result.fun)


def print_results(pt1_r, pt2_r):
    print(f"\n{'='*55}")
    print("  최적화 결과")
    print(f"{'='*55}")

    for name, r, orig in [("PT1", pt1_r, cfg.PT1_CONFIG), ("PT2", pt2_r, cfg.PT2_CONFIG)]:
        print(f"\n  [{name}] residual={r['residual']:.4f}")
        print(f"    pos_global[0]: {orig['pos_global'][0]:.4f} → {r['pos_x']:.4f}  (Δ{r['pos_x']-orig['pos_global'][0]:+.4f})")
        print(f"    pos_global[2]: {orig['pos_global'][2]:.4f} → {r['pos_z']:.4f}  (Δ{r['pos_z']-orig['pos_global'][2]:+.4f})")
        print(f"    h_pivot:       {orig['h_pivot']:.4f} → {r['h_pivot']:.4f}  (Δ{r['h_pivot']-orig['h_pivot']:+.4f})")
        print(f"    l_arm:         {orig['l_arm']:.4f} → {r['l_arm']:.4f}  (Δ{r['l_arm']-orig['l_arm']:+.4f})")
        print(f"    pan_trim:      {orig['pan_trim']} → {r['pan_trim']:.1f}")
        print(f"    tilt_trim:     {orig['tilt_trim']} → {r['tilt_trim']:.1f}")
        print(f"    axis_tilt:     {orig.get('axis_tilt', 0.0):.2f} → {r['axis_tilt']:.2f}°  (앞뒤 기울기)")
        print(f"    axis_lean:     {orig.get('axis_lean', 0.0):.2f} → {r['axis_lean']:.2f}°  (좌우 기울기)")

    print(f"\n  [포인트별 잔차 (°)]")
    for i, (ep, et) in enumerate(pt1_r["errors"]):
        print(f"    PT1 point{i+1}: pan={ep:+.2f}°  tilt={et:+.2f}°")
    for i, (ep, et) in enumerate(pt2_r["errors"]):
        print(f"    PT2 point{i+1}: pan={ep:+.2f}°  tilt={et:+.2f}°")

# ==========================================
# config 생성
# ==========================================
def generate_config(pt1_r, pt2_r):
    z_scale = float(pt1_r.get("z_scale", pt2_r.get("z_scale", Z_SCALE_INIT)))
    payload = {
        "schema": "aegis_turret_calibration_overrides_v1",
        "prediction": {"z_scale": round(z_scale, 4)},
        "pt1": {
            "pos_global": [round(float(pt1_r["pos_x"]), 4), 0.0, round(float(pt1_r["pos_z"]), 4)],
            "dx_laser": float(cfg.PT1_CONFIG["dx_laser"]),
            "dz_laser": float(cfg.PT1_CONFIG["dz_laser"]),
            "h_pivot": round(float(pt1_r["h_pivot"]), 4),
            "l_arm": round(float(pt1_r["l_arm"]), 4),
            "pan_trim": round(float(pt1_r["pan_trim"]), 1),
            "tilt_trim": round(float(pt1_r["tilt_trim"]), 1),
            "axis_tilt": round(float(pt1_r["axis_tilt"]), 2),
            "axis_lean": round(float(pt1_r["axis_lean"]), 2),
        },
        "pt2": {
            "pos_global": [round(float(pt2_r["pos_x"]), 4), 0.0, round(float(pt2_r["pos_z"]), 4)],
            "dx_laser": float(cfg.PT2_CONFIG["dx_laser"]),
            "dz_laser": float(cfg.PT2_CONFIG["dz_laser"]),
            "h_pivot": round(float(pt2_r["h_pivot"]), 4),
            "l_arm": round(float(pt2_r["l_arm"]), 4),
            "pan_trim": round(float(pt2_r["pan_trim"]), 1),
            "tilt_trim": round(float(pt2_r["tilt_trim"]), 1),
            "axis_tilt": round(float(pt2_r["axis_tilt"]), 2),
            "axis_lean": round(float(pt2_r["axis_lean"]), 2),
        },
    }

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "turret_calibration_overrides.json")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, out_path)
    print(f"\n  → 저장: {out_path}")
    print("  fusion/turret 서버를 재시작하면 config_turret.py가 이 override를 자동 적용합니다.")

# ==========================================
# 검증 모드
# ==========================================
def verify_calibration(ser, pt1_r, pt2_r, calib_3d):
    print(f"\n{'='*55}")
    print("  검증 모드: 양쪽 레이저 동시 조준")
    print("  Enter=다음, ESC=종료")
    print(f"{'='*55}")

    for i, tgt in enumerate(calib_3d):
        p1, t1 = calc_angles(tgt,
                             pt1_r["pos_x"], pt1_r["pos_z"],
                             pt1_r["h_pivot"], pt1_r["l_arm"],
                             cfg.PT1_CONFIG["dx_laser"], cfg.PT1_CONFIG["dz_laser"],
                             pt1_r["pan_trim"], pt1_r["tilt_trim"],
                             pt1_r["axis_tilt"], pt1_r["axis_lean"],
                             z_scale=pt1_r.get("z_scale", Z_SCALE_INIT))
        p2, t2 = calc_angles(tgt,
                             pt2_r["pos_x"], pt2_r["pos_z"],
                             pt2_r["h_pivot"], pt2_r["l_arm"],
                             cfg.PT2_CONFIG["dx_laser"], cfg.PT2_CONFIG["dz_laser"],
                             pt2_r["pan_trim"], pt2_r["tilt_trim"],
                             pt2_r["axis_tilt"], pt2_r["axis_lean"],
                             z_scale=pt2_r.get("z_scale", Z_SCALE_INIT))

        p1, t1 = clamp_pan_tilt(p1, t1)
        p2, t2 = clamp_pan_tilt(p2, t2)

        send_cmd(ser, p1, t1, p2, t2, 1, 1)
        last_send_time = time.time()
        print(f"\n  Point {i+1}: X={tgt[0]:.3f} Y={tgt[1]:.3f} Z={tgt[2]:.3f}")
        print(f"    PT1 pan={p1:.1f} tilt={t1:.1f}")
        print(f"    PT2 pan={p2:.1f} tilt={t2:.1f}")
        print(f"    레이저 수렴 확인. Enter=다음")

        while True:
            k = get_key()
            if k == 'enter':
                break
            if k == 'esc':
                return
            if time.time() - last_send_time >= LASER_KEEPALIVE_INTERVAL:
                send_cmd(ser, p1, t1, p2, t2, 1, 1)
                last_send_time = time.time()
            time.sleep(0.02)

# ==========================================
# Main
# ==========================================
def main():
    print("\n" + "=" * 55)
    print("  터렛 자동 보정 (카메라 3D + 레이저 조준)")
    print("=" * 55)
    print("  ★ fusion(5번 코드)이 실행 중이어야 합니다!")
    print("  ←→: pan  ↑↓: tilt  F: 미세(0.1°)/거친(0.5°)")
    print("  Enter: 확정  ESC: 중단")
    print("=" * 55)

    num_pts = int(input("\n  보정 포인트 수 (최소3, 권장10) [10]: ") or "10")
    if num_pts < 3:
        print("  최소 3개 필요!")
        return

    print(f"\n  터렛 위치: PT1 X={cfg.PT1_CONFIG['pos_global'][0]:.3f}, PT2 X={cfg.PT2_CONFIG['pos_global'][0]:.3f}")
    print(f"\n  ★ 권장 배치: 3×3 그리드 (좌/중/우 × 하/중/상)")
    print(f"  ★ 2가지 거리에서 하면 정확도 크게 향상!")
    print(f"     1차: 가까운 거리 (~1.0m) 에서 5포인트")
    print(f"     2차: 먼 거리 (~1.7m) 에서 5포인트")
    print(f"     → 총 10포인트 (한번에 연속 진행)")
    print(f"")
    print(f"  벽에 아래와 같이 타겟을 순서대로 이동시키세요:")
    print(f"")
    print(f"     ⑦좌상   ⑧중상   ⑨우상")
    print(f"     ④좌중   ⑤중중   ⑥우중")
    print(f"     ①좌하   ②중하   ③우하")
    print(f"")
    print(f"  좌우 간격: 약 25~30cm씩")
    print(f"  상하 간격: 약 15~20cm씩")
    print(f"  거리가 다르면 카메라가 Z를 자동 측정하므로 그냥 대면 됨\n")

    ser = connect_arduino(ARDUINO_PORT, ARDUINO_BAUD)

    # ★ 연결 확인: 레이저 점멸 테스트
    print("  하드웨어 테스트 중...")
    p1_home, t1_home = clamp_pan_tilt(
        SERVO_CENTER + cfg.PT1_CONFIG["pan_trim"],
        SERVO_CENTER + cfg.PT1_CONFIG["tilt_trim"],
    )
    p2_home, t2_home = clamp_pan_tilt(
        SERVO_CENTER + cfg.PT2_CONFIG["pan_trim"],
        SERVO_CENTER + cfg.PT2_CONFIG["tilt_trim"],
    )

    hold_cmd(ser, p1_home, t1_home, p2_home, t2_home, 1, 1, 0.5)
    send_cmd(ser, p1_home, t1_home, p2_home, t2_home, 0, 0)
    time.sleep(0.3)
    hold_cmd(ser, p1_home, t1_home, p2_home, t2_home, 1, 1, 0.5)
    send_cmd(ser, p1_home, t1_home, p2_home, t2_home, 0, 0)
    print("  ✓ 레이저 2회 점멸 확인되면 하드웨어 정상")
    print("    (점멸 안 보이면 아두이노 ver_3 업로드 필요)\n")

    fusion_rx = FusionReceiver(port=RESULT_PORT)

    print("  fusion 연결 확인 중...")
    time.sleep(0.5)
    pos, _ = fusion_rx.get_target()
    if pos is None:
        print("  ⚠ fusion에서 데이터 수신 안 됨. fusion이 실행 중인지 확인하세요.")
        print("  계속하려면 Enter, 중단은 ESC")
        while True:
            k = get_key()
            if k == 'enter':
                break
            if k == 'esc':
                ser.close(); fusion_rx.close(); return
            time.sleep(0.05)
    else:
        print(f"  ✓ fusion 데이터 수신 OK")

    pt1_calib = []
    pt2_calib = []
    calib_3d = []

    grid_hints = [
        "①근거리-좌","②근거리-중","③근거리-우",
        "④근거리-좌상","⑤근거리-우상",
        "⑥원거리-좌","⑦원거리-중","⑧원거리-우",
        "⑨원거리-좌상","⑩원거리-우상",
    ]

    for i in range(num_pts):
        hint = grid_hints[i] if i < len(grid_hints) else ""
        print(f"\n{'─'*45}")
        print(f"  포인트 {i+1}/{num_pts}  {hint}")
        print(f"{'─'*45}")

        # --- 카메라 자동 좌표 캡처 ---
        print(f"\n  [1/3] 타겟 3D 좌표 캡처 (카메라 자동)")
        print(f"        ※ 이 단계에서는 레이저 OFF 상태입니다")
        print(f"        ※ 좌표 확정 후 레이저가 켜집니다")
        target_3d = capture_target(fusion_rx)
        if target_3d is None:
            print("\n  중단됨"); break
        calib_3d.append(target_3d)

        # --- PT1 조준 (계산값으로 초기 위치 설정) ---
        init_p1, init_t1 = calc_angles(
            target_3d,
            cfg.PT1_CONFIG["pos_global"][0], cfg.PT1_CONFIG["pos_global"][2],
            cfg.PT1_CONFIG["h_pivot"], cfg.PT1_CONFIG["l_arm"],
            cfg.PT1_CONFIG["dx_laser"], cfg.PT1_CONFIG["dz_laser"],
            cfg.PT1_CONFIG["pan_trim"], cfg.PT1_CONFIG["tilt_trim"],
            cfg.PT1_CONFIG.get("axis_tilt", 0.0), cfg.PT1_CONFIG.get("axis_lean", 0.0),
            z_scale=Z_SCALE_INIT)
        init_p1, init_t1 = clamp_pan_tilt(init_p1, init_t1)

        print(f"\n  [2/3] PT1 레이저 조준 (←→↑↓, F=미세, Enter=확정)")
        result = aim_turret(ser, 1, init_p1, init_t1, p2_home, t2_home)
        if result is None:
            print("\n  중단됨"); break
        pt1_calib.append((target_3d, result[0], result[1]))
        print(f"\n    ✓ PT1: pan={result[0]:.1f}  tilt={result[1]:.1f}")

        # --- PT2 조준 ---
        init_p2, init_t2 = calc_angles(
            target_3d,
            cfg.PT2_CONFIG["pos_global"][0], cfg.PT2_CONFIG["pos_global"][2],
            cfg.PT2_CONFIG["h_pivot"], cfg.PT2_CONFIG["l_arm"],
            cfg.PT2_CONFIG["dx_laser"], cfg.PT2_CONFIG["dz_laser"],
            cfg.PT2_CONFIG["pan_trim"], cfg.PT2_CONFIG["tilt_trim"],
            cfg.PT2_CONFIG.get("axis_tilt", 0.0), cfg.PT2_CONFIG.get("axis_lean", 0.0),
            z_scale=Z_SCALE_INIT)
        init_p2, init_t2 = clamp_pan_tilt(init_p2, init_t2)

        print(f"\n  [3/3] PT2 레이저 조준 (←→↑↓, F=미세, Enter=확정)")
        result = aim_turret(ser, 2, init_p2, init_t2, p1_home, t1_home)
        if result is None:
            print("\n  중단됨"); break
        pt2_calib.append((target_3d, result[0], result[1]))
        print(f"\n    ✓ PT2: pan={result[0]:.1f}  tilt={result[1]:.1f}")

    send_cmd(ser, p1_home, t1_home, p2_home, t2_home, 0, 0)

    if len(pt1_calib) < 3 or len(pt2_calib) < 3:
        print(f"\n  포인트 부족 ({len(pt1_calib)}개). 최소 3개 필요.")
        ser.close(); fusion_rx.close(); return

    # --- 데이터 저장 ---
    save_data = {
        "pt1": [(t.tolist(), p, tl) for t, p, tl in pt1_calib],
        "pt2": [(t.tolist(), p, tl) for t, p, tl in pt2_calib],
    }
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calib_data.json")
    with open(json_path, 'w') as f:
        json.dump(save_data, f, indent=2)
    print(f"\n  측정 데이터 저장: {json_path}")

    # --- 최적화 ---
    print(f"\n{'='*55}")
    print("  최적화 중...")
    print(f"{'='*55}")

    pt1_init = {
        "pos_global": cfg.PT1_CONFIG["pos_global"],
        "h_pivot": cfg.PT1_CONFIG["h_pivot"], "l_arm": cfg.PT1_CONFIG["l_arm"],
        "dx_laser": cfg.PT1_CONFIG["dx_laser"], "dz_laser": cfg.PT1_CONFIG["dz_laser"],
        "pan_trim": cfg.PT1_CONFIG["pan_trim"], "tilt_trim": cfg.PT1_CONFIG["tilt_trim"],
        "axis_tilt": cfg.PT1_CONFIG.get("axis_tilt", 0.0), "axis_lean": cfg.PT1_CONFIG.get("axis_lean", 0.0),
    }
    pt2_init = {
        "pos_global": cfg.PT2_CONFIG["pos_global"],
        "h_pivot": cfg.PT2_CONFIG["h_pivot"], "l_arm": cfg.PT2_CONFIG["l_arm"],
        "dx_laser": cfg.PT2_CONFIG["dx_laser"], "dz_laser": cfg.PT2_CONFIG["dz_laser"],
        "pan_trim": cfg.PT2_CONFIG["pan_trim"], "tilt_trim": cfg.PT2_CONFIG["tilt_trim"],
        "axis_tilt": cfg.PT2_CONFIG.get("axis_tilt", 0.0), "axis_lean": cfg.PT2_CONFIG.get("axis_lean", 0.0),
    }

    pt1_r, pt2_r = optimize_turrets_joint(pt1_calib, pt1_init, pt2_calib, pt2_init)

    print_results(pt1_r, pt2_r)

    print()
    save = input("  config_turret_calibrated.py 생성? (y/n) [y]: ").strip().lower()
    if save != 'n':
        generate_config(pt1_r, pt2_r)

    print()
    verify = input("  검증 모드 실행? (y/n) [y]: ").strip().lower()
    if verify != 'n':
        verify_calibration(ser, pt1_r, pt2_r, calib_3d)

    send_cmd(ser, p1_home, t1_home, p2_home, t2_home, 0, 0)
    ser.close()
    fusion_rx.close()
    print("\n  Done")


if __name__ == "__main__":
    main()
