import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from dicom_ct import DicomReadError, load_ct_series, render_ct_png, render_ct_preview_sheet


class DicomCTTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.series_uid = generate_uid()

    def write_slice(
        self, filename, position, *, series_uid=None, pixels=None, photometric="MONOCHROME2"
    ):
        path = self.directory / filename
        if pixels is None:
            pixels = [[0, 175], [50, 100]]
        pixels = np.array(pixels, dtype="<i2")
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        uid = generate_uid()
        ds = FileDataset(path, {}, file_meta=meta, preamble=bytes(128))
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = uid
        ds.SeriesInstanceUID = series_uid or self.series_uid
        ds.Modality = "CT"
        ds.ImageOrientationPatient = [0, 1, 0, 0, 0, 1]
        ds.ImagePositionPatient = [position, 0, 0]
        ds.PixelSpacing = [0.625, 0.625]
        ds.Rows, ds.Columns = pixels.shape
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = photometric
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 1
        ds.RescaleSlope = 2
        ds.RescaleIntercept = -125
        ds.PixelData = pixels.tobytes()
        ds.save_as(path, enforce_file_format=True)
        return path

    def test_orders_slices_by_orientation_and_position(self):
        last = self.write_slice("001.dcm", 5)
        middle = self.write_slice("002.dcm", 2.5)
        first = self.write_slice("003.dcm", 0)

        slices = load_ct_series(self.directory, expected_series_uid=self.series_uid)

        self.assertEqual([item.path for item in slices], [first, middle, last])
        self.assertEqual([item.position_mm for item in slices], [0, 2.5, 5])
        self.assertEqual(slices[0].pixel_spacing_mm, (0.625, 0.625))

    def test_rejects_slice_from_another_series(self):
        self.write_slice("001.dcm", 0)
        self.write_slice("002.dcm", 2.5, series_uid=generate_uid())

        with self.assertRaisesRegex(DicomReadError, "선택한 CT 시리즈"):
            load_ct_series(self.directory, expected_series_uid=self.series_uid)

    def test_rejects_duplicate_positions(self):
        self.write_slice("001.dcm", 0)
        self.write_slice("002.dcm", 0)

        with self.assertRaisesRegex(DicomReadError, "같은 위치"):
            load_ct_series(self.directory)

    def test_rejects_file_without_dicom_metadata(self):
        (self.directory / "invalid.dcm").write_bytes(b"invalid DICOM")

        with self.assertRaisesRegex(DicomReadError, "DICOM 정보"):
            load_ct_series(self.directory)

    def test_renders_hu_window_to_png(self):
        path = self.write_slice("001.dcm", 0)

        with Image.open(BytesIO(render_ct_png(path))) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.mode, "L")
            self.assertEqual(np.asarray(image).tolist(), [[0, 255], [72, 145]])

    def test_monochrome1_inverts_the_windowed_pixels(self):
        path = self.write_slice("001.dcm", 0, photometric="MONOCHROME1")
        with Image.open(BytesIO(render_ct_png(path))) as image:
            self.assertEqual(np.asarray(image).tolist(), [[255, 0], [183, 110]])

    def test_preview_sheet_follows_slice_order_across_rows(self):
        dark = self.write_slice("001.dcm", 0, pixels=[[0, 0], [0, 0]])
        bright = self.write_slice("002.dcm", 2.5, pixels=[[175, 175], [175, 175]])
        paths = (bright,) + (dark,) * 7 + (bright,)

        with Image.open(BytesIO(render_ct_preview_sheet(paths, tile_size=32))) as sheet:
            self.assertEqual(sheet.size, (256, 64))
            self.assertEqual(sheet.getpixel((16, 16)), 255)
            self.assertEqual(sheet.getpixel((48, 16)), 0)
            self.assertEqual(sheet.getpixel((16, 48)), 255)
