#!/usr/bin/env python3
"""Create contact sheets for quick visual QA of prepared YOLO labels and ResNet crops."""
from __future__ import annotations

import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def load_font(size=18):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def yolo_sheet(root: Path, split: str, out: Path, count: int, seed: int):
    images_dir = root / "images" / split
    labels_dir = root / "labels" / split
    paths = [p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS]
    random.Random(seed).shuffle(paths)
    paths = paths[: min(count, len(paths))]
    thumb_w, thumb_h = 320, 220
    cols = 4
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), "white")
    font = load_font(16)
    for i, path in enumerate(paths):
        with Image.open(path) as im:
            im = im.convert("RGB")
            draw = ImageDraw.Draw(im)
            label_path = labels_dir / f"{path.stem}.txt"
            if label_path.exists():
                for line in label_path.read_text(encoding="utf-8").splitlines():
                    parts = line.split()
                    if len(parts) != 5:
                        continue
                    _, x, y, w, h = map(float, parts)
                    x1 = int((x - w / 2) * im.width)
                    y1 = int((y - h / 2) * im.height)
                    x2 = int((x + w / 2) * im.width)
                    y2 = int((y + h / 2) * im.height)
                    draw.rectangle((x1, y1, x2, y2), outline="red", width=max(2, im.width // 250))
            im.thumbnail((thumb_w - 10, thumb_h - 28))
            tile = Image.new("RGB", (thumb_w, thumb_h), "white")
            tile.paste(im, ((thumb_w - im.width) // 2, 5))
            ImageDraw.Draw(tile).text((5, thumb_h - 22), path.name, fill="black", font=font)
            sheet.paste(tile, ((i % cols) * thumb_w, (i // cols) * thumb_h))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=92)


def resnet_sheet(root: Path, split: str, out: Path, per_class: int, seed: int):
    class_dirs = sorted([p for p in (root / split).iterdir() if p.is_dir()])
    thumb = 180
    cols = per_class
    rows = len(class_dirs)
    sheet = Image.new("RGB", (cols * thumb, rows * (thumb + 30)), "white")
    font = load_font(16)
    rng = random.Random(seed)
    for row, class_dir in enumerate(class_dirs):
        paths = [p for p in class_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS]
        rng.shuffle(paths)
        for col, path in enumerate(paths[:per_class]):
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((thumb - 8, thumb - 8))
                tile = Image.new("RGB", (thumb, thumb + 30), "white")
                tile.paste(im, ((thumb - im.width) // 2, 4))
                ImageDraw.Draw(tile).text((4, thumb + 4), class_dir.name, fill="black", font=font)
                sheet.paste(tile, (col * thumb, row * (thumb + 30)))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=92)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prepared", required=True, help="prepared_v1 root")
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    root = Path(args.prepared)
    out = Path(args.out)
    yolo_sheet(root / "yolo_bird_v1", "train", out / "yolo_train_samples.jpg", 32, args.seed)
    yolo_sheet(root / "yolo_bird_v1", "val", out / "yolo_val_samples.jpg", 24, args.seed + 1)
    resnet_sheet(root / "resnet_birds_v1", "train", out / "resnet_train_samples.jpg", 8, args.seed)
    resnet_sheet(root / "resnet_birds_v1", "val", out / "resnet_val_samples.jpg", 8, args.seed + 1)
    print(out)


if __name__ == "__main__":
    main()
