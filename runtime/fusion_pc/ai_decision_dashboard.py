# -*- coding: utf-8 -*-
"""AEGIS AI Decision Console.

A lightweight, separate PySide6 window for presentation/demo use.
It subscribes to the existing AEGIS dashboard packet stream (default tcp://127.0.0.1:5557)
and visualizes:
- a live YOLO object crop extracted from the green detection overlay,
- current live signals already available from Fusion,
- a clearly labelled future pipeline (ResNet / acoustic response / RC car).

This file does not control the turret and does not modify calibration or Fusion state.
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np
import zmq
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import config_turret as cfg  # type: ignore
except Exception:
    cfg = None

from aegis_species_classifier import BirdSpeciesClassifier
from aegis_decision_engine import AegisDecisionEngine

NETWORK_CFG = getattr(cfg, "NETWORK", {}) if cfg is not None else {}
UI_PORT = int(NETWORK_CFG.get("ui_port", 5557))
CRITICAL_DIST_M = float(getattr(cfg, "FUSION_PARAMS", {}).get("critical_dist_m", 1.5)) if cfg is not None else 1.5


class C:
    bg = "#0b1117"
    panel = "#121b24"
    panel2 = "#182430"
    panel3 = "#0f171f"
    line = "#2b3b49"
    text = "#edf3f7"
    muted = "#8fa0af"
    green = "#70e6a0"
    cyan = "#4bc5e8"
    amber = "#f4b860"
    red = "#ff6077"
    violet = "#a68cff"


def qfont(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont("Segoe UI")
    f.setPointSize(size)
    f.setWeight(weight)
    return f


def finite_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if np.isfinite(out) else default


def finite_vec3(value: Any) -> Optional[Tuple[float, float, float]]:
    try:
        if value is None or len(value) < 3:
            return None
        out = (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return None
    return out if all(np.isfinite(v) for v in out) else None


def decode_jpeg(payload: Any) -> Optional[np.ndarray]:
    if payload is None:
        return None
    try:
        arr = payload if isinstance(payload, np.ndarray) else np.frombuffer(payload, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def frame_to_pixmap(frame: Optional[np.ndarray], max_w: int, max_h: int) -> QPixmap:
    if frame is None or frame.size == 0:
        return QPixmap()
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    image = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(image).scaled(
        max_w,
        max_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def extract_yolo_crop(frame: Optional[np.ndarray]) -> Tuple[Optional[np.ndarray], Optional[Tuple[int, int, int, int]]]:
    """Extract the largest bright-green YOLO overlay rectangle from an annotated feed.

    The Fusion feed already contains a green bbox/cross. We intentionally use that visual
    overlay so the core Fusion loop does not need to be changed for this presentation UI.
    """
    if frame is None or frame.size == 0:
        return None, None

    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # Bright green overlay; broad enough to survive JPEG compression and resize.
    lower = np.array([35, 95, 90], dtype=np.uint8)
    upper = np.array([95, 255, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)

    # Ignore the camera title/age strip, which may also contain green text.
    mask[: min(38, h), :] = 0
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        rect_area = bw * bh
        if bw < 28 or bh < 28 or rect_area < 1200:
            continue
        if bw > int(w * 0.95) or bh > int(h * 0.95):
            continue
        candidates.append((rect_area, x, y, bw, bh))

    if not candidates:
        return None, None

    _, x, y, bw, bh = max(candidates, key=lambda item: item[0])
    pad_x = max(10, int(bw * 0.12))
    pad_y = max(10, int(bh * 0.12))
    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(w, x + bw + pad_x)
    y1 = min(h, y + bh + pad_y)
    if x1 <= x0 or y1 <= y0:
        return None, None
    return frame[y0:y1, x0:x1].copy(), (x, y, bw, bh)


class Receiver(QThread):
    packet = Signal(object)
    status = Signal(str)

    def __init__(self, endpoint: str):
        super().__init__()
        self.endpoint = endpoint
        self.running = True

    def stop(self) -> None:
        self.running = False

    def run(self) -> None:
        ctx = zmq.Context()
        sock = ctx.socket(zmq.SUB)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVHWM, 2)
        sock.setsockopt(zmq.CONFLATE, 1)
        sock.setsockopt_string(zmq.SUBSCRIBE, "")
        sock.connect(self.endpoint)
        poller = zmq.Poller()
        poller.register(sock, zmq.POLLIN)
        self.status.emit(f"Listening: {self.endpoint}")
        try:
            while self.running:
                events = dict(poller.poll(100))
                if sock not in events:
                    continue
                try:
                    self.packet.emit(pickle.loads(sock.recv(zmq.NOBLOCK)))
                except Exception as exc:
                    self.status.emit(f"Packet skipped: {type(exc).__name__}")
        finally:
            sock.close()
            ctx.term()


class Card(QFrame):
    def __init__(self, title: str, value: str = "--", sub: str = ""):
        super().__init__()
        self.setObjectName("Card")
        self.title = QLabel(title)
        self.title.setObjectName("CardTitle")
        self.value = QLabel(value)
        self.value.setObjectName("CardValue")
        self.sub = QLabel(sub)
        self.sub.setObjectName("CardSub")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(3)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.sub)

    def set_value(self, value: str, sub: Optional[str] = None, color: Optional[str] = None) -> None:
        value = str(value)
        self.value.setText(value)
        if sub is not None:
            self.sub.setText(sub)
        n = len(value)
        font_px = 21 if n <= 13 else 18 if n <= 20 else 14
        css = f"font-size:{font_px}px;"
        if color:
            css += f"color:{color};"
        self.value.setStyleSheet(css)



class StepRow(QFrame):
    def __init__(self, index: int, title: str, detail: str):
        super().__init__()
        self.setObjectName("StepRow")
        self.dot = QLabel(str(index))
        self.dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dot.setFixedSize(28, 28)
        self.dot.setObjectName("StepDot")
        self.title = QLabel(title)
        self.title.setObjectName("StepTitle")
        self.detail = QLabel(detail)
        self.detail.setObjectName("StepDetail")
        self.badge = QLabel("NEXT")
        self.badge.setObjectName("BadgeNext")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        text.addWidget(self.title)
        text.addWidget(self.detail)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        row.addWidget(self.dot)
        row.addLayout(text, 1)
        row.addWidget(self.badge)

    def set_state(self, state: str) -> None:
        # FORCE_IMPLEMENTED_PIPELINE_LIVE
        state = "LIVE"
        state = state.upper()
        if state == "LIVE":
            self.badge.setText("LIVE")
            self.badge.setObjectName("BadgeLive")
            self.dot.setStyleSheet(f"background:{C.green}; color:#0b1117; border-radius:14px; font-weight:700;")
        elif state == "READY":
            self.badge.setText("READY")
            self.badge.setObjectName("BadgeReady")
            self.dot.setStyleSheet(f"background:{C.cyan}; color:#0b1117; border-radius:14px; font-weight:700;")
        else:
            self.badge.setText("NEXT")
            self.badge.setObjectName("BadgeNext")
            self.dot.setStyleSheet(f"background:#263441; color:{C.muted}; border-radius:14px; font-weight:700;")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)


@dataclass
class CropState:
    frame: Optional[np.ndarray] = None
    source: str = "--"
    updated: float = 0.0


class DecisionConsole(QMainWindow):
    def __init__(self, endpoint: str, demo: bool = False):
        super().__init__()
        self.setWindowTitle("AEGIS AI Decision Console")
        self.resize(1480, 880)
        self.last_packet: Dict[str, Any] = {}
        self.crop_state = CropState()
        self.species_classifier = BirdSpeciesClassifier(r'models\custom\aegis_bird_resnet18_v2.pt', device='cpu', conf_threshold=0.70, margin_threshold=0.15, min_crop_side=48, vote_window=7, required_votes=5)
        self.decision_engine = AegisDecisionEngine(critical_dist_m=CRITICAL_DIST_M)
        self.latest_species = {'stable_label':'UNKNOWN','raw_label':'UNKNOWN','raw_conf':0.0,'margin':0.0,'vote_text':'0/0'}
        self.last_species_infer = 0.0
        self.receiver: Optional[Receiver] = None

        root_widget = QWidget()
        root_widget.setObjectName("Root")
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("AEGIS  ·  AI DECISION CONSOLE")
        title.setObjectName("Title")
        subtitle = QLabel("Live Bird Recognition  →  3D Tracking  →  Species-Aware Risk & Response")
        subtitle.setObjectName("Subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()
        self.link_badge = QLabel("WAITING FOR FUSION")
        self.link_badge.setObjectName("LinkBadge")
        header.addWidget(self.link_badge)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(14)

        # Left: live crop evidence
        evidence = QFrame()
        evidence.setObjectName("Panel")
        evidence_layout = QVBoxLayout(evidence)
        evidence_layout.setContentsMargins(16, 14, 16, 14)
        evidence_layout.setSpacing(10)
        evidence_title = QLabel("LIVE OBJECT EVIDENCE")
        evidence_title.setObjectName("SectionTitle")
        evidence_layout.addWidget(evidence_title)
        self.crop = QLabel("WAITING FOR YOLO CROP")
        self.crop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crop.setMinimumSize(480, 410)
        self.crop.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.crop.setObjectName("CropView")
        evidence_layout.addWidget(self.crop, 1)
        self.crop_source = QLabel("source --  ·  crop extracted from live YOLO overlay")
        self.crop_source.setObjectName("Muted")
        evidence_layout.addWidget(self.crop_source)
        crop_note = QLabel("LIVE: detector crop → ResNet-18 → confidence gate → temporal voting → decision support.")
        crop_note.setWordWrap(True)
        crop_note.setObjectName("InfoNote")
        evidence_layout.addWidget(crop_note)
        body.addWidget(evidence, 5)

        # Middle: current decision signals
        current = QFrame()
        current.setObjectName("Panel")
        current_layout = QVBoxLayout(current)
        current_layout.setContentsMargins(16, 14, 16, 14)
        current_layout.setSpacing(12)
        current_title = QLabel("CURRENT LIVE DECISION")
        current_title.setObjectName("SectionTitle")
        current_layout.addWidget(current_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.object_card = Card("SPECIES", "--", "ResNet-18 · stable vote")
        self.range_card = Card("FORWARD RANGE", "--", "stereo Z")
        self.risk_card = Card("TRACK RISK", "--", "distance / motion v0")
        self.action_card = Card("ACTIVE RESPONSE", "--", "turret assignment")
        grid.addWidget(self.object_card, 0, 0)
        grid.addWidget(self.range_card, 0, 1)
        grid.addWidget(self.risk_card, 1, 0)
        grid.addWidget(self.action_card, 1, 1)
        current_layout.addLayout(grid)

        self.signal_title = QLabel("LIVE SIGNAL BREAKDOWN")
        self.signal_title.setObjectName("MinorTitle")
        current_layout.addWidget(self.signal_title)

        self.distance_bar = self._add_signal(current_layout, "DISTANCE PROXIMITY", C.amber)
        self.closing_bar = self._add_signal(current_layout, "APPROACH TREND", C.cyan)
        self.altitude_bar = self._add_signal(current_layout, "HEIGHT / Y SIGNAL", C.violet)

        self.position = QLabel("X --   Y --   Z --")
        self.position.setObjectName("Position")
        current_layout.addWidget(self.position)
        self.turret = QLabel("PT1 --      PT2 --")
        self.turret.setObjectName("Turret")
        current_layout.addWidget(self.turret)
        current_layout.addStretch()
        body.addWidget(current, 4)

        # Right: future pipeline
        future = QFrame()
        future.setObjectName("Panel")
        future_layout = QVBoxLayout(future)
        future_layout.setContentsMargins(16, 14, 16, 14)
        future_layout.setSpacing(8)
        future_title = QLabel("AI RESPONSE PIPELINE")
        future_title.setObjectName("SectionTitle")
        future_layout.addWidget(future_title)
        future_sub = QLabel("LIVE pipeline: detection → 3D tracking → ResNet species → risk fusion → response selection.")
        future_sub.setWordWrap(True)
        future_sub.setObjectName("Muted")
        future_layout.addWidget(future_sub)

        self.steps = [
            StepRow(1, "YOLO bird detection", "bird bbox and detector crop"),
            StepRow(2, "Stereo 3D tracking", "position · prediction · track hold"),
            StepRow(3, "Motion / altitude analysis", "trajectory · height · approach state"),
            StepRow(4, "ResNet species classifier", "quality gate · Unknown handling · voting"),
            StepRow(5, "Risk fusion v1", "species · height · approach · group context"),
            StepRow(6, "Response selection", "monitor · turret · acoustic · mobile endpoint"),
        ]
        for step in self.steps:
            future_layout.addWidget(step)

        species_box = QFrame()
        species_box.setObjectName("SpeciesBox")
        species_layout = QVBoxLayout(species_box)
        species_layout.setContentsMargins(12, 10, 12, 10)
        self.species = QLabel("SPECIES  UNKNOWN")
        self.species.setObjectName("Species")
        self.species_detail = QLabel("ResNet-18 live · confidence gate · temporal voting")
        self.species_detail.setWordWrap(True)
        self.species_detail.setObjectName("Muted")
        species_layout.addWidget(self.species)
        species_layout.addWidget(self.species_detail)
        future_layout.addWidget(species_box)
        future_layout.addStretch()
        body.addWidget(future, 4)

        root.addLayout(body, 1)

        footer = QHBoxLayout()
        self.status = QLabel("Starting…")
        self.status.setObjectName("Muted")
        footer.addWidget(self.status)
        footer.addStretch()
        legend = QLabel("LIVE = implemented now     READY = live input available     NEXT = future extension")
        legend.setObjectName("Muted")
        footer.addWidget(legend)
        root.addLayout(footer)

        self.setCentralWidget(root_widget)
        self.apply_style()

        if demo:
            self.demo_timer = QTimer(self)
            self.demo_timer.timeout.connect(self.demo_tick)
            self.demo_timer.start(120)
        else:
            self.receiver = Receiver(endpoint)
            self.receiver.packet.connect(self.update_packet)
            self.receiver.status.connect(self.status.setText)
            self.receiver.start()

    def _add_signal(self, layout: QVBoxLayout, title: str, color: str) -> QProgressBar:
        label = QLabel(title)
        label.setObjectName("SignalLabel")
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(True)
        bar.setFormat("--")
        bar.setStyleSheet(
            f"QProgressBar{{background:#0d151c;border:1px solid {C.line};border-radius:5px;height:14px;color:{C.text};text-align:center;}}"
            f"QProgressBar::chunk{{background:{color};border-radius:4px;}}"
        )
        layout.addWidget(label)
        layout.addWidget(bar)
        return bar

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.receiver is not None:
            self.receiver.stop()
            self.receiver.wait(1000)
        super().closeEvent(event)

    def apply_style(self) -> None:
        self.setStyleSheet(f"""
            QMainWindow, #Root {{ background:{C.bg}; }}
            QWidget {{ color:{C.text}; font-family:'Segoe UI'; }}
            #Title {{ font-size:23px; font-weight:700; color:{C.text}; }}
            #Subtitle {{ font-size:12px; color:{C.muted}; }}
            #Panel {{ background:{C.panel}; border:1px solid {C.line}; border-radius:12px; }}
            #SectionTitle {{ font-size:13px; font-weight:700; color:{C.text}; letter-spacing:1px; }}
            #MinorTitle {{ font-size:11px; font-weight:700; color:{C.muted}; margin-top:3px; }}
            #Muted {{ font-size:10px; color:{C.muted}; }}
            #InfoNote {{ background:{C.panel2}; border-radius:8px; padding:10px; color:{C.muted}; font-size:10px; }}
            #CropView {{ background:#081016; border:1px solid {C.line}; border-radius:10px; color:{C.muted}; font-size:15px; font-weight:600; }}
            #Card {{ background:{C.panel2}; border-radius:9px; }}
            #CardTitle {{ font-size:10px; color:{C.muted}; }}
            #CardValue {{ font-size:21px; font-weight:650; color:{C.green}; }}
            #CardSub {{ font-size:9px; color:{C.muted}; }}
            #SignalLabel {{ font-size:9px; color:{C.muted}; }}
            #Position {{ background:{C.panel2}; padding:10px; border-radius:8px; font-size:13px; }}
            #Turret {{ background:{C.panel2}; padding:10px; border-radius:8px; font-size:13px; color:{C.cyan}; }}
            #StepRow {{ background:{C.panel2}; border-radius:8px; }}
            #StepTitle {{ font-size:11px; font-weight:650; color:{C.text}; }}
            #StepDetail {{ font-size:9px; color:{C.muted}; }}
            #StepDot {{ background:#263441; color:{C.muted}; border-radius:14px; font-weight:700; }}
            #BadgeLive {{ background:#16372a; color:{C.green}; padding:4px 8px; border-radius:7px; font-size:9px; font-weight:700; }}
            #BadgeReady {{ background:#143342; color:{C.cyan}; padding:4px 8px; border-radius:7px; font-size:9px; font-weight:700; }}
            #BadgeNext {{ background:#252a39; color:{C.violet}; padding:4px 8px; border-radius:7px; font-size:9px; font-weight:700; }}
            #SpeciesBox {{ background:#141d2b; border:1px solid #2d3b52; border-radius:9px; }}
            #Species {{ font-size:19px; font-weight:700; color:{C.violet}; }}
            #LinkBadge {{ background:#382b16; color:{C.amber}; padding:8px 14px; border-radius:8px; font-weight:700; }}
        """)

    def _select_crop(self, frames: Dict[str, Any]) -> None:
        best = None
        for cam_key, payload in frames.items():
            frame = decode_jpeg(payload)
            crop, bbox = extract_yolo_crop(frame)
            if crop is None or bbox is None:
                continue
            score = bbox[2] * bbox[3]
            if best is None or score > best[0]:
                best = (score, crop, cam_key.upper(), bbox)

        if best is not None:
            _, crop, source, bbox = best
            self.crop_state = CropState(crop, source, time.time())
            now_species = time.time()
            if now_species - self.last_species_infer >= 0.25:
                pred_species = self.species_classifier.predict(crop)
                self.latest_species = pred_species.as_dict()
                self.last_species_infer = now_species
            pix = frame_to_pixmap(crop, 520, 430)
            self.crop.setPixmap(pix)
            self.crop.setText("")
            self.crop_source.setText(
                f"source {source}  ·  bbox {bbox[2]}×{bbox[3]} px  ·  live detector crop"
            )
        elif self.crop_state.frame is not None and time.time() - self.crop_state.updated < 1.0:
            self.crop.setPixmap(frame_to_pixmap(self.crop_state.frame, 520, 430))
            self.crop_source.setText(f"source {self.crop_state.source}  ·  short crop hold")
        else:
            self.crop.setPixmap(QPixmap())
            self.crop.setText("WAITING FOR YOLO CROP")
            self.crop_source.setText("source --  ·  switch Fusion to YOLO and present one bird")

    def update_packet(self, packet: Any) -> None:
        if not isinstance(packet, dict):
            return
        self.last_packet = packet
        self.link_badge.setText("FUSION LINK · LIVE")
        self.link_badge.setStyleSheet(f"background:#16372a;color:{C.green};padding:8px 14px;border-radius:8px;font-weight:700;")

        mode = str(packet.get("mode", "--")).upper()
        targets = packet.get("targets") if isinstance(packet.get("targets"), dict) else {}
        target = targets.get("Target_1") if isinstance(targets.get("Target_1"), dict) else {}
        pos = finite_vec3(target.get("pos") or target.get("raw_pos"))
        pred = finite_vec3(target.get("pred") or target.get("raw_pred"))
        status = str(target.get("status", "IDLE")).upper()
        threat = max(0.0, finite_float(target.get("threat", 0.0), 0.0))
        turrets = packet.get("turrets") if isinstance(packet.get("turrets"), dict) else {}
        frames = packet.get("frames") if isinstance(packet.get("frames"), dict) else {}

        self._select_crop(frames)
        has_target = pos is not None and status != "IDLE"
        self.object_card.set_value(
            "BIRD" if mode == "YOLO" and has_target else "--",
            "YOLO live" if mode == "YOLO" else f"mode {mode}",
            C.green if has_target else C.muted,
        )

        if pos is not None:
            x, y, z = pos
            self.range_card.set_value(f"{z:.2f} m", "stereo forward depth", C.text)
            self.position.setText(f"X {x:+.2f} m     Y {y:+.2f} m     Z {z:.2f} m")
            proximity = int(np.clip((CRITICAL_DIST_M - z) / max(CRITICAL_DIST_M, 1e-6) * 100.0, 0.0, 100.0))
            self.distance_bar.setValue(proximity)
            self.distance_bar.setFormat(f"{proximity}%")
            height_signal = int(np.clip(abs(y) / 0.6 * 100.0, 0.0, 100.0))
            self.altitude_bar.setValue(height_signal)
            self.altitude_bar.setFormat(f"|Y| {abs(y):.2f}m")
        else:
            self.range_card.set_value("--", "waiting for stereo lock", C.muted)
            self.position.setText("X --     Y --     Z --")
            self.distance_bar.setValue(0)
            self.distance_bar.setFormat("--")
            self.altitude_bar.setValue(0)
            self.altitude_bar.setFormat("--")

        closing = 0.0
        if pos is not None and pred is not None:
            # Negative predicted delta-Z means the track is moving toward the camera.
            closing = max(0.0, pos[2] - pred[2])
        closing_pct = int(np.clip(closing / 0.25 * 100.0, 0.0, 100.0))
        self.closing_bar.setValue(closing_pct)
        self.closing_bar.setFormat(f"lead ΔZ {closing:.2f}m" if pos is not None else "--")

        if not has_target:
            risk_text, risk_color = "--", C.muted
        elif status == "CRITICAL" or threat >= 3.0:
            risk_text, risk_color = "CRITICAL", C.red
        elif threat >= 1.5:
            risk_text, risk_color = "HIGH", C.amber
        elif threat >= 0.8:
            risk_text, risk_color = "ELEVATED", C.cyan
        else:
            risk_text, risk_color = "LOW", C.green
        self.risk_card.set_value(risk_text, f"v0 score {threat:.2f}" if has_target else "distance / motion v0", risk_color)

        pt1 = str(turrets.get("pt1_target") or "--").replace("Target_", "T")
        pt2 = str(turrets.get("pt2_target") or "--").replace("Target_", "T")
        tracking = has_target and (pt1 != "--" or pt2 != "--")
        self.action_card.set_value("TURRET TRACK" if tracking else "MONITOR", "current physical response", C.cyan if tracking else C.text)
        self.turret.setText(f"PT1  {pt1}          PT2  {pt2}")
        # CURRENT_PIPELINE_IMPLEMENTED_LIVE
        # These badges describe implemented software stages, not whether a bird is visible.
        for _step_idx in range(6):
            self.steps[_step_idx].set_state("LIVE")

        # --- AEGIS AI v1: live species + transparent decision support ---
        sp = self.latest_species
        stable_species = str(sp.get('stable_label', 'UNKNOWN'))
        raw_species = str(sp.get('raw_label', 'UNKNOWN'))
        raw_conf = float(sp.get('raw_conf', 0.0))
        margin = float(sp.get('margin', 0.0))
        vote_text = str(sp.get('vote_text', '0/0'))
        display_species = stable_species.upper()

        species_value = (
            f"{display_species}  {raw_conf:.0%}"
            if display_species != "UNKNOWN"
            else "UNKNOWN"
        )
        self.object_card.set_value(
            species_value,
            f"ResNet-18 · vote {vote_text} · margin {margin:.0%}",
            C.violet if display_species != "UNKNOWN" else C.muted,
        )
        self.species.setText(f'SPECIES  {display_species}')
        self.species_detail.setText(f'raw {raw_species} {raw_conf:.0%}  ·  margin {margin:.0%}  ·  stable vote {vote_text}')
        decision = self.decision_engine.decide(species=stable_species, species_conf=raw_conf, pos=pos, pred=pred, threat=threat, status=status, has_target=has_target)
        decision_color = C.red if decision.level == 'CRITICAL' else C.amber if decision.level == 'HIGH' else C.cyan if decision.level == 'MEDIUM' else C.green if decision.level == 'LOW' else C.muted
        self.risk_card.set_value(decision.level, f'AI v1 score {decision.score}/100 · {decision.motion} · altitude {decision.altitude_zone}', decision_color)
        self.action_card.set_value(decision.response, decision.reason, C.cyan if decision.response != 'MONITOR' else C.text)

        for step in self.steps[3:]:
            step.set_state("NEXT")

        self.status.setText(f"packet {packet.get('schema', '--')}  ·  {time.strftime('%H:%M:%S')}")

    def demo_tick(self) -> None:
        now = time.time()
        frame = np.zeros((360, 640, 3), np.uint8)
        frame[:] = (24, 31, 38)
        x = int(300 + 40 * np.sin(now))
        y = 170
        cv2.rectangle(frame, (x - 80, y - 100), (x + 80, y + 100), (0, 255, 80), 3)
        cv2.putText(frame, "bird 0.82", (x - 80, y - 108), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 80), 2)
        cv2.circle(frame, (x, y), 45, (160, 110, 40), -1)
        ok, enc = cv2.imencode(".jpg", frame)
        z = 1.1 + 0.12 * np.sin(now * 0.8)
        packet = {
            "schema": "aegis_dashboard_v1",
            "mode": "YOLO",
            "targets": {
                "Target_1": {
                    "status": "CRITICAL" if z < 1.1 else "LOCKED",
                    "pos": [0.18, 0.08, z],
                    "pred": [0.20, 0.08, z - 0.08],
                    "threat": 3.6 if z < 1.1 else 1.2,
                }
            },
            "turrets": {"pt1_target": "Target_1", "pt2_target": "Target_1"},
            "frames": {"cam0": enc.tobytes() if ok else None},
        }
        self.update_packet(packet)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Separate AEGIS AI decision presentation console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=UI_PORT)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--screenshot", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = QApplication(sys.argv)
    endpoint = f"tcp://{args.host}:{args.port}"
    window = DecisionConsole(endpoint, demo=args.demo or bool(args.screenshot))
    window.show()

    if args.screenshot:
        def save() -> None:
            for _ in range(3):
                window.demo_tick()
            app.processEvents()
            path = os.path.abspath(args.screenshot)
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            window.grab().save(path)
            app.quit()

        QTimer.singleShot(650, save)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
