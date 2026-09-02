# Safety, Claims and Limitations

## Claim Boundaries

- Custom YOLOv8s **mAP@0.5 97.5%** is a Held-Out Offline Test result, not live airport accuracy.
- The stable live detector is YOLO26n COCO bird class 14; Custom YOLOv8s is presented separately as the team-trained Held-Out Offline Test model.
- ResNet output represents 8 classes/groups; `raptor` is not a single species.
- The Y coordinate is a **relative altitude signal**, not absolute sea-level altitude.
- Risk output is an explainable decision-support score, not an airport-certified biological hazard model.
- RC-Car is a **Mobile Acoustic Response Extension Prototype**, not a completed autonomous dispatch platform.

## Physical Safety

- Laser output must follow venue rules and must never be aimed at people, vehicles or aircraft.
- Servo motion limits and zero trims must be validated before a public demonstration.
- The operator must retain a hardware power-off path.
- Recalibration is required after moving the camera rig or changing baselines.

## Future Work

- airport/field hard-negative mining
- long-range and low-light camera modules
- rain/fog/night validation
- absolute-world coordinate reference
- ornithology and airport-operation data for species-risk weights
- distributed fixed/mobile response endpoints
