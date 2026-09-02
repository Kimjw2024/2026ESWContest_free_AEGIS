# Models

| 역할 | 파일 | 비고 |
|---|---|---|
| Live detector | `detector/yolo/yolo26n.pt` | COCO bird class 14 기반 안정 Runtime |
| Live classifier | `classifier/resnet/aegis_bird_resnet18_v2.pt` | 8-class bird classification |
| Research detector | `research/aegis_bird_yolov8s_best.pt` | 자체학습 Held-Out Offline Test 모델 |

ResNet-18: Test Accuracy **94.76%**, Macro-F1 **94.56%**  
Custom YOLOv8s: Precision **96.4%**, Recall **93.5%**, mAP@0.5 **97.5%**, mAP@0.5:0.95 **70.9%**

Custom YOLO 결과는 현장 실시간 정확도가 아닌 offline held-out 수치입니다. Live Runtime은 YOLO26n을 사용하며, Custom YOLOv8s는 hard-negative mining과 field fine-tuning으로 확장 가능한 팀 학습 연구 모델입니다. Weight는 Git LFS로 관리합니다.
