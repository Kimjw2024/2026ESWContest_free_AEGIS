#!/usr/bin/env python3
"""Prepare AEGIS bird datasets without modifying the original source tree.

Creates two independent outputs:
1) one-class YOLO detector dataset (all valid birds -> class 0, optional RPi negatives)
2) 8-class ResNet crop dataset (manual review/exclusion rules + bbox quality filters)

The script intentionally COPIES/CONVERTS into a new output directory. It never deletes
or renames files inside the source dataset.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
from PIL import Image, ImageFile, UnidentifiedImageError

ImageFile.LOAD_TRUNCATED_IMAGES = False

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

try:
    import imagehash  # type: ignore
except Exception:  # pragma: no cover
    imagehash = None

CLASSES = ["crow", "duck", "egret", "gull", "pigeon", "raptor", "sparrow", "swallow"]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float
    source_class_id: int


@dataclass
class Record:
    source_class: str
    image_path: Path
    label_path: Optional[Path]
    source_number: Optional[int]
    boxes: list[Box] = field(default_factory=list)
    phash: Optional[int] = None
    group_id: Optional[int] = None
    split: Optional[str] = None
    resnet_excluded: bool = False
    resnet_exclusion_reason: str = ""
    detector_excluded: bool = False
    detector_exclusion_reason: str = ""


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


class BKTree:
    """BK-tree for 64-bit perceptual hashes using Hamming distance."""

    def __init__(self):
        self.root: Optional[tuple[int, int, dict[int, object]]] = None

    @staticmethod
    def distance(a: int, b: int) -> int:
        return (a ^ b).bit_count()

    def add(self, value: int, index: int) -> None:
        if self.root is None:
            self.root = (value, index, {})
            return
        node = self.root
        while True:
            node_value, node_index, children = node
            d = self.distance(value, node_value)
            if d in children:
                node = children[d]  # type: ignore[assignment]
            else:
                children[d] = (value, index, {})
                return

    def search(self, value: int, max_distance: int) -> list[int]:
        if self.root is None:
            return []
        found: list[int] = []
        stack = [self.root]
        while stack:
            node_value, node_index, children = stack.pop()
            d = self.distance(value, node_value)
            if d <= max_distance:
                found.append(node_index)
            low, high = d - max_distance, d + max_distance
            for edge, child in children.items():
                if low <= edge <= high:
                    stack.append(child)  # type: ignore[arg-type]
        return found


def natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def extract_number(stem: str) -> Optional[int]:
    matches = re.findall(r"(\d+)", stem)
    return int(matches[-1]) if matches else None


def load_rules(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        rules = json.load(f)
    missing = [c for c in CLASSES if c not in rules.get("classes", {})]
    if missing:
        raise ValueError(f"audit rules missing classes: {missing}")
    return rules


def list_images(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS],
        key=natural_key,
    )


def image_is_valid(path: Path) -> tuple[bool, str]:
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im.load()
            if im.width < 2 or im.height < 2:
                return False, "image_too_small"
        return True, ""
    except (UnidentifiedImageError, OSError, ValueError) as e:
        return False, f"corrupt_image:{type(e).__name__}"


def parse_label(path: Path) -> tuple[list[Box], list[str]]:
    boxes: list[Box] = []
    issues: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="strict").splitlines()
    except UnicodeDecodeError:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        issues.append("label_decode_replaced")
    except OSError as e:
        return [], [f"label_read_error:{type(e).__name__}"]

    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            issues.append(f"line_{line_no}:expected_5_tokens")
            continue
        try:
            class_id = int(float(parts[0]))
            x, y, w, h = map(float, parts[1:])
        except ValueError:
            issues.append(f"line_{line_no}:non_numeric")
            continue
        vals = (x, y, w, h)
        if not all(math.isfinite(v) for v in vals):
            issues.append(f"line_{line_no}:non_finite")
            continue
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 < w <= 1.0 and 0.0 < h <= 1.0):
            issues.append(f"line_{line_no}:out_of_range")
            continue
        # Permit tiny rounding overflow, reject clearly invalid boxes.
        if x - w / 2 < -0.02 or y - h / 2 < -0.02 or x + w / 2 > 1.02 or y + h / 2 > 1.02:
            issues.append(f"line_{line_no}:box_outside_image")
            continue
        boxes.append(Box(x=x, y=y, w=w, h=h, source_class_id=class_id))
    if not boxes:
        issues.append("no_valid_boxes")
    return boxes, issues


def compute_phash(path: Path) -> int:
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        if imagehash is not None:
            return int(str(imagehash.phash(rgb)), 16)
        # Stable fallback: 8x8 average hash.
        small = rgb.resize((8, 8), Image.Resampling.LANCZOS).convert("L")
        arr = np.asarray(small, dtype=np.float32)
        bits = (arr > arr.mean()).flatten()
        value = 0
        for bit in bits:
            value = (value << 1) | int(bit)
        return value


def scan_source(source: Path, rules: dict, exclude_review: bool) -> tuple[list[Record], list[dict]]:
    records: list[Record] = []
    issues: list[dict] = []

    for cls in CLASSES:
        cls_root = source / cls
        images_dir = cls_root / "images"
        labels_dir = cls_root / "labels"
        if not images_dir.exists():
            issues.append({"class": cls, "type": "missing_images_dir", "path": str(images_dir), "detail": ""})
            continue
        if not labels_dir.exists():
            issues.append({"class": cls, "type": "missing_labels_dir", "path": str(labels_dir), "detail": ""})
            continue

        image_paths = list_images(images_dir)
        image_by_stem: dict[str, Path] = {}
        for p in image_paths:
            if p.stem in image_by_stem:
                issues.append({"class": cls, "type": "duplicate_image_stem", "path": str(p), "detail": p.stem})
                continue
            image_by_stem[p.stem] = p

        label_paths = sorted(labels_dir.rglob("*.txt"), key=natural_key)
        label_by_stem: dict[str, Path] = {}
        for p in label_paths:
            if p.stem in label_by_stem:
                issues.append({"class": cls, "type": "duplicate_label_stem", "path": str(p), "detail": p.stem})
                continue
            label_by_stem[p.stem] = p

        for stem, label_path in label_by_stem.items():
            if stem not in image_by_stem:
                issues.append({"class": cls, "type": "orphan_label", "path": str(label_path), "detail": stem})

        cls_rules = rules["classes"][cls]
        exclude_ids = set(int(v) for v in cls_rules.get("resnet_exclude", []))
        review_ids = set(int(v) for v in cls_rules.get("resnet_review", []))
        detector_exclude_ids = set(int(v) for v in cls_rules.get("detector_exclude", []))

        for stem, image_path in image_by_stem.items():
            label_path = label_by_stem.get(stem)
            number = extract_number(stem)
            valid, reason = image_is_valid(image_path)
            if not valid:
                issues.append({"class": cls, "type": "invalid_image", "path": str(image_path), "detail": reason})
                continue
            if label_path is None:
                issues.append({"class": cls, "type": "missing_label", "path": str(image_path), "detail": stem})
                continue
            boxes, label_issues = parse_label(label_path)
            for issue in label_issues:
                issues.append({"class": cls, "type": "label_issue", "path": str(label_path), "detail": issue})
            if not boxes:
                continue

            resnet_excluded = False
            resnet_reason = ""
            detector_excluded = False
            detector_reason = ""
            if number is not None:
                if number in exclude_ids:
                    resnet_excluded = True
                    resnet_reason = "manual_exclude"
                elif exclude_review and number in review_ids:
                    resnet_excluded = True
                    resnet_reason = "manual_review_excluded"
                if number in detector_exclude_ids:
                    detector_excluded = True
                    detector_reason = "manual_detector_artifact_exclude"

            records.append(
                Record(
                    source_class=cls,
                    image_path=image_path,
                    label_path=label_path,
                    source_number=number,
                    boxes=boxes,
                    resnet_excluded=resnet_excluded,
                    resnet_exclusion_reason=resnet_reason,
                    detector_excluded=detector_excluded,
                    detector_exclusion_reason=detector_reason,
                )
            )

    return records, issues


def assign_duplicate_groups(records: list[Record], threshold: int) -> None:
    if not records:
        return
    tree = BKTree()
    uf = UnionFind(len(records))
    exact_first: dict[int, int] = {}

    for idx, record in enumerate(records):
        try:
            h = compute_phash(record.image_path)
        except Exception:
            h = int(hashlib.sha256(str(record.image_path).encode("utf-8")).hexdigest()[:16], 16)
        record.phash = h
        if h in exact_first:
            uf.union(idx, exact_first[h])
        else:
            for near_idx in tree.search(h, threshold):
                uf.union(idx, near_idx)
            tree.add(h, idx)
            exact_first[h] = idx

    root_to_group: dict[int, int] = {}
    next_group = 0
    for idx, record in enumerate(records):
        root = uf.find(idx)
        if root not in root_to_group:
            root_to_group[root] = next_group
            next_group += 1
        record.group_id = root_to_group[root]


def split_for_group(group_id: int, seed: int, train_ratio: float, val_ratio: float) -> str:
    digest = hashlib.sha1(f"{seed}:{group_id}".encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") / float(2**64)
    if value < train_ratio:
        return "train"
    if value < train_ratio + val_ratio:
        return "val"
    return "test"


def assign_splits(records: list[Record], seed: int, train_ratio: float, val_ratio: float) -> None:
    for r in records:
        if r.group_id is None:
            raise RuntimeError("duplicate groups must be assigned before splits")
        r.split = split_for_group(r.group_id, seed, train_ratio, val_ratio)


def ensure_empty_output(out: Path, overwrite: bool) -> None:
    if out.exists():
        if not overwrite:
            raise FileExistsError(f"Output already exists: {out}. Use --overwrite to replace it.")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)


def copy_image_preserving_extension(src: Path, dst_stem: Path) -> Path:
    ext = src.suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        ext = ".jpg"
    dst = dst_stem.with_suffix(ext)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def blur_score(pil_image: Image.Image) -> float:
    gray = np.asarray(pil_image.convert("L"), dtype=np.uint8)
    if cv2 is not None:
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    # Fallback approximation from horizontal and vertical differences.
    dx = np.diff(gray.astype(np.float32), axis=1)
    dy = np.diff(gray.astype(np.float32), axis=0)
    return float((dx.var() + dy.var()) / 2.0)


def crop_from_box(im: Image.Image, box: Box, padding: float) -> tuple[Image.Image, tuple[int, int, int, int], float, float]:
    width, height = im.size
    x1 = (box.x - box.w / 2) * width
    y1 = (box.y - box.h / 2) * height
    x2 = (box.x + box.w / 2) * width
    y2 = (box.y + box.h / 2) * height
    bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
    px, py = bw * padding, bh * padding
    ix1 = max(0, int(math.floor(x1 - px)))
    iy1 = max(0, int(math.floor(y1 - py)))
    ix2 = min(width, int(math.ceil(x2 + px)))
    iy2 = min(height, int(math.ceil(y2 + py)))
    crop = im.crop((ix1, iy1, ix2, iy2)).convert("RGB")
    area_ratio = (bw * bh) / float(width * height)
    min_side = min(bw, bh)
    return crop, (ix1, iy1, ix2, iy2), min_side, area_ratio


def scan_negatives(roots: list[Path]) -> tuple[list[Record], list[dict]]:
    records: list[Record] = []
    issues: list[dict] = []
    for root in roots:
        if not root.exists():
            issues.append({"class": "negative", "type": "missing_negative_root", "path": str(root), "detail": ""})
            continue
        for image_path in list_images(root):
            valid, reason = image_is_valid(image_path)
            if not valid:
                issues.append({"class": "negative", "type": "invalid_image", "path": str(image_path), "detail": reason})
                continue
            records.append(
                Record(
                    source_class="negative",
                    image_path=image_path,
                    label_path=None,
                    source_number=extract_number(image_path.stem),
                    boxes=[],
                )
            )
    return records, issues


def write_csv(path: Path, rows: Iterable[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def audit_command(args: argparse.Namespace) -> int:
    source = Path(args.source)
    rules = load_rules(Path(args.rules))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    records, issues = scan_source(source, rules, exclude_review=args.exclude_review)
    record_rows = []
    for r in records:
        record_rows.append(
            {
                "source_class": r.source_class,
                "source_number": r.source_number if r.source_number is not None else "",
                "image_path": str(r.image_path),
                "label_path": str(r.label_path) if r.label_path else "",
                "box_count": len(r.boxes),
                "resnet_excluded": int(r.resnet_excluded),
                "resnet_exclusion_reason": r.resnet_exclusion_reason,
                "detector_excluded": int(r.detector_excluded),
                "detector_exclusion_reason": r.detector_exclusion_reason,
            }
        )

    write_csv(
        out / "audit_records.csv",
        record_rows,
        [
            "source_class",
            "source_number",
            "image_path",
            "label_path",
            "box_count",
            "resnet_excluded",
            "resnet_exclusion_reason",
            "detector_excluded",
            "detector_exclusion_reason",
        ],
    )
    write_csv(out / "audit_issues.csv", issues, ["class", "type", "path", "detail"])

    stats = {
        "valid_paired_images": len(records),
        "per_class_valid": dict(Counter(r.source_class for r in records)),
        "resnet_manual_excluded": dict(Counter(r.source_class for r in records if r.resnet_excluded)),
        "detector_manual_excluded": dict(Counter(r.source_class for r in records if r.detector_excluded)),
        "issue_count": len(issues),
        "issue_types": dict(Counter(i["type"] for i in issues)),
        "exclude_review": bool(args.exclude_review),
    }
    (out / "audit_summary.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"\nAudit files written to: {out}")
    return 0


def build_command(args: argparse.Namespace) -> int:
    source = Path(args.source)
    out = Path(args.out)
    rules = load_rules(Path(args.rules))
    ensure_empty_output(out, args.overwrite)

    reports_dir = out / "reports"
    manifests_dir = out / "manifests"
    yolo_root = out / "yolo_bird_v1"
    resnet_root = out / "resnet_birds_v1"

    records, issues = scan_source(source, rules, exclude_review=args.exclude_review)
    negative_roots = [Path(p) for p in args.negative_root]
    negatives, negative_issues = scan_negatives(negative_roots)
    issues.extend(negative_issues)

    all_for_grouping = records + negatives
    print(f"Computing perceptual-hash groups for {len(all_for_grouping):,} images...")
    assign_duplicate_groups(all_for_grouping, threshold=args.phash_threshold)
    assign_splits(all_for_grouping, seed=args.seed, train_ratio=args.train_ratio, val_ratio=args.val_ratio)

    for split in ("train", "val", "test"):
        (yolo_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (yolo_root / "labels" / split).mkdir(parents=True, exist_ok=True)
        for cls in CLASSES:
            (resnet_root / split / cls).mkdir(parents=True, exist_ok=True)

    yolo_rows: list[dict] = []
    resnet_rows: list[dict] = []
    skipped_rows: list[dict] = []
    detector_counters = Counter()
    resnet_counters = Counter()

    # Positive detector samples and classifier crops.
    for r in records:
        if r.split is None:
            raise RuntimeError("split not assigned")

        if not r.detector_excluded:
            detector_counters[r.source_class] += 1
            new_stem = f"{r.source_class}_{detector_counters[r.source_class]:06d}"
            image_dst = copy_image_preserving_extension(
                r.image_path, yolo_root / "images" / r.split / new_stem
            )
            label_dst = yolo_root / "labels" / r.split / f"{new_stem}.txt"
            label_dst.write_text(
                "".join(f"0 {b.x:.8f} {b.y:.8f} {b.w:.8f} {b.h:.8f}\n" for b in r.boxes),
                encoding="utf-8",
            )
            yolo_rows.append(
                {
                    "new_stem": new_stem,
                    "split": r.split,
                    "source_class": r.source_class,
                    "source_number": r.source_number if r.source_number is not None else "",
                    "source_image": str(r.image_path),
                    "output_image": str(image_dst),
                    "output_label": str(label_dst),
                    "box_count": len(r.boxes),
                    "is_negative": 0,
                    "group_id": r.group_id,
                    "phash": f"{r.phash:016x}" if r.phash is not None else "",
                }
            )
        else:
            skipped_rows.append(
                {
                    "stage": "yolo",
                    "source_class": r.source_class,
                    "source_number": r.source_number if r.source_number is not None else "",
                    "source_image": str(r.image_path),
                    "reason": r.detector_exclusion_reason,
                    "detail": "",
                }
            )

        if r.resnet_excluded:
            skipped_rows.append(
                {
                    "stage": "resnet",
                    "source_class": r.source_class,
                    "source_number": r.source_number if r.source_number is not None else "",
                    "source_image": str(r.image_path),
                    "reason": r.resnet_exclusion_reason,
                    "detail": "",
                }
            )
            continue

        try:
            with Image.open(r.image_path) as src_im:
                src_im = src_im.convert("RGB")
                for box_index, box in enumerate(r.boxes):
                    crop, pixel_box, min_side, area_ratio = crop_from_box(src_im, box, args.crop_padding)
                    if min_side < args.min_box_side:
                        skipped_rows.append(
                            {
                                "stage": "resnet",
                                "source_class": r.source_class,
                                "source_number": r.source_number if r.source_number is not None else "",
                                "source_image": str(r.image_path),
                                "reason": "box_too_small",
                                "detail": f"min_side={min_side:.2f}",
                            }
                        )
                        continue
                    if area_ratio < args.min_area_ratio:
                        skipped_rows.append(
                            {
                                "stage": "resnet",
                                "source_class": r.source_class,
                                "source_number": r.source_number if r.source_number is not None else "",
                                "source_image": str(r.image_path),
                                "reason": "box_area_too_small",
                                "detail": f"area_ratio={area_ratio:.6f}",
                            }
                        )
                        continue
                    score = blur_score(crop)
                    if score < args.min_blur:
                        skipped_rows.append(
                            {
                                "stage": "resnet",
                                "source_class": r.source_class,
                                "source_number": r.source_number if r.source_number is not None else "",
                                "source_image": str(r.image_path),
                                "reason": "crop_too_blurry",
                                "detail": f"blur={score:.2f}",
                            }
                        )
                        continue

                    resnet_counters[r.source_class] += 1
                    crop_stem = f"{r.source_class}_{resnet_counters[r.source_class]:06d}_b{box_index:02d}"
                    crop_dst = resnet_root / r.split / r.source_class / f"{crop_stem}.jpg"
                    crop_dst.parent.mkdir(parents=True, exist_ok=True)
                    crop.save(crop_dst, format="JPEG", quality=95, subsampling=0)
                    resnet_rows.append(
                        {
                            "new_stem": crop_stem,
                            "split": r.split,
                            "class": r.source_class,
                            "source_number": r.source_number if r.source_number is not None else "",
                            "source_image": str(r.image_path),
                            "output_crop": str(crop_dst),
                            "box_index": box_index,
                            "pixel_box": ",".join(map(str, pixel_box)),
                            "min_box_side": f"{min_side:.3f}",
                            "box_area_ratio": f"{area_ratio:.8f}",
                            "blur_score": f"{score:.3f}",
                            "group_id": r.group_id,
                            "phash": f"{r.phash:016x}" if r.phash is not None else "",
                        }
                    )
        except Exception as e:
            skipped_rows.append(
                {
                    "stage": "resnet",
                    "source_class": r.source_class,
                    "source_number": r.source_number if r.source_number is not None else "",
                    "source_image": str(r.image_path),
                    "reason": "crop_exception",
                    "detail": f"{type(e).__name__}:{e}",
                }
            )

    # RPi/background negative samples.
    neg_counter = 0
    for r in negatives:
        if r.split is None:
            raise RuntimeError("negative split not assigned")
        neg_counter += 1
        new_stem = f"neg_rpi_{neg_counter:06d}"
        image_dst = copy_image_preserving_extension(
            r.image_path, yolo_root / "images" / r.split / new_stem
        )
        label_dst = yolo_root / "labels" / r.split / f"{new_stem}.txt"
        label_dst.write_text("", encoding="utf-8")
        yolo_rows.append(
            {
                "new_stem": new_stem,
                "split": r.split,
                "source_class": "negative",
                "source_number": r.source_number if r.source_number is not None else "",
                "source_image": str(r.image_path),
                "output_image": str(image_dst),
                "output_label": str(label_dst),
                "box_count": 0,
                "is_negative": 1,
                "group_id": r.group_id,
                "phash": f"{r.phash:016x}" if r.phash is not None else "",
            }
        )

    yaml_text = (
        f"path: {yolo_root.as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n\n"
        "names:\n"
        "  0: bird\n"
    )
    (yolo_root / "bird.yaml").write_text(yaml_text, encoding="utf-8")
    (resnet_root / "class_names.json").write_text(
        json.dumps(CLASSES, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    write_csv(
        manifests_dir / "yolo_manifest.csv",
        yolo_rows,
        [
            "new_stem",
            "split",
            "source_class",
            "source_number",
            "source_image",
            "output_image",
            "output_label",
            "box_count",
            "is_negative",
            "group_id",
            "phash",
        ],
    )
    write_csv(
        manifests_dir / "resnet_manifest.csv",
        resnet_rows,
        [
            "new_stem",
            "split",
            "class",
            "source_number",
            "source_image",
            "output_crop",
            "box_index",
            "pixel_box",
            "min_box_side",
            "box_area_ratio",
            "blur_score",
            "group_id",
            "phash",
        ],
    )
    write_csv(
        manifests_dir / "skipped.csv",
        skipped_rows,
        ["stage", "source_class", "source_number", "source_image", "reason", "detail"],
    )
    write_csv(reports_dir / "audit_issues.csv", issues, ["class", "type", "path", "detail"])

    yolo_split_counts = Counter(row["split"] for row in yolo_rows)
    yolo_positive_counts = Counter(
        (row["split"], row["source_class"]) for row in yolo_rows if not row["is_negative"]
    )
    resnet_split_counts = Counter((row["split"], row["class"]) for row in resnet_rows)
    summary = {
        "source": str(source),
        "output": str(out),
        "rules": str(args.rules),
        "settings": {
            "exclude_review": args.exclude_review,
            "seed": args.seed,
            "train_ratio": args.train_ratio,
            "val_ratio": args.val_ratio,
            "test_ratio": 1.0 - args.train_ratio - args.val_ratio,
            "phash_threshold": args.phash_threshold,
            "min_box_side": args.min_box_side,
            "min_area_ratio": args.min_area_ratio,
            "min_blur": args.min_blur,
            "crop_padding": args.crop_padding,
        },
        "source_valid_paired": len(records),
        "negative_images": len(negatives),
        "yolo_total": len(yolo_rows),
        "yolo_split_counts": dict(yolo_split_counts),
        "yolo_positive_by_split_and_source_class": {
            f"{split}:{cls}": count for (split, cls), count in sorted(yolo_positive_counts.items())
        },
        "resnet_total_crops": len(resnet_rows),
        "resnet_by_split_and_class": {
            f"{split}:{cls}": count for (split, cls), count in sorted(resnet_split_counts.items())
        },
        "skipped_count": len(skipped_rows),
        "skip_reasons": dict(Counter(row["reason"] for row in skipped_rows)),
        "audit_issue_count": len(issues),
        "audit_issue_types": dict(Counter(i["type"] for i in issues)),
    }
    (reports_dir / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nCreated:")
    print(f"  YOLO dataset : {yolo_root}")
    print(f"  ResNet data  : {resnet_root}")
    print(f"  Reports      : {reports_dir}")
    print(f"  Manifests    : {manifests_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare AEGIS YOLO and ResNet bird datasets safely.")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Validate image-label pairs and write reports only.")
    audit.add_argument("--source", required=True, help="Source bird_dataset directory")
    audit.add_argument("--rules", default="audit_rules.json", help="Audit-rules JSON")
    audit.add_argument("--out", required=True, help="Report output directory")
    audit.add_argument(
        "--exclude-review",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Treat REVIEW IDs as excluded from ResNet v1 (default: true)",
    )
    audit.set_defaults(func=audit_command)

    build = sub.add_parser("build", help="Build YOLO and ResNet outputs in a new directory.")
    build.add_argument("--source", required=True, help="Source bird_dataset directory")
    build.add_argument("--rules", default="audit_rules.json", help="Audit-rules JSON")
    build.add_argument("--out", required=True, help="New output root")
    build.add_argument(
        "--negative-root",
        action="append",
        default=[],
        help="Root containing background/negative images; repeat for multiple roots",
    )
    build.add_argument("--overwrite", action="store_true", help="Delete and rebuild only the OUTPUT directory")
    build.add_argument("--seed", type=int, default=42)
    build.add_argument("--train-ratio", type=float, default=0.80)
    build.add_argument("--val-ratio", type=float, default=0.10)
    build.add_argument("--phash-threshold", type=int, default=4, help="Hamming threshold for near-duplicate grouping")
    build.add_argument("--min-box-side", type=float, default=32.0, help="Minimum original bbox short side in pixels for ResNet")
    build.add_argument("--min-area-ratio", type=float, default=0.01, help="Minimum bbox area/image area for ResNet")
    build.add_argument("--min-blur", type=float, default=20.0, help="Minimum Laplacian-variance blur score for ResNet crop")
    build.add_argument("--crop-padding", type=float, default=0.12, help="Padding around bbox for ResNet crop")
    build.add_argument(
        "--exclude-review",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Treat REVIEW IDs as excluded from ResNet v1 (default: true)",
    )
    build.set_defaults(func=build_command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "command", None) == "build":
        if not (0.0 < args.train_ratio < 1.0 and 0.0 <= args.val_ratio < 1.0):
            parser.error("train/val ratios must be in valid ranges")
        if args.train_ratio + args.val_ratio >= 1.0:
            parser.error("train_ratio + val_ratio must be < 1.0")
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
