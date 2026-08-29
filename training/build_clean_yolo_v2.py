#!/usr/bin/env python3
"""Build a cleaner YOLO bird dataset from prepared_v1 without modifying prepared_v1.

Default conservative auto-exclusion rule:
    pretrained_bird_detections > gt_count
    AND max_unmatched_conf >= 0.50

Rationale:
- If the COCO bird detector sees *more* birds than the existing GT count,
  the image is a strong candidate for incomplete annotation.
- Requiring confidence >= 0.50 avoids excluding many low-confidence audit hits.
- Ambiguous audit hits are NOT deleted; they are written to
  review_remaining_suspects.csv for optional later review.

The script preserves the existing train/val/test split and all RPi negatives.
It uses NTFS hardlinks when possible (same drive), falling back to copy2.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def normpath(p: str | Path) -> str:
    return str(Path(p).resolve()).replace("\\", "/").lower()


def link_or_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
        return "hardlink"
    except Exception:
        shutil.copy2(src, dst)
        return "copy"


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prepared", required=True, help="prepared_v1 root")
    p.add_argument("--audit-csv", required=True, help="suspect_missing_labels.csv")
    p.add_argument("--out", required=True, help="new prepared_v2 root")
    p.add_argument("--min-conf", type=float, default=0.50)
    p.add_argument(
        "--exclude-all-suspects",
        action="store_true",
        help="Exclude all rows in audit CSV instead of the conservative default rule.",
    )
    p.add_argument(
        "--copy",
        action="store_true",
        help="Always copy files instead of trying NTFS hardlinks first.",
    )
    args = p.parse_args()

    prepared = Path(args.prepared).resolve()
    old_root = prepared / "yolo_bird_v1"
    audit_csv = Path(args.audit_csv).resolve()

    out_prepared = Path(args.out).resolve()
    new_root = out_prepared / "yolo_bird_v2"

    if not old_root.exists():
        raise FileNotFoundError(f"Missing source dataset: {old_root}")
    if new_root.exists() and any(new_root.iterdir()):
        raise RuntimeError(
            f"Output already exists and is not empty: {new_root}\n"
            "Use a new output directory or remove the previous failed build manually."
        )

    rows = read_csv(audit_csv)

    excluded_rows = []
    review_rows = []
    excluded_paths = set()

    for row in rows:
        try:
            gt = int(float(row.get("gt_count", 0)))
            pred = int(float(row.get("pretrained_bird_detections", 0)))
            conf = float(row.get("max_unmatched_conf", 0.0))
        except ValueError:
            review_rows.append(row)
            continue

        if args.exclude_all_suspects:
            exclude = True
            reason = "all_audit_suspects"
        else:
            exclude = (pred > gt) and (conf >= args.min_conf)
            reason = f"pred_gt_and_conf_ge_{args.min_conf:.2f}"

        if exclude:
            row = dict(row)
            row["exclude_reason"] = reason
            excluded_rows.append(row)
            excluded_paths.add(normpath(row["image"]))
        else:
            review_rows.append(row)

    counts = {
        "train": {"kept": 0, "excluded": 0, "backgrounds": 0},
        "val": {"kept": 0, "excluded": 0, "backgrounds": 0},
        "test": {"kept": 0, "excluded": 0, "backgrounds": 0},
    }
    io_mode_counts = {"hardlink": 0, "copy": 0}
    kept_image_paths = set()

    for split in ("train", "val", "test"):
        old_img_dir = old_root / "images" / split
        old_lab_dir = old_root / "labels" / split
        new_img_dir = new_root / "images" / split
        new_lab_dir = new_root / "labels" / split

        new_img_dir.mkdir(parents=True, exist_ok=True)
        new_lab_dir.mkdir(parents=True, exist_ok=True)

        for img in sorted(old_img_dir.iterdir()):
            if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
                continue

            if normpath(img) in excluded_paths:
                counts[split]["excluded"] += 1
                continue

            dst_img = new_img_dir / img.name
            if args.copy:
                shutil.copy2(img, dst_img)
                mode = "copy"
            else:
                mode = link_or_copy(img, dst_img)

            io_mode_counts[mode] += 1
            counts[split]["kept"] += 1
            kept_image_paths.add(normpath(img))

            label = old_lab_dir / f"{img.stem}.txt"
            if label.exists():
                dst_label = new_lab_dir / label.name
                if args.copy:
                    shutil.copy2(label, dst_label)
                    mode2 = "copy"
                else:
                    mode2 = link_or_copy(label, dst_label)
                io_mode_counts[mode2] += 1
            else:
                counts[split]["backgrounds"] += 1

    # Filter manifest, if present.
    old_manifest = prepared / "manifests" / "yolo_manifest.csv"
    new_manifest_dir = out_prepared / "manifests"
    new_manifest_dir.mkdir(parents=True, exist_ok=True)

    if old_manifest.exists():
        manifest_rows = read_csv(old_manifest)
        kept_manifest = []
        for row in manifest_rows:
            out_img = row.get("output_image", "")
            if out_img and normpath(out_img) in kept_image_paths:
                new_row = dict(row)

                # Rewrite output_image to point at v2 dataset.
                old_path = Path(out_img)
                try:
                    rel = old_path.resolve().relative_to(old_root.resolve())
                    new_row["output_image"] = str((new_root / rel).resolve())
                except Exception:
                    pass

                kept_manifest.append(new_row)

        fields = list(manifest_rows[0].keys()) if manifest_rows else []
        if fields:
            write_csv(new_manifest_dir / "yolo_manifest_v2.csv", kept_manifest, fields)

    suspect_fields = list(rows[0].keys()) if rows else []
    write_csv(
        new_manifest_dir / "excluded_suspects.csv",
        excluded_rows,
        suspect_fields + ["exclude_reason"],
    )
    write_csv(
        new_manifest_dir / "review_remaining_suspects.csv",
        review_rows,
        suspect_fields,
    )

    # Ultralytics YAML.
    yaml_text = (
        f"path: {new_root.as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n"
        "names:\n"
        "  0: bird\n"
    )
    (new_root / "bird.yaml").write_text(yaml_text, encoding="utf-8")

    excluded_by_class = {}
    for row in excluded_rows:
        c = row.get("source_class", "") or "unknown"
        excluded_by_class[c] = excluded_by_class.get(c, 0) + 1

    summary = {
        "source_dataset": str(old_root),
        "output_dataset": str(new_root),
        "audit_csv": str(audit_csv),
        "rule": (
            "all suspects"
            if args.exclude_all_suspects
            else f"pretrained_bird_detections > gt_count AND max_unmatched_conf >= {args.min_conf:.2f}"
        ),
        "audit_suspects_total": len(rows),
        "auto_excluded": len(excluded_rows),
        "remaining_for_optional_review": len(review_rows),
        "excluded_by_source_class": excluded_by_class,
        "split_counts": counts,
        "io_mode_counts": io_mode_counts,
        "total_images_kept": sum(v["kept"] for v in counts.values()),
        "total_images_excluded": sum(v["excluded"] for v in counts.values()),
        "total_backgrounds_kept": sum(v["backgrounds"] for v in counts.values()),
        "note": (
            "prepared_v1 was not modified. Train/val/test membership was preserved. "
            "Excluded rows remain available in manifests/excluded_suspects.csv."
        ),
    }

    reports = out_prepared / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "yolo_v2_build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nYOLO v2 YAML: {new_root / 'bird.yaml'}")


if __name__ == "__main__":
    main()
