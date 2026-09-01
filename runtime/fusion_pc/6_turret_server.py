# -*- coding: utf-8 -*-
"""
6_turret_server.py
AEGIS Dual Turret runtime controller

이번 튜닝 버전의 목적
1) 20-point calibration 결과(turret_calibration_overrides.json)는 그대로 사용
2) 위 -> 아래 이동 시 덜 내려오는 서보 backlash/hysteresis를 방향별로 보상
3) 정지 시 작은 좌표 노이즈로 인한 레이저 떨림 감소
4) 큰 이동 시 adaptive alpha로 빠르게 따라가도록 함
5) 기존 HOLD / HOME return / laser watchdog / spike clamp / ZMQ 구조 유지
"""

import math
import os
import pickle
import time

import serial
import zmq

try:
    import config_turret as cfg
except ImportError:
    print("!! config_turret.py를 찾을 수 없습니다. 기본값 사용")

    class cfg:
        PT1_CONFIG = {
            "pos_global": [0.075, 0.0, 0.0],
            "h_pivot": 0.03,
            "dx_laser": 0.0,
            "dz_laser": 0.05,
            "l_arm": 0.08,
            "pan_trim": 0.0,
            "tilt_trim": 0.0,
            "axis_tilt": 0.0,
            "axis_lean": 0.0,
        }
        PT2_CONFIG = {
            "pos_global": [0.375, 0.0, 0.0],
            "h_pivot": 0.03,
            "dx_laser": 0.0,
            "dz_laser": 0.05,
            "l_arm": 0.08,
            "pan_trim": 0.0,
            "tilt_trim": 0.0,
            "axis_tilt": 0.0,
            "axis_lean": 0.0,
        }
        FUSION_PARAMS = {"max_laser_dist": 3.0}
        SERVO_CENTER = 90.0
        SAFE_LIMITS = {
            "pan_min": 20.0,
            "pan_max": 160.0,
            "tilt_min": 45.0,
            "tilt_max": 150.0,
        }
        SERVO_SMOOTH = {
            "alpha": 0.40,
            "min_send_interval": 0.020,
            "max_deg_per_frame": 18.0,
            "poll_timeout_ms": 2,
            "clear_output_before_write": True,
            "threat_motion_boost": 0.15,
            "max_alpha": 0.90,
            "pan_deadband": 0.08,
            "tilt_alpha_scale": 1.00,
            "tilt_deadband": 0.10,
            "tilt_max_deg_scale": 0.90,
            "error_boost_deg": 1.0,
            "error_boost_alpha": 0.38,
            "laser_keepalive_interval": 0.10,
        }
        TURRET_DIRECTION_COMP = {
            "direction_epsilon_deg": 0.10,
            "pt1_down_deg": 0.60,
            "pt2_down_deg": 0.60,
            "pt1_up_deg": 0.00,
            "pt2_up_deg": 0.00,
            "down_alpha_mult": 1.18,
        }
        SERVO_PWM = {"us_min": 544, "us_max": 2400}
        TURRET_HOLD = {"hold_sec": 0.30, "return_home_sec": 1.0}
        NETWORK = {"result_port": 5556}
        ARDUINO = {"port": "COM4", "baud": 115200, "use_microseconds": True}
        PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# Config
# ============================================================

SERVO_CENTER = float(getattr(cfg, "SERVO_CENTER", 90.0))
SAFE_LIMITS = getattr(
    cfg,
    "SAFE_LIMITS",
    {"pan_min": 20, "pan_max": 160, "tilt_min": 45, "tilt_max": 150},
)

SERVO_PWM = getattr(cfg, "SERVO_PWM", {"us_min": 544, "us_max": 2400})
US_MIN = int(SERVO_PWM.get("us_min", 544))
US_MAX = int(SERVO_PWM.get("us_max", 2400))
US_RANGE = US_MAX - US_MIN

NETWORK_CFG = getattr(cfg, "NETWORK", {})
RESULT_PORT = int(NETWORK_CFG.get("result_port", 5556))

ARDUINO_CFG = getattr(cfg, "ARDUINO", {})
ARDUINO_PORT = str(ARDUINO_CFG.get("port", "COM4"))
ARDUINO_BAUD = int(ARDUINO_CFG.get("baud", 115200))
USE_MICROSECONDS = bool(ARDUINO_CFG.get("use_microseconds", True))

PROJECT_ROOT = getattr(
    cfg,
    "PROJECT_ROOT",
    os.path.dirname(os.path.abspath(__file__)),
)
TURRET_OVERRIDE_PATH = os.path.join(
    PROJECT_ROOT,
    "turret_calibration_overrides.json",
)
TURRET_OVERRIDES_PRESENT = os.path.exists(TURRET_OVERRIDE_PATH)

SMOOTH_CFG = getattr(cfg, "SERVO_SMOOTH", {})
ANGLE_ALPHA = float(SMOOTH_CFG.get("alpha", 0.40))
MIN_SEND = max(0.005, float(SMOOTH_CFG.get("min_send_interval", 0.020)))
MAX_DEG = max(1.0, float(SMOOTH_CFG.get("max_deg_per_frame", 18.0)))

POLL_TIMEOUT_MS = max(0, int(SMOOTH_CFG.get("poll_timeout_ms", 2)))
CLEAR_OUTPUT_BEFORE_WRITE = bool(
    SMOOTH_CFG.get("clear_output_before_write", True)
)

THREAT_MOTION_BOOST = max(
    0.0,
    float(SMOOTH_CFG.get("threat_motion_boost", 0.15)),
)
MAX_ALPHA = max(
    0.05,
    min(0.98, float(SMOOTH_CFG.get("max_alpha", 0.90))),
)

# 작은 움직임은 무시해서 서보 떨림을 줄인다.
PAN_DEADBAND = max(
    0.0,
    float(SMOOTH_CFG.get("pan_deadband", 0.08)),
)
TILT_DEADBAND = max(
    0.0,
    float(SMOOTH_CFG.get("tilt_deadband", 0.10)),
)

TILT_ALPHA_SCALE = max(
    0.10,
    min(1.30, float(SMOOTH_CFG.get("tilt_alpha_scale", 1.00))),
)
TILT_MAX_DEG_SCALE = max(
    0.30,
    min(1.30, float(SMOOTH_CFG.get("tilt_max_deg_scale", 0.90))),
)

ERROR_BOOST_DEG = max(
    0.1,
    float(SMOOTH_CFG.get("error_boost_deg", 1.0)),
)
ERROR_BOOST_ALPHA = max(
    0.0,
    min(0.45, float(SMOOTH_CFG.get("error_boost_alpha", 0.38))),
)

LASER_KEEPALIVE = max(
    MIN_SEND,
    float(SMOOTH_CFG.get("laser_keepalive_interval", 0.10)),
)

HOLD_CFG = getattr(cfg, "TURRET_HOLD", {})
HOLD_SEC = max(0.0, float(HOLD_CFG.get("hold_sec", 0.30)))
RETURN_SEC = max(0.05, float(HOLD_CFG.get("return_home_sec", 1.0)))

# ============================================================
# Direction-aware tilt backlash compensation
# ============================================================

DIR_CFG = getattr(cfg, "TURRET_DIRECTION_COMP", {})

DIR_EPS = max(
    0.01,
    float(DIR_CFG.get("direction_epsilon_deg", 0.10)),
)

PT1_DOWN_COMP = max(
    0.0,
    float(DIR_CFG.get("pt1_down_deg", 0.60)),
)
PT2_DOWN_COMP = max(
    0.0,
    float(DIR_CFG.get("pt2_down_deg", 0.60)),
)

PT1_UP_COMP = max(
    0.0,
    float(DIR_CFG.get("pt1_up_deg", 0.00)),
)
PT2_UP_COMP = max(
    0.0,
    float(DIR_CFG.get("pt2_up_deg", 0.00)),
)

TILT_DOWN_ALPHA_MULT = max(
    1.0,
    min(1.50, float(DIR_CFG.get("down_alpha_mult", 1.18))),
)

# raw target tilt의 이동 방향을 기억한다.
# direction +1 : 타깃이 위쪽으로 움직임 (tilt 증가)
# direction -1 : 타깃이 아래쪽으로 움직임 (tilt 감소)
tilt_direction_state = {
    "pt1": {"prev_raw": None, "direction": 0},
    "pt2": {"prev_raw": None, "direction": 0},
}


def reset_tilt_direction_state():
    for state in tilt_direction_state.values():
        state["prev_raw"] = None
        state["direction"] = 0


def apply_tilt_direction_comp(turret_name, raw_tilt):
    """
    서보/기구의 방향별 backlash 보상.

    현재 증상:
      아래 -> 위 : 정확
      위 -> 아래 : 실제 레이저가 타깃 위에 남음

    현재 geometry에서 더 낮은 타깃으로 갈수록 tilt command가 작아지므로
    하강(direction < 0) 시 command를 추가로 조금 감소시킨다.

    방향이 멈춘 뒤에도 마지막 방향을 유지하는 이유:
    gear backlash 때문에 '도착 후'에도 같은 방향의 오프셋이 필요하기 때문.
    """
    state = tilt_direction_state[turret_name]

    raw_tilt = float(raw_tilt)
    prev_raw = state["prev_raw"]

    if prev_raw is not None:
        delta = raw_tilt - prev_raw

        if delta > DIR_EPS:
            state["direction"] = +1
        elif delta < -DIR_EPS:
            state["direction"] = -1

    state["prev_raw"] = raw_tilt
    direction = int(state["direction"])

    if turret_name == "pt1":
        down_comp = PT1_DOWN_COMP
        up_comp = PT1_UP_COMP
    else:
        down_comp = PT2_DOWN_COMP
        up_comp = PT2_UP_COMP

    compensated = raw_tilt

    if direction < 0:
        # 위 -> 아래 : 실제보다 약간 더 낮게 명령해서 backlash 보상
        compensated -= down_comp

    elif direction > 0:
        compensated += up_comp

    return compensated, direction


# ============================================================
# Helpers
# ============================================================

def deg_to_us(deg):
    us = US_MIN + (float(deg) / 180.0) * US_RANGE
    return max(US_MIN, min(US_MAX, int(round(us))))


def clamp_safe_angles(pan, tilt):
    pan = max(
        float(SAFE_LIMITS["pan_min"]),
        min(float(SAFE_LIMITS["pan_max"]), float(pan)),
    )
    tilt = max(
        float(SAFE_LIMITS["tilt_min"]),
        min(float(SAFE_LIMITS["tilt_max"]), float(tilt)),
    )
    return pan, tilt


def connect_arduino(port="COM4", baud=115200, retries=3):
    for attempt in range(retries):
        try:
            ser = serial.Serial(port, baud, timeout=0.1)
            time.sleep(2.0)
            print(f"  Arduino {port} connected")
            return ser
        except Exception as exc:
            print(
                f"  Arduino fail ({attempt + 1}/{retries}): "
                f"{type(exc).__name__}: {exc}"
            )
            if attempt < retries - 1:
                time.sleep(1.0)

    print("  Simulation mode (no Arduino)")
    return None


def calculate_precise_angles(target_global, pt):
    """
    calibration_turret.py와 같은 geometry 모델.
    turret_calibration_overrides.json 적용 후 cfg.PT1/2_CONFIG를 그대로 사용.
    """
    x_rel = float(target_global[0]) - float(pt["pos_global"][0])
    z_rel = float(target_global[2]) - float(pt["pos_global"][2])
    y_rel = float(target_global[1]) - float(pt["h_pivot"])

    pan_rad = math.atan2(
        x_rel - float(pt["dx_laser"]),
        z_rel - float(pt["dz_laser"]),
    )
    pan_deg = (
        SERVO_CENTER
        - math.degrees(pan_rad)
        + float(pt["pan_trim"])
    )

    dist_h = math.sqrt(
        (x_rel - float(pt["dx_laser"])) ** 2
        + (z_rel - float(pt["dz_laser"])) ** 2
    )
    if dist_h < 0.05:
        dist_h = 0.05

    dist_pt = math.sqrt(dist_h ** 2 + y_rel ** 2)

    l_arm = float(pt.get("l_arm", 0.0))

    if dist_pt > l_arm and l_arm > 0.0:
        beta = math.asin(
            max(-1.0, min(1.0, l_arm / dist_pt))
        )
        alpha_a = math.atan2(y_rel, dist_h)

        tilt_deg = (
            SERVO_CENTER
            + math.degrees(alpha_a - beta)
            + float(pt["tilt_trim"])
        )
    else:
        tilt_deg = SERVO_CENTER + float(pt["tilt_trim"])

    # 2축 기울기 보정
    axis_tilt = float(pt.get("axis_tilt", 0.0))
    axis_lean = float(pt.get("axis_lean", 0.0))

    if axis_tilt != 0.0 or axis_lean != 0.0:
        sin_pan = math.sin(
            math.radians(pan_deg - SERVO_CENTER)
        )
        pan_deg += sin_pan * axis_lean
        tilt_deg += sin_pan * axis_tilt

    out_of_range = (
        pan_deg < float(SAFE_LIMITS["pan_min"])
        or pan_deg > float(SAFE_LIMITS["pan_max"])
        or tilt_deg < float(SAFE_LIMITS["tilt_min"])
        or tilt_deg > float(SAFE_LIMITS["tilt_max"])
    )

    safe_pan, safe_tilt = clamp_safe_angles(
        pan_deg,
        tilt_deg,
    )

    return safe_pan, safe_tilt, out_of_range


def apply_comp_and_clamp(turret_name, pan, tilt, oor):
    """
    방향성 tilt 보상을 적용한 뒤 다시 안전 범위를 확인한다.
    """
    compensated_tilt, direction = apply_tilt_direction_comp(
        turret_name,
        tilt,
    )

    comp_oor = (
        compensated_tilt < float(SAFE_LIMITS["tilt_min"])
        or compensated_tilt > float(SAFE_LIMITS["tilt_max"])
    )

    safe_pan, safe_tilt = clamp_safe_angles(
        pan,
        compensated_tilt,
    )

    return safe_pan, safe_tilt, bool(oor or comp_oor), direction


def clamp_angle(new_val, old_val, max_delta):
    """
    순간적인 3D 튐으로 한 프레임에 너무 큰 servo jump가 발생하지 않게 제한.
    """
    delta = float(new_val) - float(old_val)

    if abs(delta) > float(max_delta):
        return float(old_val) + math.copysign(
            float(max_delta),
            delta,
        )

    return float(new_val)


def sanitize_target_packet(target):
    if not isinstance(target, dict):
        return None

    if not target.get("aim", True):
        return None

    status = str(
        target.get("status", "LOCKED")
    ).upper()

    if status in ("IDLE", "DROPPED"):
        return None

    pos = target.get("pos")

    try:
        if pos is None or len(pos) < 3:
            return None
    except TypeError:
        return None

    try:
        clean_pos = [
            float(pos[0]),
            float(pos[1]),
            float(pos[2]),
        ]
    except (TypeError, ValueError):
        return None

    if not all(math.isfinite(v) for v in clean_pos):
        return None

    clean = dict(target)
    clean["pos"] = clean_pos

    try:
        clean["threat"] = float(
            clean.get("threat", 0.0)
        )
    except (TypeError, ValueError):
        clean["threat"] = 0.0

    if not math.isfinite(clean["threat"]):
        clean["threat"] = 0.0

    return clean


def build_command(p1, t1, p2, t2, l1, l2):
    if USE_MICROSECONDS:
        return (
            f"U"
            f"{deg_to_us(p1)},"
            f"{deg_to_us(t1)},"
            f"{deg_to_us(p2)},"
            f"{deg_to_us(t2)},"
            f"{int(bool(l1))},"
            f"{int(bool(l2))}\n"
        )

    return (
        f"P1{int(round(p1))}"
        f"T1{int(round(t1))}"
        f"P2{int(round(p2))}"
        f"T2{int(round(t2))}"
        f"L1{int(bool(l1))}"
        f"L2{int(bool(l2))}\n"
    )


def write_latest_command(ser, cmd, clear_output=True):
    if not ser:
        return False

    if clear_output:
        try:
            ser.reset_output_buffer()
        except Exception:
            pass

    ser.write(cmd.encode("ascii"))
    return True


def direction_text(direction):
    if direction < 0:
        return "DOWN"
    if direction > 0:
        return "UP"
    return "HOLD"


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    proto = (
        "U(microsecond)"
        if USE_MICROSECONDS
        else "P(degree)"
    )

    print("\n" + "=" * 72)
    print(f"  AEGIS TURRET SERVER - Direction Comp + Adaptive Smooth ({proto})")
    print("=" * 72)

    ser = connect_arduino(
        ARDUINO_PORT,
        ARDUINO_BAUD,
    )

    # 홈 위치
    p1h, t1h = clamp_safe_angles(
        SERVO_CENTER + float(cfg.PT1_CONFIG["pan_trim"]),
        SERVO_CENTER + float(cfg.PT1_CONFIG["tilt_trim"]),
    )
    p2h, t2h = clamp_safe_angles(
        SERVO_CENTER + float(cfg.PT2_CONFIG["pan_trim"]),
        SERVO_CENTER + float(cfg.PT2_CONFIG["tilt_trim"]),
    )

    # EMA 상태
    f_p1, f_t1 = p1h, t1h
    f_p2, f_t2 = p2h, t2h

    if ser:
        cmd = build_command(
            p1h, t1h,
            p2h, t2h,
            0, 0,
        )
        write_latest_command(
            ser,
            cmd,
            CLEAR_OUTPUT_BEFORE_WRITE,
        )
        print(f"  Init: {cmd.strip()}")

    print(
        f"  Protocol={proto} | "
        f"base alpha={ANGLE_ALPHA:.2f} | "
        f"max alpha={MAX_ALPHA:.2f}"
    )
    print(
        f"  deadband pan={PAN_DEADBAND:.2f}deg "
        f"tilt={TILT_DEADBAND:.2f}deg"
    )
    print(
        f"  update={1.0 / MIN_SEND:.0f}Hz | "
        f"spike clamp={MAX_DEG:.1f}deg/frame"
    )
    print(
        f"  DOWN comp PT1={PT1_DOWN_COMP:.2f}deg "
        f"PT2={PT2_DOWN_COMP:.2f}deg | "
        f"down speed x{TILT_DOWN_ALPHA_MULT:.2f}"
    )
    print(
        f"  Hold={HOLD_SEC:.2f}s | "
        f"ReturnHome={RETURN_SEC:.2f}s | "
        f"ZMQ={RESULT_PORT}"
    )

    if not TURRET_OVERRIDES_PRESENT:
        print(
            "!! turret_calibration_overrides.json 없음: "
            "rough default geometry 사용 중"
        )

    # --------------------------------------------------------
    # ZMQ
    # --------------------------------------------------------

    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)

    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt(zmq.CONFLATE, 1)

    try:
        sub.connect(
            f"tcp://localhost:{RESULT_PORT}"
        )
        sub.setsockopt_string(
            zmq.SUBSCRIBE,
            "",
        )
        print(
            f"  Fusion ZMQ connected ({RESULT_PORT})"
        )

    except zmq.ZMQError as exc:
        print(f"  ZMQ fail: {exc}")

        if ser:
            ser.close()

        ctx.destroy()
        raise SystemExit(1)

    poller = zmq.Poller()
    poller.register(
        sub,
        zmq.POLLIN,
    )

    # --------------------------------------------------------
    # Runtime state
    # --------------------------------------------------------

    tracking_active = False
    last_nonempty_time = 0.0

    last_target_p1, last_target_t1 = p1h, t1h
    last_target_p2, last_target_t2 = p2h, t2h

    desired_l1 = 0
    desired_l2 = 0

    last_command = ""
    last_send_time = 0.0
    last_control_time = 0.0

    target_alpha_p1 = ANGLE_ALPHA
    target_alpha_p2 = ANGLE_ALPHA

    target_tilt_dir_p1 = 0
    target_tilt_dir_p2 = 0

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
        """
        작은 오차 -> base alpha로 안정적으로
        큰 오차 -> alpha 증가 -> 빠른 추적
        """
        err = max(
            abs(float(pan_err)),
            abs(float(tilt_err)),
        )

        if (
            err <= ERROR_BOOST_DEG
            or ERROR_BOOST_ALPHA <= 0.0
        ):
            return float(base_alpha)

        boost_ratio = min(
            1.0,
            (err - ERROR_BOOST_DEG)
            / max(ERROR_BOOST_DEG, 1e-6),
        )

        return min(
            MAX_ALPHA,
            float(base_alpha)
            + ERROR_BOOST_ALPHA * boost_ratio,
        )

    def get_target_angles(target_info, pt_cfg, turret_name):
        """
        Fusion target -> calibrated turret angles
        -> direction compensation
        -> safe clamp.
        """
        p, t, oor = calculate_precise_angles(
            target_info["pos"],
            pt_cfg,
        )

        p, t, oor, direction = apply_comp_and_clamp(
            turret_name,
            p,
            t,
            oor,
        )

        return p, t, oor, direction

    try:
        while True:
            now = time.time()

            # =================================================
            # 1) 최신 Fusion packet 수신
            # =================================================

            got_data = False
            packet = {}

            try:
                events = dict(
                    poller.poll(POLL_TIMEOUT_MS)
                )

                if sub in events:
                    raw_data = None

                    # CONFLATE + drain: 항상 가장 최신 packet만 사용
                    while True:
                        try:
                            raw_data = sub.recv(
                                flags=zmq.NOBLOCK
                            )
                        except zmq.Again:
                            break

                    if raw_data is not None:
                        loaded = pickle.loads(raw_data)

                        if isinstance(loaded, dict):
                            packet = loaded
                            got_data = True

                            fusion_ts = packet.get(
                                "fusion_ts"
                            )

                            if (
                                isinstance(
                                    fusion_ts,
                                    (int, float),
                                )
                                and math.isfinite(
                                    float(fusion_ts)
                                )
                            ):
                                packet_age = max(
                                    0.0,
                                    now - float(fusion_ts),
                                )

                                packet_age_sum += packet_age
                                packet_age_max = max(
                                    packet_age_max,
                                    packet_age,
                                )
                                packet_age_count += 1

            except Exception:
                # 일시적인 decode/ZMQ 오류가 제어루프 전체를 멈추지 않게 함
                time.sleep(0.001)

            # =================================================
            # 2) 새 target -> 각도 계산
            # =================================================

            if got_data:
                data = packet.get(
                    "targets",
                    {},
                )
                trims = packet.get(
                    "trims",
                )

                if not isinstance(data, dict):
                    data = {}

                # Fusion에서 runtime trim을 보내는 기존 기능 유지
                if isinstance(trims, dict):
                    pt1_trim = trims.get("pt1")
                    pt2_trim = trims.get("pt2")

                    try:
                        if (
                            pt1_trim is not None
                            and len(pt1_trim) >= 2
                        ):
                            cfg.PT1_CONFIG["pan_trim"] = float(
                                pt1_trim[0]
                            )
                            cfg.PT1_CONFIG["tilt_trim"] = float(
                                pt1_trim[1]
                            )

                        if (
                            pt2_trim is not None
                            and len(pt2_trim) >= 2
                        ):
                            cfg.PT2_CONFIG["pan_trim"] = float(
                                pt2_trim[0]
                            )
                            cfg.PT2_CONFIG["tilt_trim"] = float(
                                pt2_trim[1]
                            )

                    except (
                        TypeError,
                        ValueError,
                    ):
                        pass

                    p1h, t1h = clamp_safe_angles(
                        SERVO_CENTER
                        + float(cfg.PT1_CONFIG["pan_trim"]),
                        SERVO_CENTER
                        + float(cfg.PT1_CONFIG["tilt_trim"]),
                    )

                    p2h, t2h = clamp_safe_angles(
                        SERVO_CENTER
                        + float(cfg.PT2_CONFIG["pan_trim"]),
                        SERVO_CENTER
                        + float(cfg.PT2_CONFIG["tilt_trim"]),
                    )

                alpha_p1 = ANGLE_ALPHA
                alpha_p2 = ANGLE_ALPHA

                aimable_data = {}

                for name, target in data.items():
                    clean_target = sanitize_target_packet(
                        target
                    )

                    if clean_target is not None:
                        aimable_data[name] = clean_target

                if aimable_data:
                    last_nonempty_time = now
                    tracking_active = True

                    sorted_targets = sorted(
                        aimable_data.items(),
                        key=lambda item:
                        item[1].get("threat", 0.0),
                        reverse=True,
                    )

                    t1d = (
                        sorted_targets[0][1]
                        if len(sorted_targets) > 0
                        else None
                    )

                    t2d = (
                        sorted_targets[1][1]
                        if len(sorted_targets) > 1
                        else None
                    )

                    def z_valid(pos, pt_cfg):
                        return (
                            float(pos[2])
                            <= float(
                                cfg.FUSION_PARAMS[
                                    "max_laser_dist"
                                ]
                            )
                            and (
                                float(pos[2])
                                - float(
                                    pt_cfg[
                                        "pos_global"
                                    ][2]
                                )
                            )
                            > 0.10
                        )

                    # -----------------------------------------
                    # PT1
                    # -----------------------------------------

                    if (
                        t1d
                        and z_valid(
                            t1d["pos"],
                            cfg.PT1_CONFIG,
                        )
                    ):
                        p, t, oor, tilt_dir = get_target_angles(
                            t1d,
                            cfg.PT1_CONFIG,
                            "pt1",
                        )

                        threat = max(
                            0.0,
                            min(
                                float(
                                    t1d.get(
                                        "threat",
                                        0.0,
                                    )
                                ),
                                2.0,
                            ),
                        )

                        dyn_max = (
                            MAX_DEG
                            * (
                                1.0
                                + threat
                                * THREAT_MOTION_BOOST
                            )
                        )

                        alpha_p1 = min(
                            MAX_ALPHA,
                            ANGLE_ALPHA
                            * (
                                1.0
                                + threat
                                * THREAT_MOTION_BOOST
                            ),
                        )

                        new_p = clamp_angle(
                            p,
                            last_target_p1,
                            dyn_max,
                        )

                        new_t = clamp_angle(
                            t,
                            last_target_t1,
                            dyn_max
                            * TILT_MAX_DEG_SCALE,
                        )

                        if (
                            new_p != p
                            or new_t != t
                        ):
                            spike_count += 1

                        last_target_p1 = new_p
                        last_target_t1 = new_t
                        target_tilt_dir_p1 = tilt_dir

                        desired_l1 = (
                            0 if oor else 1
                        )

                        pt1_state = (
                            "oor"
                            if oor
                            else "lock"
                        )

                    else:
                        last_target_p1 = p1h
                        last_target_t1 = t1h
                        desired_l1 = 0
                        target_tilt_dir_p1 = 0

                        pt1_state = (
                            "z_gate"
                            if t1d
                            else "no_target"
                        )

                    # -----------------------------------------
                    # PT2
                    # -----------------------------------------

                    pt2_source = None
                    pt2_same_target = False

                    if (
                        t2d
                        and z_valid(
                            t2d["pos"],
                            cfg.PT2_CONFIG,
                        )
                    ):
                        pt2_source = t2d

                    elif (
                        t1d
                        and z_valid(
                            t1d["pos"],
                            cfg.PT2_CONFIG,
                        )
                    ):
                        # single target일 때 PT1/PT2가 같은 타깃을 조준
                        pt2_source = t1d
                        pt2_same_target = True

                    if pt2_source is not None:
                        p, t, oor, tilt_dir = get_target_angles(
                            pt2_source,
                            cfg.PT2_CONFIG,
                            "pt2",
                        )

                        threat = max(
                            0.0,
                            min(
                                float(
                                    pt2_source.get(
                                        "threat",
                                        0.0,
                                    )
                                ),
                                2.0,
                            ),
                        )

                        dyn_max = (
                            MAX_DEG
                            * (
                                1.0
                                + threat
                                * THREAT_MOTION_BOOST
                            )
                        )

                        alpha_p2 = min(
                            MAX_ALPHA,
                            ANGLE_ALPHA
                            * (
                                1.0
                                + threat
                                * THREAT_MOTION_BOOST
                            ),
                        )

                        new_p = clamp_angle(
                            p,
                            last_target_p2,
                            dyn_max,
                        )

                        new_t = clamp_angle(
                            t,
                            last_target_t2,
                            dyn_max
                            * TILT_MAX_DEG_SCALE,
                        )

                        if (
                            new_p != p
                            or new_t != t
                        ):
                            spike_count += 1

                        last_target_p2 = new_p
                        last_target_t2 = new_t
                        target_tilt_dir_p2 = tilt_dir

                        desired_l2 = (
                            0 if oor else 1
                        )

                        if pt2_same_target:
                            pt2_state = (
                                "same_oor"
                                if oor
                                else "same_lock"
                            )
                        else:
                            pt2_state = (
                                "oor"
                                if oor
                                else "lock"
                            )

                    else:
                        last_target_p2 = p2h
                        last_target_t2 = t2h
                        desired_l2 = 0
                        target_tilt_dir_p2 = 0

                        pt2_state = (
                            "z_gate"
                            if (t2d or t1d)
                            else "no_target"
                        )

                else:
                    tracking_active = False
                    pt1_state = "no_data"
                    pt2_state = "no_data"

                target_alpha_p1 = alpha_p1
                target_alpha_p2 = alpha_p2

            # =================================================
            # 3) Servo control tick
            # =================================================

            if (
                now - last_control_time
                < MIN_SEND
            ):
                continue

            last_control_time = now

            alpha_p1 = target_alpha_p1
            alpha_p2 = target_alpha_p2

            age = (
                now - last_nonempty_time
                if last_nonempty_time > 0
                else 1e9
            )

            # -----------------------------------------
            # Hold / return-home
            # -----------------------------------------

            if age <= HOLD_SEC:
                tgt_p1 = last_target_p1
                tgt_t1 = last_target_t1
                tgt_p2 = last_target_p2
                tgt_t2 = last_target_t2

                if tracking_active:
                    eff_l1 = desired_l1
                    eff_l2 = desired_l2
                else:
                    eff_l1 = 0
                    eff_l2 = 0

            elif age <= HOLD_SEC + RETURN_SEC:
                tracking_active = False

                ratio = min(
                    1.0,
                    (age - HOLD_SEC)
                    / RETURN_SEC,
                )

                tgt_p1 = (
                    last_target_p1
                    + (p1h - last_target_p1)
                    * ratio
                )
                tgt_t1 = (
                    last_target_t1
                    + (t1h - last_target_t1)
                    * ratio
                )

                tgt_p2 = (
                    last_target_p2
                    + (p2h - last_target_p2)
                    * ratio
                )
                tgt_t2 = (
                    last_target_t2
                    + (t2h - last_target_t2)
                    * ratio
                )

                eff_l1 = 0
                eff_l2 = 0

            else:
                tracking_active = False

                tgt_p1, tgt_t1 = p1h, t1h
                tgt_p2, tgt_t2 = p2h, t2h

                eff_l1 = 0
                eff_l2 = 0

                # 완전히 home으로 돌아간 뒤 오래된 backlash 방향 폐기
                reset_tilt_direction_state()
                target_tilt_dir_p1 = 0
                target_tilt_dir_p2 = 0

            # -----------------------------------------
            # Adaptive response
            # -----------------------------------------

            if (
                age <= HOLD_SEC
                and tracking_active
            ):
                alpha_p1 = adaptive_alpha(
                    alpha_p1,
                    tgt_p1 - f_p1,
                    tgt_t1 - f_t1,
                )

                alpha_p2 = adaptive_alpha(
                    alpha_p2,
                    tgt_p2 - f_p2,
                    tgt_t2 - f_t2,
                )

            # -----------------------------------------
            # PAN EMA + deadband
            # -----------------------------------------

            pan_err1 = tgt_p1 - f_p1
            pan_err2 = tgt_p2 - f_p2

            if abs(pan_err1) > PAN_DEADBAND:
                f_p1 += (
                    alpha_p1
                    * pan_err1
                )

            if abs(pan_err2) > PAN_DEADBAND:
                f_p2 += (
                    alpha_p2
                    * pan_err2
                )

            # -----------------------------------------
            # TILT EMA + direction-aware speed
            # -----------------------------------------

            tilt_alpha_p1 = min(
                0.98,
                alpha_p1
                * TILT_ALPHA_SCALE,
            )

            tilt_alpha_p2 = min(
                0.98,
                alpha_p2
                * TILT_ALPHA_SCALE,
            )

            # 위 -> 아래 이동 시 조금 더 빠르게 따라감
            if target_tilt_dir_p1 < 0:
                tilt_alpha_p1 = min(
                    0.98,
                    tilt_alpha_p1
                    * TILT_DOWN_ALPHA_MULT,
                )

            if target_tilt_dir_p2 < 0:
                tilt_alpha_p2 = min(
                    0.98,
                    tilt_alpha_p2
                    * TILT_DOWN_ALPHA_MULT,
                )

            tilt_err1 = tgt_t1 - f_t1
            tilt_err2 = tgt_t2 - f_t2

            if abs(tilt_err1) > TILT_DEADBAND:
                f_t1 += (
                    tilt_alpha_p1
                    * tilt_err1
                )

            if abs(tilt_err2) > TILT_DEADBAND:
                f_t2 += (
                    tilt_alpha_p2
                    * tilt_err2
                )

            # 항상 안전 범위로 최종 clamp
            f_p1, f_t1 = clamp_safe_angles(
                f_p1,
                f_t1,
            )

            f_p2, f_t2 = clamp_safe_angles(
                f_p2,
                f_t2,
            )

            # =================================================
            # 4) Arduino 전송
            # =================================================

            cmd = build_command(
                f_p1,
                f_t1,
                f_p2,
                f_t2,
                eff_l1,
                eff_l2,
            )

            cmd_changed = (
                cmd != last_command
            )

            laser_keepalive_due = (
                bool(eff_l1 or eff_l2)
                and (
                    now - last_send_time
                    >= LASER_KEEPALIVE
                )
            )

            if (
                (
                    cmd_changed
                    and (
                        now - last_send_time
                        >= MIN_SEND
                    )
                )
                or laser_keepalive_due
            ):
                if ser:
                    write_latest_command(
                        ser,
                        cmd,
                        CLEAR_OUTPUT_BEFORE_WRITE,
                    )

                if (
                    laser_keepalive_due
                    and not cmd_changed
                ):
                    keepalive_count += 1

                last_command = cmd
                last_send_time = now
                send_count += 1

            # =================================================
            # 5) Diagnostic log
            # =================================================

            if (
                now - last_log_time
                > 5.0
            ):
                elapsed = max(
                    now - last_log_time,
                    0.01,
                )

                send_hz = (
                    send_count
                    / elapsed
                )

                avg_pkt_ms = (
                    packet_age_sum
                    / packet_age_count
                    * 1000.0
                    if packet_age_count
                    else 0.0
                )

                max_pkt_ms = (
                    packet_age_max
                    * 1000.0
                )

                print(
                    "  [turret] "
                    f"send={send_hz:.0f}Hz "
                    f"age={age:.2f}s "
                    f"active={tracking_active} "
                    f"laser={eff_l1},{eff_l2} "
                    f"pt={pt1_state},{pt2_state} "
                    f"tiltDir="
                    f"{direction_text(target_tilt_dir_p1)}/"
                    f"{direction_text(target_tilt_dir_p2)} "
                    f"pkt={avg_pkt_ms:.0f}/{max_pkt_ms:.0f}ms "
                    f"keepalive={keepalive_count} "
                    f"spikes={spike_count}"
                )

                send_count = 0
                keepalive_count = 0
                spike_count = 0

                packet_age_sum = 0.0
                packet_age_max = 0.0
                packet_age_count = 0

                last_log_time = now

    except KeyboardInterrupt:
        print("\n  Shutting down...")

    except Exception as exc:
        print(
            f"\n  Error: "
            f"{type(exc).__name__}: {exc}"
        )

        import traceback
        traceback.print_exc()

    finally:
        # 종료 시 홈 + 레이저 OFF
        if ser:
            try:
                cmd = build_command(
                    p1h, t1h,
                    p2h, t2h,
                    0, 0,
                )

                write_latest_command(
                    ser,
                    cmd,
                    CLEAR_OUTPUT_BEFORE_WRITE,
                )

                time.sleep(0.5)

            finally:
                ser.close()

        sub.close()
        ctx.destroy()

        print("  Done")
