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


def summarize_roi(gray, bounds, pixel_spacing_mm=None):
    mean_brightness, counts = analyze_roi(gray, bounds)
    pixel_count = int(counts.sum())
    area_mm2 = None
    if pixel_spacing_mm is not None:
        row_mm, col_mm = pixel_spacing_mm
        area_mm2 = pixel_count * row_mm * col_mm

    x0, x1, y0, y1 = bounds
    roi = {
        "bounds": {"x0": x0, "x1": x1, "y0": y0, "y1": y1},
        "mean_brightness": mean_brightness,
        "pixel_count": pixel_count,
        "area_mm2": area_mm2,
    }
    return roi, counts


def build_measurement_summary(*, case_id, slice_number, source, ct_slice, image_sha256, measurement):
    area_cm2 = None
    volume_ml = None
    if measurement is not None and source != "uploaded_png":
        area_mm2 = measurement.areas_mm2.get(slice_number)
        if area_mm2 is not None:
            area_cm2 = area_mm2 / 100
        volume_ml = measurement.volume_ml

    return {
        "case_id": case_id,
        "slice_number": slice_number,
        "source": source,
        "series_uid": ct_slice.series_instance_uid if ct_slice else None,
        "sop_uid": ct_slice.sop_instance_uid if ct_slice else None,
        "image_sha256": image_sha256,
        "tumor_area_cm2": area_cm2,
        "tumor_volume_ml": volume_ml,
        "roi": None,
    }
