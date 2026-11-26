import numpy as np


def analyze_roi(gray, bounds):
    x0, x1, y0, y1 = bounds
    roi = gray[y0:y1, x0:x1]

    mean_brightness = float(roi.mean())
    counts = np.bincount(roi.ravel(), minlength=256)
    return mean_brightness, counts
