# AI Quantitative Results

이 디렉터리는 **최종 선택된 AI 학습·평가 run의 원본 결과 파일**을 보존한다. 발표자료와 README에 사용하는 수치는 아래 파일과 `docs/AI_RESULTS.md`를 기준으로 한다.

> Custom YOLOv8s 결과는 **Held-Out Offline Test**이며 live field accuracy가 아니다.

---

## 1. Custom YOLOv8s — `aegis_bird_v2_final`

### Summary

| Metric | Result |
|---|---:|
| Precision | **96.4%** |
| Recall | **93.5%** |
| mAP@0.5 | **97.5%** |
| mAP@0.5:0.95 | **70.9%** |
| Held-Out Test | **1,325 images / 1,436 bird instances / 67 backgrounds** |

### Final Evidence

| Training Curves | Normalized Confusion Matrix |
|---|---|
| ![](yolo/training_curves.png) | ![](yolo/confusion_matrix_normalized.png) |

| F1–Confidence | Precision–Confidence | Recall–Confidence |
|---|---|---|
| ![](yolo/box_f1_curve.png) | ![](yolo/box_precision_curve.png) | ![](yolo/box_recall_curve.png) |

### Files

```text
yolo/training_curves.png
yolo/confusion_matrix.png
yolo/confusion_matrix_normalized.png
yolo/box_f1_curve.png
yolo/box_precision_curve.png
yolo/box_recall_curve.png
yolo/labels.jpg
yolo/results.csv
```

`results.csv`는 epoch별 train/validation loss와 Precision·Recall·mAP 변화를 보존한다.

---

## 2. ResNet-18 — `resnet18_bird_v2_stable`

### Aggregate Result

| Metric | Result |
|---|---:|
| Test Accuracy | **94.76%** |
| Test Macro-F1 | **94.56%** |
| Best Validation Accuracy | **95.52%** |
| Best Validation Macro-F1 | **95.20%** |
| Best Epoch | **7** |
| Test Support | **1,375** |

<p align="center"><img src="resnet/confusion_matrix.png" alt="ResNet-18 final confusion matrix" width="760"></p>

### Class-wise Test Report

| Class / Group | Precision | Recall | F1-score | Support |
|---|---:|---:|---:|---:|
| crow | 91.10% | 99.43% | 95.08% | 175 |
| duck | 96.95% | 92.98% | 94.93% | 171 |
| egret | 94.82% | 97.34% | 96.06% | 188 |
| gull | 95.10% | 94.33% | 94.72% | 247 |
| pigeon | 96.20% | 93.16% | 94.65% | 190 |
| raptor | 94.44% | 87.74% | 90.97% | 155 |
| sparrow | 95.91% | 98.80% | 97.33% | 166 |
| swallow | 92.77% | 92.77% | 92.77% | 83 |
| **Macro average** | **94.66%** | **94.57%** | **94.56%** | **1,375** |
| **Weighted average** | **94.82%** | **94.76%** | **94.74%** | **1,375** |

### Files

```text
resnet/confusion_matrix.png
resnet/history.csv
resnet/test_summary.json
```

- `history.csv`: epoch별 train/validation loss·accuracy·macro-F1
- `test_summary.json`: class names, train counts, best epoch, aggregate·class-wise report

---

## 3. Runtime Gate

| Gate | Value |
|---|---:|
| Minimum crop side | 48 px |
| Top-1 confidence | ≥ 0.70 |
| Top1–Top2 margin | ≥ 0.15 |
| Vote window | recent 7 |
| Stable requirement | 5 votes |
| Stale reset | 1.2 s |
| Gate failure | `UNKNOWN` |

`UNKNOWN`은 오류가 아니라, 분류 근거가 부족할 때 과도한 대응을 막고 Track3D 연속성을 유지하기 위한 안전 상태다.

---

## 4. Interpretation Boundaries

- YOLO 그래프와 aggregate score는 정제된 held-out dataset에서의 offline result다.
- Raspberry Pi field input의 domain shift와 false positive는 별도로 분석한다.
- ResNet class별 지표는 crop classifier의 성능이며, detector 누락까지 포함한 End-to-End field accuracy가 아니다.
- Risk Engine은 neural network가 아니라 explainable operational rule set이다.
- 자세한 해석과 수치 근거: [`../docs/AI_RESULTS.md`](../docs/AI_RESULTS.md)
- 정량 claim 범위: [`../docs/METRICS.md`](../docs/METRICS.md)
