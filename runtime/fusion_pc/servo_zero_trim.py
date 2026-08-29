# -*- coding: utf-8 -*-
"""
servo_zero_trim.py - manual neutral trim tool for the AEGIS turret.

This tool does not need camera calibration or fusion. It only talks to the
Arduino and lets you align PT1/PT2 neutral positions with the arrow keys.

Keys:
  1 / 2 / a : select PT1, PT2, or both
  arrows    : adjust pan/tilt using the same direction mapping as calibration_turret.py
  4/6/8/5   : fallback adjust keys for terminals that do not pass arrows well
  f         : toggle fine/coarse step (0.25 / 1.0 degree)
  l         : toggle selected laser(s)
  j / k     : force only L1 / only L2 on for wiring diagnostics
  o         : lasers off
  r         : reset selected turret(s) to raw 90/90
  s         : save pan_trim/tilt_trim to turret_calibration_overrides.json
  q / ESC   : quit safely with lasers off
"""
import argparse
import json
import os
import time
import msvcrt

import serial

try:
    import config_turret as cfg
except ImportError:
    print("config_turret.py가 같은 폴더에 필요합니다.")
    raise SystemExit(1)


SERVO_CENTER = float(getattr(cfg, "SERVO_CENTER", 90.0))
SAFE_LIMITS = getattr(cfg, "SAFE_LIMITS", {"pan_min": 20, "pan_max": 160, "tilt_min": 45, "tilt_max": 150})
SERVO_PWM = getattr(cfg, "SERVO_PWM", {"us_min": 544, "us_max": 2400})
ARDUINO_CFG = getattr(cfg, "ARDUINO", {})
SERVO_SMOOTH = getattr(cfg, "SERVO_SMOOTH", {})
LASER_KEEPALIVE_INTERVAL = max(0.05, min(0.25, float(SERVO_SMOOTH.get("laser_keepalive_interval", 0.10))))
MANUAL_FINE_STEP_DEG = 0.25
MANUAL_COARSE_STEP_DEG = 1.0
MANUAL_MOVE_DEBOUNCE_SEC = 0.05
MANUAL_MOVE_SETTLE_SEC = 0.03

US_MIN = int(SERVO_PWM.get("us_min", 544))
US_MAX = int(SERVO_PWM.get("us_max", 2400))
US_RANGE = US_MAX - US_MIN


def deg_to_us(deg):
    us = US_MIN + (float(deg) / 180.0) * US_RANGE
    return max(US_MIN, min(US_MAX, int(round(us))))


def clamp_pan_tilt(pan, tilt):
    pan = max(float(SAFE_LIMITS["pan_min"]), min(float(SAFE_LIMITS["pan_max"]), float(pan)))
    tilt = max(float(SAFE_LIMITS["tilt_min"]), min(float(SAFE_LIMITS["tilt_max"]), float(tilt)))
    return pan, tilt


def build_command(angles, lasers, use_microseconds):
    p1, t1 = clamp_pan_tilt(angles["pt1"]["pan"], angles["pt1"]["tilt"])
    p2, t2 = clamp_pan_tilt(angles["pt2"]["pan"], angles["pt2"]["tilt"])
    l1, l2 = int(bool(lasers["pt1"])), int(bool(lasers["pt2"]))
    if use_microseconds:
        return f"U{deg_to_us(p1)},{deg_to_us(t1)},{deg_to_us(p2)},{deg_to_us(t2)},{l1},{l2}\n"
    return f"P1{int(round(p1))}T1{int(round(t1))}P2{int(round(p2))}T2{int(round(t2))}L1{l1}L2{l2}\n"


def send_command(ser, angles, lasers, use_microseconds):
    cmd = build_command(angles, lasers, use_microseconds)
    try:
        ser.reset_output_buffer()
    except Exception:
        pass
    ser.write(cmd.encode("ascii"))
    ser.flush()
    return cmd.strip()


def get_key():
    if not msvcrt.kbhit():
        return None
    ch = msvcrt.getch()
    if ch in (b"\xe0", b"\x00"):
        ch2 = msvcrt.getch()
        return {b"H": "up", b"P": "down", b"K": "left", b"M": "right"}.get(ch2)
    if ch == b"\x1b":
        return "esc"
    key = ch.decode("utf-8", errors="ignore").lower()
    return {"4": "left", "6": "right", "8": "up", "5": "down"}.get(key, key)


def initial_angles():
    p1 = SERVO_CENTER + float(cfg.PT1_CONFIG.get("pan_trim", 0.0))
    t1 = SERVO_CENTER + float(cfg.PT1_CONFIG.get("tilt_trim", 0.0))
    p2 = SERVO_CENTER + float(cfg.PT2_CONFIG.get("pan_trim", 0.0))
    t2 = SERVO_CENTER + float(cfg.PT2_CONFIG.get("tilt_trim", 0.0))
    p1, t1 = clamp_pan_tilt(p1, t1)
    p2, t2 = clamp_pan_tilt(p2, t2)
    return {
        "pt1": {"pan": p1, "tilt": t1},
        "pt2": {"pan": p2, "tilt": t2},
    }


def selected_ids(selected):
    if selected == "both":
        return ("pt1", "pt2")
    return (selected,)


def adjust(angles, selected, key, step):
    for tid in selected_ids(selected):
        pan = angles[tid]["pan"]
        tilt = angles[tid]["tilt"]
        # Same manual mapping as calibration_turret.py.
        if key == "left":
            pan += step
        elif key == "right":
            pan -= step
        elif key == "up":
            tilt -= step
        elif key == "down":
            tilt += step
        angles[tid]["pan"], angles[tid]["tilt"] = clamp_pan_tilt(pan, tilt)


def reset_selected(angles, selected):
    for tid in selected_ids(selected):
        angles[tid]["pan"], angles[tid]["tilt"] = clamp_pan_tilt(SERVO_CENTER, SERVO_CENTER)


def toggle_selected_lasers(lasers, selected):
    ids = selected_ids(selected)
    new_value = not any(lasers[tid] for tid in ids)
    for tid in ids:
        lasers[tid] = new_value


def status_line(angles, lasers, selected, step, last_cmd):
    return (
        f"sel={selected:<4} step={step:.2f} "
        f"PT1 pan={angles['pt1']['pan']:6.2f} tilt={angles['pt1']['tilt']:6.2f} "
        f"trim=({angles['pt1']['pan']-SERVO_CENTER:+5.2f},{angles['pt1']['tilt']-SERVO_CENTER:+5.2f}) "
        f"L1={int(lasers['pt1'])} | "
        f"PT2 pan={angles['pt2']['pan']:6.2f} tilt={angles['pt2']['tilt']:6.2f} "
        f"trim=({angles['pt2']['pan']-SERVO_CENTER:+5.2f},{angles['pt2']['tilt']-SERVO_CENTER:+5.2f}) "
        f"L2={int(lasers['pt2'])} | {last_cmd}"
    )


def print_status(angles, lasers, selected, step, last_cmd):
    print(status_line(angles, lasers, selected, step, last_cmd), flush=True)


def save_trims(angles, out_path):
    payload = {}
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

    payload.setdefault("schema", "aegis_turret_calibration_overrides_v1")
    payload["neutral_trim_source"] = "servo_zero_trim.py"
    payload["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    for tid in ("pt1", "pt2"):
        values = payload.get(tid)
        if not isinstance(values, dict):
            values = {}
        values["pan_trim"] = round(float(angles[tid]["pan"] - SERVO_CENTER), 2)
        values["tilt_trim"] = round(float(angles[tid]["tilt"] - SERVO_CENTER), 2)
        payload[tid] = values

    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, out_path)


def parse_args():
    parser = argparse.ArgumentParser(description="Keyboard neutral trim tool for PT1/PT2 servos.")
    parser.add_argument("--port", default=str(ARDUINO_CFG.get("port", "COM3")))
    parser.add_argument("--baud", type=int, default=int(ARDUINO_CFG.get("baud", 115200)))
    parser.add_argument("--degree-protocol", action="store_true", help="Use P/T degree protocol instead of U microseconds.")
    return parser.parse_args()


def main():
    args = parse_args()
    use_microseconds = not args.degree_protocol and bool(ARDUINO_CFG.get("use_microseconds", True))
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "turret_calibration_overrides.json")

    print("\n" + "=" * 72)
    print("  Servo Neutral Trim")
    print("=" * 72)
    print("  1/2/a: select PT1/PT2/both | arrows or 4/6/8/5: adjust")
    print("  f: 0.25/0.5 deg")
    print("  l: selected laser toggle | j/k: L1/L2 test | o: lasers off")
    print("  r: reset selected to 90/90")
    print("  s: save trims | q/ESC: quit")
    print("  VS Code에서 안 먹으면 터미널 영역을 한번 클릭한 뒤 숫자키 4/6/8/5를 쓰세요.")
    print("  시작 시 레이저는 꺼져 있습니다. 필요한 순간에만 l로 켜세요.")
    print("=" * 72)

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.1)
        time.sleep(2.0)
    except Exception as exc:
        print(f"Arduino 연결 실패: {type(exc).__name__}: {exc}")
        return 1

    angles = initial_angles()
    lasers = {"pt1": False, "pt2": False}
    selected = "pt1"
    step = MANUAL_COARSE_STEP_DEG
    last_cmd = ""
    last_send_time = 0.0
    last_move_time = 0.0

    try:
        last_cmd = send_command(ser, angles, lasers, use_microseconds)
        last_send_time = time.time()
        print_status(angles, lasers, selected, step, last_cmd)
        while True:
            key = get_key()
            command_changed = False
            display_changed = False
            move_command = False

            if key in ("q", "esc"):
                break
            if key == "1":
                selected = "pt1"
                display_changed = True
            elif key == "2":
                selected = "pt2"
                display_changed = True
            elif key == "a":
                selected = "both"
                display_changed = True
            elif key == "f":
                step = MANUAL_FINE_STEP_DEG if step > MANUAL_FINE_STEP_DEG else MANUAL_COARSE_STEP_DEG
                display_changed = True
            elif key == "l":
                toggle_selected_lasers(lasers, selected)
                command_changed = True
            elif key == "j":
                lasers = {"pt1": True, "pt2": False}
                command_changed = True
            elif key == "k":
                lasers = {"pt1": False, "pt2": True}
                command_changed = True
            elif key == "o":
                lasers = {"pt1": False, "pt2": False}
                command_changed = True
            elif key == "r":
                reset_selected(angles, selected)
                command_changed = True
            elif key in ("left", "right", "up", "down"):
                now = time.time()
                if now - last_move_time >= MANUAL_MOVE_DEBOUNCE_SEC:
                    adjust(angles, selected, key, step)
                    command_changed = True
                    move_command = True
                    last_move_time = now
            elif key == "s":
                save_trims(angles, out_path)
                print(f"\n저장 완료: {out_path}")
                command_changed = True

            if command_changed:
                last_cmd = send_command(ser, angles, lasers, use_microseconds)
                last_send_time = time.time()
                print_status(angles, lasers, selected, step, last_cmd)
                if move_command:
                    time.sleep(MANUAL_MOVE_SETTLE_SEC)
            elif display_changed:
                print_status(angles, lasers, selected, step, last_cmd)
            elif any(lasers.values()) and time.time() - last_send_time >= LASER_KEEPALIVE_INTERVAL:
                last_cmd = send_command(ser, angles, lasers, use_microseconds)
                last_send_time = time.time()
            time.sleep(0.01)
    finally:
        lasers = {"pt1": False, "pt2": False}
        try:
            send_command(ser, angles, lasers, use_microseconds)
        finally:
            ser.close()
        print("\n종료: 레이저 OFF 명령을 보냈습니다.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
