from math import ceil, floor

import numpy as np


def normalize_roi_bounds(bounds, width, height):
    if bounds is None:
        return None

    x0, x1, y0, y1 = bounds
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))

    left = max(0, left)
    right = min(width, right)
    top = max(0, top)
    bottom = min(height, bottom)

    if left >= right or top >= bottom:
        return None

    return floor(left), ceil(right), floor(top), ceil(bottom)


def analyze_roi(gray, bounds):
    x0, x1, y0, y1 = bounds
    roi = gray[y0:y1, x0:x1]

    mean_brightness = float(roi.mean())
    counts = np.bincount(roi.ravel(), minlength=256)
    return mean_brightness, counts
