import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, SegmentationStorage, generate_uid

from dicom_ct import CTSlice, DicomReadError, render_ct_contour_png
from dicom_seg import load_tumor_masks


def item(**attributes):
    dataset = Dataset()
    for name, value in attributes.items():
        setattr(dataset, name, value)
    return dataset


def reference(uid):
    return item(ReferencedSOPClassUID=CTImageStorage, ReferencedSOPInstanceUID=uid)


class DicomSegTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        self.series_uid = generate_uid()
        self.grid_uid = generate_uid()
        self.shape = (8, 8)
        self.path = directory / "seg.dcm"
        self.slices = tuple(
            CTSlice(
                path=directory / f"ct_{number}.dcm",
                sop_instance_uid=generate_uid(),
                position_mm=z,
                pixel_spacing_mm=(0.625, 0.625),
                series_instance_uid=self.series_uid,
                frame_of_reference_uid=self.grid_uid,
                image_position_patient=(0.0, 0.0, z),
                image_orientation_patient=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                shape=self.shape,
            )
            for number, z in enumerate((0.0, 2.5, 5.0), 1)
        )

    def make_seg(self, frames):
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        seg = FileDataset(self.path, {}, file_meta=meta, preamble=bytes(128))
        seg.SOPClassUID = SegmentationStorage
        seg.SOPInstanceUID = generate_uid()
        seg.Modality = "SEG"
        seg.SegmentationType = "BINARY"
        seg.FrameOfReferenceUID = self.grid_uid
        seg.Rows, seg.Columns = self.shape
        seg.NumberOfFrames = len(frames)
        seg.SamplesPerPixel = 1
        seg.PhotometricInterpretation = "MONOCHROME2"
        seg.BitsAllocated = seg.BitsStored = 1
        seg.HighBit = 0
        seg.PixelRepresentation = 0
        seg.SegmentSequence = [
            item(SegmentNumber=1, SegmentLabel="Liver"),
            item(SegmentNumber=7, SegmentLabel="Mass"),
        ]
        seg.ReferencedSeriesSequence = [
            item(
                SeriesInstanceUID=self.series_uid,
                ReferencedInstanceSequence=[reference(ct.sop_instance_uid) for ct in self.slices],
            )
        ]
        shared = self.slices[0]
        seg.SharedFunctionalGroupsSequence = [
            item(
                PlaneOrientationSequence=[item(ImageOrientationPatient=list(shared.image_orientation_patient))],
                PixelMeasuresSequence=[item(PixelSpacing=list(shared.pixel_spacing_mm))],
            )
        ]
        seg.PerFrameFunctionalGroupsSequence = [
            item(
                SegmentIdentificationSequence=[item(ReferencedSegmentNumber=segment)],
                PlanePositionSequence=[item(ImagePositionPatient=list(ct.image_position_patient))],
                DerivationImageSequence=[item(SourceImageSequence=[reference(ct.sop_instance_uid)])],
            )
            for segment, ct, _ in frames
        ]
        seg.PixelData = np.packbits(
            np.stack([mask for _, _, mask in frames]), bitorder="little"
        ).tobytes()
        return seg

    def test_matches_mass_frames_by_uid_and_skips_empty_frames(self):
        first, middle, last = self.slices
        empty = np.zeros(self.shape, dtype=bool)
        mask_first = empty.copy()
        mask_first[2, 3] = True
        mask_last = empty.copy()
        mask_last[5, 6] = True
        seg = self.make_seg([
            (7, last, mask_last), (1, middle, ~empty), (7, middle, empty), (7, first, mask_first)
        ])
        seg.save_as(self.path, enforce_file_format=True)

        masks = load_tumor_masks(self.path, self.slices)
        self.assertEqual(set(masks), {first.path, last.path})
        np.testing.assert_array_equal(masks[first.path], mask_first)
        np.testing.assert_array_equal(masks[last.path], mask_last)

    def test_rejects_wrong_frame_reference_even_on_the_same_grid(self):
        seg = self.make_seg([(7, self.slices[0], np.ones(self.shape, dtype=bool))])
        frame = seg.PerFrameFunctionalGroupsSequence[0]
        frame.DerivationImageSequence[0].SourceImageSequence = [reference(generate_uid())]
        seg.save_as(self.path, enforce_file_format=True)

        with self.assertRaisesRegex(DicomReadError, "참조 UID"):
            load_tumor_masks(self.path, self.slices)

    def test_rejects_geometry_mismatch_even_with_the_correct_reference(self):
        for geometry in ("position", "orientation", "spacing"):
            with self.subTest(geometry=geometry):
                seg = self.make_seg([(7, self.slices[0], np.ones(self.shape, dtype=bool))])
                shared = seg.SharedFunctionalGroupsSequence[0]
                if geometry == "position":
                    frame = seg.PerFrameFunctionalGroupsSequence[0]
                    frame.PlanePositionSequence[0].ImagePositionPatient = [0.625, 0.0, 0.0]
                elif geometry == "orientation":
                    shared.PlaneOrientationSequence[0].ImageOrientationPatient = [0, 1, 0, -1, 0, 0]
                else:
                    shared.PixelMeasuresSequence[0].PixelSpacing = [0.75, 0.625]
                seg.save_as(self.path, enforce_file_format=True)

                with self.assertRaisesRegex(DicomReadError, "위치, 방향 또는 픽셀 간격"):
                    load_tumor_masks(self.path, self.slices)

    def test_draws_outline_without_covering_the_center_or_background(self):
        original = BytesIO()
        Image.new("L", (8, 8), 100).save(original, format="PNG")
        mask = np.zeros(self.shape, dtype=bool)
        mask[1:7, 1:7] = True
        result = render_ct_contour_png(original.getvalue(), mask)

        with Image.open(BytesIO(result)) as image:
            self.assertEqual(image.getpixel((0, 0)), (100, 100, 100))
            self.assertEqual(image.getpixel((1, 3)), (92, 231, 196))
            self.assertEqual(image.getpixel((3, 3)), (100, 100, 100))
