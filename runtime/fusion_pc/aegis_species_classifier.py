from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Dict, List, Optional

import cv2
import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torchvision import models, transforms

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

@dataclass
class SpeciesPrediction:
    raw_label: str
    raw_conf: float
    margin: float
    top2_label: str
    top2_conf: float
    accepted: bool
    stable_label: str
    vote_text: str
    def as_dict(self) -> Dict[str, object]:
        return self.__dict__.copy()

class SpeciesVoteTracker:
    def __init__(self, window: int = 7, required_votes: int = 5, stale_sec: float = 1.2):
        self.window = max(1, int(window))
        self.required_votes = max(1, int(required_votes))
        self.stale_sec = float(stale_sec)
        self.votes = deque(maxlen=self.window)
        self.last_update = 0.0
    def reset(self) -> None:
        self.votes.clear(); self.last_update = 0.0
    def update(self, label: str, accepted: bool) -> tuple[str, str]:
        now = time.time()
        if self.last_update and now - self.last_update > self.stale_sec:
            self.votes.clear()
        self.last_update = now
        self.votes.append(label if accepted else 'UNKNOWN')
        valid = [x for x in self.votes if x != 'UNKNOWN']
        if not valid:
            return 'UNKNOWN', f'0/{len(self.votes)}'
        label_best, count = Counter(valid).most_common(1)[0]
        stable = label_best if count >= self.required_votes else 'UNKNOWN'
        return stable, f'{count}/{len(self.votes)}'

class BirdSpeciesClassifier:
    def __init__(self, checkpoint_path: str, device: str = 'cpu', conf_threshold: float = 0.70,
                 margin_threshold: float = 0.15, min_crop_side: int = 48,
                 vote_window: int = 7, required_votes: int = 5):
        self.checkpoint_path = str(Path(checkpoint_path))
        self.device = torch.device(device)
        self.conf_threshold = float(conf_threshold)
        self.margin_threshold = float(margin_threshold)
        self.min_crop_side = int(min_crop_side)
        ckpt = torch.load(self.checkpoint_path, map_location=self.device, weights_only=False)
        self.class_names: List[str] = list(ckpt.get('class_names',
            ['crow','duck','egret','gull','pigeon','raptor','sparrow','swallow']))
        model = models.resnet18(weights=None)
        in_features = model.fc.in_features
        model.fc = nn.Sequential(nn.Dropout(p=0.25), nn.Linear(in_features, len(self.class_names)))
        model.load_state_dict(ckpt['model_state'], strict=True)
        model.to(self.device); model.eval(); self.model = model
        self.eval_tf = transforms.Compose([
            transforms.Resize(256), transforms.CenterCrop(224), transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ])
        self.vote = SpeciesVoteTracker(vote_window, required_votes)

    @torch.inference_mode()
    def predict(self, crop_bgr: Optional[np.ndarray]) -> SpeciesPrediction:
        if crop_bgr is None or crop_bgr.size == 0:
            self.vote.reset()
            return SpeciesPrediction('UNKNOWN',0.0,0.0,'--',0.0,False,'UNKNOWN','0/0')
        h,w = crop_bgr.shape[:2]
        if min(h,w) < self.min_crop_side:
            stable, vote_text = self.vote.update('UNKNOWN', False)
            return SpeciesPrediction('UNKNOWN',0.0,0.0,'--',0.0,False,stable,vote_text)
        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        x = self.eval_tf(Image.fromarray(rgb)).unsqueeze(0).to(self.device)
        probs = torch.softmax(self.model(x), dim=1)[0]
        values, indices = torch.topk(probs, k=min(2, len(self.class_names)))
        top1_conf = float(values[0].item()); top1_label = self.class_names[int(indices[0].item())]
        if len(values) > 1:
            top2_conf = float(values[1].item()); top2_label = self.class_names[int(indices[1].item())]
        else:
            top2_conf, top2_label = 0.0, '--'
        margin = top1_conf - top2_conf
        accepted = top1_conf >= self.conf_threshold and margin >= self.margin_threshold
        stable, vote_text = self.vote.update(top1_label, accepted)
        return SpeciesPrediction(top1_label, top1_conf, margin, top2_label, top2_conf,
                                 accepted, stable, vote_text)
