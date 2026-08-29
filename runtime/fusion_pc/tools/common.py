# -*- coding: utf-8 -*-
import os

import cv2
import numpy as np

# 10 x 7 printed checkerboard squares -> 9 x 6 inner corners.
CHECKERBOARD = (9, 6)

# Default square size in meters. Use --square-size-mm with the measured print size.
SQUARE_SIZE = 0.018


def get_objp():
    objp = np.zeros((CHECKERBOARD[0] * CHECKERBOARD[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:CHECKERBOARD[0], 0:CHECKERBOARD[1]].T.reshape(-1, 2) * SQUARE_SIZE
    return objp


def imread_unicode(path, flags=cv2.IMREAD_COLOR):
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite_unicode(path, image, params=None):
    ext = os.path.splitext(path)[1] or ".png"
    ok, encoded = cv2.imencode(ext, image, params or [])
    if not ok:
        return False
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    try:
        encoded.tofile(path)
    except OSError:
        return False
    return os.path.exists(path) and os.path.getsize(path) > 0

def _calib_flag(name, default=0):
    return int(getattr(cv2, name, default))


def find_checkerboard_corners(image, pattern_size=None, robust=True):
    """Robust checkerboard detector shared by capture and calibration scripts."""
    pattern = pattern_size or CHECKERBOARD
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    gray = np.ascontiguousarray(gray)

    base_flags = _calib_flag("CALIB_CB_ACCURACY")
    sb_flag_sets = [base_flags]
    if robust:
        sb_flag_sets.extend([
            base_flags | _calib_flag("CALIB_CB_NORMALIZE_IMAGE"),
            base_flags | _calib_flag("CALIB_CB_NORMALIZE_IMAGE") | _calib_flag("CALIB_CB_EXHAUSTIVE"),
        ])
    for flags in sb_flag_sets:
        found, corners = cv2.findChessboardCornersSB(gray, pattern, flags)
        if found:
            return True, corners

    if not robust:
        return False, None

    eq = cv2.equalizeHist(gray)
    for flags in sb_flag_sets[1:]:
        found, corners = cv2.findChessboardCornersSB(eq, pattern, flags)
        if found:
            return True, corners

    h, w = gray.shape[:2]
    if max(w, h) >= 1000:
        scale = 0.5
        small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        for flags in sb_flag_sets:
            found, corners = cv2.findChessboardCornersSB(small, pattern, flags)
            if found:
                return True, corners.astype(np.float32) / scale

    classic_flags = _calib_flag("CALIB_CB_ADAPTIVE_THRESH") | _calib_flag("CALIB_CB_NORMALIZE_IMAGE")
    found, corners = cv2.findChessboardCorners(gray, pattern, classic_flags)
    if found:
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.001)
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        return True, corners

    return False, None
