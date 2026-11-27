from case_list import (
    ALL_STATUSES,
    SOURCE_DEMO,
    SOURCE_STORED,
    case_record,
    count_by_status,
    displayed_status,
    filter_cases,
    merge_cases,
)
from case_store import INITIAL_REVIEW_STATUS, InMemoryCaseRepository, LocalFileStorage, register_case

STATUSES = ["검토 대기", "검토 중", "검토 완료"]
REF = "cases/HCC_025/20261125T0100_ab12cd34"

DEMO = {
    "HCC_004": {"exam": "치료 전 CT", "slice_count": 79},
    "HCC_012": {"exam": "치료 후 CT", "slice_count": 86},
}

STORED = {
    "HCC_025": {
        "exam_type": "치료 전 CT",
        "slice_count": 3,
        "file_count": 3,
        "image_ref": REF,
        "series_uid": "1.2.3",
        "review_status": "검토 중",
    },
    "LIVER_7": {"exam_type": "치료 후 CT", "slice_count": 2, "image_ref": "cases/LIVER_7/x"},
}


class Upload:
    def __init__(self, name, data):
        self.name, self.size, self._data = name, len(data), data

    def getvalue(self):
        return self._data


def ids(records):
    return [record["case_id"] for record in records]


# --- 레코드 변환 -------------------------------------------------------------


def test_case_record_reads_firestore_document():
    record = case_record("HCC_025", STORED["HCC_025"])
    assert record["exam"] == "치료 전 CT"
    assert record["slice_count"] == 3
    assert record["file_count"] == 3
    assert record["storage_ref"] == REF
    assert record["series_uid"] == "1.2.3"
    assert record["review_status"] == "검토 중"
    assert record["source"] == SOURCE_STORED


def test_demo_record_has_no_ct_reference_keys():
    """뷰어(B)는 image_ref·series_uid 키가 있으면 등록된 CT로 보고 DICOM을 열려고 합니다."""
    record = case_record("HCC_004", {**DEMO["HCC_004"], "image_ref": "x", "series_uid": "y"}, SOURCE_DEMO)
    assert not {"image_ref", "storage_ref", "series_uid"} & record.keys()
    assert record["exam"] == "치료 전 CT"
    assert record["slice_count"] == 79


def test_stored_record_without_files_has_no_ct_reference_keys():
    record = case_record("HCC_099", {"exam_type": "치료 전 CT"})
    assert not {"image_ref", "storage_ref", "series_uid"} & record.keys()


def test_case_record_fills_defaults_for_broken_document():
    record = case_record("HCC_099", {"slice_count": "많음"})
    assert record["exam"] == "—"
    assert record["slice_count"] == 1
    assert record["file_count"] is None
    assert record["review_status"] == INITIAL_REVIEW_STATUS


def test_case_record_tolerates_wrong_field_types():
    """콘솔에서 잘못 고친 문서(숫자·목록·dict 값)도 목록 계산을 깨뜨리지 않습니다."""
    record = case_record("HCC_098", {
        "review_status": ["검토 중"],
        "exam_type": 3,
        "image_ref": {"path": "x"},
        "series_uid": 1.2,
        "file_count": "3",
    })
    assert record["review_status"] == INITIAL_REVIEW_STATUS
    assert record["exam"] == "—"
    assert "storage_ref" not in record
    assert "series_uid" not in record
    assert record["file_count"] is None
    assert case_record("HCC_097", ["not", "a", "dict"])["review_status"] == INITIAL_REVIEW_STATUS


def test_case_record_strips_whitespace():
    record = case_record("A", {"review_status": " 검토 중 ", "image_ref": "  cases/A/x "})
    assert record["review_status"] == "검토 중"
    assert record["storage_ref"] == "cases/A/x"
    assert case_record("A", {"review_status": "   "})["review_status"] == INITIAL_REVIEW_STATUS


def test_case_record_rejects_bool_and_non_positive_counts():
    assert case_record("A", {"slice_count": True})["slice_count"] == 1
    assert case_record("A", {"slice_count": 0})["slice_count"] == 1
    assert case_record("A", {"file_count": False})["file_count"] is None
    assert case_record("A", None)["slice_count"] == 1


# --- 합치기 ------------------------------------------------------------------


def test_merge_sorts_by_case_id_and_marks_source():
    cases = merge_cases(STORED, DEMO)
    assert list(cases) == ["HCC_004", "HCC_012", "HCC_025", "LIVER_7"]
    assert cases["HCC_004"]["source"] == SOURCE_DEMO
    assert cases["HCC_025"]["source"] == SOURCE_STORED


def test_stored_document_wins_over_demo_with_same_id():
    stored = {"HCC_004": {"exam_type": "치료 후 CT", "slice_count": 5, "image_ref": "cases/HCC_004/y"}}
    cases = merge_cases(stored, DEMO)
    assert cases["HCC_004"]["exam"] == "치료 후 CT"
    assert cases["HCC_004"]["storage_ref"] == "cases/HCC_004/y"
    assert cases["HCC_004"]["source"] == SOURCE_STORED


def test_merge_does_not_modify_inputs():
    stored = {"HCC_025": dict(STORED["HCC_025"])}
    cases = merge_cases(stored, DEMO)
    cases["HCC_025"]["review_status"] = "검토 완료"
    assert stored["HCC_025"]["review_status"] == "검토 중"
    assert "image_ref" in stored["HCC_025"]


# --- 화면에 보일 검토 상태 ---------------------------------------------------


def test_displayed_status_prefers_session_override():
    case = merge_cases(STORED)["HCC_025"]
    assert displayed_status(case) == "검토 중"
    assert displayed_status(case, {"HCC_025": "검토 완료"}) == "검토 완료"
    assert displayed_status(case, {"HCC_025": None}) == "검토 중"
    assert displayed_status(case, {"HCC_025": ["검토 완료"]}) == "검토 중"


def test_displayed_status_maps_unknown_values_to_initial_status():
    """목록에 없는 상태가 문서에 있어도 상태 배지·기호 계산이 깨지지 않게 합니다."""
    case = case_record("X_1", {"review_status": "보류"})
    assert displayed_status(case) == "보류"
    assert displayed_status(case, known_statuses=STATUSES) == INITIAL_REVIEW_STATUS
    assert displayed_status(case, {"X_1": "엉뚱함"}, STATUSES) == INITIAL_REVIEW_STATUS


# --- 검색·필터 ---------------------------------------------------------------


def test_filter_by_partial_id_ignores_case_and_spaces():
    cases = merge_cases(STORED, DEMO)
    assert ids(filter_cases(cases, "  hcc_0 ")) == ["HCC_004", "HCC_012", "HCC_025"]
    assert ids(filter_cases(cases, "liver")) == ["LIVER_7"]
    assert ids(filter_cases(cases, "")) == list(cases)
    assert ids(filter_cases(cases, None)) == list(cases)


def test_filter_by_status():
    cases = merge_cases(STORED, DEMO)
    assert ids(filter_cases(cases, status_filter="검토 중")) == ["HCC_025"]
    assert ids(filter_cases(cases, status_filter="검토 완료")) == []
    assert ids(filter_cases(cases, status_filter=ALL_STATUSES)) == list(cases)
    assert ids(filter_cases(cases, status_filter=None)) == list(cases)  # 선택 해제 = 전체


def test_filter_and_count_use_given_status_function():
    cases = merge_cases(STORED, DEMO)
    overrides = {"HCC_012": "검토 완료"}

    def status_of(case):
        return displayed_status(case, overrides, STATUSES)

    assert ids(filter_cases(cases, "", "검토 완료", status_of)) == ["HCC_012"]
    assert count_by_status(cases, STATUSES, status_of) == {"검토 대기": 2, "검토 중": 1, "검토 완료": 1}


def test_filter_combines_query_and_status():
    cases = merge_cases(STORED, DEMO)
    assert ids(filter_cases(cases, "012", "검토 대기")) == ["HCC_012"]
    assert ids(filter_cases(cases, "012", "검토 중")) == []


def test_count_by_status_ignores_unknown_statuses():
    cases = merge_cases({"X_1": {"review_status": "보류"}, **STORED}, DEMO)
    assert count_by_status(cases, STATUSES) == {"검토 대기": 3, "검토 중": 1, "검토 완료": 0}


# --- 등록부터 목록까지 -------------------------------------------------------


def test_registered_case_appears_in_list_and_points_to_saved_files(tmp_path):
    """등록 → 목록 조회 → storage_ref로 원본 폴더 찾기까지 이어지는지 확인합니다."""
    repo, storage = InMemoryCaseRepository(), LocalFileStorage(tmp_path)
    files = [Upload(f"{i}.dcm", f"dicom-{i}".encode()) for i in (1, 2)]
    register_case(repo, storage, "HCC_025", "치료 전 CT", files)

    found = filter_cases(merge_cases(repo.list_cases(), DEMO), "025")
    assert ids(found) == ["HCC_025"]
    assert found[0]["review_status"] == INITIAL_REVIEW_STATUS
    assert found[0]["slice_count"] == 2

    folder = storage.path_for(found[0]["storage_ref"])
    assert sorted(path.read_bytes() for path in folder.iterdir()) == [b"dicom-1", b"dicom-2"]
