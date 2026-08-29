#!/usr/bin/env python3

import pickle
import socket
import struct
import subprocess
import time

import cv2

from sender_FIXED_2 import (
    RPiCamStream,
    parse_args,
    validate_args,
)


def connect_tcp(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    s.settimeout(2.0)
    s.connect((host, port))
    print(f">> TCP connected: {host}:{port}", flush=True)
    return s


def main():
    args = parse_args()
    validate_args(args)

    subprocess.run(
        ["pkill", "-9", "rpicam-vid"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)

    cam0 = RPiCamStream(
        0, args.width, args.height,
        args.fps, args.rotation, args.sensor_mode
    )

    # Pi 5 dual IMX219: avoid simultaneous libcamera initialization.
    print(">> Camera 0 started; waiting before Camera 1 init...", flush=True)
    time.sleep(1.5)

    cam1 = RPiCamStream(
        1, args.width, args.height,
        args.fps, args.rotation, args.sensor_mode
    )

    encode_param = [
        int(cv2.IMWRITE_JPEG_QUALITY),
        int(args.jpeg_quality),
    ]

    sock = None
    seq = 0
    last_sent0 = 0
    last_sent1 = 0

    sent_window = 0
    last_stats = time.time()
    reconnects = 0

    print(
        f">> AEGIS RAW-TCP sender: "
        f"{args.width}x{args.height}@{args.fps} "
        f"JPEG={args.jpeg_quality} "
        f"-> {args.laptop_ip}:{args.port}",
        flush=True,
    )

    try:
        while True:

            r0, f0, t0, s0 = cam0.read()
            r1, f1, t1, s1 = cam1.read()

            if not (r0 and r1):
                time.sleep(0.002)
                continue

            if s0 == last_sent0 or s1 == last_sent1:
                time.sleep(0.001)
                continue

            ok0, b0 = cv2.imencode(".jpg", f0, encode_param)
            ok1, b1 = cv2.imencode(".jpg", f1, encode_param)

            if not (ok0 and ok1):
                continue

            packet = {
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
            }

            payload = pickle.dumps(
                packet,
                protocol=pickle.HIGHEST_PROTOCOL
            )

            wire = struct.pack("!I", len(payload)) + payload

            if sock is None:
                try:
                    sock = connect_tcp(
                        args.laptop_ip,
                        args.port
                    )
                except OSError as e:
                    print(
                        f">> TCP waiting: {e}",
                        flush=True
                    )
                    time.sleep(0.5)
                    continue

            try:
                sock.sendall(wire)

            except (OSError, socket.timeout) as e:
                print(
                    f">> TCP reconnect: {e}",
                    flush=True
                )

                try:
                    sock.close()
                except Exception:
                    pass

                sock = None
                reconnects += 1
                continue

            seq += 1
            sent_window += 1
            last_sent0 = s0
            last_sent1 = s1

            now = time.time()

            if now - last_stats >= args.stats_interval:
                dt = max(now - last_stats, 0.001)

                print(
                    f"[TCP] sent={sent_window/dt:.1f}Hz "
                    f"seq={seq} "
                    f"reconnects={reconnects}",
                    flush=True,
                )

                sent_window = 0
                last_stats = now

    except KeyboardInterrupt:
        pass

    finally:
        cam0.release()
        cam1.release()

        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

        print(f"\nDone seq={seq}")


if __name__ == "__main__":
    main()
