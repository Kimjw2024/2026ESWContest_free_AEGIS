# -*- coding: utf-8 -*-
"""
6_turret_server_SYNC_PRED_FIXED.py

잘 작동하던 SMOOTH 버전 기반 + HOLD/레이저 안전 추가.
P/U 프로토콜 자동 선택: USE_MICROSECONDS = True/False

[수정] Spike clamp 추가: 한 프레임에 last_target이 max_deg_per_frame 이상
       점프하면 잘라냄 → 순간 튀는 현상 방지
"""
import zmq
import pickle
import math
import serial
import time
import os

# 기본값은 config_turret.ARDUINO에서 덮어쓴다.
USE_MICROSECONDS = False

try:
    import config_turret as cfg
except ImportError:
    print("!! config_turret.py를 찾을 수 없습니다. 기본값 사용")
    class cfg:
        PT1_CONFIG = {"pos_global": [0.075, 0, 0], "h_pivot": 0.03, "dx_laser": 0.0, "dz_laser": 0.05, "l_arm": 0.08, "pan_trim": 0, "tilt_trim": 0}
        PT2_CONFIG = {"pos_global": [0.375, 0, 0], "h_pivot": 0.03, "dx_laser": 0.0, "dz_laser": 0.05, "l_arm": 0.08, "pan_trim": 0, "tilt_trim": 0}
        FUSION_PARAMS = {"max_laser_dist": 3.0}
        SERVO_CENTER = 90
        SAFE_LIMITS = {"pan_min": 30, "pan_max": 150, "tilt_min": 30, "tilt_max": 150}
        SERVO_SMOOTH = {"alpha": 0.35, "min_send_interval": 0.030, "max_deg_per_frame": 12.0, "laser_keepalive_interval": 0.10}
        SERVO_PWM = {"us_min": 544, "us_max": 2400}
        TURRET_HOLD = {"hold_sec": 0.30, "return_home_sec": 1.0}
        NETWORK = {"result_port": 5556}
        ARDUINO = {"port": "COM3", "baud": 115200, "use_microseconds": False}

for attr, default in [
    ('SERVO_SMOOTH', {"alpha": 0.35, "min_send_interval": 0.030, "max_deg_per_frame": 12.0}),
    ('SERVO_PWM', {"us_min": 544, "us_max": 2400}),
    ('TURRET_HOLD', {"hold_sec": 0.30, "return_home_sec": 1.0}),
    ('NETWORK', {"result_port": 5556}),
    ('ARDUINO', {"port": "COM3", "baud": 115200, "use_microseconds": False}),
]:
    if not hasattr(cfg, attr):
        setattr(cfg, attr, default)

US_MIN = cfg.SERVO_PWM["us_min"]
US_MAX = cfg.SERVO_PWM["us_max"]
RESULT_PORT = int(cfg.NETWORK.get("result_port", 5556))
ARDUINO_CFG = getattr(cfg, "ARDUINO", {})
ARDUINO_PORT = str(ARDUINO_CFG.get("port", "COM3"))
ARDUINO_BAUD = int(ARDUINO_CFG.get("baud", 115200))
USE_MICROSECONDS = bool(ARDUINO_CFG.get("use_microseconds", USE_MICROSECONDS))
US_RANGE = US_MAX - US_MIN
PROJECT_ROOT = getattr(cfg, "PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
TURRET_OVERRIDE_PATH = os.path.join(PROJECT_ROOT, "turret_calibration_overrides.json")
TURRET_OVERRIDES_PRESENT = os.path.exists(TURRET_OVERRIDE_PATH)

def deg_to_us(deg):
    us = US_MIN + (deg / 180.0) * US_RANGE
    return max(US_MIN, min(US_MAX, int(round(us))))

def clamp_safe_angles(pan, tilt):
    pan = max(cfg.SAFE_LIMITS["pan_min"], min(cfg.SAFE_LIMITS["pan_max"], float(pan)))
    tilt = max(cfg.SAFE_LIMITS["tilt_min"], min(cfg.SAFE_LIMITS["tilt_max"], float(tilt)))
    return pan, tilt

def connect_arduino(port='COM3', baud=115200, retries=3):
    for attempt in range(retries):
        try:
            ser = serial.Serial(port, baud, timeout=0.1)
            time.sleep(2)
            print(f"  Arduino {port} connected")
            return ser
        except Exception as e:
            print(f"  Arduino fail ({attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(1)
    print("  Simulation mode (no Arduino)")
    return None

def calculate_precise_angles(target_global, pt):
    x_rel = target_global[0] - pt["pos_global"][0]
    z_rel = target_global[2] - pt["pos_global"][2]
    y_rel = target_global[1] - pt["h_pivot"]

    pan_rad = math.atan2(x_rel - pt["dx_laser"], z_rel - pt["dz_laser"])
    pan_deg = cfg.SERVO_CENTER - math.degrees(pan_rad) + pt["pan_trim"]

    dist_h = math.sqrt((x_rel - pt["dx_laser"])**2 + (z_rel - pt["dz_laser"])**2)
    if dist_h < 0.05:
        dist_h = 0.05
    dist_PT = math.sqrt(dist_h**2 + y_rel**2)

    l_arm = float(pt.get("l_arm", 0.0))
    if dist_PT > l_arm and l_arm > 0.0:
        beta = math.asin(max(-1.0, min(1.0, l_arm / dist_PT)))
        alpha_a = math.atan2(y_rel, dist_h)
        tilt_rad = alpha_a - beta
        tilt_deg = cfg.SERVO_CENTER + math.degrees(tilt_rad) + pt["tilt_trim"]
    else:
        tilt_deg = cfg.SERVO_CENTER + pt["tilt_trim"]

    # ★ 2축 기울기 보정 (config에 axis_tilt/axis_lean이 있으면 적용)
    ax_tilt = pt.get("axis_tilt", 0.0)
    ax_lean = pt.get("axis_lean", 0.0)
    if ax_tilt != 0.0 or ax_lean != 0.0:
        sin_pan = math.sin(math.radians(pan_deg - cfg.SERVO_CENTER))
        pan_deg  += sin_pan * ax_lean
        tilt_deg += sin_pan * ax_tilt

    safe_pan = max(cfg.SAFE_LIMITS["pan_min"], min(cfg.SAFE_LIMITS["pan_max"], pan_deg))
    safe_tilt = max(cfg.SAFE_LIMITS["tilt_min"], min(cfg.SAFE_LIMITS["tilt_max"], tilt_deg))

    out_of_range = (pan_deg < cfg.SAFE_LIMITS["pan_min"] or pan_deg > cfg.SAFE_LIMITS["pan_max"] or
                    tilt_deg < cfg.SAFE_LIMITS["tilt_min"] or tilt_deg > cfg.SAFE_LIMITS["tilt_max"])

    return safe_pan, safe_tilt, out_of_range


def clamp_angle(new_val, old_val, max_delta):
    """한 프레임 변화량을 max_delta 이하로 제한 (spike 방지)"""
    delta = new_val - old_val
    if abs(delta) > max_delta:
        return old_val + math.copysign(max_delta, delta)
    return new_val


def sanitize_target_packet(target):
    if not isinstance(target, dict):
        return None
    if not target.get("aim", True):
        return None
    status = str(target.get("status", "LOCKED")).upper()
    if status in ("IDLE", "DROPPED"):
        return None

    pos = target.get("pos")
    try:
        if pos is None or len(pos) < 3:
            return None
    except TypeError:
        return None
    try:
        clean_pos = [float(pos[0]), float(pos[1]), float(pos[2])]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in clean_pos):
        return None

    clean = dict(target)
    clean["pos"] = clean_pos
    try:
        clean["threat"] = float(clean.get("threat", 0.0))
    except (TypeError, ValueError):
        clean["threat"] = 0.0
    if not math.isfinite(clean["threat"]):
        clean["threat"] = 0.0
    return clean


def build_command(p1, t1, p2, t2, l1, l2):
    """프로토콜에 맞는 시리얼 명령 생성"""
    if USE_MICROSECONDS:
        return f"U{deg_to_us(p1)},{deg_to_us(t1)},{deg_to_us(p2)},{deg_to_us(t2)},{l1},{l2}\n"
    else:
        return f"P1{int(round(p1))}T1{int(round(t1))}P2{int(round(p2))}T2{int(round(t2))}L1{l1}L2{l2}\n"


def write_latest_command(ser, cmd, clear_output=True):
    """PC 송신 버퍼에 남은 이전 명령을 버리고 최신 명령만 전송한다."""
    if not ser:
        return False
    if clear_output:
        try:
            ser.reset_output_buffer()
        except Exception:
            pass
    ser.write(cmd.encode())
    return True


if __name__ == '__main__':
    proto = "U(microsecond)" if USE_MICROSECONDS else "P(degree)"
    print("\n" + "="*55)
    print(f"  TURRET SERVER (EMA smooth + spike clamp, {proto})")
    print("="*55)

    ser = connect_arduino(ARDUINO_PORT, ARDUINO_BAUD)

    ANGLE_ALPHA = cfg.SERVO_SMOOTH.get("alpha", 0.35)
    MIN_SEND = cfg.SERVO_SMOOTH.get("min_send_interval", 0.030)
    # ★ spike clamp: 한 프레임에 허용할 최대 각도 변화량
    MAX_DEG = cfg.SERVO_SMOOTH.get("max_deg_per_frame", 12.0)
    POLL_TIMEOUT_MS = max(0, int(cfg.SERVO_SMOOTH.get("poll_timeout_ms", 2)))
    CLEAR_OUTPUT_BEFORE_WRITE = bool(cfg.SERVO_SMOOTH.get("clear_output_before_write", True))
    THREAT_MOTION_BOOST = max(0.0, float(cfg.SERVO_SMOOTH.get("threat_motion_boost", 0.35)))
    MAX_ALPHA = max(0.05, min(0.95, float(cfg.SERVO_SMOOTH.get("max_alpha", 0.62))))
    TILT_ALPHA_SCALE = max(0.10, min(1.15, float(cfg.SERVO_SMOOTH.get("tilt_alpha_scale", 0.55))))
    TILT_DEADBAND = max(0.0, float(cfg.SERVO_SMOOTH.get("tilt_deadband", 0.9)))
    TILT_MAX_DEG_SCALE = max(0.30, min(1.30, float(cfg.SERVO_SMOOTH.get("tilt_max_deg_scale", 0.6))))
    ERROR_BOOST_DEG = max(0.1, float(cfg.SERVO_SMOOTH.get("error_boost_deg", 4.0)))
    ERROR_BOOST_ALPHA = max(0.0, min(0.4, float(cfg.SERVO_SMOOTH.get("error_boost_alpha", 0.0))))
    LASER_KEEPALIVE = max(MIN_SEND, float(cfg.SERVO_SMOOTH.get("laser_keepalive_interval", 0.10)))
    HOLD_SEC = cfg.TURRET_HOLD["hold_sec"]
    RETURN_SEC = cfg.TURRET_HOLD["return_home_sec"]

    # 홈 위치
    p1h, t1h = clamp_safe_angles(
        cfg.SERVO_CENTER + cfg.PT1_CONFIG["pan_trim"],
        cfg.SERVO_CENTER + cfg.PT1_CONFIG["tilt_trim"],
    )
    p2h, t2h = clamp_safe_angles(
        cfg.SERVO_CENTER + cfg.PT2_CONFIG["pan_trim"],
        cfg.SERVO_CENTER + cfg.PT2_CONFIG["tilt_trim"],
    )

    # EMA 상태
    f_p1, f_t1 = p1h, t1h
    f_p2, f_t2 = p2h, t2h

    # 초기 홈 명령
    if ser:
        cmd = build_command(p1h, t1h, p2h, t2h, 0, 0)
        write_latest_command(ser, cmd, CLEAR_OUTPUT_BEFORE_WRITE)
        print(f"  Init: {cmd.strip()}")

    print(f"  Protocol={proto}, EMA alpha={ANGLE_ALPHA}, min_send={MIN_SEND}s")
    print(f"  Spike clamp max_deg={MAX_DEG}°/frame")
    print(f"  Hold={HOLD_SEC}s, ReturnHome={RETURN_SEC}s")
    print(f"  ZMQ poll={POLL_TIMEOUT_MS}ms, serial_latest_clear={CLEAR_OUTPUT_BEFORE_WRITE}")
    print(f"  Laser keepalive={LASER_KEEPALIVE}s while laser is ON")
    if not TURRET_OVERRIDES_PRESENT:
        print("!! turret_calibration_overrides.json not found; using rough default turret geometry")
        print("!! Run calibration_turret.py after camera fusion is stable, otherwise laser accuracy will be poor")

    # ZMQ
    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt(zmq.CONFLATE, 1)
    try:
        sub.connect(f"tcp://localhost:{RESULT_PORT}")
        sub.setsockopt_string(zmq.SUBSCRIBE, "")
        print(f"  ZMQ connected ({RESULT_PORT})")
    except zmq.ZMQError as e:
        print(f"  ZMQ fail: {e}")
        if ser: ser.close()
        ctx.destroy()
        raise SystemExit(1)

    poller = zmq.Poller()
    poller.register(sub, zmq.POLLIN)

    # 상태
    tracking_active = False
    last_nonempty_time = 0.0
    last_target_p1, last_target_t1 = p1h, t1h
    last_target_p2, last_target_t2 = p2h, t2h
    desired_l1, desired_l2 = 0, 0

    last_command = ""
    last_send_time = 0
    last_control_time = 0
    no_data_count = 0
    target_alpha_p1 = ANGLE_ALPHA
    target_alpha_p2 = ANGLE_ALPHA
    pt1_state = "idle"
    pt2_state = "idle"
    packet_age_sum = 0.0
    packet_age_max = 0.0
    packet_age_count = 0

    send_count = 0
    keepalive_count = 0
    spike_count = 0
    last_log_time = time.time()

    def adaptive_alpha(base_alpha, pan_err, tilt_err):
        err = max(abs(float(pan_err)), abs(float(tilt_err)))
        if err <= ERROR_BOOST_DEG or ERROR_BOOST_ALPHA <= 0.0:
            return base_alpha
        boost_ratio = min(1.0, (err - ERROR_BOOST_DEG) / ERROR_BOOST_DEG)
        return min(MAX_ALPHA, base_alpha + ERROR_BOOST_ALPHA * boost_ratio)

    try:
        while True:
            now = time.time()

            # (1) ZMQ 수신
            got_data = False
            packet = {}
            try:
                events = dict(poller.poll(POLL_TIMEOUT_MS))
                if sub in events:
                    raw_data = None
                    while True:
                        try:
                            raw_data = sub.recv(flags=zmq.NOBLOCK)
                        except zmq.Again:
                            break
                    if raw_data is not None:
                        packet = pickle.loads(raw_data)
                        if isinstance(packet, dict):
                            got_data = True
                            no_data_count = 0
                            fusion_ts = packet.get("fusion_ts")
                            if isinstance(fusion_ts, (int, float)) and math.isfinite(float(fusion_ts)):
                                packet_age = max(0.0, now - float(fusion_ts))
                                packet_age_sum += packet_age
                                packet_age_max = max(packet_age_max, packet_age)
                                packet_age_count += 1
                        else:
                            packet = {}
                else:
                    no_data_count += 1
            except zmq.Again:
                no_data_count += 1
            except Exception:
                no_data_count += 1
                time.sleep(0.001)

            # (2) 타겟 각도 계산
            if got_data:
                data = packet.get("targets", {})
                trims = packet.get("trims")
                if not isinstance(data, dict):
                    data = {}

                if isinstance(trims, dict):
                    pt1_trim = trims.get("pt1")
                    pt2_trim = trims.get("pt2")
                    try:
                        if pt1_trim is not None and len(pt1_trim) >= 2:
                            cfg.PT1_CONFIG["pan_trim"] = float(pt1_trim[0])
                            cfg.PT1_CONFIG["tilt_trim"] = float(pt1_trim[1])
                        if pt2_trim is not None and len(pt2_trim) >= 2:
                            cfg.PT2_CONFIG["pan_trim"] = float(pt2_trim[0])
                            cfg.PT2_CONFIG["tilt_trim"] = float(pt2_trim[1])
                    except (TypeError, ValueError):
                        pass
                    p1h, t1h = clamp_safe_angles(
                        cfg.SERVO_CENTER + cfg.PT1_CONFIG["pan_trim"],
                        cfg.SERVO_CENTER + cfg.PT1_CONFIG["tilt_trim"],
                    )
                    p2h, t2h = clamp_safe_angles(
                        cfg.SERVO_CENTER + cfg.PT2_CONFIG["pan_trim"],
                        cfg.SERVO_CENTER + cfg.PT2_CONFIG["tilt_trim"],
                    )

                alpha_p1, alpha_p2 = ANGLE_ALPHA, ANGLE_ALPHA
                aimable_data = {}
                for name, target in data.items():
                    clean_target = sanitize_target_packet(target)
                    if clean_target is not None:
                        aimable_data[name] = clean_target

                if aimable_data:
                    last_nonempty_time = now
                    tracking_active = True

                    sorted_t = sorted(aimable_data.items(), key=lambda x: x[1].get("threat", 0), reverse=True)
                    t1d = sorted_t[0][1] if len(sorted_t) > 0 else None
                    t2d = sorted_t[1][1] if len(sorted_t) > 1 else None

                    # ★ z_rel gate: 터렛 앞쪽(z>0.10m)만 유효, 음수/비정상 Z 차단
                    def _z_valid(pos, pt_cfg):
                        return pos[2] <= cfg.FUSION_PARAMS["max_laser_dist"] and \
                               (pos[2] - pt_cfg["pos_global"][2]) > 0.10

                    if t1d and _z_valid(t1d["pos"], cfg.PT1_CONFIG):
                        p, t, oor = calculate_precise_angles(t1d["pos"], cfg.PT1_CONFIG)
                        threat = max(0.0, min(float(t1d.get("threat", 0.0)), 2.0))
                        dyn_max = MAX_DEG * (1.0 + threat * THREAT_MOTION_BOOST)
                        alpha_p1 = min(MAX_ALPHA, ANGLE_ALPHA * (1.0 + threat * THREAT_MOTION_BOOST))
                        new_p = clamp_angle(p, last_target_p1, dyn_max)
                        new_t = clamp_angle(t, last_target_t1, dyn_max * TILT_MAX_DEG_SCALE)
                        if new_p != p or new_t != t:
                            spike_count += 1
                        last_target_p1, last_target_t1 = new_p, new_t
                        desired_l1 = 0 if oor else 1
                        pt1_state = "oor" if oor else "lock"
                    else:
                        last_target_p1, last_target_t1 = p1h, t1h
                        desired_l1 = 0
                        pt1_state = "z_gate" if t1d else "no_target"

                    if t2d and _z_valid(t2d["pos"], cfg.PT2_CONFIG):
                        p, t, oor = calculate_precise_angles(t2d["pos"], cfg.PT2_CONFIG)
                        threat = max(0.0, min(float(t2d.get("threat", 0.0)), 2.0))
                        dyn_max = MAX_DEG * (1.0 + threat * THREAT_MOTION_BOOST)
                        alpha_p2 = min(MAX_ALPHA, ANGLE_ALPHA * (1.0 + threat * THREAT_MOTION_BOOST))
                        new_p = clamp_angle(p, last_target_p2, dyn_max)
                        new_t = clamp_angle(t, last_target_t2, dyn_max * TILT_MAX_DEG_SCALE)
                        if new_p != p or new_t != t:
                            spike_count += 1
                        last_target_p2, last_target_t2 = new_p, new_t
                        desired_l2 = 0 if oor else 1
                        pt2_state = "oor" if oor else "lock"
                    elif t1d and _z_valid(t1d["pos"], cfg.PT2_CONFIG):
                        p, t, oor = calculate_precise_angles(t1d["pos"], cfg.PT2_CONFIG)
                        threat = max(0.0, min(float(t1d.get("threat", 0.0)), 2.0))
                        dyn_max = MAX_DEG * (1.0 + threat * THREAT_MOTION_BOOST)
                        alpha_p2 = min(MAX_ALPHA, ANGLE_ALPHA * (1.0 + threat * THREAT_MOTION_BOOST))
                        new_p = clamp_angle(p, last_target_p2, dyn_max)
                        new_t = clamp_angle(t, last_target_t2, dyn_max * TILT_MAX_DEG_SCALE)
                        if new_p != p or new_t != t:
                            spike_count += 1
                        last_target_p2, last_target_t2 = new_p, new_t
                        desired_l2 = 0 if oor else 1
                        pt2_state = "same_oor" if oor else "same_lock"
                    else:
                        last_target_p2, last_target_t2 = p2h, t2h
                        desired_l2 = 0
                        pt2_state = "z_gate" if (t2d or t1d) else "no_target"
                else:
                    tracking_active = False
                    pt1_state = "no_data"
                    pt2_state = "no_data"
                target_alpha_p1 = alpha_p1
                target_alpha_p2 = alpha_p2

            if now - last_control_time < MIN_SEND:
                continue
            last_control_time = now
            alpha_p1 = target_alpha_p1
            alpha_p2 = target_alpha_p2

            # (3) Hold/Ramp → EMA 타겟
            age = now - last_nonempty_time if last_nonempty_time > 0 else 1e9

            if age <= HOLD_SEC:
                tgt_p1, tgt_t1 = last_target_p1, last_target_t1
                tgt_p2, tgt_t2 = last_target_p2, last_target_t2
                if tracking_active:
                    eff_l1, eff_l2 = desired_l1, desired_l2
                else:
                    eff_l1, eff_l2 = 0, 0
            elif age <= HOLD_SEC + RETURN_SEC:
                tracking_active = False
                t_ratio = min(1.0, (age - HOLD_SEC) / RETURN_SEC)
                tgt_p1 = last_target_p1 + (p1h - last_target_p1) * t_ratio
                tgt_t1 = last_target_t1 + (t1h - last_target_t1) * t_ratio
                tgt_p2 = last_target_p2 + (p2h - last_target_p2) * t_ratio
                tgt_t2 = last_target_t2 + (t2h - last_target_t2) * t_ratio
                eff_l1, eff_l2 = 0, 0
            else:
                tracking_active = False
                tgt_p1, tgt_t1 = p1h, t1h
                tgt_p2, tgt_t2 = p2h, t2h
                eff_l1, eff_l2 = 0, 0

            # (4) Adaptive EMA smoothing. Small jitter stays filtered, large tracking error responds faster.
            if age <= HOLD_SEC and tracking_active:
                alpha_p1 = adaptive_alpha(alpha_p1, tgt_p1 - f_p1, tgt_t1 - f_t1)
                alpha_p2 = adaptive_alpha(alpha_p2, tgt_p2 - f_p2, tgt_t2 - f_t2)

            f_p1 += alpha_p1 * (tgt_p1 - f_p1)
            tilt_alpha_p1 = min(0.98, alpha_p1 * TILT_ALPHA_SCALE)
            if abs(tgt_t1 - f_t1) > TILT_DEADBAND:
                f_t1 += tilt_alpha_p1 * (tgt_t1 - f_t1)
            f_p2 += alpha_p2 * (tgt_p2 - f_p2)
            tilt_alpha_p2 = min(0.98, alpha_p2 * TILT_ALPHA_SCALE)
            if abs(tgt_t2 - f_t2) > TILT_DEADBAND:
                f_t2 += tilt_alpha_p2 * (tgt_t2 - f_t2)

            # (5) 전송
            cmd = build_command(f_p1, f_t1, f_p2, f_t2, eff_l1, eff_l2)

            cmd_changed = cmd != last_command
            laser_keepalive_due = bool(eff_l1 or eff_l2) and (now - last_send_time >= LASER_KEEPALIVE)
            if (cmd_changed and (now - last_send_time >= MIN_SEND)) or laser_keepalive_due:
                if ser:
                    write_latest_command(ser, cmd, CLEAR_OUTPUT_BEFORE_WRITE)
                if laser_keepalive_due and not cmd_changed:
                    keepalive_count += 1
                last_command = cmd
                last_send_time = now
                send_count += 1

            # 로그 (5초마다)
            if now - last_log_time > 5.0:
                elapsed = max(now - last_log_time, 0.01)
                hz = send_count / elapsed
                avg_pkt_ms = (packet_age_sum / packet_age_count * 1000.0) if packet_age_count else 0.0
                max_pkt_ms = packet_age_max * 1000.0
                print(f"  [turret] send={hz:.0f}Hz age={age:.2f}s active={tracking_active} "
                      f"l={eff_l1},{eff_l2} pt={pt1_state},{pt2_state} "
                      f"pkt={avg_pkt_ms:.0f}/{max_pkt_ms:.0f}ms keepalive={keepalive_count} spikes={spike_count}")
                send_count = 0
                keepalive_count = 0
                spike_count = 0
                packet_age_sum = 0.0
                packet_age_max = 0.0
                packet_age_count = 0
                last_log_time = now

    except KeyboardInterrupt:
        print("\n  Shutting down...")
    except Exception as e:
        print(f"\n  Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if ser:
            cmd = build_command(p1h, t1h, p2h, t2h, 0, 0)
            write_latest_command(ser, cmd, CLEAR_OUTPUT_BEFORE_WRITE)
            time.sleep(0.5)
            ser.close()
        sub.close()
        ctx.destroy()
        print("  Done")
