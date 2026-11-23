from dataclasses import dataclass

import pytest

from case_validation import (
    MSG_DUPLICATE_CASE_ID,
    MSG_EMPTY_CASE_ID,
    MSG_NO_FILES,
    normalize_case_id,
    validate_case_id,
    validate_dicom_selection,
    validate_registration,
)


@dataclass
class FakeUpload:
    """Streamlit UploadedFile에서 검사에 쓰는 속성(name, size)만 흉내 냅니다."""

    name: str
    size: int


class BytesOnlyUpload:
    """size 속성 없이 getvalue()만 있는 파일 객체."""

    def __init__(self, name, data):
        self.name = name
        self._data = data

    def getvalue(self):
        return self._data


EXISTING = {"HCC_004", "HCC_012"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  hcc_025 ", "HCC_025"),
        ("HCC_025", "HCC_025"),
        ("\thcc_7\n", "HCC_7"),
        ("", ""),
        ("   ", ""),
        (None, ""),
    ],
)
def test_normalize_case_id(raw, expected):
    assert normalize_case_id(raw) == expected


def test_case_id_empty_is_rejected():
    assert validate_case_id("", EXISTING) == [MSG_EMPTY_CASE_ID]


def test_case_id_duplicate_is_rejected():
    assert validate_case_id("HCC_004", EXISTING) == [MSG_DUPLICATE_CASE_ID]


def test_case_id_new_is_accepted():
    assert validate_case_id("HCC_025", EXISTING) == []


def test_duplicate_detected_after_normalization():
    case_id, errors = validate_registration(" hcc_004 ", EXISTING, [FakeUpload("1-001.dcm", 10)])
    assert case_id == "HCC_004"
    assert errors == [MSG_DUPLICATE_CASE_ID]


@pytest.mark.parametrize("files", [None, []])
def test_no_files_selected_is_rejected(files):
    assert validate_dicom_selection(files) == [MSG_NO_FILES]


def test_zero_byte_file_is_rejected_with_name():
    files = [FakeUpload("1-001.dcm", 524_000), FakeUpload("1-002.dcm", 0)]
    errors = validate_dicom_selection(files)
    assert len(errors) == 1
    assert "0바이트" in errors[0]
    assert "1-002.dcm" in errors[0]
    assert "1-001.dcm" not in errors[0]


def test_zero_byte_detected_via_getvalue_when_size_missing():
    errors = validate_dicom_selection([BytesOnlyUpload("1-001.dcm", b"")])
    assert len(errors) == 1 and "0바이트" in errors[0]


def test_many_zero_byte_files_are_summarized():
    files = [FakeUpload(f"1-{i:03d}.dcm", 0) for i in range(1, 9)]
    errors = validate_dicom_selection(files)
    assert len(errors) == 1
    assert "1-005.dcm" in errors[0]
    assert "1-006.dcm" not in errors[0]
    assert "외 3개" in errors[0]


@pytest.mark.parametrize("name", ["slice.png", "series.zip", "1-001", "dcm"])
def test_non_dcm_extension_is_rejected(name):
    errors = validate_dicom_selection([FakeUpload(name, 100)])
    assert len(errors) == 1
    assert ".dcm" in errors[0] and name in errors[0]


def test_uppercase_extension_is_accepted():
    assert validate_dicom_selection([FakeUpload("1-001.DCM", 100)]) == []


def test_multiple_valid_files_are_accepted():
    files = [FakeUpload(f"1-{i:03d}.dcm", 524_000) for i in range(1, 80)]
    assert validate_dicom_selection(files) == []


def test_valid_registration_returns_normalized_id_and_no_errors():
    case_id, errors = validate_registration(" hcc_025 ", EXISTING, [FakeUpload("1-001.dcm", 10)])
    assert case_id == "HCC_025"
    assert errors == []


def test_registration_reports_id_and_file_errors_together():
    case_id, errors = validate_registration("  ", EXISTING, [])
    assert case_id == ""
    assert errors == [MSG_EMPTY_CASE_ID, MSG_NO_FILES]


def test_existing_ids_can_be_a_dict():
    cases = {"HCC_004": {"exam": "치료 전 CT", "slice_count": 79}}
    _, errors = validate_registration("hcc_004", cases, [FakeUpload("1-001.dcm", 10)])
    assert errors == [MSG_DUPLICATE_CASE_ID]
