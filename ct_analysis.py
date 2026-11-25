from collections.abc import Mapping
from dataclasses import dataclass
from math import fsum
from pathlib import Path

import numpy as np

from dicom_ct import CTSlice, render_ct_png


@dataclass(frozen=True, eq=False)
class CTAnalysisSlice:
    slice_no: int
    ct_slice: CTSlice
    tumor_mask: np.ndarray | None

    def display_png(self) -> bytes:
        """Render the original display pixels on the mask's grid when requested."""
        return render_ct_png(self.ct_slice.path)


def build_analysis_slices(
    ct_slices: tuple[CTSlice, ...], masks: Mapping[Path, np.ndarray]
) -> tuple[CTAnalysisSlice, ...]:
    """Pair the ordered CT slices with masks verified by the SEG loader."""
    return tuple(
        CTAnalysisSlice(slice_no, ct_slice, masks.get(ct_slice.path))
        for slice_no, ct_slice in enumerate(ct_slices, 1)
    )


@dataclass(frozen=True)
class TumorMeasurement:
    areas_mm2: dict[int, float]
    volume_ml: float | None
    volume_error: str | None = None


def measure_tumor(slices: tuple[CTAnalysisSlice, ...]) -> TumorMeasurement | None:
    """Measure aligned masks using the CT's pixel and slice spacing."""
    areas_mm2 = {}
    for item in slices:
        if item.tumor_mask is None:
            continue
        pixel_count = int(np.count_nonzero(item.tumor_mask))
        if pixel_count:
            row_mm, col_mm = item.ct_slice.pixel_spacing_mm
            areas_mm2[item.slice_no] = pixel_count * row_mm * col_mm

    if not areas_mm2:
        return None
    if len(slices) < 2:
        return TumorMeasurement(
            areas_mm2, None, "부피를 계산하려면 CT 단면이 두 장 이상 필요해요."
        )

    gaps_mm = np.diff([item.ct_slice.position_mm for item in slices])
    gap_mm = float(np.median(gaps_mm))
    if (
        not np.isfinite(gap_mm)
        or np.any(gaps_mm <= 0)
        or not np.allclose(gaps_mm, gap_mm, atol=1e-3, rtol=0)
    ):
        return TumorMeasurement(
            areas_mm2, None, "CT 단면 간격이 일정하지 않아 부피를 계산할 수 없어요."
        )

    volume_ml = fsum(areas_mm2.values()) * gap_mm / 1000
    return TumorMeasurement(areas_mm2, volume_ml)
