from base64 import b64encode
from copy import deepcopy
from hashlib import sha256
from html import escape
from io import BytesIO
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw

from ct_analysis import TumorMeasurement, build_analysis_slices, measure_tumor
from ct_case import has_case_ct_reference, load_case_ct, load_case_seg
from dicom_ct import (
    CT_PREVIEW_COLUMNS,
    DicomReadError,
    render_ct_contour_png,
    render_ct_png,
    render_ct_preview_sheet,
)
from i18n import (
    LANG_CHOICES,
    LANG_KO,
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
from roi_analysis import build_measurement_summary, normalize_roi_bounds, summarize_roi

APP_DIR = Path(__file__).resolve().parent
MOCK_CT_DIR = APP_DIR / "assets" / "mock_ct"
CT_PREVIEW_TILE_SIZE = 256

INK = "#09090B"
INK_3 = "#71717A"
LINE = "#E4E4E7"
LINE_STRONG = "#D4D4D8"
STAGE = "#080809"
STAGE_AXIS = "#A1A1AA"
STAGE_ACTIVE = "#FFFFFF"
STAGE_MUTED = "#3F3F46"
CHART_BAR = "#18181B"
SANS_FONT = "IBM Plex Sans KR"
MONO_FONT = "IBM Plex Mono"

REVIEW_STATUSES = ["검토 대기", "검토 중", "검토 완료"]
STATUS_STYLES = {
    "검토 대기": ("waiting", "○"),
    "검토 중": ("progress", "●"),
    "검토 완료": ("done", "✓"),
}
PROCESSING_METHODS = [
    "CLAHE 대비 보정",
    "양방향 필터",
    "Canny 경계 검출",
    "2D 연결 성분 분석",
]
ROI_MODES = ["영상에서 드래그", "좌표 슬라이더"]
LOGO_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" '
    'stroke-width="2.1" stroke-linecap="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="7.5"></circle>'
    '<circle cx="12" cy="12" r="3" stroke-opacity="0.7"></circle></svg>'
)

PERSISTENT_KEY_PREFIXES = (
    "ui_lang",
    "case_query",
    "status_filter",
    "slice_",
    "contour_",
    "compare_processing_",
    "processing_method_",
    "brightness_",
    "show_roi_",
    "roi_mode_",
)


def current_lang() -> str:
    return normalize_lang(st.session_state.get("ui_lang", LANG_KO))


def _sync_language():
    choice = st.session_state.get("ui_lang_control")
    if choice is None:
        st.session_state["ui_lang_control"] = lang_to_choice(current_lang())
        return
    st.session_state["ui_lang"] = normalize_lang(choice)


st.set_page_config(page_title=t("app_title", current_lang()), layout="wide")
st.html("<style>" + (APP_DIR / "assets" / "app.css").read_text(encoding="utf-8") + "</style>")
ct_viewport_component = st.components.v2.component(
    "ct_viewport",
    html=(
        '<div class="ct-view-controls" role="group" aria-label="CT 보기 조작">'
        '<button type="button" data-view-action="zoom-out" aria-label="축소">− 축소</button>'
        '<output aria-label="현재 배율">100%</output>'
        '<button type="button" data-view-action="zoom-in" aria-label="확대">+ 확대</button>'
        '<button type="button" data-view-action="reset">초기화</button>'
        "</div>"
        '<div class="ct-slice-preview" role="region" aria-label="CT 영상" tabindex="0">'
        '<div class="ct-view-content">'
        '<img alt="CT 단면" draggable="false"><canvas hidden aria-hidden="true"></canvas>'
        "</div>"
        "</div>"
    ),
    js=(APP_DIR / "assets" / "ct_slice_preview.js").read_text(encoding="utf-8"),
    isolate_styles=False,
)

for state_key in list(st.session_state.keys()):
    if str(state_key).startswith(PERSISTENT_KEY_PREFIXES):
        st.session_state[state_key] = st.session_state[state_key]


def select_roi_by_drag(source, key):
    width, height = source.size
    preview = source.copy()
    preview.thumbnail((360, 360))
    buffer = BytesIO()
    preview.save(buffer, format="PNG")
    image_url = "data:image/png;base64," + b64encode(buffer.getvalue()).decode("ascii")

    brush = alt.selection_interval(
        name="roi_box",
        encodings=["x", "y"],
        translate=False,
        zoom=False,
        mark=alt.BrushConfig(
            fill=STAGE_ACTIVE,
            fillOpacity=0.14,
            stroke=STAGE_ACTIVE,
            strokeWidth=2,
        ),
    )
    chart = (
        alt.Chart(alt.Data(values=[{"x": width / 2, "y": height / 2, "url": image_url}]))
        .mark_image(
            width=alt.ExprRef(expr="width"),
            height=alt.ExprRef(expr="height"),
            aspect=False,
            tooltip=None,
        )
        .encode(
            x=alt.X("x:Q", axis=None, scale=alt.Scale(domain=[0, width], nice=False)),
            y=alt.Y("y:Q", axis=None, scale=alt.Scale(domain=[height, 0], nice=False)),
            url="url:N",
        )
        .properties(
            width=preview.width,
            height=preview.height,
            padding=0,
            autosize="none",
        )
        .add_params(brush)
        .configure(background=STAGE)
        .configure_view(stroke=None)
    )

    event = st.altair_chart(
        chart,
        key=f"roi_drag_{key}",
        theme=None,
        use_container_width=False,
        on_select="rerun",
    )
    box = event.selection.get("roi_box", {})
    if not box.get("x") or not box.get("y"):
        return None

    return box["x"][0], box["x"][1], box["y"][0], box["y"][1]


initial_cases = {
    "HCC_004": {"exam": "치료 전 CT", "slice_count": 79},
    "HCC_012": {"exam": "치료 후 CT", "slice_count": 86},
    "HCC_018": {"exam": "치료 전 CT", "slice_count": 72},
}

# A 담당(case_ui.py): Firestore에 등록된 케이스와 위 모의 케이스를 합쳐 읽습니다.
import case_ui  # noqa: E402

cases = case_ui.load_cases(initial_cases)

mock_ct_images = {
    "HCC_004": {
        34: "slice_034.png",
        41: "slice_041.png",
        50: "slice_050.png",
    },
}

mock_measurements = {
    "HCC_004": TumorMeasurement(areas_mm2={34: 2960, 41: 3190, 50: 1570}, volume_ml=154.8),
}

review_statuses = st.session_state.setdefault("review_statuses", {})
uploads_by_case = st.session_state.setdefault("uploaded_ct_images", {})
notes_by_case = st.session_state.setdefault("review_notes", {})
roi_by_slice = st.session_state.setdefault("roi_by_slice", {})


def set_review_status(case_id, status):
    st.session_state["review_statuses"][case_id] = status


def open_viewer(case_id):
    st.session_state["viewer_case_id"] = case_id


def close_viewer(case_id):
    st.session_state["selected_case_id"] = case_id
    st.session_state.pop("viewer_case_id", None)


def move_to_slice(slice_key, number, total_slices):
    st.session_state[slice_key] = min(max(number, 1), total_slices)


def keep_choice(key, fallback):
    if st.session_state.get(key) is None:
        st.session_state[key] = fallback


@st.cache_data(show_spinner=False)
def image_data_url(image_bytes, max_side=480):
    with Image.open(BytesIO(image_bytes)) as image:
        preview = image.convert("RGB")
    preview.thumbnail((max_side, max_side))
    buffer = BytesIO()
    preview.save(buffer, format="PNG")
    return "data:image/png;base64," + b64encode(buffer.getvalue()).decode("ascii")


def status_badge(status, lang=LANG_KO):
    style_key = STATUS_STYLES[status][0]
    return f'<span class="badge badge-{style_key}">{escape(label_status(status, lang))}</span>'


def render_app_bar(case_name=None):
    lang = current_lang()
    st.session_state.setdefault("ui_lang", lang)
    st.session_state.setdefault("ui_lang_control", lang_to_choice(lang))

    if case_name is None:
        crumbs = f'<span class="is-current">{escape(t("case_list_title", lang))}</span>'
    else:
        crumbs = (
            f'<span>{escape(t("case_list_title", lang))}</span>'
            '<span aria-hidden="true">/</span>'
            f'<span class="is-current mono">{escape(case_name)}</span>'
        )
    st.html(
        '<header class="appbar"><div class="appbar-inner">'
        f'<span class="appbar-logo">{LOGO_SVG}</span>'
        f'<span class="appbar-name">{escape(t("app_title", lang))}</span>'
        '<span class="appbar-divider"></span>'
        f'<nav class="appbar-crumbs" aria-label="{escape(t("nav_aria", lang))}">{crumbs}</nav>'
        f'<span class="appbar-badge">{escape(t("app_badge", lang))}</span>'
        "</div></header>"
    )
    with st.container(key="lang_switcher"):
        st.segmented_control(
            t("lang_aria", lang),
            list(LANG_CHOICES),
            key="ui_lang_control",
            on_change=_sync_language,
            label_visibility="collapsed",
        )


def section_heading(number, title, description, anchor):
    desc_html = f'<span class="section-desc">{escape(description)}</span>' if description else ""
    return (
        f'<div class="section-head" id="{anchor}">'
        f'<span class="section-num">{number}</span>'
        f'<h2 class="section-title">{escape(title)}</h2>'
        f"{desc_html}"
        "</div>"
    )


def render_measurement_values(summary, lang=LANG_KO):
    name = label_case_name(cases[summary["case_id"]], lang)
    st.caption(
        t(
            "summary_caption_line",
            lang,
            name=name,
            slice_number=summary["slice_number"],
            source=label_source(summary["source"], lang),
        )
    )
    area = summary["tumor_area_cm2"]
    volume = summary["tumor_volume_ml"]
    area_col, volume_col = st.columns(2)
    area_col.metric(
        t("summary_metric_area", lang),
        f"{area:.1f} cm²" if area is not None else t("no_measurement", lang),
    )
    volume_col.metric(
        t("summary_metric_volume", lang),
        f"{volume:.1f} mL" if volume is not None else t("no_measurement", lang),
    )
    roi = summary["roi"]
    if roi is None:
        st.caption(t("summary_no_roi", lang))
        return
    bounds = roi["bounds"]
    text = t(
        "summary_roi_line",
        lang,
        x0=bounds["x0"],
        x1=bounds["x1"] - 1,
        y0=bounds["y0"],
        y1=bounds["y1"] - 1,
        pixels=roi["pixel_count"],
        mean=roi["mean_brightness"],
    )
    if roi["area_mm2"] is not None:
        text += t("summary_roi_area_suffix", lang, area=roi["area_mm2"])
    st.caption(text)


def case_slice_numbers(case_id):
    mock_slices = set(mock_ct_images.get(case_id, {}))
    uploaded = set(uploads_by_case.get(case_id, {}))
    return sorted(mock_slices | uploaded)


def load_slice_bytes(case_id, number):
    uploaded = uploads_by_case.get(case_id, {}).get(number)
    if uploaded is not None:
        return uploaded
    file_name = mock_ct_images.get(case_id, {}).get(number)
    if file_name and (MOCK_CT_DIR / file_name).is_file():
        return (MOCK_CT_DIR / file_name).read_bytes()
    return None


@st.cache_data(show_spinner=False, max_entries=2)
def ct_preview_sheet(files: tuple[tuple[Path, int], ...], seg_source=None, _masks=None) -> bytes:
    # seg_source keeps the normal and annotated preview sheets in separate cache entries.
    paths = tuple(path for path, _ in files)
    return render_ct_preview_sheet(paths, CT_PREVIEW_TILE_SIZE, masks=_masks)


def render_ct_viewport(
    image_source,
    viewer_id,
    slice_number,
    slice_count,
    dicom_slices,
    *,
    lang=LANG_KO,
    seg_source=None,
    masks=None,
):
    # Streamlit serves these images at stable media URLs across reruns.
    with st.container(key=f"ct_full_slice_{slice_number}"):
        st.image(image_source, width="stretch", output_format="PNG")
    if len(dicom_slices) > 1:
        try:
            files = tuple((item.path, item.path.stat().st_mtime_ns) for item in dicom_slices)
            sheet = ct_preview_sheet(files, seg_source, _masks=masks)
        except (DicomReadError, OSError):
            sheet = None
        if sheet is not None:
            with st.container(key="ct_preview_sheet"):
                st.image(sheet, width=CT_PREVIEW_TILE_SIZE * CT_PREVIEW_COLUMNS, output_format="JPEG")

    ct_viewport_component(
        key=f"ct_viewport_{viewer_id}_{lang}",
        data={
            "caseId": viewer_id,
            "tileSize": CT_PREVIEW_TILE_SIZE,
            "sliceCount": slice_count,
            "slicePrefix": t("slice_prefix", lang),
            "labels": {
                "zoomOut": t("zoom_out", lang),
                "zoomIn": t("zoom_in", lang),
                "reset": t("zoom_reset", lang),
                "zoomOutAria": t("zoom_out_aria", lang),
                "zoomInAria": t("zoom_in_aria", lang),
                "controlsAria": t("zoom_controls_aria", lang),
                "readoutAria": t("zoom_readout_aria", lang),
                "imageAria": t("ct_image_aria", lang),
                "imageAlt": t("ct_image_alt", lang),
            },
        },
    )


def chart_axis_style(chart):
    return (
        chart.configure(background="#FFFFFF")
        .configure_axis(
            labelFont=MONO_FONT,
            labelFontSize=10.5,
            labelColor=INK_3,
            titleFont=SANS_FONT,
            titleFontSize=11,
            titleFontWeight=500,
            titleColor=INK_3,
            gridColor=LINE,
            domainColor=LINE_STRONG,
            tickColor=LINE_STRONG,
        )
        .configure_view(stroke=None)
    )


def render_case_list():
    lang = current_lang()
    render_app_bar()
    case_ui.render_storage_notice(lang=lang)

    title_col, action_col = st.columns([3, 1], vertical_alignment="bottom")
    title_col.html(
        f'<h1 class="page-title">{escape(t("case_list_title", lang))}</h1>'
        f'<p class="page-desc">{escape(t("case_list_desc", lang))}</p>'
    )
    with action_col.container(horizontal=True, horizontal_alignment="right"):
        with st.popover(t("register_case", lang), icon=":material/add:"):
            case_ui.render_register_form(cases, lang=lang)

    list_col, detail_col = st.columns([2.35, 1], gap="large")
    selected_case = None

    with list_col:
        selected_case = case_ui.render_case_table(
            cases,
            review_statuses,
            REVIEW_STATUSES,
            {status: mark for status, (_, mark) in STATUS_STYLES.items()},
            lang=lang,
        )

    with detail_col.container(border=True, key="card_detail", gap="medium"):
        if selected_case is None:
            st.html(
                '<div class="detail-head">'
                f'<span class="overline">{escape(t("selected_case_overline", lang))}</span>'
                f'<div class="thumb-empty">{escape(t("select_case_prompt", lang))}</div></div>'
            )
            return

        selected_id = selected_case["케이스 ID"]
        case = cases[selected_id]
        display_name = escape(label_case_name(case, lang))
        ct_slices, ct_error = load_case_ct(selected_id, case)
        registered_ct = has_case_ct_reference(case)
        slice_count = len(ct_slices) if ct_slices else selected_case["단면 수"]
        if ct_slices or registered_ct:
            image_label = t("dicom_image_label", lang)
            image_text = (
                t("slice_count_text", lang, count=len(ct_slices))
                if ct_slices
                else t("cannot_open", lang)
            )
            volume_label = t("tumor_volume_label", lang)
            preview_bytes = None
            measurement = None
            if ct_slices:
                preview_number = (len(ct_slices) + 1) // 2
                try:
                    preview_bytes = render_ct_png(ct_slices[preview_number - 1].path)
                except DicomReadError as exc:
                    ct_error = str(exc)
                _, tumor_masks, _ = load_case_seg(selected_id, case, ct_slices)
                measurement = measure_tumor(build_analysis_slices(ct_slices, tumor_masks))
        else:
            slices = case_slice_numbers(selected_id)
            preview_number = 41 if 41 in slices else (slices[0] if slices else None)
            preview_bytes = load_slice_bytes(selected_id, preview_number) if preview_number else None
            image_label = t("mock_image_label", lang)
            image_text = (
                t("mock_slices_text", lang, slices=" · ".join(map(str, slices)))
                if slices
                else t("none", lang)
            )
            volume_label = t("mock_volume_label", lang)
            measurement = mock_measurements.get(selected_id)

        if preview_bytes is not None:
            alt_text = escape(t("thumb_alt", lang, name=label_case_name(case, lang), number=preview_number))
            chip_text = escape(t("key_slice_chip", lang, current=preview_number, total=slice_count))
            thumbnail = (
                '<div class="thumb">'
                f'<img src="{image_data_url(preview_bytes)}" alt="{alt_text}">'
                f'<span class="thumb-chip">{chip_text}</span>'
                "</div>"
            )
        else:
            missing = t("no_dicom_preview", lang) if registered_ct else t("no_attached_image", lang)
            thumbnail = f'<div class="thumb-empty">{escape(missing)}</div>'

        count_text = t("slice_count_text", lang, count=slice_count) if slice_count is not None else "—"
        volume_ml = measurement.volume_ml if measurement is not None else None
        volume_text = f"{volume_ml:.1f} mL" if volume_ml is not None else "—"
        volume_class = ' class="is-measure"' if volume_ml is not None else ""

        st.html(
            '<div class="detail-head">'
            f'<span class="overline">{escape(t("selected_case_overline", lang))}</span>'
            '<div class="detail-title">'
            f'<span class="case-id">{display_name}</span>'
            f"{status_badge(selected_case['검토 상태'], lang)}"
            "</div></div>"
            f"{thumbnail}"
            '<dl class="facts">'
            f"<div><dt>{escape(t('col_exam_type', lang))}</dt>"
            f"<dd>{escape(label_exam(str(selected_case['검사 종류']), lang))}</dd></div>"
            f"<div><dt>{escape(t('col_slice_count', lang))}</dt><dd>{escape(count_text)}</dd></div>"
            f"<div><dt>{escape(image_label)}</dt><dd>{escape(image_text)}</dd></div>"
            f"<div><dt>{escape(volume_label)}</dt><dd{volume_class}>{escape(volume_text)}</dd></div>"
            "</dl>"
        )
        if ct_error and registered_ct:
            st.warning(ct_error)
        st.button(
            t("open_viewer", lang),
            type="primary",
            icon=":material/arrow_forward:",
            width="stretch",
            on_click=open_viewer,
            args=(selected_id,),
        )


def render_viewer(viewer_id):
    lang = current_lang()
    case = cases[viewer_id]
    registered_ct = has_case_ct_reference(case)
    dicom_slices, dicom_error = load_case_ct(viewer_id, case)
    is_dicom = bool(dicom_slices)
    use_mock = not (registered_ct or is_dicom)
    seg_source, tumor_masks, seg_error = (
        load_case_seg(viewer_id, case, dicom_slices) if is_dicom else (None, {}, None)
    )
    total_slices = len(dicom_slices) if is_dicom else (case.get("slice_count") or 1)
    slice_key = f"slice_{viewer_id}"
    contour_key = f"contour_{viewer_id}"
    case_images = mock_ct_images.get(viewer_id, {}) if use_mock else {}
    analysis_slices = build_analysis_slices(dicom_slices, tumor_masks)
    measurement = mock_measurements.get(viewer_id) if use_mock else measure_tumor(analysis_slices)
    areas_cm2 = (
        {number: area / 100 for number, area in measurement.areas_mm2.items()}
        if measurement is not None
        else {}
    )
    area_title = t("area_title_dicom", lang) if is_dicom else t("area_title_mock", lang)
    uploaded_slices = uploads_by_case.setdefault(viewer_id, {}) if use_mock else {}
    case_notes = notes_by_case.setdefault(viewer_id, [])
    viewer_status = review_statuses.get(viewer_id, "검토 대기")

    if total_slices == 1:
        slice_number = 1
    else:
        move_to_slice(slice_key, st.session_state.get(slice_key, 1), total_slices)
        slice_number = st.session_state[slice_key]

    display_name = label_case_name(case, lang)
    render_app_bar(display_name)

    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        st.button(
            t("back_to_list", lang),
            key="back_to_list",
            icon=":material/arrow_back:",
            type="tertiary",
            on_click=close_viewer,
            args=(viewer_id,),
        )
        meta = label_exam(str(case.get("exam") or "CT 검사"), lang)
        if not (registered_ct and dicom_error):
            meta += " · " + t("meta_slices", lang, count=total_slices)
        if measurement is not None and use_mock:
            meta += " · " + t("meta_mock_measurements", lang)
        st.html(
            '<div class="viewer-title">'
            '<div class="viewer-title-row">'
            f'<h1 class="viewer-id">{escape(display_name)}</h1>{status_badge(viewer_status, lang)}'
            "</div>"
            f'<span class="caption">{escape(meta)}</span>'
            "</div>",
            width="stretch",
        )

        if use_mock:
            with st.popover(t("attach_png", lang), icon=":material/attach_file:"):
                with st.form(f"attach_ct_{viewer_id}_{slice_number}", clear_on_submit=True):
                    png_file = st.file_uploader(t("mock_ct_png", lang), type=["png"])
                    attach_clicked = st.form_submit_button(t("attach_submit", lang), type="primary")

                if attach_clicked:
                    if png_file is None:
                        st.warning(t("attach_warning", lang))
                    else:
                        image_bytes = png_file.getvalue()
                        try:
                            with Image.open(BytesIO(image_bytes), formats=("PNG",)) as image:
                                image.load()
                        except (OSError, SyntaxError, Image.DecompressionBombError):
                            st.error(t("attach_invalid", lang))
                        else:
                            uploaded_slices[slice_number] = image_bytes
                            st.success(
                                t("attach_success", lang, case_id=viewer_id, slice_number=slice_number)
                            )

        if viewer_status == "검토 대기":
            st.button(
                t("start_review", lang),
                key=f"start_review_{viewer_id}",
                type="primary",
                icon=":material/play_arrow:",
                on_click=set_review_status,
                args=(viewer_id, "검토 중"),
            )
        elif viewer_status == "검토 중":
            st.button(
                t("complete_review", lang),
                key=f"complete_review_{viewer_id}",
                type="primary",
                icon=":material/check:",
                on_click=set_review_status,
                args=(viewer_id, "검토 완료"),
            )

    if dicom_error:
        if registered_ct:
            st.error(t("dicom_open_error", lang, error=dicom_error))
            return
        st.warning(t("dicom_fallback_warning", lang, error=dicom_error))

    uploaded_image = uploaded_slices.get(slice_number)
    original_bytes = uploaded_image
    file_name = case_images.get(slice_number)
    overlay_path = None
    image_error = None
    tumor_mask = None

    if is_dicom:
        analysis_slice = analysis_slices[slice_number - 1]
        tumor_mask = analysis_slice.tumor_mask
        try:
            original_bytes = analysis_slice.display_png()
        except DicomReadError as exc:
            image_error = str(exc)
    elif uploaded_image is None and file_name:
        candidate = MOCK_CT_DIR / file_name
        if candidate.is_file():
            original_bytes = candidate.read_bytes()
            overlay_candidate = candidate.with_name(f"{candidate.stem}_overlay.png")
            if overlay_candidate.is_file():
                overlay_path = overlay_candidate
        else:
            image_error = f"{file_name}"

    ct_slice = analysis_slice.ct_slice if is_dicom else None
    source_kind = "dicom" if is_dicom else "mock"
    if is_dicom and case.get("synthetic"):
        source_kind = "synthetic_dicom"
    image_hash = None
    roi_key = None
    if ct_slice is not None:
        roi_key = f"{viewer_id}_{ct_slice.series_instance_uid}_{ct_slice.sop_instance_uid}"
    elif original_bytes is not None:
        if uploaded_image is not None:
            source_kind = "uploaded_png"
        image_hash = sha256(original_bytes).hexdigest()
        roi_key = f"{viewer_id}_mock_{slice_number}_{image_hash}"

    summary = build_measurement_summary(
        case_id=viewer_id,
        slice_number=slice_number,
        source=source_kind,
        ct_slice=ct_slice,
        image_sha256=image_hash,
        measurement=measurement,
    )

    overlay_slices = [
        number
        for number, name in sorted(case_images.items())
        if (MOCK_CT_DIR / f"{Path(name).stem}_overlay.png").is_file()
    ]
    contour_requested = st.session_state.get(contour_key, False)
    show_mock_contour = overlay_path is not None and contour_requested
    show_dicom_contour = bool(tumor_masks) and contour_requested
    image_source = str(overlay_path) if show_mock_contour else original_bytes
    if show_dicom_contour and tumor_mask is not None and original_bytes is not None:
        try:
            image_source = render_ct_contour_png(original_bytes, tumor_mask)
        except DicomReadError as exc:
            seg_error = str(exc)
            show_dicom_contour = False

    stage_col, side_col = st.columns([2.75, 1], gap="medium")

    with stage_col.container(key="stage"):
        source_label = label_source(source_kind, lang)
        contour_chip = ""
        if show_dicom_contour:
            contour_chip = f'<span class="chip is-contour">{escape(t("contour_on_dicom", lang))}</span>'
        elif show_mock_contour:
            contour_chip = f'<span class="chip is-contour">{escape(t("contour_on_mock", lang))}</span>'
        slice_prefix = escape(t("slice_prefix", lang))
        st.html(
            '<div class="stage-bar"><div class="stage-chips">'
            f'<span class="chip is-strong" data-slice-prefix="{slice_prefix}">{slice_prefix} {slice_number} / {total_slices}</span>'
            f'<span class="chip">{escape(source_label)}</span>'
            f"</div>{contour_chip}</div>"
        )

        with st.container(key="stage_image"):
            if image_source is not None:
                render_ct_viewport(
                    image_source,
                    viewer_id,
                    slice_number,
                    total_slices,
                    dicom_slices,
                    lang=lang,
                    seg_source=seg_source if show_dicom_contour else None,
                    masks=tumor_masks if show_dicom_contour else None,
                )
            else:
                if image_error:
                    hint = escape(image_error)
                elif case_images:
                    available = " · ".join(str(number) for number in sorted(case_images))
                    hint = escape(t("stage_empty_available", lang, available=available))
                else:
                    hint = escape(t("stage_empty_upload", lang))
                st.html(
                    '<div class="stage-empty">'
                    f'<strong>{escape(t("stage_empty_title", lang, slice_number=slice_number))}</strong>'
                    f"<span>{hint}</span>"
                    "</div>"
                )

        if total_slices > 1:
            with st.container(horizontal=True, vertical_alignment="center", gap="small", key="slice_row"):
                st.button(
                    "",
                    key=f"prev_slice_{viewer_id}",
                    icon=":material/chevron_left:",
                    help=t("prev_slice", lang),
                    on_click=move_to_slice,
                    args=(slice_key, slice_number - 1, total_slices),
                    disabled=slice_number <= 1,
                )
                st.slider(
                    t("slice_slider_label", lang),
                    min_value=1,
                    max_value=total_slices,
                    key=slice_key,
                    label_visibility="collapsed",
                    width="stretch",
                )
                st.button(
                    "",
                    key=f"next_slice_{viewer_id}",
                    icon=":material/chevron_right:",
                    help=t("next_slice", lang),
                    on_click=move_to_slice,
                    args=(slice_key, slice_number + 1, total_slices),
                    disabled=slice_number >= total_slices,
                )

        if areas_cm2:
            measurements = []
            for number, area in areas_cm2.items():
                measurements.append({
                    "slice_number": number,
                    "area_cm2": area,
                    "is_current": number == slice_number,
                    "label": f"{number} · {area:.1f} cm²",
                })
            chart_key = f"area_chart_{viewer_id}_{slice_number}_{lang}"

            def move_to_selected_slice():
                chart_selection = st.session_state[chart_key]["selection"]
                points = chart_selection.get("area_point", [])
                if points:
                    move_to_slice(slice_key, int(points[0]["slice_number"]), total_slices)

            point_selection = alt.selection_point(
                name="area_point",
                fields=["slice_number"],
                on="click",
                toggle=False,
            )
            tick_values = sorted({1, total_slices} | set(range(20, total_slices, 20)))
            x = alt.X(
                "slice_number:Q",
                title=None,
                scale=alt.Scale(domain=[1, total_slices], nice=False, zero=False),
                axis=alt.Axis(
                    values=tick_values,
                    format="d",
                    labelColor=STAGE_AXIS,
                    labelFont=MONO_FONT,
                    labelFontSize=10.5,
                    domainColor="#27272A",
                    ticks=False,
                    grid=False,
                    labelPadding=8,
                ),
            )
            max_area_slice = max(areas_cm2, key=areas_cm2.get)
            max_area = areas_cm2[max_area_slice]
            y = alt.Y(
                "area_cm2:Q",
                axis=None,
                scale=alt.Scale(domain=[0, max_area * 1.4]),
            )
            slice_intervals = max(1, total_slices - 1)
            chart = (
                alt.Chart(alt.Data(values=measurements))
                .mark_bar(
                    width=alt.ExprRef(expr=f"min(11, width / {slice_intervals} * 0.78)"),
                    cornerRadiusTopLeft=4,
                    cornerRadiusTopRight=4,
                    cursor="pointer",
                )
                .encode(
                    x=x,
                    y=y,
                    color=alt.condition(
                        "datum.is_current",
                        alt.value(STAGE_ACTIVE),
                        alt.value(STAGE_MUTED),
                    ),
                    tooltip=[
                        alt.Tooltip("slice_number:Q", title=t("tooltip_slice", lang)),
                        alt.Tooltip("area_cm2:Q", title=f"{area_title} (cm²)", format=".1f"),
                    ],
                )
                .add_params(point_selection)
                .properties(height=104, padding={"left": 48, "right": 48, "top": 6, "bottom": 4})
                .configure(background=STAGE)
                .configure_view(stroke=None)
            )

            st.html(
                '<div class="stage-label">'
                f'<strong>{escape(t("area_chart_title", lang, area_title=area_title))}</strong>'
                f'<span>{escape(t("area_chart_hint", lang))}</span>'
                "</div>"
            )
            st.altair_chart(
                chart,
                key=chart_key,
                on_select=move_to_selected_slice,
                theme=None,
                width="stretch",
            )
            st.button(
                t("max_area_button", lang, slice_number=max_area_slice),
                key=f"max_area_slice_{viewer_id}",
                on_click=move_to_slice,
                args=(slice_key, max_area_slice, total_slices),
                disabled=slice_number == max_area_slice,
            )

    with side_col:
        current_area = summary["tumor_area_cm2"]
        if current_area is not None:
            slice_value = (
                f'<span class="metric-value">{current_area:.1f}'
                '<span class="metric-unit">cm²</span></span>'
            )
            slice_caption = area_title
        else:
            slice_value = f'<span class="metric-value is-empty">{escape(t("no_measurement", lang))}</span>'
            if is_dicom:
                if measurement is not None:
                    slice_caption = t("no_seg_this_slice", lang)
                elif seg_error:
                    slice_caption = seg_error
                elif seg_source is None:
                    slice_caption = t("no_seg_connected", lang)
                else:
                    slice_caption = t("empty_seg_mask", lang)
            elif uploaded_image is not None:
                slice_caption = t("uploaded_no_measurement", lang)
            elif areas_cm2:
                measured = " · ".join(str(number) for number in sorted(areas_cm2))
                slice_caption = t("measured_slices_hint", lang, slices=measured)
            else:
                slice_caption = t("no_mock_measurements", lang)

        volume_ml = summary["tumor_volume_ml"]
        if volume_ml is None:
            case_value = '<span class="metric-value is-small is-empty">—</span>'
        else:
            case_value = (
                f'<span class="metric-value is-small">{volume_ml:.1f}'
                '<span class="metric-unit">mL</span></span>'
            )
        volume_caption = t("volume_caption_dicom", lang) if is_dicom else t("volume_caption_mock", lang)
        volume_error = (
            f'<span class="metric-caption">{escape(measurement.volume_error)}</span>'
            if measurement is not None and measurement.volume_error
            else ""
        )
        st.html(
            '<div class="metric is-slice">'
            f'<span class="overline"><span class="dot"></span>'
            f'{escape(t("this_slice_overline", lang, current=slice_number, total=total_slices))}</span>'
            f'{slice_value}<span class="metric-caption">{escape(slice_caption)}</span>'
            "</div>"
            '<div class="metric" style="margin-top: 10px">'
            f'<span class="overline">{escape(t("whole_case_overline", lang))}</span>'
            f'{case_value}<span class="metric-caption">{escape(volume_caption)}</span>{volume_error}'
            "</div>"
        )

        with st.container(border=True, key="card_display", gap="small"):
            contour_available = bool(tumor_masks) and not seg_error if is_dicom else overlay_path is not None
            with st.container(key="contour_row"):
                st.toggle(t("contour_toggle", lang), key=contour_key, disabled=not contour_available)
            if seg_error:
                contour_caption = seg_error
            elif is_dicom and tumor_mask is not None:
                contour_caption = t("contour_caption_dicom", lang)
            elif is_dicom and tumor_masks:
                contour_caption = t("contour_caption_dicom_none", lang)
            elif is_dicom and seg_source is None:
                contour_caption = t("no_seg_connected", lang)
            elif is_dicom:
                contour_caption = t("empty_seg_mask", lang)
            elif overlay_path is not None:
                contour_caption = t("contour_caption_mock", lang)
            elif overlay_slices:
                listed = " · ".join(str(number) for number in overlay_slices)
                contour_caption = t("contour_caption_mock_available", lang, slices=listed)
            else:
                contour_caption = t("contour_caption_none", lang)
            st.html(f'<span class="caption">{escape(contour_caption)}</span>')

        st.html(
            f'<nav class="jump" aria-label="{escape(t("jump_overline", lang))}">'
            f'<span class="overline">{escape(t("jump_overline", lang))}</span>'
            f'<a href="#section-processing"><span><span class="mono">02</span>{escape(t("sec_02_title", lang))}</span><span>→</span></a>'
            f'<a href="#section-roi"><span><span class="mono">03</span>{escape(t("sec_03_title", lang))}</span><span>→</span></a>'
            f'<a href="#section-summary"><span><span class="mono">04</span>{escape(t("sec_04_title", lang))}</span><span>→</span></a>'
            f'<a href="#section-memo"><span><span class="mono">05</span>{escape(t("sec_05_title", lang))}</span><span>→</span></a>'
            "</nav>"
        )

    with st.container(border=True, key="card_processing", gap="medium"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html(
                section_heading(
                    "02",
                    t("sec_02_title", lang),
                    t("sec_02_desc", lang),
                    "section-processing",
                ),
                width="stretch",
            )
            compare_enabled = st.toggle(
                t("toggle_compare", lang),
                key=f"compare_processing_{viewer_id}",
                disabled=original_bytes is None,
            )

        if original_bytes is None:
            st.html(f'<div class="notice">{escape(t("need_slice_image", lang))}</div>')
        elif compare_enabled:
            controls_column, images_column = st.columns([1, 2.6], gap="large")

            with controls_column:
                use_brightness = st.checkbox(
                    t("use_brightness", lang),
                    key=f"brightness_enabled_{viewer_id}",
                )
                method = st.radio(
                    t("processing_tool", lang),
                    PROCESSING_METHODS,
                    format_func=lambda item: label_method(item, lang),
                    captions=[method_caption(item, lang) for item in PROCESSING_METHODS],
                    disabled=use_brightness,
                    key=f"processing_method_algorithm_{viewer_id}",
                )
                if use_brightness:
                    method = "밝기 보정"

                with Image.open(BytesIO(original_bytes)) as image:
                    original = np.array(image.convert("RGB"))

                result = None
                factor = 1.0

                if method == "밝기 보정":
                    brightness_key = f"brightness_{viewer_id}"
                    st.session_state.setdefault(brightness_key, 1.0)
                    factor = st.slider(
                        t("brightness_factor", lang),
                        min_value=0.5,
                        max_value=2.0,
                        step=0.1,
                        format="×%.1f",
                        key=brightness_key,
                    )
                    scaled = original.astype(np.float32) * factor
                    result = np.clip(scaled, 0, 255).astype(np.uint8)
                    st.html(f'<span class="caption">{escape(t("brightness_hint", lang))}</span>')

                elif method == "CLAHE 대비 보정":
                    st.slider(t("clahe_clip", lang), 1.0, 5.0, 2.0, 0.1)
                    st.select_slider(t("clahe_tile", lang), options=[4, 8, 16], value=8)

                elif method == "양방향 필터":
                    st.slider(t("bilateral_sigma", lang), 1, 150, 50)

                elif method == "Canny 경계 검출":
                    st.slider(t("canny_thresh", lang), 0, 255, (50, 150))

                elif method == "2D 연결 성분 분석":
                    st.caption(t("cc_caption", lang))

            with images_column:
                original_column, result_column = st.columns(2, gap="medium")
                with original_column.container(key="tile_original"):
                    st.image(original, width="stretch")
                    st.html(
                        '<div class="tile-caption">'
                        f'<span>{escape(t("tile_original", lang, slice_number=slice_number))}</span>'
                        '<span class="mono">×1.0</span></div>'
                    )
                with result_column.container(key="tile_result"):
                    method_label = label_method(method, lang)
                    result_caption = (
                        f'<span>{escape(t("tile_result", lang, method=method_label, slice_number=slice_number))}</span>'
                    )
                    if result is None:
                        st.html(f'<div class="tile-empty">{escape(t("tile_empty", lang))}</div>')
                    else:
                        st.image(result, width="stretch")
                        result_caption += f'<span class="mono is-accent">×{factor:.1f}</span>'
                    st.html(f'<div class="tile-caption">{result_caption}</div>')

    with st.container(border=True, key="card_roi", gap="medium"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html(
                section_heading(
                    "03",
                    t("sec_03_title", lang),
                    t("sec_03_desc", lang),
                    "section-roi",
                ),
                width="stretch",
            )
            roi_enabled = st.toggle(
                t("toggle_roi", lang),
                key=f"show_roi_{viewer_id}",
                disabled=original_bytes is None,
            )

        saved_bounds = roi_by_slice.get(roi_key)
        bounds = saved_bounds
        if original_bytes is not None and (roi_enabled or saved_bounds is not None):
            with Image.open(BytesIO(original_bytes)) as image:
                source = image.convert("RGB")
            gray = np.array(source.convert("L"))

        if original_bytes is None:
            st.html(f'<div class="notice">{escape(t("need_slice_image", lang))}</div>')
        elif roi_enabled:
            height, width = gray.shape
            mode_key = f"roi_mode_{viewer_id}"
            st.session_state.setdefault(mode_key, ROI_MODES[0])
            st.segmented_control(
                t("roi_mode_label", lang),
                ROI_MODES,
                format_func=lambda item: label_roi_mode(item, lang),
                key=mode_key,
                on_change=keep_choice,
                args=(mode_key, ROI_MODES[0]),
            )
            mode = st.session_state.get(mode_key) or ROI_MODES[0]
            preview_column, stats_column = st.columns([1, 1.25], gap="large")

            if mode == "좌표 슬라이더":
                x_key = f"roi_x_{roi_key}"
                y_key = f"roi_y_{roi_key}"
                default_x = saved_bounds[:2] if saved_bounds else (width // 4, width - width // 4)
                default_y = saved_bounds[2:] if saved_bounds else (height // 4, height - height // 4)
                st.session_state.setdefault(x_key, default_x)
                st.session_state.setdefault(y_key, default_y)
                x0, x1 = preview_column.slider(t("roi_x_range", lang), 0, width, key=x_key)
                y0, y1 = preview_column.slider(t("roi_y_range", lang), 0, height, key=y_key)
                raw_bounds = x0, x1, y0, y1

            roi_preview = preview_column.container(key="tile_roi")
            if mode == "영상에서 드래그":
                with roi_preview:
                    raw_bounds = select_roi_by_drag(source, roi_key)
                    st.html(
                        f'<div class="tile-caption"><span>{escape(t("roi_drag_caption", lang))}</span></div>'
                    )

            bounds = normalize_roi_bounds(raw_bounds, width, height)
            if raw_bounds is None:
                bounds = saved_bounds
            elif bounds is not None:
                roi_by_slice[roi_key] = bounds

            if bounds is None and raw_bounds is None:
                stats_column.html(f'<div class="notice">{escape(t("roi_prompt", lang))}</div>')
            elif bounds is None:
                stats_column.html(
                    f'<div class="notice is-warning">{escape(t("roi_min_warning", lang))}</div>'
                )
        if original_bytes is not None and bounds is not None:
            spacing = ct_slice.pixel_spacing_mm if ct_slice else None
            roi, counts = summarize_roi(gray, bounds, spacing)
            summary["roi"] = roi
            if roi_enabled:
                x0, x1, y0, y1 = bounds
                roi_mean = roi["mean_brightness"]
                pixel_count = roi["pixel_count"]

                if mode == "좌표 슬라이더" or raw_bounds is None:
                    preview = source.copy()
                    ImageDraw.Draw(preview).rectangle(
                        (x0, y0, x1 - 1, y1 - 1),
                        outline=STAGE_ACTIVE,
                        width=3,
                    )
                    with roi_preview:
                        st.image(preview, width="stretch")
                        st.html(
                            '<div class="tile-caption">'
                            f'<span>{escape(t("roi_selected_caption", lang, slice_number=slice_number))}</span>'
                            "</div>"
                        )

                histogram = pd.DataFrame({"brightness": np.arange(256), "pixels": counts})
                bars = (
                    alt.Chart(histogram)
                    .mark_area(interpolate="step-after", color=CHART_BAR, opacity=0.90)
                    .encode(
                        x=alt.X(
                            "brightness:Q",
                            title=t("axis_brightness", lang),
                            scale=alt.Scale(domain=[0, 255], nice=False),
                            axis=alt.Axis(values=[0, 64, 128, 192, 255], grid=False),
                        ),
                        y=alt.Y(
                            "pixels:Q",
                            title=t("axis_pixels", lang),
                            axis=alt.Axis(grid=True, tickCount=4, tickMinStep=1),
                        ),
                        tooltip=[
                            alt.Tooltip("brightness:Q", title=t("tooltip_brightness", lang)),
                            alt.Tooltip("pixels:Q", title=t("tooltip_pixels", lang)),
                        ],
                    )
                )
                mean_rule = (
                    alt.Chart(alt.Data(values=[{"mean": roi_mean}]))
                    .mark_rule(color=INK, strokeDash=[4, 3], strokeWidth=1.5)
                    .encode(x="mean:Q")
                )
                with stats_column.container(border=True, key="card_histogram", gap="small"):
                    st.html(
                        '<div class="roi-result-metrics">'
                        f'<div>{escape(t("roi_mean_label", lang))} <strong>{roi_mean:.1f}</strong></div>'
                        f'<div>{escape(t("roi_size_label", lang))} <strong>{x1 - x0} × {y1 - y0} px</strong>'
                        f'<span>{escape(t("roi_pixel_total", lang, count=pixel_count))}</span></div>'
                        "</div>"
                        '<div class="roi-chart-heading">'
                        f'<strong>{escape(t("roi_hist_heading", lang))}</strong>'
                        f'<span class="roi-mean-legend">{escape(t("roi_mean_legend", lang))}</span>'
                        "</div>"
                    )
                    st.altair_chart(
                        chart_axis_style(alt.layer(bars, mean_rule).properties(height=156)),
                        theme=None,
                        width="stretch",
                    )
                    with st.expander(t("roi_details_expander", lang)):
                        st.caption(
                            t("roi_bounds_caption", lang, x0=x0, x1=x1 - 1, y0=y0, y1=y1 - 1)
                        )
                        if roi["area_mm2"] is not None:
                            st.caption(t("roi_area_caption", lang, area=roi["area_mm2"]))

    with st.container(border=True, key="card_measurement_summary", gap="medium"):
        st.html(section_heading("04", t("sec_04_title", lang), "", "section-summary"))
        render_measurement_values(summary, lang=lang)
        if original_bytes is None:
            st.caption(t("summary_need_image", lang))
        has_values = any(summary[key] is not None for key in ("roi", "tumor_area_cm2", "tumor_volume_ml"))
        selected_by_case = st.session_state.setdefault("review_measurements", {})
        if st.button(
            t("select_measurement_btn", lang),
            key=f"select_measurement_{viewer_id}",
            disabled=original_bytes is None or not has_values,
        ):
            selected_by_case[viewer_id] = deepcopy(summary)

        selected = selected_by_case.get(viewer_id)
        if selected is not None:
            with st.expander(
                t("saved_measurement_expander", lang, slice_number=selected["slice_number"])
            ):
                render_measurement_values(selected, lang=lang)

    with st.container(border=True, key="card_memo", gap="medium"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html(
                section_heading(
                    "05",
                    t("sec_05_title", lang),
                    t("sec_05_desc", lang),
                    "section-memo",
                ),
                width="stretch",
            )
            note_count_slot = st.empty()

        compose_column, notes_column = st.columns(2, gap="large")

        with compose_column:
            st.html(
                '<div class="memo-head">'
                f'<span class="caption">{escape(t("memo_content_label", lang))}</span>'
                f'<span class="slice-tag">{escape(t("memo_slice_tag", lang, slice_number=slice_number))}</span>'
                "</div>"
            )
            with st.form(f"review_note_{viewer_id}", clear_on_submit=True, border=False):
                note = st.text_area(
                    t("memo_content_label", lang),
                    placeholder=t("memo_placeholder", lang),
                    height=104,
                    label_visibility="collapsed",
                )
                submitted = st.form_submit_button(t("memo_submit", lang), type="primary")

            if submitted:
                note = note.strip()
                if note:
                    case_notes.append({"slice_number": slice_number, "text": note})
                    st.success(t("memo_saved", lang))
                else:
                    st.warning(t("memo_empty_warning", lang))

        note_count_slot.html(
            f'<span class="caption mono">{escape(t("memo_count", lang, count=len(case_notes)))}</span>',
            width="content",
        )

        with notes_column:
            if case_notes:
                items = "".join(
                    "<li>"
                    f'<span class="memo-slice">{escape(t("memo_slice_badge", lang, slice_number=saved_note["slice_number"]))}</span>'
                    f'<span class="memo-text">{escape(saved_note["text"])}</span>'
                    "</li>"
                    for saved_note in reversed(case_notes)
                )
                st.html(f'<ol class="memo-list">{items}</ol>')
                st.html(f'<span class="caption">{escape(t("memo_order_caption", lang))}</span>')
            else:
                st.html(
                    '<div class="empty">'
                    f'<span class="empty-title">{escape(t("memo_empty_title", lang))}</span>'
                    f'<span class="empty-desc">{escape(t("memo_empty_desc", lang))}</span>'
                    "</div>"
                )


viewer_case_id = st.session_state.get("viewer_case_id")
if viewer_case_id in cases:
    render_viewer(viewer_case_id)
else:
    render_case_list()
