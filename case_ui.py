"""A 담당 화면 조각: 케이스 등록·저장소 연결·목록 검색.

app.py는 아래 네 함수만 부릅니다. 나머지(저장·검사·목록 계산)는 이 파일이 부르는 모듈에 있습니다.

    cases = case_ui.load_cases(demo_cases)                    # 케이스 목록 읽기
    case_ui.render_storage_notice(lang="ko")                   # 저장소 연결 오류·안내
    case_ui.render_register_form(cases, lang="ko")             # 등록 팝오버 안의 폼
    selected = case_ui.render_case_table(cases, ..., lang="ko")# 검색·필터·표, 고른 행 돌려줌

저장 구조:
    CT 원본  → JCloud 영구 디스크 (LocalFileStorage, 경로는 secrets [storage] root 또는 CASE_STORAGE_ROOT)
    케이스 정보 → Cloud Firestore `cases/{case_id}` (secrets [firebase]가 없으면 세션 메모리)
"""

import os
from html import escape
from json import loads
from pathlib import Path

import pandas as pd
import streamlit as st

from case_list import (
    ALL_STATUSES,
    SOURCE_DEMO,
    SOURCE_STORED,
    case_display_name,
    case_record,
    count_by_status,
    displayed_status,
    filter_cases,
    merge_cases,
)
from case_store import (
    CaseAlreadyExistsError,
    CaseStoreError,
    InMemoryCaseRepository,
    LocalFileStorage,
    make_firestore_repository,
    register_case,
)
from case_validation import DICOM_EXTENSIONS, validate_registration
from dicom_ct import load_ct_series  # B 담당: CT 시리즈 읽기·검사
from i18n import LANG_KO, label_case_name, label_exam, label_status, t

APP_DIR = Path(__file__).resolve().parent
DEFAULT_STORAGE_ROOT = APP_DIR / "data" / "uploads"
EXAM_TYPES = ["치료 전 CT", "치료 후 CT"]

# A가 새로 쓰는 session_state 키는 "a_"로 시작합니다. (검색어·필터 키는 프로토타입 이름을 그대로 씁니다)
KEY_REPOSITORY = "a_case_repository"
KEY_LOAD_ERROR = "a_case_load_error"


# ---------------------------------------------------------------------------
# 저장소 연결
# ---------------------------------------------------------------------------


def _secret_section(name):
    try:
        return dict(st.secrets[name]) if name in st.secrets else {}
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return {}


@st.cache_resource(show_spinner=False)
def _firestore_repository():
    # 모든 접속자가 하나를 같이 씁니다. 목록 캐시도 공유되어 Firestore 읽기 횟수를 아낍니다.
    return make_firestore_repository(_secret_section("firebase"))


@st.cache_resource(show_spinner=False)
def _file_storage(root):
    return LocalFileStorage(root)


def _connect():
    """(케이스 정보 저장소, CT 파일 저장소, 연결 오류 문구)를 돌려줍니다."""
    root = _secret_section("storage").get("root") or os.environ.get("CASE_STORAGE_ROOT") or DEFAULT_STORAGE_ROOT
    storage = _file_storage(str(root))

    if not _secret_section("firebase"):
        # Firebase 설정이 없으면 이 세션에서만 유지되는 미연결 모드로 동작합니다.
        return st.session_state.setdefault(KEY_REPOSITORY, InMemoryCaseRepository()), storage, None
    try:
        return _firestore_repository(), storage, None
    except Exception as error:  # 잘못된 키·네트워크 오류를 화면에 알립니다.
        return None, storage, f"Firestore에 연결하지 못했어요: {error}"


def inspect_ct_series(folder):
    """등록 직전에 저장한 폴더를 뷰어(B)와 같은 방법으로 읽어 봅니다.

    한 CT 시리즈가 아니면 DicomReadError(ValueError)가 나고 등록이 취소됩니다.
    성공하면 뷰어가 같은 시리즈를 다시 찾을 수 있게 (series_uid, 실제 단면 수)를 돌려줍니다.
    """
    slices = load_ct_series(folder)
    return slices[0].series_instance_uid, len(slices)


def _with_server_path(case, storage):
    """뷰어(B)가 열 수 있게 storage_ref를 서버 폴더 경로(image_ref)로 바꿔 붙입니다."""
    storage_ref = case.get("storage_ref")
    if storage_ref:
        try:
            case["image_ref"] = str(storage.path_for(storage_ref))
        except ValueError:
            pass  # 저장소 밖을 가리키는 잘못된 문서: 경로를 넘기지 않습니다.
    return case


def _load_synthetic_hcc_001():
    directory = APP_DIR / "assets" / "synthetic_ct" / "HCC_001"
    ct_directory = directory / "ct"
    seg_path = directory / "seg.dcm"
    if not ct_directory.is_dir() or not seg_path.is_file():
        return None

    try:
        metadata = loads((directory / "case.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(metadata, dict) or metadata.get("synthetic") is not True:
        return None
    series_uid = metadata.get("series_uid")
    if not isinstance(series_uid, str) or not series_uid:
        return None

    # A separate key keeps test measurements and notes apart from a registered HCC_001.
    case = case_record("demo:HCC_001", metadata, SOURCE_DEMO)
    case.update(
        display_name="HCC_001 (AI 생성 테스트용 이미지)",
        exam="치료 전 CT · 합성 실험용",
        image_ref=str(ct_directory),
        seg_ref=str(seg_path),
        series_uid=series_uid,
        synthetic=True,
    )
    return case


# ---------------------------------------------------------------------------
# app.py가 부르는 함수
# ---------------------------------------------------------------------------


def load_cases(demo_cases):
    """저장소의 케이스와 모의 케이스를 합쳐 {case_id: 레코드}로 돌려줍니다 (형식은 case_list 참고).

    읽기에 실패해도 화면은 모의 케이스로 계속 동작하고, 오류는 render_storage_notice()가 보여 줍니다.
    """
    repository, storage, error = _connect()
    stored_docs = {}
    if repository is not None:
        try:
            stored_docs = repository.list_cases()
        except Exception as list_error:
            error = f"저장된 케이스 목록을 불러오지 못했어요: {list_error}"
    st.session_state[KEY_LOAD_ERROR] = error

    cases = merge_cases(stored_docs, demo_cases)
    synthetic_case = _load_synthetic_hcc_001()
    if synthetic_case is not None:
        cases[synthetic_case["case_id"]] = synthetic_case
    for case in cases.values():
        _with_server_path(case, storage)
    return dict(sorted(cases.items(), key=lambda entry: case_display_name(entry[1])))


def render_storage_notice(lang=LANG_KO):
    """저장소 연결 오류나 미연결 안내를 보여 줍니다. 목록 화면 맨 위에서 부릅니다."""
    error = st.session_state.get(KEY_LOAD_ERROR)
    if error:
        st.error(error)
        return
    repository, _, _ = _connect()
    if repository is not None and not repository.is_persistent:
        st.caption(t("firestore_disconnected_caption", lang))


def render_register_form(cases, lang=LANG_KO):
    """케이스 등록 폼. app.py의 '케이스 등록' 팝오버 안에서 부릅니다.

    성공하면 cases에 새 레코드를 넣어 같은 화면의 목록에 바로 보이게 합니다.
    """
    with st.form("register_case"):
        case_id_input = st.text_input(
            t("register_new_id", lang),
            placeholder=t("register_id_placeholder", lang),
        )
        exam_type = st.selectbox(
            t("exam_type", lang),
            EXAM_TYPES,
            format_func=lambda item: label_exam(item, lang),
        )
        dicom_files = st.file_uploader(
            t("ct_dicom_files", lang),
            type=list(DICOM_EXTENSIONS),
            accept_multiple_files=True,
            help=t("ct_dicom_help", lang),
        )
        submitted = st.form_submit_button(t("submit_register", lang), type="primary")

    if not submitted:
        return

    new_case_id, errors = validate_registration(case_id_input, cases, dicom_files)
    if errors:
        for error in errors:
            st.warning(error)
        return

    repository, storage, connect_error = _connect()
    if repository is None:
        st.error(t("storage_not_connected", lang, error=connect_error))
        return

    try:
        with st.spinner(t("register_spinner", lang)):
            saved = register_case(
                repository,
                storage,
                new_case_id,
                exam_type,
                dicom_files,
                inspect_series=inspect_ct_series,
            )
    except CaseAlreadyExistsError as error:
        st.warning(str(error))
        return
    except CaseStoreError as error:
        st.error(str(error))
        return
    except Exception as error:
        st.error(t("register_unexpected_error", lang, error=error))
        return

    cases[new_case_id] = _with_server_path(case_record(new_case_id, saved, SOURCE_STORED), storage)
    total_mb = saved["total_bytes"] / (1024 * 1024)
    summary = t(
        "register_summary",
        lang,
        slice_count=saved["slice_count"],
        file_count=saved["file_count"],
        total_mb=total_mb,
    )
    if repository.is_persistent:
        st.success(t("register_success_persistent", lang, case_id=new_case_id, summary=summary))
    else:
        # Firestore 미연결: 영구 저장 성공으로 표시하지 않습니다.
        st.info(t("register_success_session", lang, case_id=new_case_id, summary=summary))


def _refresh_cases():
    repository, _, _ = _connect()
    if repository is not None:
        repository.invalidate_cache()


def _keep_status_filter():
    # 이미 고른 칸을 다시 눌러 선택이 풀리면 '전체'로 되돌립니다.
    if st.session_state.get("status_filter") is None:
        st.session_state["status_filter"] = ALL_STATUSES


def render_case_table(cases, review_statuses, statuses, status_marks, lang=LANG_KO):
    """검색창·상태 필터·새로고침·케이스 표·개수 안내를 그립니다.

    review_statuses: 이 세션에서 바꾼 검토 상태 {case_id: status} (D 연결 전 시연용)
    statuses: 화면이 아는 검토 상태 목록 / status_marks: {상태: 표시 기호}
    고른 행을 app.py 요약 카드가 쓰던 형식의 dict로 돌려줍니다. 표가 비면 None입니다.
        {"케이스 ID", "검사 종류", "단면 수", "검토 상태"}
    """
    def status_of(case):
        return displayed_status(case, review_statuses, statuses)

    search_col, filter_col, refresh_col = st.columns([1, 1.35, 0.2], vertical_alignment="center")
    query = search_col.text_input(
        t("search_label", lang),
        placeholder=t("search_placeholder", lang),
        key="case_query",
        icon=":material/search:",
        label_visibility="collapsed",
    )

    st.session_state.setdefault("status_filter", ALL_STATUSES)
    with filter_col.container(horizontal=True, horizontal_alignment="right"):
        st.segmented_control(
            t("status_filter_label", lang),
            [ALL_STATUSES] + list(statuses),
            format_func=lambda item: label_status(item, lang),
            key="status_filter",
            on_change=_keep_status_filter,
            label_visibility="collapsed",
        )
    status_filter = st.session_state.get("status_filter") or ALL_STATUSES

    refresh_col.button(
        "",
        key="a_refresh_cases",
        icon=":material/refresh:",
        help=t("refresh_help", lang),
        type="tertiary",
        on_click=_refresh_cases,
    )

    rows = [
        {
            "케이스 ID": case["case_id"],
            "검사 종류": case["exam"],
            "단면 수": case["slice_count"],
            "검토 상태": status_of(case),
        }
        for case in filter_cases(cases, query, status_filter, status_of)
    ]

    selected = None
    if rows:
        table_key = f"case_table_{lang}_" + "_".join(row["케이스 ID"] for row in rows)
        display_rows = [
            {
                "케이스 ID": label_case_name(cases[row["케이스 ID"]], lang),
                "검사 종류": label_exam(row["검사 종류"], lang),
                "단면 수": row["단면 수"],
                "검토 상태": f"{status_marks.get(row['검토 상태'], '·')}  {label_status(row['검토 상태'], lang)}",
            }
            for row in rows
        ]
        table = pd.DataFrame(display_rows)
        event = st.dataframe(
            table,
            key=table_key,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            width="stretch",
            row_height=42,
            column_config={
                "케이스 ID": st.column_config.TextColumn(t("col_case_id", lang), width=230),
                "검사 종류": st.column_config.TextColumn(t("col_exam_type", lang)),
                "단면 수": st.column_config.NumberColumn(
                    t("col_slice_count", lang),
                    format=t("slice_count_format", lang),
                ),
                "검토 상태": st.column_config.TextColumn(t("col_review_status", lang)),
            },
        )
        if event.selection.rows:
            selected = rows[event.selection.rows[0]]
            st.session_state["selected_case_id"] = selected["케이스 ID"]
        else:
            remembered_id = st.session_state.get("selected_case_id")
            selected = next((row for row in rows if row["케이스 ID"] == remembered_id), rows[0])
    else:
        st.html(
            '<div class="empty">'
            f'<span class="empty-title">{escape(t("empty_cases_title", lang))}</span>'
            f'<span class="empty-desc">{escape(t("empty_cases_desc", lang))}</span>'
            "</div>"
        )

    counts = count_by_status(cases, statuses, status_of)
    counts_text = " · ".join(f"{label_status(status, lang)} {count}" for status, count in counts.items())
    st.html(
        '<div class="caption-row">'
        f'<span>{escape(t("cases_caption_left", lang, count=len(rows)))}</span>'
        f"<span>{escape(counts_text)}</span>"
        "</div>"
    )
    return selected
