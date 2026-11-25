import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from ct_analysis import build_analysis_slices, measure_tumor
from dicom_ct import CTSlice


class CTAnalysisTests(unittest.TestCase):
    def make_series(self, positions):
        return tuple(
            CTSlice(
                path=Path(f"slice-{number}.dcm"),
                sop_instance_uid=f"1.2.3.{number}",
                position_mm=position,
                pixel_spacing_mm=(1.0, 2.0),
                series_instance_uid="1.2.3",
                frame_of_reference_uid="1.2.4",
                image_position_patient=(0.0, 0.0, position),
                image_orientation_patient=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                shape=(8, 8),
            )
            for number, position in enumerate(positions, 1)
        )

    def make_mask(self, pixel_count):
        mask = np.zeros((8, 8), dtype=bool)
        mask.flat[:pixel_count] = True
        return mask

    def test_handoff_preserves_order_mask_and_display_source(self):
        ct_slices = self.make_series((0.0, 2.5, 5.0))
        mask = self.make_mask(32)

        with patch("ct_analysis.render_ct_png", return_value=b"display png") as render:
            slices = build_analysis_slices(ct_slices, {ct_slices[1].path: mask})
            render.assert_not_called()
            self.assertEqual([item.slice_no for item in slices], [1, 2, 3])
            self.assertIs(slices[1].ct_slice, ct_slices[1])
            self.assertIs(slices[1].tumor_mask, mask)
            self.assertIsNone(slices[0].tumor_mask)
            self.assertEqual(slices[1].display_png(), b"display png")
            render.assert_called_once_with(ct_slices[1].path)

    def test_area_and_volume_use_pixel_spacing_and_all_ct_positions(self):
        ct_slices = self.make_series((0.0, 2.5, 5.0))
        masks = {ct_slices[0].path: self.make_mask(32), ct_slices[2].path: self.make_mask(24)}

        measurement = measure_tumor(build_analysis_slices(ct_slices, masks))

        self.assertEqual(measurement.areas_mm2, {1: 64.0, 3: 48.0})
        self.assertAlmostEqual(measurement.volume_ml, 0.28)
        self.assertIsNone(measurement.volume_error)

    def test_area_is_available_when_volume_spacing_cannot_be_verified(self):
        for positions in ((0.0,), (0.0, 2.5, 7.5)):
            with self.subTest(positions=positions):
                ct_slices = self.make_series(positions)
                masks = {ct_slices[0].path: self.make_mask(32)}

                measurement = measure_tumor(build_analysis_slices(ct_slices, masks))

                self.assertEqual(measurement.areas_mm2, {1: 64.0})
                self.assertIsNone(measurement.volume_ml)
                self.assertTrue(measurement.volume_error)

    def test_empty_mask_has_no_measurement(self):
        ct_slices = self.make_series((0.0, 2.5))
        masks = {ct_slices[0].path: self.make_mask(0)}

        self.assertIsNone(measure_tumor(build_analysis_slices(ct_slices, masks)))
