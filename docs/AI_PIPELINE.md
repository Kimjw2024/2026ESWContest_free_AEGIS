# AI · Dataset · Decision Pipeline

AEGIS의 AI 파트는 **조류의 위치를 찾는 문제**와 **어떤 조류군인지 판별하는 문제**를 분리하고, 두 결과를 3D 추적·위험 판단·대응 출력에 연결한다.

> 상세 그래프, confusion matrix, class별 Precision/Recall/F1과 Risk weight는 [AI_RESULTS.md](AI_RESULTS.md)에서 확인할 수 있다.

---

## 1. End-to-End AI Flow

```text
Frame
→ YOLO bird bbox / center
→ Detection2D standard
→ Multi-Camera Stereo 3D / Track3D
→ object crop
→ crop quality gate
→ ResNet-18 8-class classification
→ Top-1 confidence + Top1–Top2 margin
→ track-level temporal voting
→ explainable risk assessment
→ AI Decision Console / response layer
```

이 2-stage 구조는 분류가 `UNKNOWN`을 반환하더라도 bird bbox와 Track3D를 유지하므로, fine-grained classification의 불확실성이 3D tracking과 터렛 제어를 즉시 중단시키지 않는다.

---

## 2. 모델 운용 정책

| 구분 | 모델 | 역할 | 선택 이유 |
|---|---|---|---|
| Live Detector | `yolo26n.pt` | bird bbox·center 검출 | field Runtime에서 안정적인 bird localization |
| Research Detector | Custom YOLOv8s | bird-specific 학습·성능 분석 | Held-Out Offline Test와 hard-negative 연구 |
| Live Classifier | ResNet-18 | 8개 조류군 분류 | crop 기반 lightweight classification |
| Decision Engine | Rule-based | risk score·response recommendation | 판단 근거를 설명 가능한 형태로 유지 |

Custom YOLO의 높은 offline score를 live accuracy로 과장하지 않고, **현장 Runtime 모델과 연구용 detector를 분리**한다.

---

## 3. Dataset Scale & Curation

### Raw Working Archive

- 약 **13 GB**
- **156,416 files**
- **33 folders**
- 약 **40K candidate images**

위 수치는 원천 수집·중간 산출물·검수 후보를 포함한 작업 아카이브 규모이며, 최종 학습 split과 동일하지 않다.

### Curated Valid Source Pool

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

추가 정제 결과:

| 항목 | 수량 |
|---|---:|
| Raspberry Pi field background / negative | **518** |
| Final prepared YOLO v2 | **12,819 images** |
| YOLO Held-Out Test | **1,325 images / 1,436 instances / 67 backgrounds** |
| ResNet Final Test | **1,375 crops** |

### Contamination Audit

```text
source image/label pairing
→ class-wise candidate review
→ missing-label audit
→ duplicate / blur / low-resolution removal
→ wrong-class / non-bird / invalid-box exclusion
→ field background hard-negative integration
→ detector split + classifier crop split
→ train / validation / held-out test
```

재현 코드:

- `training/prepare_aegis_bird_data.py`
- `training/audit_yolo_missing_birds_v2.py`
- `training/build_clean_yolo_v2.py`
- `training/inspect_prepared_samples.py`
- `training/audit_rules.json`

<p align="center"><img src="../assets/dataset/dataset_candidate_review.png" alt="class-wise candidate review" width="900"></p>

---

## 4. Stage 1 — YOLO Bird Detection

### Live Runtime Detector

| Setting | Value |
|---|---:|
| Model | YOLO26n |
| Class | COCO bird class 14 |
| Confidence threshold | 0.16 |
| Minimum bbox area | 80 px² |
| CPU input | 320–640 class runtime path |
| GPU / TensorRT evaluation | up to 1280 |
| 3D interface | bbox center → `Detection2D` |

### Custom YOLOv8s — Held-Out Offline Test

| Metric | Result |
|---|---:|
| Precision | **96.4%** |
| Recall | **93.5%** |
| mAP@0.5 | **97.5%** |
| mAP@0.5:0.95 | **70.9%** |

| Final Training Curves | Normalized Confusion Matrix |
|---|---|
| ![](../results/yolo/training_curves.png) | ![](../results/yolo/confusion_matrix_normalized.png) |

| F1–Confidence | Precision–Confidence | Recall–Confidence |
|---|---|---|
| ![](../results/yolo/box_f1_curve.png) | ![](../results/yolo/box_precision_curve.png) | ![](../results/yolo/box_recall_curve.png) |

현장 Raspberry Pi 영상에서 배경·조명·작은 bbox로 인한 domain-shift false positive를 확인했기 때문에, 다음 개선 우선순위는 **공항·야외 hard-negative mining → field fine-tuning → 거리·bbox 크기별 검출률 평가**다.

---

## 5. Stage 2 — ResNet-18 Classification

Classes/groups:

```text
crow · duck · egret · gull · pigeon · raptor · sparrow · swallow
```

`raptor`는 단일 생물학적 종이 아니라 조류군이므로 **8-class bird classification / 8개 조류군 분류**라고 표현한다.

### Aggregate Metrics

| Metric | Result |
|---|---:|
| Test Accuracy | **94.76%** |
| Test Macro-F1 | **94.56%** |
| Best Validation Accuracy | **95.52%** |
| Best Validation Macro-F1 | **95.20%** |
| Best Epoch | **7** |

<p align="center"><img src="../results/resnet/confusion_matrix.png" alt="ResNet-18 final confusion matrix" width="760"></p>

### Class-wise F1 Summary

| Class / Group | F1-score |
|---|---:|
| crow | 95.08% |
| duck | 94.93% |
| egret | 96.06% |
| gull | 94.72% |
| pigeon | 94.65% |
| raptor | 90.97% |
| sparrow | 97.33% |
| swallow | 92.77% |

전체 class별 Precision·Recall·Support는 [AI_RESULTS.md](AI_RESULTS.md)에 정리되어 있다.

---

## 6. Runtime Quality Gate & Temporal Voting

| Gate | Value | Function |
|---|---:|---|
| Minimum crop side | 48 px | 지나치게 작은 crop 차단 |
| Top-1 confidence | ≥ 0.70 | 저신뢰 예측 차단 |
| Top1–Top2 margin | ≥ 0.15 | class ambiguity 차단 |
| Vote window | recent 7 | frame-level noise 완화 |
| Stable requirement | 5 votes | track-level label 확정 |
| Stale reset | 1.2 s | 오래된 vote 제거 |
| Gate failure | `UNKNOWN` | 3D tracking 연속성 유지 |

ResNet raw prediction을 바로 위험도 입력으로 사용하지 않고, crop quality와 confidence gate를 통과한 결과를 track-level voting으로 안정화한다.

---

## 7. Explainable Risk Assessment

PPT의 개념식은 DistanceRisk, HeightRisk, ApproachSpeed, SpeciesRisk, GroupRisk를 결합하는 형태다. 현재 공개 Runtime은 다음 가중합을 사용한다.

```text
score = 30 × DistanceRisk
      + 20 × ApproachState
      + 10 × RelativeAltitude
      + 15 × SpeciesPriority
      + 10 × TrackState
      + 15 × FusionThreat
```

| Score | Risk Level |
|---:|---|
| 0–29 | LOW |
| 30–54 | MEDIUM |
| 55–74 | HIGH |
| 75–100 | CRITICAL |

현재 species-priority example:

```text
raptor 1.00 · gull 0.90 · crow/pigeon 0.78 · duck 0.72
· egret 0.68 · swallow 0.58 · sparrow 0.52 · UNKNOWN 0.35
```

PPT의 generic equation에 있는 별도 `GroupRisk` 항은 현재 public release 코드에서 독립적인 군집 수 feature로 노출되지 않는다. Runtime은 species/group identity, track state, Fusion threat evidence를 결합한다.

---

## 8. AI Decision Console

Console input:

- live bird crop
- raw / stable class prediction
- confidence, margin, vote
- X / Y / Z, forward range
- relative altitude signal
- approaching / crossing / leaving
- Fusion threat and track status

Console output:

- Risk Score 0–100
- LOW / MEDIUM / HIGH / CRITICAL
- Recommended Response

| Pigeon Result | Crow Result |
|---|---|
| ![](../assets/ai_console/pigeon_result.png) | ![](../assets/ai_console/crow_result.png) |

Decision Engine은 airport-certified autonomous controller가 아니라 **prototype decision-support layer**이며, operator supervision과 exhibition safety rule을 전제로 한다.

---

## 9. Evidence & Reproducibility

- 상세 AI 표·그래프: [AI_RESULTS.md](AI_RESULTS.md)
- 최종 raw result index: [`results/README.md`](../results/README.md)
- Dataset 문서: [DATASET.md](DATASET.md)
- 정량 표기 원칙: [METRICS.md](METRICS.md)
- 역할 및 산출물: [`TEAM.md`](../TEAM.md)
