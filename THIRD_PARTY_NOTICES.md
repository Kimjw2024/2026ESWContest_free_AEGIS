# Third-Party Software & Model Notices

AEGIS uses third-party open-source software. Each component remains governed by its own license; this file is an attribution/compliance index and does not replace the original license text.

## Runtime dependencies

| Component | Use in AEGIS | Upstream license / note |
|---|---|---|
| Python | Runtime / training | Python Software Foundation License |
| OpenCV (`opencv-python`) | Image processing, calibration, stereo vision | OpenCV 4.5+ is Apache-2.0 |
| NumPy | Numerical computing | BSD-3-Clause (main project; distributed wheels may include additional notices) |
| SciPy | Optimization / numerical routines | BSD-3-Clause |
| PyTorch / torchvision | ResNet-18 training and inference | PyTorch main project BSD-3-Clause; packaged dependencies may include additional notices |
| PyZMQ | ZeroMQ Python bindings | BSD-3-Clause; packaged libzmq may carry its own license |
| pySerial | Arduino serial communication | BSD-3-Clause |
| PySide6 / Qt for Python | AI Decision Console UI | LGPLv3 / GPLv3 / Qt commercial options, depending on use and distribution |
| Ultralytics | YOLO runtime/training API and model workflow | Ultralytics provides AGPL-3.0 and Enterprise licensing options; the open-source path is AGPL-3.0 |

## Ultralytics / YOLO note

AEGIS uses Ultralytics tooling and YOLO model artifacts. The public competition repository therefore preserves source-level transparency and separates:

- live detector integration (`YOLO26n` bird detection),
- custom YOLOv8s research training/evaluation,
- AEGIS-owned 3D Fusion, tracking, decision and response logic.

Before redistributing the project outside the competition/research context or using it commercially, the team must re-check the then-current Ultralytics licensing terms and the provenance/license of every redistributed model weight.

## AEGIS-owned material

Unless a file states otherwise, AEGIS-specific source, calibration procedures, system integration code, experiment documentation and project media were produced by Team AEGIS. Third-party libraries and model artifacts are not claimed as Team AEGIS intellectual property.

## Competition compliance

The competition rules require participants to respect licenses of any included open-source software. This repository therefore keeps dependency names explicit and avoids presenting third-party frameworks/models as self-developed work.

For exact legal terms, consult each upstream project's original LICENSE and documentation. This notice is technical attribution, not legal advice.
