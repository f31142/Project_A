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

from case_list import case_display_name
from ct_analysis import TumorMeasurement, build_analysis_slices, measure_tumor
from ct_case import has_case_ct_reference, load_case_ct, load_case_seg
from dicom_ct import (
    CT_PREVIEW_COLUMNS,
    DicomReadError,
    render_ct_contour_png,
    render_ct_png,
    render_ct_preview_sheet,
)
from roi_analysis import build_measurement_summary, normalize_roi_bounds, summarize_roi

APP_DIR = Path(__file__).resolve().parent
MOCK_CT_DIR = APP_DIR / "assets" / "mock_ct"
CT_PREVIEW_TILE_SIZE = 256

INK = "#121917"
INK_3 = "#636D69"
LINE = "#E2E6E1"
LINE_STRONG = "#CDD3CD"
STAGE = "#0B100F"
STAGE_AXIS = "#8E9A96"
MINT = "#5CE7C4"
TEAL = "#10997D"
TEAL_DIM = "#2E6B5D"
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
SOURCE_LABELS = {
    "dicom": "DICOM CT",
    "synthetic_dicom": "합성 DICOM CT",
    "mock": "모의 CT",
    "uploaded_png": "첨부한 PNG",
}
LOGO_SVG = (
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#5CE7C4" '
    'stroke-width="2" stroke-linecap="round" aria-hidden="true">'
    '<ellipse cx="12" cy="12" rx="8" ry="6"></ellipse><path d="M7 12h10"></path></svg>'
)

PERSISTENT_KEY_PREFIXES = (
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

st.set_page_config(page_title="간 CT 검토실", layout="wide")
st.html("<style>" + (APP_DIR / "assets" / "app.css").read_text(encoding="utf-8") + "</style>")
ct_viewport_component = st.components.v2.component(
    "ct_viewport",
    html=(
        '<div class="ct-view-controls" role="group" aria-label="CT 보기 조작">'
        '<button type="button" data-view-action="zoom-out" aria-label="축소">− 축소</button>'
        '<output aria-label="현재 배율">100%</output>'
        '<button type="button" data-view-action="zoom-in" aria-label="확대">+ 확대</button>'
        '<button type="button" data-view-action="reset">초기화</button>'
        '</div>'
        '<div class="ct-slice-preview" role="region" aria-label="CT 영상" tabindex="0">'
        '<div class="ct-view-content">'
        '<img alt="CT 단면" draggable="false"><canvas hidden aria-hidden="true"></canvas>'
        '</div>'
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
        mark=alt.BrushConfig(fill=MINT, fillOpacity=0.16, stroke=MINT, strokeWidth=2),
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


def status_badge(status):
    return f'<span class="badge badge-{STATUS_STYLES[status][0]}">{status}</span>'


def render_app_bar(case_name=None):
    if case_name is None:
        crumbs = '<span class="is-current">케이스 목록</span>'
    else:
        crumbs = (
            '<span>케이스 목록</span><span aria-hidden="true">›</span>'
            f'<span class="is-current mono">{escape(case_name)}</span>'
        )
    st.html(
        '<header class="appbar"><div class="appbar-inner">'
        f'<span class="appbar-logo">{LOGO_SVG}</span>'
        '<span class="appbar-name">간 CT 검토실</span>'
        '<span class="appbar-divider"></span>'
        f'<nav class="appbar-crumbs" aria-label="현재 위치">{crumbs}</nav>'
        '<span class="appbar-badge">교육용 · 검토 기록은 세션 동안 유지</span>'
        "</div></header>"
    )


def section_heading(number, title, description, anchor):
    return (
        f'<div class="section-head" id="{anchor}">'
        f'<span class="section-num">{number}</span>'
        f'<h2 class="section-title">{title}</h2>'
        f'<span class="section-desc">{description}</span>'
        "</div>"
    )


def render_measurement_values(summary):
    name = case_display_name(cases[summary["case_id"]])
    st.caption(f"{name} · {summary['slice_number']}번 단면 · {SOURCE_LABELS[summary['source']]}")
    area = summary["tumor_area_cm2"]
    volume = summary["tumor_volume_ml"]
    area_col, volume_col = st.columns(2)
    area_col.metric("현재 단면의 종양 면적", f"{area:.1f} cm²" if area is not None else "측정값 없음")
    volume_col.metric("케이스 전체 종양 부피", f"{volume:.1f} mL" if volume is not None else "측정값 없음")
    roi = summary["roi"]
    if roi is None:
        st.caption("선택한 ROI 없음")
        return
    bounds = roi["bounds"]
    text = (
        f"사각형 ROI · x {bounds['x0']}–{bounds['x1'] - 1}, y {bounds['y0']}–{bounds['y1'] - 1}"
        f" · {roi['pixel_count']:,}픽셀 · 평균 밝기 {roi['mean_brightness']:.1f} / 255"
    )
    if roi["area_mm2"] is not None:
        text += f" · ROI 면적 {roi['area_mm2']:,.2f} mm²"
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
    image_source, viewer_id, slice_number, slice_count, dicom_slices, *, seg_source=None, masks=None
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
        key=f"ct_viewport_{viewer_id}",
        data={
            "caseId": viewer_id,
            "tileSize": CT_PREVIEW_TILE_SIZE,
            "sliceCount": slice_count,
        },
    )


def chart_axis_style(chart):
    return (
        chart.configure(background="#FFFFFF")
        .configure_axis(
            labelFont=MONO_FONT,
            labelFontSize=11,
            labelColor=INK_3,
            titleFont=SANS_FONT,
            titleFontSize=12,
            titleFontWeight=500,
            titleColor=INK_3,
            gridColor=LINE,
            domainColor=LINE_STRONG,
            tickColor=LINE_STRONG,
        )
        .configure_view(stroke=None)
    )



def render_case_list():
    render_app_bar()
    case_ui.render_storage_notice()

    title_col, action_col = st.columns([3, 1], vertical_alignment="bottom")
    title_col.html(
        '<h1 class="page-title">케이스 목록</h1>'
        '<p class="page-desc">검토할 케이스를 고르면 오른쪽에 요약이 나오고, 뷰어에서 단면을 엽니다.</p>'
    )
    with action_col.container(horizontal=True, horizontal_alignment="right"):
        with st.popover("케이스 등록", icon=":material/add:"):
            case_ui.render_register_form(cases)

    list_col, detail_col = st.columns([2.3, 1], gap="large")
    selected_case = None

    with list_col:
        selected_case = case_ui.render_case_table(
            cases,
            review_statuses,
            REVIEW_STATUSES,
            {status: mark for status, (_, mark) in STATUS_STYLES.items()},
        )

    with detail_col.container(border=True, key="card_detail", gap="medium"):
        if selected_case is None:
            st.html(
                '<div class="detail-head"><span class="overline">선택한 케이스</span>'
                '<div class="thumb-empty">표에서 케이스를 고르면 요약이 나와요</div></div>'
            )
            return

        selected_id = selected_case["케이스 ID"]
        case = cases[selected_id]
        display_name = escape(case_display_name(case))
        ct_slices, ct_error = load_case_ct(selected_id, case)
        registered_ct = has_case_ct_reference(case)
        slice_count = len(ct_slices) if ct_slices else selected_case["단면 수"]
        if ct_slices or registered_ct:
            image_label = "DICOM 영상"
            image_text = f"{len(ct_slices)}장" if ct_slices else "열 수 없음"
            volume_label = "종양 부피"
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
            image_label = "모의 영상"
            image_text = " · ".join(map(str, slices)) + "번" if slices else "없음"
            volume_label = "모의 부피"
            measurement = mock_measurements.get(selected_id)

        if preview_bytes is not None:
            thumbnail = (
                '<div class="thumb">'
                f'<img src="{image_data_url(preview_bytes)}" '
                f'alt="{display_name} {preview_number}번 단면 미리보기">'
                f'<span class="thumb-chip">{preview_number} / {slice_count} · 대표 단면</span>'
                "</div>"
            )
        else:
            missing = "DICOM 미리보기 없음" if registered_ct else "첨부된 영상 없음"
            thumbnail = f'<div class="thumb-empty">{missing}</div>'

        count_text = f"{slice_count}장" if slice_count is not None else "—"
        volume_ml = measurement.volume_ml if measurement is not None else None
        volume_text = f"{volume_ml:.1f} mL" if volume_ml is not None else "—"
        volume_class = ' class="is-measure"' if volume_ml is not None else ""

        st.html(
            '<div class="detail-head">'
            '<span class="overline">선택한 케이스</span>'
            '<div class="detail-title">'
            f'<span class="case-id">{display_name}</span>'
            f"{status_badge(selected_case['검토 상태'])}"
            "</div></div>"
            f"{thumbnail}"
            '<dl class="facts">'
            f"<div><dt>검사 종류</dt><dd>{escape(str(selected_case['검사 종류']))}</dd></div>"
            f"<div><dt>단면 수</dt><dd>{count_text}</dd></div>"
            f"<div><dt>{image_label}</dt><dd>{image_text}</dd></div>"
            f"<div><dt>{volume_label}</dt><dd{volume_class}>{volume_text}</dd></div>"
            "</dl>"
        )
        if ct_error and registered_ct:
            st.warning(ct_error)
        st.button(
            "뷰어 열기",
            type="primary",
            icon=":material/arrow_forward:",
            width="stretch",
            on_click=open_viewer,
            args=(selected_id,),
        )



def render_viewer(viewer_id):
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
        if measurement is not None else {}
    )
    area_title = "종양 면적" if is_dicom else "모의 종양 면적"
    uploaded_slices = uploads_by_case.setdefault(viewer_id, {}) if use_mock else {}
    case_notes = notes_by_case.setdefault(viewer_id, [])
    viewer_status = review_statuses.get(viewer_id, "검토 대기")

    if total_slices == 1:
        slice_number = 1
    else:
        move_to_slice(slice_key, st.session_state.get(slice_key, 1), total_slices)
        slice_number = st.session_state[slice_key]

    display_name = case_display_name(case)
    render_app_bar(display_name)

    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        st.button(
            "케이스 목록",
            key="back_to_list",
            icon=":material/arrow_back:",
            type="tertiary",
            on_click=close_viewer,
            args=(viewer_id,),
        )
        meta = str(case.get("exam") or "CT 검사")
        if not (registered_ct and dicom_error):
            meta += f" · {total_slices} 단면"
        if measurement is not None and use_mock:
            meta += " · 모의 측정값 있음"
        st.html(
            '<div class="viewer-title">'
            '<div class="viewer-title-row">'
            f'<h1 class="viewer-id">{escape(display_name)}</h1>{status_badge(viewer_status)}'
            "</div>"
            f'<span class="caption">{escape(meta)}</span>'
            "</div>",
            width="stretch",
        )

        if use_mock:
            with st.popover("현재 단면에 PNG 첨부", icon=":material/attach_file:"):
                with st.form(f"attach_ct_{viewer_id}_{slice_number}", clear_on_submit=True):
                    png_file = st.file_uploader("모의 CT PNG", type=["png"])
                    attach_clicked = st.form_submit_button("첨부", type="primary")

                if attach_clicked:
                    if png_file is None:
                        st.warning("첨부할 PNG를 선택해 주세요.")
                    else:
                        image_bytes = png_file.getvalue()
                        try:
                            with Image.open(BytesIO(image_bytes), formats=("PNG",)) as image:
                                image.load()
                        except (OSError, SyntaxError, Image.DecompressionBombError):
                            st.error("이미지를 읽을 수 없어요. 정상적인 PNG 파일을 선택해 주세요.")
                        else:
                            uploaded_slices[slice_number] = image_bytes
                            st.success(f"{viewer_id}의 {slice_number}번 단면에 PNG를 첨부했어요.")

        if viewer_status == "검토 대기":
            st.button(
                "검토 시작",
                key=f"start_review_{viewer_id}",
                type="primary",
                icon=":material/play_arrow:",
                on_click=set_review_status,
                args=(viewer_id, "검토 중"),
            )
        elif viewer_status == "검토 중":
            st.button(
                "검토 완료",
                key=f"complete_review_{viewer_id}",
                type="primary",
                icon=":material/check:",
                on_click=set_review_status,
                args=(viewer_id, "검토 완료"),
            )

    if dicom_error:
        if registered_ct:
            st.error(f"등록된 DICOM CT를 열 수 없어요. {dicom_error}")
            return
        st.warning(f"원본 DICOM을 열 수 없어 모의 영상을 표시해요. {dicom_error}")

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
            image_error = f"표시할 이미지 파일: {file_name}"

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
        case_id=viewer_id, slice_number=slice_number, source=source_kind,
        ct_slice=ct_slice, image_sha256=image_hash, measurement=measurement,
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
        source_label = SOURCE_LABELS[source_kind]
        contour_chip = ""
        if show_dicom_contour:
            contour_chip = '<span class="chip is-contour">종양 윤곽 켜짐</span>'
        elif show_mock_contour:
            contour_chip = '<span class="chip is-contour">종양 윤곽 표시 중</span>'
        st.html(
            '<div class="stage-bar"><div class="stage-chips">'
            f'<span class="chip is-strong">단면 {slice_number} / {total_slices}</span>'
            f'<span class="chip">{source_label}</span>'
            f"</div>{contour_chip}</div>"
        )

        with st.container(key="stage_image"):
            if image_source is not None:
                render_ct_viewport(
                    image_source, viewer_id, slice_number, total_slices, dicom_slices,
                    seg_source=seg_source if show_dicom_contour else None,
                    masks=tumor_masks if show_dicom_contour else None,
                )
            else:
                if image_error:
                    hint = escape(image_error)
                elif case_images:
                    available = " · ".join(str(number) for number in sorted(case_images))
                    hint = f"{available}번 단면에서 모의 CT를 볼 수 있어요. 이 단면에 PNG를 첨부할 수도 있어요."
                else:
                    hint = "위의 ‘현재 단면에 PNG 첨부’로 모의 CT를 올려 보세요."
                st.html(
                    '<div class="stage-empty">'
                    f"<strong>{slice_number}번 단면에 표시할 영상이 없어요</strong>"
                    f"<span>{hint}</span>"
                    "</div>"
                )

        if total_slices > 1:
            with st.container(horizontal=True, vertical_alignment="center", gap="small", key="slice_row"):
                st.button(
                    "",
                    key=f"prev_slice_{viewer_id}",
                    icon=":material/chevron_left:",
                    help="이전 단면",
                    on_click=move_to_slice,
                    args=(slice_key, slice_number - 1, total_slices),
                    disabled=slice_number <= 1,
                )
                st.slider(
                    "단면 번호",
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
                    help="다음 단면",
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
            chart_key = f"area_chart_{viewer_id}_{slice_number}"

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
                    labelFontSize=11,
                    domainColor="#3A4542",
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
                    width=alt.ExprRef(expr=f"min(12, width / {slice_intervals} * 0.8)"),
                    cornerRadiusTopLeft=6,
                    cornerRadiusTopRight=6,
                    cursor="pointer",
                )
                .encode(
                    x=x,
                    y=y,
                    color=alt.condition("datum.is_current", alt.value(MINT), alt.value(TEAL_DIM)),
                    tooltip=[
                        alt.Tooltip("slice_number:Q", title="단면"),
                        alt.Tooltip("area_cm2:Q", title=f"{area_title} (cm²)", format=".1f"),
                    ],
                )
                .add_params(point_selection)
                .properties(height=120, padding={"left": 56, "right": 56, "top": 8, "bottom": 4})
                .configure(background=STAGE)
                .configure_view(stroke=None)
            )

            st.html(
                '<div class="stage-label">'
                f"<strong>단면별 {area_title}</strong>"
                "<span>슬라이더와 같은 가로축 · 막대를 누르면 그 단면으로 이동</span>"
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
                f"최대 면적 단면 보기 · {max_area_slice}번",
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
            slice_value = '<span class="metric-value is-empty">측정값 없음</span>'
            if is_dicom:
                if measurement is not None:
                    slice_caption = "이 단면에 SEG로 표시된 종양 영역이 없어요."
                elif seg_error:
                    slice_caption = seg_error
                elif seg_source is None:
                    slice_caption = "이 케이스에 연결된 DICOM SEG가 없어요."
                else:
                    slice_caption = "SEG에 측정할 종양 영역이 없어요."
            elif uploaded_image is not None:
                slice_caption = "첨부한 PNG에는 연결된 종양 측정값이 없어요."
            elif areas_cm2:
                measured = " · ".join(str(number) for number in sorted(areas_cm2))
                slice_caption = f"{measured}번 단면에 측정값이 있어요"
            else:
                slice_caption = "이 케이스에는 모의 측정값이 없어요"

        volume_ml = summary["tumor_volume_ml"]
        if volume_ml is None:
            case_value = '<span class="metric-value is-small is-empty">—</span>'
        else:
            case_value = (
                f'<span class="metric-value is-small">{volume_ml:.1f}'
                '<span class="metric-unit">mL</span></span>'
            )
        volume_caption = "전체 종양 부피" if is_dicom else "모의 전체 종양 부피 · 단면을 바꿔도 그대로"
        volume_error = (
            f'<span class="metric-caption">{escape(measurement.volume_error)}</span>'
            if measurement is not None and measurement.volume_error else ""
        )
        st.html(
            '<div class="metric is-slice">'
            f'<span class="overline"><span class="dot"></span>이 단면 · {slice_number} / {total_slices}</span>'
            f'{slice_value}<span class="metric-caption">{escape(slice_caption)}</span>'
            "</div>"
            '<div class="metric" style="margin-top: 12px">'
            '<span class="overline">케이스 전체</span>'
            f'{case_value}<span class="metric-caption">{volume_caption}</span>{volume_error}'
            "</div>"
        )

        with st.container(border=True, key="card_display", gap="small"):
            contour_available = bool(tumor_masks) and not seg_error if is_dicom else overlay_path is not None
            with st.container(key="contour_row"):
                st.toggle("종양 윤곽", key=contour_key, disabled=not contour_available)
            if seg_error:
                contour_caption = seg_error
            elif is_dicom and tumor_mask is not None:
                contour_caption = "이 단면의 SEG 종양 윤곽을 겹쳐 봅니다"
            elif is_dicom and tumor_masks:
                contour_caption = "이 단면에는 종양 윤곽이 없어요"
            elif is_dicom and seg_source is None:
                contour_caption = "이 케이스에 연결된 DICOM SEG가 없어요"
            elif is_dicom:
                contour_caption = "이 SEG의 종양 마스크가 비어 있어요"
            elif overlay_path is not None:
                contour_caption = "이 단면의 모의 윤곽을 겹쳐 봅니다"
            elif overlay_slices:
                listed = " · ".join(str(number) for number in overlay_slices)
                contour_caption = f"{listed}번 단면에서 쓸 수 있어요"
            else:
                contour_caption = "이 케이스에는 윤곽 오버레이가 없어요"
            st.html(f'<span class="caption">{escape(contour_caption)}</span>')

        st.html(
            '<nav class="jump" aria-label="아래로 이어지는 도구">'
            '<span class="overline">아래로 이어지는 도구</span>'
            '<a href="#section-processing"><span><span class="mono">02</span>원본·처리 비교</span><span>↓</span></a>'
            '<a href="#section-roi"><span><span class="mono">03</span>관심 영역(ROI) 분석</span><span>↓</span></a>'
            '<a href="#section-summary"><span><span class="mono">04</span>현재 단면 측정 요약</span><span>↓</span></a>'
            '<a href="#section-memo"><span><span class="mono">05</span>검토 메모</span><span>↓</span></a>'
            "</nav>"
        )

    with st.container(border=True, key="card_processing", gap="medium"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html(
                section_heading(
                    "02",
                    "원본·처리 비교",
                    "영상처리 도구를 바꿔 가며 원본과 결과를 나란히 봅니다",
                    "section-processing",
                ),
                width="stretch",
            )
            compare_enabled = st.toggle(
                "비교 열기",
                key=f"compare_processing_{viewer_id}",
                disabled=original_bytes is None,
            )

        if original_bytes is None:
            st.html('<div class="notice">이 단면에 영상이 있을 때 쓸 수 있어요.</div>')
        elif compare_enabled:
            controls_column, images_column = st.columns([1, 2.6], gap="large")

            with controls_column:
                use_brightness = st.checkbox(
                    "기본 밝기 보정 사용",
                    key=f"brightness_enabled_{viewer_id}",
                )
                method = st.radio(
                    "영상처리 도구",
                    PROCESSING_METHODS,
                    captions=[
                        "CT의 부분별 명암 차이를 강조해요.",
                        "경계를 유지하면서 잔잔한 노이즈를 줄여요.",
                        "밝기가 급격히 바뀌는 부분을 선으로 표시해요.",
                        "SEG에서 서로 떨어진 영역을 구분해 면적을 살펴봐요.",
                    ],
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
                        "밝기 배율",
                        min_value=0.5,
                        max_value=2.0,
                        step=0.1,
                        format="×%.1f",
                        key=brightness_key,
                    )
                    scaled = original.astype(np.float32) * factor
                    result = np.clip(scaled, 0, 255).astype(np.uint8)
                    st.html('<span class="caption">1.0으로 돌리면 원본과 같아요.</span>')

                elif method == "CLAHE 대비 보정":
                    st.slider("대비 제한값", 1.0, 5.0, 2.0, 0.1)
                    st.select_slider("가로·세로 타일 수", options=[4, 8, 16], value=8)

                elif method == "양방향 필터":
                    st.slider("밝기 차이 허용 정도", 1, 150, 50)

                elif method == "Canny 경계 검출":
                    st.slider("경계 임계값", 0, 255, (50, 150))

                elif method == "2D 연결 성분 분석":
                    st.caption("현재 단면의 종양 SEG를 사용해 영역별 면적을 계산할 예정이에요.")

            with images_column:
                original_column, result_column = st.columns(2, gap="medium")
                with original_column.container(key="tile_original"):
                    st.image(original, width="stretch")
                    st.html(
                        f'<div class="tile-caption"><span>원본 · 단면 {slice_number}</span>'
                        '<span class="mono">×1.0</span></div>'
                    )
                with result_column.container(key="tile_result"):
                    result_caption = f"<span>{method} 결과 · 단면 {slice_number}</span>"
                    if result is None:
                        st.html('<div class="tile-empty">처리 함수를 연결한 뒤 결과가 표시돼요.</div>')
                    else:
                        st.image(result, width="stretch")
                        result_caption += f'<span class="mono is-mint">×{factor:.1f}</span>'
                    st.html(f'<div class="tile-caption">{result_caption}</div>')

    with st.container(border=True, key="card_roi", gap="medium"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html(
                section_heading(
                    "03",
                    "관심 영역(ROI) 분석",
                    "영역을 고르면 평균 밝기와 분포가 바로 갱신됩니다",
                    "section-roi",
                ),
                width="stretch",
            )
            roi_enabled = st.toggle(
                "분석 열기",
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
            st.html('<div class="notice">이 단면에 영상이 있을 때 쓸 수 있어요.</div>')
        elif roi_enabled:
            height, width = gray.shape
            mode_key = f"roi_mode_{viewer_id}"
            st.session_state.setdefault(mode_key, ROI_MODES[0])
            st.segmented_control(
                "ROI 지정 방식",
                ROI_MODES,
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
                x0, x1 = preview_column.slider("가로 범위 (x)", 0, width, key=x_key)
                y0, y1 = preview_column.slider("세로 범위 (y)", 0, height, key=y_key)
                raw_bounds = x0, x1, y0, y1

            roi_preview = preview_column.container(key="tile_roi")
            if mode == "영상에서 드래그":
                with roi_preview:
                    raw_bounds = select_roi_by_drag(source, roi_key)
                    st.html('<div class="tile-caption"><span>영상 위를 드래그해 상자를 그립니다</span></div>')

            bounds = normalize_roi_bounds(raw_bounds, width, height)
            if raw_bounds is None:
                bounds = saved_bounds
            elif bounds is not None:
                roi_by_slice[roi_key] = bounds

            if bounds is None and raw_bounds is None:
                stats_column.html(
                    '<div class="notice">CT 위에서 드래그해 관심 영역을 선택해 주세요.</div>'
                )
            elif bounds is None:
                stats_column.html(
                    '<div class="notice is-warning">가로와 세로 범위를 각각 한 픽셀 이상으로 골라 주세요.</div>'
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
                        (x0, y0, x1 - 1, y1 - 1), outline=MINT, width=3,
                    )
                    with roi_preview:
                        st.image(preview, width="stretch")
                        st.html(f'<div class="tile-caption"><span>{slice_number}번 단면 · 선택한 ROI</span></div>')

                histogram = pd.DataFrame({"brightness": np.arange(256), "pixels": counts})
                bars = (
                    alt.Chart(histogram)
                    .mark_area(interpolate="step-after", color=TEAL, opacity=0.85)
                    .encode(
                        x=alt.X(
                            "brightness:Q",
                            title="픽셀 밝기",
                            scale=alt.Scale(domain=[0, 255], nice=False),
                            axis=alt.Axis(values=[0, 64, 128, 192, 255], grid=False),
                        ),
                        y=alt.Y(
                            "pixels:Q",
                            title="픽셀 수",
                            axis=alt.Axis(grid=True, tickCount=4, tickMinStep=1),
                        ),
                        tooltip=[
                            alt.Tooltip("brightness:Q", title="밝기"),
                            alt.Tooltip("pixels:Q", title="픽셀 수"),
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
                        f'<div>평균 밝기 <strong>{roi_mean:.1f}</strong></div>'
                        f'<div>선택 크기 <strong>{x1 - x0} × {y1 - y0} px</strong>'
                        f'<span>총 {pixel_count:,}픽셀</span></div>'
                        '</div>'
                        '<div class="roi-chart-heading">'
                        '<strong>밝기 분포</strong>'
                        '<span class="roi-mean-legend">평균</span>'
                        '</div>'
                    )
                    st.altair_chart(
                        chart_axis_style(alt.layer(bars, mean_rule).properties(height=160)),
                        theme=None,
                        width="stretch",
                    )
                    with st.expander("ROI 상세정보"):
                        st.caption(f"선택 범위 · x {x0}–{x1 - 1}, y {y0}–{y1 - 1}")
                        if roi["area_mm2"] is not None:
                            st.caption(f"사각형 ROI 면적 · {roi['area_mm2']:,.2f} mm²")

    with st.container(border=True, key="card_measurement_summary", gap="medium"):
        st.html(section_heading("04", "현재 단면 측정 요약", "", "section-summary"))
        render_measurement_values(summary)
        if original_bytes is None:
            st.caption("영상이 있는 단면에서 측정값을 선택할 수 있어요.")
        has_values = any(summary[key] is not None for key in ("roi", "tumor_area_cm2", "tumor_volume_ml"))
        selected_by_case = st.session_state.setdefault("review_measurements", {})
        if st.button(
            "검토 기록에 사용할 측정값 선택",
            key=f"select_measurement_{viewer_id}",
            disabled=original_bytes is None or not has_values,
        ):
            selected_by_case[viewer_id] = deepcopy(summary)

        selected = selected_by_case.get(viewer_id)
        if selected is not None:
            with st.expander(f"검토 기록용 측정값 · {selected['slice_number']}번 단면"):
                render_measurement_values(selected)

    with st.container(border=True, key="card_memo", gap="medium"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html(
                section_heading(
                    "05",
                    "검토 메모",
                    "저장하면 현재 단면 번호가 함께 남습니다",
                    "section-memo",
                ),
                width="stretch",
            )
            note_count_slot = st.empty()

        compose_column, notes_column = st.columns(2, gap="large")

        with compose_column:
            st.html(
                '<div class="memo-head"><span class="caption">메모 내용</span>'
                f'<span class="slice-tag">{slice_number}번 단면에 저장</span></div>'
            )
            with st.form(f"review_note_{viewer_id}", clear_on_submit=True, border=False):
                note = st.text_area(
                    "메모 내용",
                    placeholder="이 단면에서 확인한 내용을 적어 주세요",
                    height=112,
                    label_visibility="collapsed",
                )
                submitted = st.form_submit_button("메모 저장", type="primary")

            if submitted:
                note = note.strip()
                if note:
                    case_notes.append({"slice_number": slice_number, "text": note})
                    st.success("메모를 저장했어요.")
                else:
                    st.warning("메모 내용을 입력해 주세요.")

        note_count_slot.html(f'<span class="caption mono">메모 {len(case_notes)}개</span>', width="content")

        with notes_column:
            if case_notes:
                items = "".join(
                    "<li>"
                    f'<span class="memo-slice">{saved_note["slice_number"]}번</span>'
                    f'<span class="memo-text">{escape(saved_note["text"])}</span>'
                    "</li>"
                    for saved_note in reversed(case_notes)
                )
                st.html(f'<ol class="memo-list">{items}</ol>')
                st.html('<span class="caption">최근 저장한 메모가 위에 옵니다</span>')
            else:
                st.html(
                    '<div class="empty">'
                    '<span class="empty-title">아직 저장한 메모가 없어요</span>'
                    '<span class="empty-desc">단면을 보며 확인한 내용을 왼쪽에 적어 저장해 보세요.</span>'
                    "</div>"
                )


viewer_case_id = st.session_state.get("viewer_case_id")
if viewer_case_id in cases:
    render_viewer(viewer_case_id)
else:
    render_case_list()
