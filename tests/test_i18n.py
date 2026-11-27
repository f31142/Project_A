from case_list import ALL_STATUSES
from i18n import (
    LANG_EN,
    LANG_KO,
    STRINGS,
    label_case_name,
    label_exam,
    label_method,
    label_roi_mode,
    label_source,
    label_status,
    lang_to_choice,
    method_caption,
    normalize_lang,
    t,
)


def test_normalize_lang_and_choice_roundtrip():
    assert normalize_lang(None) == LANG_KO
    assert normalize_lang("KO") == LANG_KO
    assert normalize_lang("ko") == LANG_KO
    assert normalize_lang("EN") == LANG_EN
    assert normalize_lang("en") == LANG_EN
    assert lang_to_choice(LANG_KO) == "KO"
    assert lang_to_choice(LANG_EN) == "EN"


def test_every_string_key_has_both_ko_and_en():
    for key, entry in STRINGS.items():
        assert LANG_KO in entry and entry[LANG_KO], f"Missing KO for {key}"
        assert LANG_EN in entry and entry[LANG_EN], f"Missing EN for {key}"


def test_domain_label_mappers_preserve_canonical_keys():
    assert label_status(ALL_STATUSES, LANG_KO) == "전체"
    assert label_status(ALL_STATUSES, LANG_EN) == "All"
    assert label_status("검토 중", LANG_EN) == "In Review"
    assert label_status("검토 완료", LANG_EN) == "Done"

    assert label_exam("치료 전 CT", LANG_EN) == "Pre-Tx CT"
    assert label_exam("치료 후 CT", LANG_EN) == "Post-Tx CT"
    assert label_source("synthetic_dicom", LANG_EN) == "Synthetic DICOM"
    assert label_method("CLAHE 대비 보정", LANG_EN) == "CLAHE Contrast"
    assert method_caption("양방향 필터", LANG_EN)
    assert label_roi_mode("영상에서 드래그", LANG_EN) == "Drag on CT"


def test_label_case_name_localizes_synthetic_demo():
    synthetic = {
        "case_id": "demo:HCC_001",
        "display_name": "HCC_001 (AI 생성 테스트용 이미지)",
        "synthetic": True,
    }
    regular = {"case_id": "HCC_004"}
    assert label_case_name(synthetic, LANG_KO) == "HCC_001 (AI 생성 테스트용 이미지)"
    assert label_case_name(synthetic, LANG_EN) == "HCC_001 (AI Synthetic)"
    assert label_case_name(regular, LANG_EN) == "HCC_004"


def test_translation_formatting():
    assert t("app_title", LANG_KO) == "간 CT 검토실"
    assert t("app_title", LANG_EN) == "LIVER CT STUDIO"
    assert t("max_area_button", LANG_EN, slice_number=41) == "Jump to Peak · #41"
