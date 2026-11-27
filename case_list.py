"""케이스 목록·검색 계산 (A 담당 04단계).

저장소(Firestore) 문서와 교육용 모의 케이스를 한 형식의 레코드로 합치고,
ID 검색·검토 상태 필터·상태별 개수를 계산합니다.
Streamlit에 의존하지 않아 pytest로 바로 검사할 수 있습니다.

레코드 형식 (app.py와 뷰어가 `cases[case_id]`로 읽는 dict):
    case_id, exam, slice_count, file_count, review_status, source("stored" | "demo")
    storage_ref  Firestore에 적힌 저장 위치 (CT 저장 폴더 기준 상대 경로). 원본이 없으면 키 없음
    image_ref    뷰어(B)가 여는 서버 폴더 경로. case_ui가 storage_ref로 채웁니다. 원본이 없으면 키 없음
    series_uid   DICOM 시리즈 UID. 문서에 있을 때만 키가 있습니다

뷰어는 image_ref·series_uid 키가 있으면 "등록된 CT"로 보고 DICOM을 엽니다.
그래서 모의 케이스에는 이 키를 넣지 않습니다.
"""

from case_store import INITIAL_REVIEW_STATUS

ALL_STATUSES = "전체"
SOURCE_STORED = "stored"
SOURCE_DEMO = "demo"


def _positive_int(value):
    # bool은 int의 하위 타입이라 따로 걸러 냅니다.
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _text(value):
    """비어 있지 않은 문자열이면 앞뒤 공백을 지워 돌려주고, 아니면 None입니다.

    Firestore 문서는 콘솔에서 직접 고칠 수 있어 숫자·목록 같은 값이 들어올 수 있습니다.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def case_record(case_id, doc, source=SOURCE_STORED):
    """Firestore 문서(또는 모의 케이스 dict)를 화면용 레코드로 바꿉니다.

    문서에 값이 빠지거나 형식이 잘못돼 있어도 목록 화면이 깨지지 않도록 기본값을 채웁니다.
    """
    doc = doc if isinstance(doc, dict) else {}
    slice_count = doc.get("slice_count")
    file_count = doc.get("file_count")
    record = {
        "case_id": str(case_id),
        "exam": _text(doc.get("exam_type")) or _text(doc.get("exam")) or "—",
        "slice_count": slice_count if _positive_int(slice_count) else 1,
        "file_count": file_count if _positive_int(file_count) else None,
        # 검토 상태는 D 담당이 Firestore 문서에 기록합니다. 없으면 등록 직후 상태로 봅니다.
        "review_status": _text(doc.get("review_status")) or INITIAL_REVIEW_STATUS,
        "source": source,
    }
    if source == SOURCE_STORED:
        storage_ref = _text(doc.get("image_ref"))
        series_uid = _text(doc.get("series_uid"))
        if storage_ref:
            record["storage_ref"] = storage_ref
        if series_uid:
            record["series_uid"] = series_uid
    return record


def merge_cases(stored_docs, demo_cases=None):
    """저장소 문서와 모의 케이스를 합쳐 케이스 ID 순으로 돌려줍니다.

    같은 ID가 둘 다 있으면 저장소 문서를 씁니다(실제 등록이 모의 데이터보다 우선).
    """
    cases = {
        str(case_id): case_record(case_id, doc, SOURCE_DEMO)
        for case_id, doc in (demo_cases or {}).items()
    }
    for case_id, doc in (stored_docs or {}).items():
        cases[str(case_id)] = case_record(case_id, doc, SOURCE_STORED)
    return dict(sorted(cases.items()))


def displayed_status(case, status_overrides=None, known_statuses=None):
    """화면에 보여 줄 검토 상태.

    - status_overrides: 이 세션에서 바꾼 상태 {case_id: status} (app.py의 review_statuses).
      D 담당의 검토 상태 저장이 연결되기 전까지 화면 시연용으로 씁니다.
    - known_statuses: 화면이 아는 상태 목록. 목록에 없는 값은 등록 직후 상태로 보여 줍니다.
    """
    status = _text((status_overrides or {}).get(case["case_id"])) or case["review_status"]
    if known_statuses is not None and status not in known_statuses:
        return INITIAL_REVIEW_STATUS
    return status


def normalize_query(query):
    return (query or "").strip().casefold()


def case_display_name(case):
    return case.get("display_name", case["case_id"])


def filter_cases(cases, query="", status_filter=ALL_STATUSES, status_of=None):
    """케이스 ID 부분 일치(대소문자 무시)와 검토 상태로 걸러 레코드 목록을 돌려줍니다.

    status_of: 레코드 → 상태 함수. 없으면 레코드의 review_status를 씁니다.
    """
    needle = normalize_query(query)
    status_filter = status_filter or ALL_STATUSES
    status_of = status_of or (lambda case: case["review_status"])
    return [
        case for case in cases.values()
        if needle in case_display_name(case).casefold()
        and (status_filter == ALL_STATUSES or status_of(case) == status_filter)
    ]


def count_by_status(cases, statuses, status_of=None):
    """statuses 순서대로 상태별 케이스 수를 셉니다. 목록에 없는 상태는 세지 않습니다."""
    status_of = status_of or (lambda case: case["review_status"])
    counts = {status: 0 for status in statuses}
    for case in cases.values():
        status = status_of(case)
        if status in counts:
            counts[status] += 1
    return counts
