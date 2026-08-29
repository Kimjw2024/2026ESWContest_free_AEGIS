# -*- coding: utf-8 -*-
import argparse
import os
import sys
import time

import cv2
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import config_turret as cfg
except ImportError:
    cfg = None


DETECTION_CFG = getattr(cfg, "DETECTION", {}) if cfg is not None else {}
CAMERA_STREAM = getattr(cfg, "CAMERA_STREAM", {}) if cfg is not None else {}

def resolve_project_path(path):
    if not path:
        return path
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)

MODEL_EXTS = (".pt", ".engine", ".onnx", ".torchscript", ".xml")

def model_candidates_from_dir(model_dir):
    model_dir = resolve_project_path(model_dir)
    if not model_dir or not os.path.isdir(model_dir):
        return []
    priority = (
        "best.engine", "best.pt", "custom.engine", "custom.pt",
        "model.engine", "model.pt", "yolo_custom.engine", "yolo_custom.pt",
    )
    candidates = []
    for name in priority:
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
        if os.path.isfile(path) and name.lower().endswith(MODEL_EXTS):
            discovered.append(path)
    discovered.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for path in discovered:
        if path not in candidates:
            candidates.append(path)
    return candidates

def select_model_path(model_arg, model_dir, fallback_arg):
    candidates = []
    if model_arg:
        candidates.append(resolve_project_path(model_arg))
    candidates.extend(model_candidates_from_dir(model_dir))
    if fallback_arg:
        candidates.append(resolve_project_path(fallback_arg))
    candidates.append(resolve_project_path("models/yolo26n.engine"))
    seen = set()
    for path in candidates:
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.exists(path):
            return path
    return resolve_project_path(model_arg or fallback_arg or "models/yolo26n.engine")

def is_custom_model(path, model_dir):
    basename = os.path.basename(str(path)).lower()
    standard_names = {
        os.path.basename(str(name)).lower()
        for name in DETECTION_CFG.get("yolo_pretrained_candidates", ())
    }
    if basename in standard_names:
        return False
    try:
        model_dir = os.path.normcase(os.path.abspath(resolve_project_path(model_dir)))
        model_path = os.path.normcase(os.path.abspath(path))
        return os.path.commonpath([model_dir, model_path]) == model_dir
    except Exception:
        return False

def parse_class_config(value, is_custom):
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("", "none", "all"):
            return None
        if text == "auto":
            return None if is_custom else DETECTION_CFG.get("yolo_fallback_classes", [14])
        try:
            return [int(x.strip()) for x in text.split(",") if x.strip()]
        except ValueError:
            return None
    try:
        return [int(x) for x in value]
    except TypeError:
        return None

def resolve_model_task(path, is_custom, task_cfg):
    text = str(task_cfg or "auto").strip().lower()
    if text in ("detect", "segment", "pose", "obb"):
        return text
    basename = os.path.basename(str(path)).lower()
    if any(token in basename for token in ("-seg", "_seg", "seg.")):
        return "segment"
    if any(token in basename for token in ("-pose", "_pose", "pose.")):
        return "pose"
    if is_custom:
        return None
    return "detect"

def load_yolo_model(cls, model_path, task):
    return cls(model_path) if task is None else cls(model_path, task=task)

def make_synthetic_frame(width, height, seed):
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 255, width, dtype=np.uint8)
    y = np.linspace(0, 180, height, dtype=np.uint8)[:, None]
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = x
    frame[:, :, 1] = y
    frame[:, :, 2] = 120
    for _ in range(8):
        cx = int(rng.integers(80, max(81, width - 80)))
        cy = int(rng.integers(60, max(61, height - 60)))
        radius = int(rng.integers(12, 45))
        color = tuple(int(v) for v in rng.integers(40, 230, size=3))
        cv2.circle(frame, (cx, cy), radius, color, -1)
    return frame


def parse_args():
    parser = argparse.ArgumentParser(description="Benchmark YOLO inference for the 4-camera fusion loop.")
    parser.add_argument("--model", default=None, help="Model path. Defaults to models/best.* when present, then models/yolo26n.engine.")
    parser.add_argument("--model-dir", default=DETECTION_CFG.get("yolo_model_dir", "models"))
    parser.add_argument("--fallback-model", default=DETECTION_CFG.get("yolo_fallback_model_path", DETECTION_CFG.get("yolo_model_path", "models/yolo26n.engine")))
    parser.add_argument("--width", type=int, default=int(CAMERA_STREAM.get("width", 1280)))
    parser.add_argument("--height", type=int, default=int(CAMERA_STREAM.get("height", 720)))
    parser.add_argument("--imgsz", type=int, default=int(DETECTION_CFG.get("yolo_imgsz_gpu", 1280)))
    parser.add_argument("--conf", type=float, default=float(DETECTION_CFG.get("yolo_conf", 0.16)))
    parser.add_argument("--classes", nargs="*", type=int, default=None, help="Override class filter. Omit for config/auto; pass no values for all classes.")
    parser.add_argument("--task", default=DETECTION_CFG.get("yolo_task", "auto"),
                        help="YOLO task: auto, detect, segment, pose, or obb.")
    parser.add_argument("--max-det", type=int, default=int(DETECTION_CFG.get("yolo_max_det", 1)))
    parser.add_argument("--loops", type=int, default=30)
    parser.add_argument("--cameras", type=int, default=4)
    parser.add_argument("--target-hz", type=float, default=15.0)
    parser.add_argument("--include-jpeg-decode", action="store_true")
    parser.add_argument("--jpeg-quality", type=int, default=int(CAMERA_STREAM.get("jpeg_quality", 88)))
    parser.add_argument("--random-noise", action="store_true", help="Use high-entropy frames as a JPEG/decode stress test.")
    parser.add_argument("--batch", action="store_true", help="Run all camera frames in one YOLO call.")
    parser.add_argument("--rect", dest="rect", action="store_true", default=bool(DETECTION_CFG.get("yolo_rect", True)))
    parser.add_argument("--no-rect", dest="rect", action="store_false")
    return parser.parse_args()


def main():
    args = parse_args()

    import torch
    from ultralytics import YOLO

    cuda_ok = torch.cuda.is_available()
    device = "0" if cuda_ok else "cpu"
    half = bool(cuda_ok)
    model_path = select_model_path(args.model, args.model_dir, args.fallback_model)
    custom_model = is_custom_model(model_path, args.model_dir)
    if args.classes is not None:
        classes = args.classes if len(args.classes) > 0 else None
    else:
        class_cfg = DETECTION_CFG.get("yolo_custom_classes", "auto") if custom_model else DETECTION_CFG.get("yolo_classes", [14])
        classes = parse_class_config(class_cfg, custom_model)
    task = resolve_model_task(model_path, custom_model, args.task)
    model = load_yolo_model(YOLO, model_path, task)

    if args.random_noise:
        frames = [
            np.random.randint(0, 256, (args.height, args.width, 3), dtype=np.uint8)
            for _ in range(args.cameras)
        ]
    else:
        frames = [make_synthetic_frame(args.width, args.height, i) for i in range(args.cameras)]
    encoded_frames = None
    if args.include_jpeg_decode:
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), int(args.jpeg_quality)]
        encoded_frames = []
        for frame in frames:
            ok, encoded = cv2.imencode(".jpg", frame, encode_param)
            if not ok:
                raise SystemExit("JPEG encode failed during benchmark setup")
            encoded_frames.append(encoded)

    # Warm-up.
    infer_kwargs = {
        "conf": args.conf,
        "imgsz": args.imgsz,
        "max_det": args.max_det,
        "device": device,
        "half": half,
        "rect": args.rect,
        "verbose": False,
    }
    if classes is not None:
        infer_kwargs["classes"] = classes
    if args.batch:
        model(frames, **infer_kwargs)
    else:
        for frame in frames:
            model(frame, **infer_kwargs)
    if cuda_ok:
        torch.cuda.synchronize()

    samples = []
    for _ in range(args.loops):
        t0 = time.perf_counter()
        if encoded_frames is not None:
            loop_frames = [cv2.imdecode(buf, cv2.IMREAD_COLOR) for buf in encoded_frames]
        else:
            loop_frames = frames
        if args.batch:
            model(loop_frames, **infer_kwargs)
        else:
            for frame in loop_frames:
                model(frame, **infer_kwargs)
        if cuda_ok:
            torch.cuda.synchronize()
        samples.append(time.perf_counter() - t0)

    arr = np.asarray(samples, dtype=np.float64)
    mean_ms = float(arr.mean() * 1000.0)
    p95_ms = float(np.percentile(arr, 95) * 1000.0)
    fps_4cam = 1000.0 / mean_ms if mean_ms > 0 else 0.0
    per_cam_fps = fps_4cam * args.cameras
    target_budget_ms = 1000.0 / args.target_hz if args.target_hz > 0 else 0.0
    status = "OK" if target_budget_ms > 0 and p95_ms <= target_budget_ms else "LIMITED"

    print(f">> device={device} cuda={cuda_ok} gpu={torch.cuda.get_device_name(0) if cuda_ok else 'CPU'}")
    class_text = "all/custom" if classes is None else ",".join(str(x) for x in classes)
    task_text = "auto" if task is None else task
    print(f">> model={model_path} task={task_text} classes={class_text} custom={custom_model}")
    print(f">> size={args.width}x{args.height} imgsz={args.imgsz} rect={args.rect} cameras={args.cameras}")
    frame_kind = "random_noise" if args.random_noise else "synthetic_scene"
    print(f">> jpeg_decode={'on' if args.include_jpeg_decode else 'off'} quality={args.jpeg_quality} frame={frame_kind} batch={args.batch}")
    print(f">> 4-camera loop: mean={mean_ms:.1f}ms p95={p95_ms:.1f}ms effective={fps_4cam:.1f}Hz")
    print(f">> per-camera inference throughput: {per_cam_fps:.1f} FPS")
    if target_budget_ms > 0:
        print(f">> target={args.target_hz:.1f}Hz budget={target_budget_ms:.1f}ms status={status}")


if __name__ == "__main__":
    main()
