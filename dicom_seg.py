from pathlib import Path

import numpy as np
from pydicom import dcmread
from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError
from pydicom.uid import SegmentationStorage

from dicom_ct import CTSlice, DicomReadError


def _frame_geometry(group: Dataset, shared: Dataset, sequence_name: str) -> Dataset:
    items = group.get(sequence_name) or shared.get(sequence_name, ())
    if len(items) != 1:
        raise DicomReadError("SEG에서 단면의 위치, 방향 또는 픽셀 간격을 읽을 수 없어요.")
    return items[0]


def _matches_geometry(values, expected: tuple[float, ...], tolerance: float) -> bool:
    values = np.asarray(values, dtype=float)
    return values.shape == (len(expected),) and np.allclose(values, expected, atol=tolerance, rtol=0)


def load_tumor_masks(path: Path, ct_slices: tuple[CTSlice, ...]) -> dict[Path, np.ndarray]:
    """Read HCC-TACE-Seg Mass frames that match the CT pixel grid."""
    if not ct_slices:
        raise DicomReadError("SEG와 대응할 CT 시리즈가 없어요.")

    try:
        seg = dcmread(path)
        if seg.Modality != "SEG" or seg.SOPClassUID != SegmentationStorage or seg.SegmentationType != "BINARY":
            raise DicomReadError("종양 윤곽에는 BINARY DICOM SEG 파일을 사용해 주세요.")

        ct_by_uid = {item.sop_instance_uid: item for item in ct_slices}
        series_uid = ct_slices[0].series_instance_uid
        declared_uids = {
            str(instance.ReferencedSOPInstanceUID)
            for series in seg.get("ReferencedSeriesSequence", ())
            if str(series.SeriesInstanceUID) == series_uid
            for instance in series.get("ReferencedInstanceSequence", ())
        }
        if not declared_uids:
            raise DicomReadError("SEG가 선택한 CT 시리즈를 참조하지 않아요.")

        mass_segments = [
            int(item.SegmentNumber)
            for item in seg.SegmentSequence
            if str(item.SegmentLabel).strip().casefold() == "mass"
        ]
        if len(mass_segments) != 1:
            raise DicomReadError("SEG에서 하나의 종양(Mass) 영역을 찾지 못했어요.")

        grid_uid = str(seg.get("FrameOfReferenceUID") or "")
        if not grid_uid or grid_uid != ct_slices[0].frame_of_reference_uid:
            raise DicomReadError("SEG와 CT의 환자 좌표계 UID가 달라요.")

        shape = (int(seg.Rows), int(seg.Columns))
        groups = seg.PerFrameFunctionalGroupsSequence
        if len(groups) != int(seg.NumberOfFrames):
            raise DicomReadError("SEG의 프레임 수와 프레임별 정보 개수가 달라요.")
        shared_groups = seg.get("SharedFunctionalGroupsSequence", ())
        shared = shared_groups[0] if shared_groups else Dataset()
        aligned = {}
        for index, group in enumerate(groups):
            segment_number = int(group.SegmentIdentificationSequence[0].ReferencedSegmentNumber)
            if segment_number != mass_segments[0]:
                continue

            derivations = group.get("DerivationImageSequence") or shared.get("DerivationImageSequence", ())
            sources = [item for derivation in derivations for item in derivation.get("SourceImageSequence", ())]
            if len(sources) != 1:
                raise DicomReadError("종양 마스크 프레임마다 참조 CT 단면이 하나씩 필요해요.")

            source_uid = str(sources[0].ReferencedSOPInstanceUID)
            ct_slice = ct_by_uid.get(source_uid)
            if ct_slice is None or source_uid not in declared_uids:
                raise DicomReadError("종양 마스크 프레임의 참조 UID가 이 CT에 없어요.")
            if ct_slice.path in aligned:
                raise DicomReadError("하나의 CT 단면을 참조하는 종양 마스크 프레임이 중복돼요.")
            if grid_uid != ct_slice.frame_of_reference_uid or shape != ct_slice.shape:
                raise DicomReadError("SEG와 참조 CT 단면의 좌표계 또는 영상 크기가 달라요.")

            position = _frame_geometry(group, shared, "PlanePositionSequence").ImagePositionPatient
            orientation = _frame_geometry(group, shared, "PlaneOrientationSequence").ImageOrientationPatient
            spacing = _frame_geometry(group, shared, "PixelMeasuresSequence").PixelSpacing
            if not (
                _matches_geometry(position, ct_slice.image_position_patient, 1e-3)
                and _matches_geometry(orientation, ct_slice.image_orientation_patient, 1e-4)
                and _matches_geometry(spacing, ct_slice.pixel_spacing_mm, 1e-4)
            ):
                raise DicomReadError("종양 마스크의 위치, 방향 또는 픽셀 간격이 참조 CT와 달라요.")
            aligned[ct_slice.path] = index

        if not aligned:
            raise DicomReadError("SEG에 CT를 참조하는 종양(Mass) 프레임이 없어요.")
        frames = seg.pixel_array
        if frames.ndim == 2:
            frames = frames[np.newaxis, ...]
        if frames.shape != (len(groups), *shape):
            raise DicomReadError("SEG의 프레임 배열이 영상 크기 또는 프레임 수와 맞지 않아요.")

        masks = {}
        for ct_path, index in aligned.items():
            if frames[index].any():
                mask = frames[index].astype(bool)
                mask.setflags(write=False)
                masks[ct_path] = mask
        return masks
    except DicomReadError:
        raise
    except (InvalidDicomError, OSError, AttributeError, IndexError, TypeError, ValueError, RuntimeError) as exc:
        raise DicomReadError("SEG 파일의 프레임 또는 참조 정보를 읽을 수 없어요.") from exc
