# sender_rpi2_wired_hd.py
import argparse
import os
import pickle
import subprocess
import sys
import threading
import time

import cv2
import numpy as np
import zmq


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
try:
    import config_turret as cfg
except ImportError:
    cfg = None


DEFAULT_CAMERA_STREAM = {
    "width": 1280,
    "height": 720,
    "fps": 20,
    "jpeg_quality": 76,
    "sensor_mode": "2304:1296",
    "rotation": 180,
}
DEFAULT_RUNTIME_STREAM = {
    "width": 640,
    "height": 360,
    "fps": 30,
    "jpeg_quality": 70,
    "sensor_mode": "2304:1296",
    "rotation": 180,
}
DEFAULT_NETWORK_CFG = {
    "laptop_ip": "192.0.2.10",
    "video_port": 5555,
    "sender_sndhwm": 1,
}

CAMERA_STREAM = getattr(cfg, "CAMERA_STREAM", DEFAULT_CAMERA_STREAM) if cfg is not None else DEFAULT_CAMERA_STREAM
RUNTIME_STREAM = getattr(cfg, "RUNTIME_STREAM", DEFAULT_RUNTIME_STREAM) if cfg is not None else DEFAULT_RUNTIME_STREAM
NETWORK_CFG = getattr(cfg, "NETWORK", DEFAULT_NETWORK_CFG) if cfg is not None else DEFAULT_NETWORK_CFG
CALIB_RESOLUTION = tuple(getattr(cfg, "CALIB_RESOLUTION", (1280, 720))) if cfg is not None else (1280, 720)

DEFAULT_PORT = int(NETWORK_CFG.get("video_port", 5555))
# Switch-hub topology: laptop, rpi1, and rpi2 share the 192.168.137.x subnet.
# Keep rpi2 pointed at the laptop built-in Ethernet address by default.
# Use --laptop-ip only when intentionally reverting to a different wiring layout.
DEFAULT_LAPTOP_IP = "192.0.2.10"
DEFAULT_PROFILE = os.environ.get("SENDER_PROFILE", "calibration").strip().lower()
DEFAULT_SNDHWM = int(os.environ.get("SENDER_SNDHWM", NETWORK_CFG.get("sender_sndhwm", "1")))
DEFAULT_SENDER_ID = "rpi2"
# Change only this value when this sender is used for a different stereo pair.
# Examples: "01", "02", "03", "12", "13", "23".
DEFAULT_LOGICAL_PAIR = os.environ.get("SENDER_LOGICAL_PAIR", "23").strip()


def _parse_default_logical_pair(pair_text):
    text = str(pair_text).replace("cam", "").replace("-", "").replace("_", "")
    if len(text) != 2 or not text.isdigit():
        raise SystemExit('DEFAULT_LOGICAL_PAIR must look like "01", "02", "12", or "23"')
    left_id = int(text[0])
    right_id = int(text[1])
    if left_id not in (0, 1, 2, 3) or right_id not in (0, 1, 2, 3) or left_id == right_id:
        raise SystemExit("DEFAULT_LOGICAL_PAIR must use two different camera ids from 0..3")
    return left_id, right_id


DEFAULT_LEFT_LOGICAL_ID, DEFAULT_RIGHT_LOGICAL_ID = _parse_default_logical_pair(DEFAULT_LOGICAL_PAIR)


class RPiCamStream:
    def __init__(self, camera_index, width, height, fps, rotation, sensor_mode):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self.rotation = rotation
        self.sensor_mode = sensor_mode
        self.frame_size = int(width * height * 1.5)
        self.process = None
        self.running = True
        self.lock = threading.Lock()
        self.latest_frame = None
        self.latest_ts = 0.0
        self.latest_seq = 0
        self._start()
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    def _start(self):
        cmd = [
            "rpicam-vid",
            "--camera", str(self.camera_index),
            "--mode", self.sensor_mode,
            "--width", str(self.width),
            "--height", str(self.height),
            "--codec", "yuv420",
            "-t", "0",
            "--nopreview",
            "-o", "-",
            "--framerate", str(self.fps),
            "--rotation", str(self.rotation),
        ]
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    def read_exact(self, size):
        buf = bytearray()
        while self.running and len(buf) < size:
            chunk = self.process.stdout.read(size - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf) if len(buf) == size else None

    def _reader_loop(self):
        while self.running:
            raw = self.read_exact(self.frame_size)
            if raw is None:
                if not self.running:
                    break
                print(f"\n! cam{self.camera_index} died, restarting...", flush=True)
                self._restart_process()
                continue

            ts = time.time()
            try:
                yuv = np.frombuffer(raw, dtype=np.uint8).reshape((int(self.height * 1.5), self.width))
                bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)
            except Exception as exc:
                print(f"\n! cam{self.camera_index} decode error: {exc}", flush=True)
                continue

            with self.lock:
                self.latest_frame = bgr
                self.latest_ts = ts
                self.latest_seq += 1

    def _restart_process(self):
        self._stop_process()
        time.sleep(0.5)
        if self.running:
            self._start()

    def read(self):
        with self.lock:
            if self.latest_frame is None:
                return False, None, 0.0, 0
            return True, self.latest_frame, self.latest_ts, self.latest_seq

    def _stop_process(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def release(self):
        self.running = False
        self._stop_process()
        thread = getattr(self, "thread", None)
        if thread and thread.is_alive():
            thread.join(timeout=1.0)


def _stream_value(stream, key, fallback):
    return stream.get(key, fallback) if isinstance(stream, dict) else fallback


def _normalize_profile(profile):
    profile = str(profile or "calibration").strip().lower()
    return profile if profile in ("calibration", "runtime") else "calibration"


def _stream_for_profile(profile):
    return RUNTIME_STREAM if _normalize_profile(profile) == "runtime" else CAMERA_STREAM


def _profile_default(args, env_name, key, fallback, cast):
    value = os.environ.get(env_name)
    if value is None:
        value = getattr(args, key, None)
    if value is None:
        value = _stream_value(_stream_for_profile(args.profile), key, fallback)
    return cast(value)


def apply_profile_defaults(args):
    args.profile = _normalize_profile(args.profile)
    args.width = _profile_default(args, "CAM_WIDTH", "width", int(CALIB_RESOLUTION[0]), int)
    args.height = _profile_default(args, "CAM_HEIGHT", "height", int(CALIB_RESOLUTION[1]), int)
    args.fps = _profile_default(args, "CAM_FPS", "fps", 20, int)
    args.jpeg_quality = _profile_default(args, "JPEG_QUALITY", "jpeg_quality", 76, int)
    args.sensor_mode = _profile_default(args, "SENSOR_MODE", "sensor_mode", "2304:1296", str)
    args.rotation = _profile_default(args, "CAM_ROTATION", "rotation", 180, int)
    return args


def parse_args():
    parser = argparse.ArgumentParser(description=f"{DEFAULT_SENDER_ID} stereo sender for wired ZMQ/JPEG streaming.")
    parser.add_argument("--profile", choices=("calibration", "runtime"),
                        default=_normalize_profile(DEFAULT_PROFILE),
                        help="calibration=1280x720 capture profile, runtime=low-latency RUNTIME_STREAM profile")
    parser.add_argument("--laptop-ip", default=DEFAULT_LAPTOP_IP, help="Laptop wired Ethernet IP.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--width", type=int, default=None, help="Override selected profile width.")
    parser.add_argument("--height", type=int, default=None, help="Override selected profile height.")
    parser.add_argument("--fps", type=int, default=None, help="Override selected profile FPS.")
    parser.add_argument("--jpeg-quality", type=int, default=None, help="Override selected profile JPEG quality.")
    parser.add_argument("--sensor-mode", default=None, help="Override selected profile rpicam sensor mode.")
    parser.add_argument("--rotation", type=int, default=None, help="Override selected profile rotation.")
    parser.add_argument("--sender-id", default=DEFAULT_SENDER_ID, choices=(DEFAULT_SENDER_ID,),
                        help="Fixed logical sender id for this Raspberry Pi.")
    parser.add_argument("--left-logical-id", type=int, default=DEFAULT_LEFT_LOGICAL_ID,
                        help="Logical camera id for physical CSI camera 0 in the outgoing payload.")
    parser.add_argument("--right-logical-id", type=int, default=DEFAULT_RIGHT_LOGICAL_ID,
                        help="Logical camera id for physical CSI camera 1 in the outgoing payload.")
    parser.add_argument("--verbose-dots", action="store_true", help="Print one character for each sent/dropped packet.")
    parser.add_argument("--stats-interval", type=float, default=5.0, help="Seconds between sender status logs.")
    parser.add_argument("--allow-resolution-mismatch", action="store_true",
                        help="Diagnostic only. Fusion accepts CALIB_RESOLUTION and config_turret.RUNTIME_STREAM sizes.")
    args = parser.parse_args()
    return apply_profile_defaults(args)


def validate_args(args):
    if args.left_logical_id not in (0, 1, 2, 3) or args.right_logical_id not in (0, 1, 2, 3):
        raise SystemExit("logical camera ids must be in 0..3")
    if args.left_logical_id == args.right_logical_id:
        raise SystemExit("left/right logical camera ids must be different")
    if args.width <= 0 or args.height <= 0:
        raise SystemExit("width/height must be positive")
    if args.width % 2 or args.height % 2:
        raise SystemExit("width/height must be even for yuv420")
    if not 1 <= args.jpeg_quality <= 100:
        raise SystemExit("jpeg-quality must be between 1 and 100")
    calib_size = (int(CALIB_RESOLUTION[0]), int(CALIB_RESOLUTION[1]))
    runtime_size = (
        int(_stream_value(RUNTIME_STREAM, "width", calib_size[0])),
        int(_stream_value(RUNTIME_STREAM, "height", calib_size[1])),
    )
    stream_size = (int(args.width), int(args.height))
    same_aspect = stream_size[0] * calib_size[1] == stream_size[1] * calib_size[0]
    supported_sizes = {calib_size, runtime_size}
    if args.profile == "calibration" and stream_size != calib_size and not args.allow_resolution_mismatch:
        raise SystemExit(
            f"calibration profile must stream {calib_size[0]}x{calib_size[1]} for calibration capture, "
            f"got {stream_size[0]}x{stream_size[1]}. Use --profile runtime for low-latency tracking."
        )
    if (stream_size not in supported_sizes or not same_aspect) and not args.allow_resolution_mismatch:
        supported = ", ".join(f"{w}x{h}" for w, h in sorted(supported_sizes))
        raise SystemExit(
            f"stream resolution {stream_size[0]}x{stream_size[1]} is not supported. "
            f"Supported sizes: {supported}. Keep the same 16:9 FOV as CALIB_RESOLUTION."
        )


def main():
    args = parse_args()
    validate_args(args)

    context = zmq.Context()
    socket = context.socket(zmq.PUB)

    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.SNDHWM, max(1, int(DEFAULT_SNDHWM)))
    socket.setsockopt(zmq.CONFLATE, 1)
    try:
        socket.setsockopt(zmq.IMMEDIATE, 1)
    except (AttributeError, zmq.ZMQError):
        pass
    try:
        socket.setsockopt(zmq.SNDBUF, 1024 * 1024)
    except zmq.ZMQError:
        pass
    socket.connect(f"tcp://{args.laptop_ip}:{args.port}")

    subprocess.run(
        ["pkill", "-9", "rpicam-vid"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)

    cam0 = RPiCamStream(0, args.width, args.height, args.fps, args.rotation, args.sensor_mode)
    cam1 = RPiCamStream(1, args.width, args.height, args.fps, args.rotation, args.sensor_mode)

    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), int(args.jpeg_quality)]
    seq = 0
    drop_count = 0
    error_count = 0
    sent_count_window = 0
    last_stats_time = time.time()
    last_sent0 = 0
    last_sent1 = 0

    print(
        f">> {args.sender_id} sender[{args.profile}]: {args.width}x{args.height}@{args.fps} "
        f"JPEG={args.jpeg_quality} physical CSI0/1 -> logical cam{args.left_logical_id}/cam{args.right_logical_id} "
        f"latest-frame -> tcp://{args.laptop_ip}:{args.port}",
        flush=True,
    )

    try:
        while True:
            r0, f0, t0, s0 = cam0.read()
            r1, f1, t1, s1 = cam1.read()

            if r0 and r1:
                if s0 == last_sent0 or s1 == last_sent1:
                    time.sleep(0.001)
                    continue
                ok0, b0 = cv2.imencode(".jpg", f0, encode_param)
                ok1, b1 = cv2.imencode(".jpg", f1, encode_param)
                if not (ok0 and ok1):
                    error_count += 1
                    if args.verbose_dots:
                        print("E", end="", flush=True)
                    continue

                try:
                    socket.send(
                        pickle.dumps({
                            "id": "stereo",
                            "sender_id": args.sender_id,
                            "ts": time.time(),
                            "seq": seq,
                            "profile": args.profile,
                            "width": args.width,
                            "height": args.height,
                            "encoding": "jpg",
                            "jpeg_quality": args.jpeg_quality,
                            f"img{args.left_logical_id}": b0,
                            f"img{args.right_logical_id}": b1,
                            f"img{args.left_logical_id}_ts": t0,
                            f"img{args.right_logical_id}_ts": t1,
                            "pair_dt": abs(t1 - t0),
                            "pair_dt_s": abs(t1 - t0),
                        }),
                        zmq.NOBLOCK,
                    )
                    seq += 1
                    sent_count_window += 1
                    last_sent0 = s0
                    last_sent1 = s1
                    if args.verbose_dots:
                        print("2", end="", flush=True)
                except zmq.Again:
                    drop_count += 1
                    if args.verbose_dots and drop_count % 100 == 1:
                        print(f"D({drop_count})", end="", flush=True)
            else:
                error_count += 1
                if args.verbose_dots:
                    print("X", end="", flush=True)

            now = time.time()
            if args.stats_interval > 0 and now - last_stats_time >= args.stats_interval:
                elapsed = max(now - last_stats_time, 1e-3)
                print(
                    f"[{args.sender_id}] sent={sent_count_window / elapsed:.1f}Hz "
                    f"seq={seq} drops={drop_count} errors={error_count}",
                    flush=True,
                )
                sent_count_window = 0
                error_count = 0
                last_stats_time = now

    except KeyboardInterrupt:
        pass
    finally:
        cam0.release()
        cam1.release()
        socket.close()
        context.destroy()
        print(f"\nDone (seq={seq}, drops={drop_count})")


if __name__ == "__main__":
    main()
