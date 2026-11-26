"""Load the DICOM CT and SEG references used by the case viewer."""

from os import getenv
from pathlib import Path

import streamlit as st

from dicom_ct import DicomReadError, load_ct_series
from dicom_seg import load_tumor_masks

APP_DIR = Path(__file__).resolve().parent
DEMO_CT_CASE = "HCC_004"
DEMO_CT_SERIES_UID = "1.3.6.1.4.1.14519.5.2.1.1706.8374.285388762605622963541285440661"
DEMO_CT_DIR = (
    APP_DIR.parent / "hcc_tace_seg" / DEMO_CT_CASE
    / "1997-10-06-LIVER_PELVIS-14785" / "5-Recon 3_ LIVER 3 PHASE (AP)-40661"
)
DEMO_SEG_FOLDER = "300-Segmentation-39561"


def load_demo_ct():
    directory = Path(getenv("PROJECT_A_CT_DIR") or DEMO_CT_DIR).expanduser()
    try:
        return load_ct_series(directory, expected_series_uid=DEMO_CT_SERIES_UID), None
    except DicomReadError as exc:
        return (), str(exc)


def has_case_ct_reference(case):
    return "image_ref" in case or "series_uid" in case


def case_dicom_path(reference):
    if not isinstance(reference, (str, Path)) or not str(reference).strip():
        raise DicomReadError("케이스의 DICOM 저장 경로가 없어요.")
    location = str(reference).strip()
    if "://" in location:
        raise DicomReadError("앱 서버에서 읽을 수 있는 DICOM 폴더나 파일 경로가 필요해요.")
    try:
        return APP_DIR / Path(location).expanduser()
    except RuntimeError as exc:
        raise DicomReadError("케이스의 DICOM 저장 경로가 올바르지 않아요.") from exc


def load_case_ct(case_id, case):
    if not has_case_ct_reference(case):
        return load_demo_ct() if case_id == DEMO_CT_CASE else ((), None)

    try:
        directory = case_dicom_path(case.get("image_ref"))
        series_uid = case.get("series_uid")
        if not isinstance(series_uid, str) or not series_uid.strip():
            raise DicomReadError("등록된 CT 시리즈 UID가 없어요.")
        return load_ct_series(directory, expected_series_uid=series_uid.strip()), None
    except DicomReadError as exc:
        return (), str(exc)
    except (OSError, ValueError):
        return (), "등록된 CT 폴더를 열 수 없어요. 저장 위치를 확인해 주세요."


@st.cache_resource(show_spinner=False, max_entries=2)
def cached_tumor_masks(seg_source, ct_slices):
    return load_tumor_masks(seg_source[0], ct_slices)


def load_case_seg(case_id, case, ct_slices):
    seg_ref = case.get("seg_ref")
    if not seg_ref:
        if case_id != DEMO_CT_CASE or has_case_ct_reference(case):
            return None, {}, None
        seg_ref = getenv("PROJECT_A_SEG_PATH")

    try:
        if seg_ref:
            path = case_dicom_path(seg_ref)
        else:
            study_dir = ct_slices[0].path.parent.parent
            candidates = list((study_dir / DEMO_SEG_FOLDER).glob("*.dcm"))
            if len(candidates) != 1:
                raise DicomReadError("이 CT와 연결할 DICOM SEG 파일을 확인해 주세요.")
            path = candidates[0]
        stat = path.stat()
        source = (path, stat.st_mtime_ns, stat.st_size)
        return source, cached_tumor_masks(source, ct_slices), None
    except OSError:
        return None, {}, "DICOM SEG 파일을 열 수 없어요."
    except DicomReadError as exc:
        return None, {}, str(exc)
