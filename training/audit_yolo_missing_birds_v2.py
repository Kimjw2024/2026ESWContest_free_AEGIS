#!/usr/bin/env python3
"""Memory-safe audit for likely missing bird annotations in a prepared YOLO dataset.

Why this version exists
-----------------------
Do NOT pass all image paths as one Python list to Ultralytics for this task.
With a very large list, recent Ultralytics versions may treat it as an
in-memory image batch and attempt to stack the whole dataset.

This version processes each split DIRECTORY with stream=True, so images are
read incrementally from disk.

It never modifies the dataset.

Outputs
-------
- suspect_missing_labels.csv
- hard_negative_candidates.csv
- audit_summary.json
- suspect_contact_sheet.jpg

Contact sheet:
- existing GT boxes: green
- pretrained COCO bird detections that do not sufficiently overlap GT: red
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw
from ultralytics import YOLO


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def normpath(p: str | Path) -> str:
    return str(Path(p).resolve()).replace("\\", "/").lower()


def read_yolo_boxes(label_path: Path, w: int, h: int):
    boxes = []
    if not label_path.exists():
        return boxes

    for line in label_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            _, xc, yc, bw, bh = map(float, parts[:5])
        except ValueError:
            continue

        x1 = (xc - bw / 2.0) * w
        y1 = (yc - bh / 2.0) * h
        x2 = (xc + bw / 2.0) * w
        y2 = (yc + bh / 2.0) * h
        boxes.append((x1, y1, x2, y2))

    return boxes


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)

    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih

    aa = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    ba = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = aa + ba - inter
    return inter / denom if denom > 0 else 0.0


def load_manifest(path: Path) -> Dict[str, dict]:
    rows = {}
    if not path.exists():
        return rows

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            output_image = row.get("output_image", "")
            if output_image:
                rows[normpath(output_image)] = row

    return rows


def write_csv(path: Path, rows: List[dict], fields: List[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def make_contact_sheet(items, out_path: Path, cols=4, thumb=360, max_items=80):
    items = items[:max_items]
    if not items:
        return

    rows = math.ceil(len(items) / cols)
    caption_h = 58
    sheet = Image.new("RGB", (cols * thumb, rows * (thumb + caption_h)), "white")
    sheet_draw = ImageDraw.Draw(sheet)

    for idx, item in enumerate(items):
        path = Path(item["image"])

        try:
            im = Image.open(path).convert("RGB")
        except Exception:
            continue

        ow, oh = im.size
        scale = min(thumb / max(ow, 1), thumb / max(oh, 1))
        nw = max(1, int(ow * scale))
        nh = max(1, int(oh * scale))

        resized = im.resize((nw, nh), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (thumb, thumb), "white")
        ox = (thumb - nw) // 2
        oy = (thumb - nh) // 2
        canvas.paste(resized, (ox, oy))

        draw = ImageDraw.Draw(canvas)

        def transform(box):
            x1, y1, x2, y2 = box
            return (
                ox + x1 * scale,
                oy + y1 * scale,
                ox + x2 * scale,
                oy + y2 * scale,
            )

        for box in item["gt_boxes"]:
            draw.rectangle(transform(box), outline="green", width=3)

        for box, conf in item["unmatched"]:
            bb = transform(box)
            draw.rectangle(bb, outline="red", width=3)
            draw.text(
                (bb[0] + 2, max(0, bb[1] - 14)),
                f"{conf:.2f}",
                fill="red",
            )

        x = (idx % cols) * thumb
        y = (idx // cols) * (thumb + caption_h)
        sheet.paste(canvas, (x, y))

        title = (
            f"{path.name} | GT:{len(item['gt_boxes'])} "
            f"| unmatched:{len(item['unmatched'])}"
        )
        sheet_draw.text((x + 4, y + thumb + 4), title[:64], fill="black")

        src = item.get("source_image", "")
        if src:
            sheet_draw.text(
                (x + 4, y + thumb + 26),
                Path(src).name[:64],
                fill="black",
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=92)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", required=True, help="prepared_v1 root")
    parser.add_argument("--weights", required=True, help="COCO-pretrained YOLO weights")
    parser.add_argument("--out", required=True)

    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="0")
    parser.add_argument("--conf", type=float, default=0.30)
    parser.add_argument("--match-iou", type=float, default=0.25)
    parser.add_argument("--max-sheet", type=int, default=80)

    args = parser.parse_args()

    prepared = Path(args.prepared).resolve()
    yolo_root = prepared / "yolo_bird_v1"
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    manifest_path = prepared / "manifests" / "yolo_manifest.csv"
    manifest = load_manifest(manifest_path)

    model = YOLO(str(Path(args.weights).resolve()))

    suspects = []
    hard_negatives = []

    total_scanned = 0
    total_positive = 0
    total_negative = 0
    split_scanned = {}

    for split in ("train", "val", "test"):
        img_dir = yolo_root / "images" / split
        label_dir = yolo_root / "labels" / split

        if not img_dir.exists():
            print(f"[WARN] Missing image directory: {img_dir}")
            continue

        expected = sum(
            1 for p in img_dir.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        )

        print(f"\n[{split.upper()}] streaming {expected} images from:")
        print(f"  {img_dir}")

        # IMPORTANT:
        # Use the DIRECTORY as source. Do not pass a 13k-element Python list.
        results = model.predict(
            source=str(img_dir),
            stream=True,
            imgsz=args.imgsz,
            conf=args.conf,
            classes=[14],      # COCO bird class
            device=args.device,
            batch=args.batch,
            verbose=False,
        )

        split_count = 0

        for result in results:
            image_path = Path(result.path).resolve()
            split_count += 1
            total_scanned += 1

            row = manifest.get(normpath(image_path), {})

            # Fall back to filename matching only if absolute-path lookup failed.
            if not row:
                same_name = [
                    r for k, r in manifest.items()
                    if Path(k).name.lower() == image_path.name.lower()
                ]
                if len(same_name) == 1:
                    row = same_name[0]

            with Image.open(image_path) as im:
                w, h = im.size

            label_path = label_dir / f"{image_path.stem}.txt"
            gt_boxes = read_yolo_boxes(label_path, w, h)

            pred_boxes: List[Tuple[Tuple[float, float, float, float], float]] = []
            if result.boxes is not None and len(result.boxes) > 0:
                xyxy = result.boxes.xyxy.detach().cpu().tolist()
                confs = result.boxes.conf.detach().cpu().tolist()
                pred_boxes = [
                    (tuple(map(float, box)), float(conf))
                    for box, conf in zip(xyxy, confs)
                ]

            is_negative = str(row.get("is_negative", "0")).strip() == "1"

            if is_negative:
                total_negative += 1

                if pred_boxes:
                    hard_negatives.append(
                        {
                            "split": split,
                            "image": str(image_path),
                            "source_image": row.get("source_image", ""),
                            "pretrained_bird_detections": len(pred_boxes),
                            "max_conf": max(conf for _, conf in pred_boxes),
                        }
                    )
                continue

            total_positive += 1

            unmatched = []
            for pred_box, pred_conf in pred_boxes:
                best_iou = max(
                    (iou(pred_box, gt_box) for gt_box in gt_boxes),
                    default=0.0,
                )
                if best_iou < args.match_iou:
                    unmatched.append((pred_box, pred_conf))

            if unmatched:
                suspects.append(
                    {
                        "split": split,
                        "image": str(image_path),
                        "source_image": row.get("source_image", ""),
                        "source_class": row.get("source_class", ""),
                        "source_number": row.get("source_number", ""),
                        "gt_count": len(gt_boxes),
                        "pretrained_bird_detections": len(pred_boxes),
                        "unmatched_count": len(unmatched),
                        "max_unmatched_conf": max(conf for _, conf in unmatched),
                        "gt_boxes": gt_boxes,
                        "unmatched": unmatched,
                    }
                )

            if split_count % 500 == 0:
                print(
                    f"  processed {split_count}/{expected} | "
                    f"suspects={len(suspects)} | "
                    f"hard-neg={len(hard_negatives)}"
                )

        split_scanned[split] = split_count
        print(f"[{split.upper()}] done: {split_count} images")

    suspects.sort(
        key=lambda x: (x["max_unmatched_conf"], x["unmatched_count"]),
        reverse=True,
    )
    hard_negatives.sort(key=lambda x: x["max_conf"], reverse=True)

    write_csv(
        out / "suspect_missing_labels.csv",
        suspects,
        [
            "split",
            "image",
            "source_image",
            "source_class",
            "source_number",
            "gt_count",
            "pretrained_bird_detections",
            "unmatched_count",
            "max_unmatched_conf",
        ],
    )

    write_csv(
        out / "hard_negative_candidates.csv",
        hard_negatives,
        [
            "split",
            "image",
            "source_image",
            "pretrained_bird_detections",
            "max_conf",
        ],
    )

    make_contact_sheet(
        suspects,
        out / "suspect_contact_sheet.jpg",
        max_items=args.max_sheet,
    )

    summary = {
        "images_scanned": total_scanned,
        "positive_images_scanned": total_positive,
        "negative_images_scanned": total_negative,
        "split_scanned": split_scanned,
        "positive_suspects": len(suspects),
        "hard_negative_candidates": len(hard_negatives),
        "settings": {
            "conf": args.conf,
            "match_iou": args.match_iou,
            "imgsz": args.imgsz,
            "batch": args.batch,
            "device": args.device,
        },
        "note": (
            "Screening only. A COCO-pretrained bird detector can produce false positives "
            "and false negatives. Review the contact sheet/CSV before changing labels."
        ),
    }

    (out / "audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n=== AUDIT COMPLETE ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nOutputs: {out}")


if __name__ == "__main__":
    main()
