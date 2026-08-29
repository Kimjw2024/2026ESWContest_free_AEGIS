# Training & Data Curation

최종 대회 결과를 재현하는 데 필요한 데이터 정제·학습 코드만 남겼습니다.

1. `prepare_aegis_bird_data.py` — 원천 데이터 검증·split·준비
2. `audit_yolo_missing_birds_v2.py` — missing-label / contamination audit
3. `build_clean_yolo_v2.py` — audit 규칙을 적용한 clean detector dataset 생성
4. `inspect_prepared_samples.py` — 학습 전 샘플 시각 검수
5. `train_yolo.py` — custom YOLOv8s detector 학습
6. `train_resnet_v3_stable.py` — 최종 ResNet-18 8-class classifier 학습
7. `audit_rules.json` — 수동 제외·정제 규칙

대용량 원본 이미지는 저장소에 포함하지 않으며, 데이터셋 구성과 수치는 [`../docs/DATASET.md`](../docs/DATASET.md)에 기록합니다.
