"""케이스 등록 폼의 기본 입력 검사.

Streamlit에 의존하지 않는 순수 함수만 두어 pytest로 바로 검사할 수 있게 합니다.
케이스 ID(빈 값·형식·중복)와 선택한 파일의 기본 조건(개수·크기·확장자)을 확인합니다.
DICOM 내용·시리즈 검증은 다음 단계(B 담당 검사 함수)에서 연결합니다.
"""

import re
from pathlib import PurePath

DICOM_EXTENSIONS = ("dcm",)
MAX_LISTED_NAMES = 5
CASE_ID_MAX_LENGTH = 40
# Firestore 문서 ID와 저장 폴더 이름으로 그대로 쓸 수 있는 문자만 허용합니다.
CASE_ID_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9_-]*")

MSG_EMPTY_CASE_ID = "케이스 ID를 입력해 주세요."
MSG_DUPLICATE_CASE_ID = "이미 등록된 케이스 ID예요."
MSG_CASE_ID_FORMAT = "케이스 ID는 영문·숫자로 시작하고 영문·숫자·_·-만 쓸 수 있어요. (예: HCC_025)"
MSG_CASE_ID_TOO_LONG = f"케이스 ID는 {CASE_ID_MAX_LENGTH}자 이하로 입력해 주세요."
MSG_NO_FILES = "DICOM 파일을 하나 이상 선택해 주세요."


def normalize_case_id(raw_case_id):
    """앞뒤 공백을 지우고 대문자로 맞춥니다. None은 빈 문자열로 봅니다."""
    return (raw_case_id or "").strip().upper()


def validate_case_id_format(case_id):
    """정규화된 케이스 ID의 형식만 검사합니다. 빈 값은 따로 검사하므로 여기서는 통과시킵니다."""
    if not case_id:
        return []
    if len(case_id) > CASE_ID_MAX_LENGTH:
        return [MSG_CASE_ID_TOO_LONG]
    if not CASE_ID_PATTERN.fullmatch(case_id):
        return [MSG_CASE_ID_FORMAT]
    return []


def validate_case_id(case_id, existing_case_ids):
    """정규화된 케이스 ID의 빈 값·형식·중복을 검사하고 오류 문구 목록을 돌려줍니다."""
    if not case_id:
        return [MSG_EMPTY_CASE_ID]
    format_errors = validate_case_id_format(case_id)
    if format_errors:
        return format_errors
    if case_id in existing_case_ids:
        return [MSG_DUPLICATE_CASE_ID]
    return []


def _file_size(file):
    size = getattr(file, "size", None)
    if size is None:
        size = len(file.getvalue())
    return size


def _name_list(names):
    shown = ", ".join(names[:MAX_LISTED_NAMES])
    hidden = len(names) - MAX_LISTED_NAMES
    return f"{shown} 외 {hidden}개" if hidden > 0 else shown


def validate_dicom_selection(files):
    """선택한 파일 목록의 기본 조건을 검사하고 오류 문구 목록을 돌려줍니다.

    files의 각 항목은 Streamlit UploadedFile처럼 name과 size(또는 getvalue())를 가집니다.
    """
    files = list(files or [])
    if not files:
        return [MSG_NO_FILES]

    errors = []
    wrong_type = [
        file.name for file in files
        if PurePath(file.name).suffix.lower().lstrip(".") not in DICOM_EXTENSIONS
    ]
    if wrong_type:
        allowed = ", ".join(f".{ext}" for ext in DICOM_EXTENSIONS)
        errors.append(f"{allowed} 파일만 선택할 수 있어요: {_name_list(wrong_type)}")

    empty = [file.name for file in files if _file_size(file) == 0]
    if empty:
        errors.append(f"내용이 없는 0바이트 파일이 있어요: {_name_list(empty)}")

    return errors


def validate_registration(raw_case_id, existing_case_ids, files):
    """등록 폼 전체를 검사합니다. (정규화된 케이스 ID, 오류 문구 목록)을 돌려줍니다.

    ID 오류와 파일 오류를 한 번에 모두 보여 주기 위해 두 검사를 모두 실행합니다.
    """
    case_id = normalize_case_id(raw_case_id)
    errors = validate_case_id(case_id, existing_case_ids) + validate_dicom_selection(files)
    return case_id, errors
