"""등록할 때 CT 시리즈를 검사하고, 등록한 케이스를 뷰어(B)가 실제로 여는지 확인합니다."""

from io import BytesIO

import numpy as np
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

import ct_case
from case_list import merge_cases
from case_store import CaseStoreError, InMemoryCaseRepository, LocalFileStorage, register_case
from case_ui import _with_server_path, inspect_ct_series


class Upload:
    def __init__(self, name, data):
        self.name, self.size, self._data = name, len(data), data

    def getvalue(self):
        return self._data


def ct_bytes(position, series_uid, modality="CT"):
    """2×2 픽셀짜리 단일 프레임 CT DICOM 파일 내용을 만듭니다."""
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset("slice.dcm", {}, file_meta=meta, preamble=bytes(128))
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = generate_uid()
    ds.SeriesInstanceUID = series_uid
    ds.FrameOfReferenceUID = "1.2.840.99999.1"
    ds.Modality = modality
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [0, 0, position]
    ds.PixelSpacing = [0.7, 0.7]
    ds.Rows = ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.RescaleSlope, ds.RescaleIntercept = 1, -1024
    ds.PixelData = np.zeros((2, 2), dtype="<i2").tobytes()
    buffer = BytesIO()
    ds.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()


def series(series_uid, positions):
    return [Upload(f"{i}.dcm", ct_bytes(p, series_uid)) for i, p in enumerate(positions)]


@pytest.fixture
def stores(tmp_path):
    return InMemoryCaseRepository(), LocalFileStorage(tmp_path)


def uploaded_folders(storage, case_id):
    case_dir = storage.root / "cases" / case_id
    return list(case_dir.iterdir()) if case_dir.exists() else []


def test_valid_series_stores_uid_and_real_slice_count(stores):
    repo, storage = stores
    uid = generate_uid()
    # 파일 선택 순서가 뒤섞여 있어도 시리즈 하나면 통과합니다.
    saved = register_case(repo, storage, "HCC_025", "치료 전 CT", series(uid, [5, 0, 2.5]),
                          inspect_series=inspect_ct_series)
    doc = repo.get("HCC_025")
    assert doc["series_uid"] == uid == saved["series_uid"]
    assert doc["slice_count"] == 3


def test_registered_case_opens_in_viewer(stores):
    """A 등록 → 목록 레코드 → B의 load_case_ct까지 약속대로 이어지는지 확인합니다."""
    repo, storage = stores
    uid = generate_uid()
    register_case(repo, storage, "HCC_025", "치료 전 CT", series(uid, [0, 2.5, 5]),
                  inspect_series=inspect_ct_series)

    case = _with_server_path(merge_cases(repo.list_cases())["HCC_025"], storage)
    assert ct_case.has_case_ct_reference(case)
    slices, error = ct_case.load_case_ct("HCC_025", case)
    assert error is None
    assert [s.position_mm for s in slices] == [0, 2.5, 5]
    assert {s.series_instance_uid for s in slices} == {uid}


def test_mixed_series_is_rejected_and_upload_removed(stores):
    repo, storage = stores
    files = series(generate_uid(), [0, 2.5]) + series(generate_uid(), [5])
    with pytest.raises(CaseStoreError, match="등록을 취소"):
        register_case(repo, storage, "HCC_026", "치료 전 CT", files, inspect_series=inspect_ct_series)
    assert repo.get("HCC_026") is None
    assert uploaded_folders(storage, "HCC_026") == []


def test_non_ct_file_is_rejected_with_reader_message(stores):
    repo, storage = stores
    files = series(generate_uid(), [0]) + [Upload("x.dcm", b"not a dicom file")]
    with pytest.raises(CaseStoreError) as caught:
        register_case(repo, storage, "HCC_027", "치료 전 CT", files, inspect_series=inspect_ct_series)
    assert "DICOM 정보가 없거나" in str(caught.value)  # B가 만든 안내 문구를 그대로 보여 줍니다.
    assert repo.get("HCC_027") is None
    assert uploaded_folders(storage, "HCC_027") == []


def test_unexpected_inspector_error_also_cancels(stores):
    repo, storage = stores

    def broken(folder):
        raise OSError("disk read failed")

    with pytest.raises(CaseStoreError, match="확인하지 못해"):
        register_case(repo, storage, "HCC_028", "치료 전 CT", series(generate_uid(), [0]),
                      inspect_series=broken)
    assert repo.get("HCC_028") is None
    assert uploaded_folders(storage, "HCC_028") == []


def test_without_inspector_keeps_file_count_and_no_uid(stores):
    repo, storage = stores
    register_case(repo, storage, "HCC_029", "치료 전 CT", [Upload("a.dcm", b"x"), Upload("b.dcm", b"y")])
    doc = repo.get("HCC_029")
    assert doc["slice_count"] == 2
    assert "series_uid" not in doc
