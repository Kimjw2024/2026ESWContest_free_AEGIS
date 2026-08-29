#!/usr/bin/env python3
"""Train and evaluate the one-class AEGIS bird detector with Ultralytics YOLO."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Train AEGIS one-class bird detector")
    p.add_argument("--data", required=True, help="Path to bird.yaml")
    p.add_argument("--weights", required=True, help="Pretrained model, e.g. yolov8s.pt")
    p.add_argument("--project", required=True, help="Output project directory")
    p.add_argument("--name", default="yolov8s_bird_baseline_v1")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument(
        "--batch",
        type=float,
        default=-1,
        help="Integer batch, -1 auto ~60%% VRAM, or fraction such as 0.70",
    )
    p.add_argument("--device", default="0")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--patience", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--cache", choices=["false", "ram", "disk"], default="false")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--sanity", action="store_true", help="2-epoch pipeline test before full training")
    return p


def normalize_batch(value: float):
    if value == -1:
        return -1
    if 0.0 < value < 1.0:
        return value
    if value >= 1.0 and float(value).is_integer():
        return int(value)
    raise ValueError("--batch must be -1, a positive integer, or a fraction between 0 and 1")


def main() -> int:
    args = build_parser().parse_args()
    data = Path(args.data).resolve()
    weights = Path(args.weights).resolve()
    project = Path(args.project).resolve()
    project.mkdir(parents=True, exist_ok=True)
    if not data.exists():
        raise FileNotFoundError(data)
    if not weights.exists():
        raise FileNotFoundError(weights)

    cache = False if args.cache == "false" else args.cache
    epochs = 2 if args.sanity else args.epochs
    run_name = f"{args.name}_sanity" if args.sanity else args.name
    batch = normalize_batch(args.batch)

    model = YOLO(str(weights))
    results = model.train(
        data=str(data),
        epochs=epochs,
        imgsz=args.imgsz,
        batch=batch,
        device=args.device,
        workers=args.workers,
        patience=args.patience,
        seed=args.seed,
        deterministic=True,
        cache=cache,
        amp=True,
        project=str(project),
        name=run_name,
        exist_ok=False,
        save=True,
        save_period=10,
        plots=True,
        pretrained=True,
        optimizer="auto",
        close_mosaic=10 if epochs > 10 else 0,
        mosaic=1.0,
        mixup=0.05,
        degrees=5.0,
        translate=0.10,
        scale=0.50,
        shear=2.0,
        perspective=0.0005,
        fliplr=0.5,
        flipud=0.0,
        hsv_h=0.015,
        hsv_s=0.55,
        hsv_v=0.35,
    )

    save_dir = Path(results.save_dir)
    best = save_dir / "weights" / "best.pt"
    if best.exists() and not args.sanity:
        best_model = YOLO(str(best))
        metrics = best_model.val(
            data=str(data),
            split="test",
            imgsz=args.imgsz,
            batch=batch,
            device=args.device,
            workers=args.workers,
            plots=True,
            project=str(project),
            name=f"{run_name}_test",
        )
        summary = {
            "best_weights": str(best),
            "test_save_dir": str(metrics.save_dir),
        }
        (save_dir / "aegis_training_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(f"Training output: {save_dir}")
    if best.exists():
        print(f"Best weights: {best}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
