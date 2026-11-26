from types import SimpleNamespace

import numpy as np
import pytest

from ct_analysis import TumorMeasurement
from roi_analysis import build_measurement_summary, summarize_roi


@pytest.mark.parametrize("spacing, expected_area", [((0.7, 0.8), 2.24), (None, None)])
def test_rectangular_roi_measures_original_display_pixels(spacing, expected_area):
    gray = np.arange(12, dtype=np.uint8).reshape(3, 4)
    roi, counts = summarize_roi(gray, (1, 3, 0, 2), spacing)

    assert roi["bounds"] == {"x0": 1, "x1": 3, "y0": 0, "y1": 2}
    assert roi["pixel_count"] == counts.sum() == 4
    assert roi["mean_brightness"] == 3.5
    assert roi["area_mm2"] == (pytest.approx(expected_area) if spacing else None)


def test_dicom_summary_links_exact_slice_and_keeps_missing_volume():
    ct_slice = SimpleNamespace(series_instance_uid="1.2.3", sop_instance_uid="1.2.3.41")
    summary = build_measurement_summary(
        case_id="case", slice_number=41, source="dicom", ct_slice=ct_slice,
        image_sha256=None, measurement=TumorMeasurement({41: 3190}, None),
    )
    assert (summary["series_uid"], summary["sop_uid"]) == ("1.2.3", "1.2.3.41")
    assert summary["tumor_area_cm2"] == 31.9
    assert summary["tumor_volume_ml"] is None
    assert summary["roi"] is None


@pytest.mark.parametrize(
    "source, number, expected_area, expected_volume",
    [("mock", 41, 31.9, 154.8), ("mock", 42, None, 154.8), ("uploaded_png", 41, None, None)],
)
def test_replacement_png_does_not_inherit_mock_measurements(source, number, expected_area, expected_volume):
    summary = build_measurement_summary(
        case_id="case", slice_number=number, source=source, ct_slice=None,
        image_sha256="image-hash", measurement=TumorMeasurement({41: 3190}, 154.8),
    )
    assert (summary["tumor_area_cm2"], summary["tumor_volume_ml"]) == (expected_area, expected_volume)
    assert summary["image_sha256"] == "image-hash"
    assert summary["sop_uid"] is None
