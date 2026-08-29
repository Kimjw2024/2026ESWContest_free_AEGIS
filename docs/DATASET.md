# Dataset & Curation

## 1. Raw Archive vs Curated Training Data

The project uses two different scale descriptions, and they must not be mixed.

### Raw Working Archive

Recorded in the competition deck:

- approximately **13 GB**
- **156,416 files**
- **33 folders**
- approximately **40K candidate images**

This includes source images, labels, intermediate exports, logs, model artifacts and backup material.

### Curated Valid Paired Images

| Class / Group | Valid paired images |
|---|---:|
| crow | 1,674 |
| duck | 1,588 |
| egret | 2,125 |
| gull | 2,288 |
| pigeon | 1,294 |
| raptor | 1,481 |
| sparrow | 1,379 |
| swallow | 1,341 |
| **Total** | **13,170** |

`raptor` is a bird group rather than a single biological species; the correct wording is **8-class bird classification / 8개 조류군 분류**.

## 2. Curation Pipeline

```text
source image/label pairing
→ class-wise candidate review
→ duplicate / low-resolution / blur removal
→ non-bird / wrong-class exclusion
→ missing-label audit
→ manual exclusion rules
→ Raspberry Pi field-background hard negatives
→ detector split and classifier crop split
→ training / validation / held-out test
```

- Raspberry Pi field-background negatives: **518**
- Final prepared YOLO v2: **12,819 images**
- Held-out test: **1,325 images / 1,436 bird instances / 67 backgrounds**

<p align="center"><img src="../assets/dataset/dataset_candidate_review.png" alt="class-wise dataset candidate review" width="900"></p>

## 3. Detector and Classifier Data Separation

### YOLO

- full image
- bird bbox label
- background / hard-negative image
- objective: localization center for 3D tracking

### ResNet-18

- detector-derived or curated object crop
- one of 8 class/group labels
- objective: species/group evidence for risk assessment

The detector and classifier are related but do not use an identical sample representation.

## 4. Reproducibility

- preparation: `training/prepare_aegis_bird_data.py`
- audit: `training/audit_yolo_missing_birds_v2.py`
- clean build: `training/build_clean_yolo_v2.py`
- visual inspection: `training/inspect_prepared_samples.py`
- manual rules: `training/audit_rules.json`

The raw corpus is not committed because of size and source-management constraints. The repository preserves code, class definitions, summary counts, final metrics and representative evidence.

## 5. Limitation

The dataset is a research/competition prototype and does not fully represent every airport, weather, altitude, sensor and background distribution. Offline metrics must not be presented as certified field performance.
