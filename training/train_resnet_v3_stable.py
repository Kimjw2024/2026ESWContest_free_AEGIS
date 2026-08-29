#!/usr/bin/env python3
"""Stable AEGIS ResNet-18 trainer.

Key differences from v2:
- FP32 training by default for maximum numerical stability on GTX 1660 SUPER.
- Uses ONE class-imbalance mechanism only: class-weighted CrossEntropyLoss.
- Uses normal shuffled sampling (no WeightedRandomSampler double compensation).
- Stops immediately if a non-finite loss/gradient is detected.
- Selects the best checkpoint by validation macro-F1, accuracy as tie-breaker.
- Keeps optional AMP via --amp, but default is OFF.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from torch.amp import GradScaler, autocast
from torch.utils.data import DataLoader
from torchvision import datasets, models, transforms
from torchvision.models import ResNet18_Weights


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = True


def build_transforms():
    mean = [0.485, 0.456, 0.406]
    std = [0.229, 0.224, 0.225]

    train_tf = transforms.Compose(
        [
            transforms.RandomResizedCrop(224, scale=(0.72, 1.0), ratio=(0.80, 1.25)),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.RandomRotation(10),
            transforms.ColorJitter(
                brightness=0.25,
                contrast=0.25,
                saturation=0.20,
                hue=0.03,
            ),
            transforms.ToTensor(),
            transforms.Normalize(mean=mean, std=std),
        ]
    )

    eval_tf = transforms.Compose(
        [
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean=mean, std=std),
        ]
    )

    return train_tf, eval_tf


def make_loader(dataset, batch_size, workers, shuffle=False):
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=workers,
        pin_memory=torch.cuda.is_available(),
        persistent_workers=workers > 0,
        drop_last=False,
    )


def evaluate(model, loader, criterion, device, amp_enabled):
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0
    ys, preds = [], []

    with torch.inference_mode():
        for images, targets in loader:
            images = images.to(device, non_blocking=True)
            targets = targets.to(device, non_blocking=True)

            with autocast(
                device_type=device.type,
                enabled=amp_enabled and device.type == "cuda",
            ):
                logits = model(images)
                loss = criterion(logits, targets)

            if not torch.isfinite(loss):
                raise RuntimeError(
                    "Non-finite validation/test loss detected. "
                    f"logits_finite={bool(torch.isfinite(logits).all())}"
                )

            total_loss += float(loss.item()) * images.size(0)
            pred = logits.argmax(dim=1)

            correct += int((pred == targets).sum().item())
            total += int(targets.numel())
            ys.extend(targets.detach().cpu().tolist())
            preds.extend(pred.detach().cpu().tolist())

    macro_f1 = f1_score(
        ys,
        preds,
        average="macro",
        zero_division=0,
    ) if ys else 0.0

    return {
        "loss": total_loss / max(total, 1),
        "accuracy": correct / max(total, 1),
        "macro_f1": float(macro_f1),
        "targets": ys,
        "predictions": preds,
    }


def save_confusion(cm, class_names, out_path: Path):
    fig = plt.figure(figsize=(10, 9))
    ax = fig.add_subplot(111)
    im = ax.imshow(cm)
    fig.colorbar(im, ax=ax)

    ax.set_xticks(range(len(class_names)))
    ax.set_yticks(range(len(class_names)))
    ax.set_xticklabels(class_names, rotation=45, ha="right")
    ax.set_yticklabels(class_names)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title("AEGIS ResNet-18 Confusion Matrix")

    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center")

    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--out", required=True)

    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--weight-decay", type=float, default=1e-4)
    p.add_argument("--patience", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)

    # Deliberately OFF by default for the current GTX 1660 SUPER run.
    p.add_argument("--amp", action="store_true")

    args = p.parse_args()

    seed_everything(args.seed)

    data_root = Path(args.data).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    for split in ("train", "val", "test"):
        if not (data_root / split).exists():
            raise FileNotFoundError(data_root / split)

    train_tf, eval_tf = build_transforms()

    train_ds = datasets.ImageFolder(data_root / "train", transform=train_tf)
    val_ds = datasets.ImageFolder(data_root / "val", transform=eval_tf)
    test_ds = datasets.ImageFolder(data_root / "test", transform=eval_tf)

    if train_ds.classes != val_ds.classes or train_ds.classes != test_ds.classes:
        raise RuntimeError("Class folder order differs across train/val/test")

    class_names = train_ds.classes
    num_classes = len(class_names)

    train_targets = [target for _, target in train_ds.samples]
    counts = Counter(train_targets)

    # ONE balancing mechanism only:
    # class-weighted CE. This is the same stable loss family used by the
    # successful sanity run, without also using WeightedRandomSampler.
    class_count_array = np.array(
        [counts.get(i, 0) for i in range(num_classes)],
        dtype=np.float64,
    )
    class_weights = class_count_array.sum() / np.maximum(class_count_array, 1.0)
    class_weights = class_weights / class_weights.mean()

    train_loader = make_loader(
        train_ds,
        args.batch,
        args.workers,
        shuffle=True,
    )
    val_loader = make_loader(
        val_ds,
        args.batch,
        args.workers,
        shuffle=False,
    )
    test_loader = make_loader(
        test_ds,
        args.batch,
        args.workers,
        shuffle=False,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    amp_enabled = bool(args.amp and device.type == "cuda")

    model = models.resnet18(weights=ResNet18_Weights.DEFAULT)
    in_features = model.fc.in_features
    model.fc = nn.Sequential(
        nn.Dropout(p=0.25),
        nn.Linear(in_features, num_classes),
    )
    model.to(device)

    criterion = nn.CrossEntropyLoss(
        weight=torch.tensor(
            class_weights,
            dtype=torch.float32,
            device=device,
        ),
        label_smoothing=0.08,
    )

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=args.lr,
        weight_decay=args.weight_decay,
    )

    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=max(args.epochs, 1),
    )

    # Kept for optional --amp only.
    # Lower initial scale than the generic default for additional safety.
    scaler = GradScaler(
        "cuda",
        enabled=amp_enabled,
        init_scale=4096.0,
        growth_interval=2000,
    )

    print("=== AEGIS ResNet-18 stable training ===")
    print(f"device       : {device}")
    print(f"AMP          : {amp_enabled}")
    print(f"epochs       : {args.epochs}")
    print(f"batch        : {args.batch}")
    print(f"lr           : {args.lr}")
    print(f"patience     : {args.patience}")
    print(f"train images : {len(train_ds)}")
    print(f"val images   : {len(val_ds)}")
    print(f"test images  : {len(test_ds)}")
    print("class weights:")
    for i, name in enumerate(class_names):
        print(
            f"  {name:8s} count={counts.get(i,0):4d} "
            f"weight={class_weights[i]:.4f}"
        )

    history = []
    best_f1 = -1.0
    best_acc = -1.0
    best_path = out / "best_resnet18.pt"
    no_improve = 0

    for epoch in range(1, args.epochs + 1):
        model.train()

        running_loss = 0.0
        correct = 0
        total = 0

        for batch_idx, (images, targets) in enumerate(train_loader, start=1):
            images = images.to(device, non_blocking=True)
            targets = targets.to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)

            with autocast(
                device_type=device.type,
                enabled=amp_enabled,
            ):
                logits = model(images)
                loss = criterion(logits, targets)

            # Fail loudly instead of silently producing a poisoned checkpoint.
            if not torch.isfinite(loss):
                finite_logits = bool(torch.isfinite(logits).all())
                finite_images = bool(torch.isfinite(images).all())
                raise RuntimeError(
                    "NON-FINITE TRAIN LOSS. "
                    f"epoch={epoch}, batch={batch_idx}, "
                    f"loss={loss.item()}, "
                    f"images_finite={finite_images}, "
                    f"logits_finite={finite_logits}, "
                    f"logit_abs_max="
                    f"{float(torch.nan_to_num(logits.detach()).abs().max().item()):.6g}"
                )

            if amp_enabled:
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
            else:
                loss.backward()

            grad_norm = torch.nn.utils.clip_grad_norm_(
                model.parameters(),
                max_norm=5.0,
                error_if_nonfinite=False,
            )

            if not torch.isfinite(torch.as_tensor(grad_norm)):
                raise RuntimeError(
                    "NON-FINITE GRADIENT NORM. "
                    f"epoch={epoch}, batch={batch_idx}, grad_norm={grad_norm}"
                )

            if amp_enabled:
                scaler.step(optimizer)
                scaler.update()
            else:
                optimizer.step()

            running_loss += float(loss.item()) * images.size(0)

            pred = logits.argmax(dim=1)
            correct += int((pred == targets).sum().item())
            total += int(targets.numel())

        # Scheduler runs only after a successful epoch of optimizer updates.
        scheduler.step()

        train_loss = running_loss / max(total, 1)
        train_acc = correct / max(total, 1)

        val = evaluate(
            model,
            val_loader,
            criterion,
            device,
            amp_enabled,
        )

        current_lr = optimizer.param_groups[0]["lr"]

        row = {
            "epoch": epoch,
            "train_loss": train_loss,
            "train_accuracy": train_acc,
            "val_loss": val["loss"],
            "val_accuracy": val["accuracy"],
            "val_macro_f1": val["macro_f1"],
            "lr": current_lr,
        }
        history.append(row)

        print(
            f"Epoch {epoch:03d}/{args.epochs} | "
            f"train loss {train_loss:.4f} acc {train_acc:.4f} | "
            f"val loss {val['loss']:.4f} "
            f"acc {val['accuracy']:.4f} "
            f"macroF1 {val['macro_f1']:.4f} | "
            f"lr {current_lr:.2e}"
        )

        improved = (
            val["macro_f1"] > best_f1 + 1e-12
            or (
                abs(val["macro_f1"] - best_f1) <= 1e-12
                and val["accuracy"] > best_acc
            )
        )

        if improved:
            best_f1 = val["macro_f1"]
            best_acc = val["accuracy"]
            no_improve = 0

            torch.save(
                {
                    "model_state": model.state_dict(),
                    "class_names": class_names,
                    "best_val_macro_f1": best_f1,
                    "best_val_accuracy": best_acc,
                    "epoch": epoch,
                    "weights": "ResNet18_Weights.DEFAULT",
                    "amp": amp_enabled,
                    "class_weights": class_weights.tolist(),
                },
                best_path,
            )
        else:
            no_improve += 1
            if no_improve >= args.patience:
                print(
                    f"Early stopping at epoch {epoch} "
                    f"(no macro-F1 improvement for {args.patience} epochs)"
                )
                break

    if not best_path.exists():
        raise RuntimeError("No valid checkpoint was produced.")

    with (out / "history.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(history[0].keys()),
        )
        writer.writeheader()
        writer.writerows(history)

    checkpoint = torch.load(
        best_path,
        map_location=device,
        weights_only=False,
    )
    model.load_state_dict(checkpoint["model_state"])

    test = evaluate(
        model,
        test_loader,
        criterion,
        device,
        amp_enabled,
    )

    report = classification_report(
        test["targets"],
        test["predictions"],
        labels=list(range(num_classes)),
        target_names=class_names,
        output_dict=True,
        zero_division=0,
    )

    cm = confusion_matrix(
        test["targets"],
        test["predictions"],
        labels=list(range(num_classes)),
    )

    save_confusion(
        cm,
        class_names,
        out / "confusion_matrix.png",
    )

    summary = {
        "device": str(device),
        "amp": amp_enabled,
        "class_names": class_names,
        "train_counts": {
            class_names[i]: counts.get(i, 0)
            for i in range(num_classes)
        },
        "best_val_macro_f1": checkpoint["best_val_macro_f1"],
        "best_val_accuracy": checkpoint["best_val_accuracy"],
        "best_epoch": checkpoint["epoch"],
        "test_loss": test["loss"],
        "test_accuracy": test["accuracy"],
        "test_macro_f1": test["macro_f1"],
        "classification_report": report,
    }

    (out / "test_summary.json").write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n=== FINAL RESULT ===")
    print(
        json.dumps(
            {k: v for k, v in summary.items()
             if k != "classification_report"},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"Best checkpoint: {best_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
