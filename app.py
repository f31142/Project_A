from base64 import b64encode
from html import escape
from io import BytesIO
from math import ceil, floor
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw

APP_DIR = Path(__file__).parent
MOCK_CT_DIR = APP_DIR / "assets" / "mock_ct"

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
    "검토 대기": ("waiting", "○", "#636D69"),
    "검토 중": ("progress", "●", "#8A5A00"),
    "검토 완료": ("done", "✓", "#121917"),
}
PROCESSING_METHODS = [
    "밝기 보정",
    "CLAHE 대비 보정",
    "가우시안 노이즈 완화",
    "Canny 경계 검출",
]
ROI_MODES = ["영상에서 드래그", "좌표 슬라이더"]
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
    "roi_x_",
    "roi_y_",
)

st.set_page_config(page_title="간 CT 검토실", layout="wide")
st.html("<style>" + (APP_DIR / "assets" / "app.css").read_text(encoding="utf-8") + "</style>")

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

    return (
        max(0, floor(min(box["x"]))),
        min(width, ceil(max(box["x"]))),
        max(0, floor(min(box["y"]))),
        min(height, ceil(max(box["y"]))),
    )


initial_cases = {
    "HCC_004": {"exam": "치료 전 CT", "slice_count": 79},
    "HCC_012": {"exam": "치료 후 CT", "slice_count": 86},
    "HCC_018": {"exam": "치료 전 CT", "slice_count": 72},
}

cases = st.session_state.setdefault("cases", initial_cases)

mock_ct_images = {
    "HCC_004": {
        34: "slice_034.png",
        41: "slice_041.png",
        50: "slice_050.png",
    },
}

mock_measurements = {
    "HCC_004": {
        "areas_cm2": {34: 29.6, 41: 31.9, 50: 15.7},
        "volume_ml": 154.8,
    },
}

review_statuses = st.session_state.setdefault("review_statuses", {})
uploads_by_case = st.session_state.setdefault("uploaded_ct_images", {})
notes_by_case = st.session_state.setdefault("review_notes", {})



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


def render_app_bar(case_id=None):
    if case_id is None:
        crumbs = '<span class="is-current">케이스 목록</span>'
    else:
        crumbs = (
            '<span>케이스 목록</span><span aria-hidden="true">›</span>'
            f'<span class="is-current mono">{escape(case_id)}</span>'
        )
    st.html(
        '<header class="appbar"><div class="appbar-inner">'
        f'<span class="appbar-logo">{LOGO_SVG}</span>'
        '<span class="appbar-name">간 CT 검토실</span>'
        '<span class="appbar-divider"></span>'
        f'<nav class="appbar-crumbs" aria-label="현재 위치">{crumbs}</nav>'
        '<span class="appbar-badge">모의 데이터 · 세션 동안만 유지</span>'
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

    title_col, action_col = st.columns([3, 1], vertical_alignment="bottom")
    title_col.html(
        '<h1 class="page-title">케이스 목록</h1>'
        '<p class="page-desc">검토할 케이스를 고르면 오른쪽에 요약이 나오고, 뷰어에서 단면을 엽니다.</p>'
    )
    with action_col.container(horizontal=True, horizontal_alignment="right"):
        with st.popover("케이스 등록", icon=":material/add:"):
            with st.form("register_case"):
                case_id_input = st.text_input("새 케이스 ID", placeholder="예: HCC_025")
                exam_type = st.selectbox("검사 종류", ["치료 전 CT", "치료 후 CT"])
                new_slice_count = st.number_input("단면 수", min_value=1, value=1)
                submitted = st.form_submit_button("등록", type="primary")

            if submitted:
                new_case_id = case_id_input.strip().upper()

                if not new_case_id:
                    st.warning("케이스 ID를 입력해 주세요.")
                elif new_case_id in cases:
                    st.warning("이미 등록된 케이스 ID예요.")
                else:
                    cases[new_case_id] = {
                        "exam": exam_type,
                        "slice_count": new_slice_count,
                    }
                    st.success(f"{new_case_id} 케이스를 등록했어요.")

    list_col, detail_col = st.columns([2.3, 1], gap="large")
    selected_case = None

    with list_col:
        search_col, filter_col = st.columns([1, 1.3], vertical_alignment="center")
        query = search_col.text_input(
            "케이스 ID 검색",
            placeholder="케이스 ID 검색 · 예: 012",
            key="case_query",
            icon=":material/search:",
            label_visibility="collapsed",
        ).strip().casefold()

        st.session_state.setdefault("status_filter", "전체")
        with filter_col.container(horizontal=True, horizontal_alignment="right"):
            st.segmented_control(
                "검토 상태 필터",
                ["전체"] + REVIEW_STATUSES,
                key="status_filter",
                on_change=keep_choice,
                args=("status_filter", "전체"),
                label_visibility="collapsed",
            )
        status_filter = st.session_state.get("status_filter") or "전체"

        rows = []
        for case_id, case in cases.items():
            status = review_statuses.get(case_id, "검토 대기")
            matches_id = query in case_id.casefold()
            matches_status = status_filter == "전체" or status == status_filter

            if matches_id and matches_status:
                rows.append({
                    "케이스 ID": case_id,
                    "검사 종류": case["exam"],
                    "단면 수": case["slice_count"],
                    "검토 상태": status,
                })

        if rows:
            table_key = "case_table_" + "_".join(row["케이스 ID"] for row in rows)
            table = (
                pd.DataFrame(rows)
                .style.map(
                    lambda status: f"color: {STATUS_STYLES[status][2]}",
                    subset=["검토 상태"],
                )
                .format(
                    lambda status: f"{STATUS_STYLES[status][1]}  {status}",
                    subset=["검토 상태"],
                )
            )
            event = st.dataframe(
                table,
                key=table_key,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                width="stretch",
                row_height=48,
                column_config={
                    "케이스 ID": st.column_config.TextColumn("케이스 ID"),
                    "검사 종류": st.column_config.TextColumn("검사 종류"),
                    "단면 수": st.column_config.NumberColumn("단면 수", format="%d장"),
                    "검토 상태": st.column_config.TextColumn("검토 상태"),
                },
            )

            selected_rows = event.selection.rows
            if selected_rows:
                selected_case = rows[selected_rows[0]]
                st.session_state["selected_case_id"] = selected_case["케이스 ID"]
            else:
                remembered_id = st.session_state.get("selected_case_id")
                selected_case = next(
                    (row for row in rows if row["케이스 ID"] == remembered_id),
                    rows[0],
                )
        else:
            st.html(
                '<div class="empty">'
                '<span class="empty-title">검색 조건에 맞는 케이스가 없어요</span>'
                '<span class="empty-desc">검색어를 지우거나 상태 필터를 ‘전체’로 바꿔 보세요.</span>'
                "</div>"
            )

        status_counts = " · ".join(
            f"{status} {sum(review_statuses.get(case_id, '검토 대기') == status for case_id in cases)}"
            for status in REVIEW_STATUSES
        )
        st.html(
            '<div class="caption-row">'
            f"<span>케이스 {len(rows)}개 · 행을 눌러 고릅니다</span>"
            f"<span>{status_counts}</span>"
            "</div>"
        )

    with detail_col.container(border=True, key="card_detail", gap="medium"):
        if selected_case is None:
            st.html(
                '<div class="detail-head"><span class="overline">선택한 케이스</span>'
                '<div class="thumb-empty">표에서 케이스를 고르면 요약이 나와요</div></div>'
            )
            return

        selected_id = selected_case["케이스 ID"]
        slice_count = selected_case["단면 수"]
        slices = case_slice_numbers(selected_id)
        preview_number = 41 if 41 in slices else (slices[0] if slices else None)
        preview_bytes = load_slice_bytes(selected_id, preview_number) if preview_number else None

        if preview_bytes is not None:
            thumbnail = (
                '<div class="thumb">'
                f'<img src="{image_data_url(preview_bytes)}" '
                f'alt="{escape(selected_id)} {preview_number}번 단면 미리보기">'
                f'<span class="thumb-chip">{preview_number} / {slice_count} · 대표 단면</span>'
                "</div>"
            )
        else:
            thumbnail = '<div class="thumb-empty">첨부된 영상 없음</div>'

        measurement = mock_measurements.get(selected_id)
        image_text = " · ".join(str(number) for number in slices) + "번" if slices else "없음"
        volume_text = f"{measurement['volume_ml']:.1f} mL" if measurement else "—"
        volume_class = ' class="is-measure"' if measurement else ""

        st.html(
            '<div class="detail-head">'
            '<span class="overline">선택한 케이스</span>'
            '<div class="detail-title">'
            f'<span class="case-id">{escape(selected_id)}</span>'
            f"{status_badge(selected_case['검토 상태'])}"
            "</div></div>"
            f"{thumbnail}"
            '<dl class="facts">'
            f"<div><dt>검사 종류</dt><dd>{selected_case['검사 종류']}</dd></div>"
            f"<div><dt>단면 수</dt><dd>{slice_count}장</dd></div>"
            f"<div><dt>모의 영상</dt><dd>{image_text}</dd></div>"
            f"<div><dt>모의 부피</dt><dd{volume_class}>{volume_text}</dd></div>"
            "</dl>"
        )
        st.button(
            "뷰어 열기",
            type="primary",
            icon=":material/arrow_forward:",
            width="stretch",
            on_click=open_viewer,
            args=(selected_id,),
        )



def render_viewer(viewer_id):
    total_slices = cases[viewer_id]["slice_count"]
    slice_key = f"slice_{viewer_id}"
    contour_key = f"contour_{viewer_id}"
    case_images = mock_ct_images.get(viewer_id, {})
    measurement = mock_measurements.get(viewer_id)
    uploaded_slices = uploads_by_case.setdefault(viewer_id, {})
    case_notes = notes_by_case.setdefault(viewer_id, [])
    viewer_status = review_statuses.get(viewer_id, "검토 대기")

    if total_slices == 1:
        slice_number = 1
    else:
        st.session_state.setdefault(slice_key, 1)
        slice_number = st.session_state[slice_key]

    render_app_bar(viewer_id)

    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        st.button(
            "케이스 목록",
            key="back_to_list",
            icon=":material/arrow_back:",
            type="tertiary",
            on_click=close_viewer,
            args=(viewer_id,),
        )
        meta = f"{cases[viewer_id]['exam']} · {total_slices} 단면"
        if measurement is not None:
            meta += " · 모의 측정값 있음"
        st.html(
            '<div class="viewer-title">'
            '<div class="viewer-title-row">'
            f'<h1 class="viewer-id">{escape(viewer_id)}</h1>{status_badge(viewer_status)}'
            "</div>"
            f'<span class="caption">{meta}</span>'
            "</div>",
            width="stretch",
        )

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

    uploaded_image = uploaded_slices.get(slice_number)
    original_bytes = uploaded_image
    file_name = case_images.get(slice_number)
    image_path = None
    overlay_path = None
    missing_file = None

    if uploaded_image is None and file_name:
        candidate = MOCK_CT_DIR / file_name
        if candidate.is_file():
            image_path = candidate
            original_bytes = candidate.read_bytes()
            overlay_candidate = candidate.with_name(f"{candidate.stem}_overlay.png")
            if overlay_candidate.is_file():
                overlay_path = overlay_candidate
        else:
            missing_file = file_name

    overlay_slices = [
        number
        for number, name in sorted(case_images.items())
        if (MOCK_CT_DIR / f"{Path(name).stem}_overlay.png").is_file()
    ]
    show_overlay = overlay_path is not None and st.session_state.get(contour_key, False)

    stage_col, side_col = st.columns([2.75, 1], gap="medium")

    with stage_col.container(key="stage"):
        source_label = "첨부한 PNG" if uploaded_image is not None else "모의 CT"
        contour_chip = '<span class="chip is-contour">종양 윤곽 표시 중</span>' if show_overlay else ""
        st.html(
            '<div class="stage-bar"><div class="stage-chips">'
            f'<span class="chip is-strong">단면 {slice_number} / {total_slices}</span>'
            f'<span class="chip">{source_label}</span>'
            f"</div>{contour_chip}</div>"
        )

        with st.container(key="stage_image"):
            if uploaded_image is not None:
                st.image(uploaded_image, width="stretch")
            elif image_path is not None:
                st.image(str(overlay_path if show_overlay else image_path), width="stretch")
            else:
                if missing_file:
                    hint = f"표시할 이미지 파일: {escape(missing_file)}"
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

        if measurement is not None:
            measurements = []
            for number, area in measurement["areas_cm2"].items():
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
                    st.session_state[slice_key] = int(points[0]["slice_number"])

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
            max_area = max(measurement["areas_cm2"].values())
            y = alt.Y(
                "area_cm2:Q",
                axis=None,
                scale=alt.Scale(domain=[0, max_area * 1.4]),
            )
            chart = (
                alt.Chart(alt.Data(values=measurements))
                .mark_bar(
                    width=12,
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
                        alt.Tooltip("area_cm2:Q", title="모의 면적 (cm²)", format=".1f"),
                    ],
                )
                .add_params(point_selection)
                .properties(height=120, padding={"left": 56, "right": 56, "top": 8, "bottom": 4})
                .configure(background=STAGE)
                .configure_view(stroke=None)
            )

            st.html(
                '<div class="stage-label">'
                "<strong>단면별 모의 종양 면적</strong>"
                "<span>슬라이더와 같은 가로축 · 막대를 누르면 그 단면으로 이동</span>"
                "</div>"
            )
            st.altair_chart(
                chart,
                key=chart_key,
                on_select=move_to_selected_slice,
                theme=None,
                use_container_width=True,
            )

    with side_col:
        if measurement is None:
            slice_value = '<span class="metric-value is-empty">측정값 없음</span>'
            slice_caption = "이 케이스에는 모의 측정값이 없어요"
            case_value = '<span class="metric-value is-small is-empty">—</span>'
        else:
            current_area = measurement["areas_cm2"].get(slice_number)
            if current_area is None:
                measured = " · ".join(str(number) for number in sorted(measurement["areas_cm2"]))
                slice_value = '<span class="metric-value is-empty">측정값 없음</span>'
                slice_caption = f"{measured}번 단면에 측정값이 있어요"
            else:
                slice_value = (
                    f'<span class="metric-value">{current_area:.1f}'
                    '<span class="metric-unit">cm²</span></span>'
                )
                slice_caption = "모의 종양 면적"
            case_value = (
                f'<span class="metric-value is-small">{measurement["volume_ml"]:.1f}'
                '<span class="metric-unit">mL</span></span>'
            )

        st.html(
            '<div class="metric is-slice">'
            f'<span class="overline"><span class="dot"></span>이 단면 · {slice_number} / {total_slices}</span>'
            f'{slice_value}<span class="metric-caption">{slice_caption}</span>'
            "</div>"
            '<div class="metric" style="margin-top: 12px">'
            '<span class="overline">케이스 전체</span>'
            f'{case_value}<span class="metric-caption">모의 전체 종양 부피 · 단면을 바꿔도 그대로</span>'
            "</div>"
        )

        with st.container(border=True, key="card_display", gap="small"):
            with st.container(key="contour_row"):
                st.toggle("종양 윤곽", key=contour_key, disabled=overlay_path is None)
            if overlay_path is not None:
                contour_caption = "이 단면의 모의 윤곽을 겹쳐 봅니다"
            elif overlay_slices:
                listed = " · ".join(str(number) for number in overlay_slices)
                contour_caption = f"{listed}번 단면에서 쓸 수 있어요"
            else:
                contour_caption = "이 케이스에는 윤곽 오버레이가 없어요"
            st.html(f'<span class="caption">{contour_caption}</span>')

            if 41 in case_images:
                st.button(
                    "예시 단면 41번으로 이동",
                    key=f"jump_41_{viewer_id}",
                    width="stretch",
                    on_click=move_to_slice,
                    args=(slice_key, 41, total_slices),
                )

        st.html(
            '<nav class="jump" aria-label="아래로 이어지는 도구">'
            '<span class="overline">아래로 이어지는 도구</span>'
            '<a href="#section-processing"><span><span class="mono">02</span>원본·처리 비교</span><span>↓</span></a>'
            '<a href="#section-roi"><span><span class="mono">03</span>관심 영역(ROI) 분석</span><span>↓</span></a>'
            '<a href="#section-memo"><span><span class="mono">04</span>검토 메모</span><span>↓</span></a>'
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
                method = st.radio(
                    "영상처리 도구",
                    PROCESSING_METHODS,
                    captions=["", "처리 함수 연결 예정", "처리 함수 연결 예정", "처리 함수 연결 예정"],
                    key=f"processing_method_{viewer_id}",
                )

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

                elif method == "가우시안 노이즈 완화":
                    st.select_slider("커널 크기", options=[3, 5, 7, 9], value=5)

                elif method == "Canny 경계 검출":
                    st.slider("경계 임계값", 0, 255, (50, 150))

            with images_column:
                original_column, result_column = st.columns(2, gap="medium")
                with original_column.container(key="tile_original"):
                    st.image(original, width="stretch")
                    st.html(
                        '<div class="tile-caption"><span>원본</span>'
                        '<span class="mono">×1.0</span></div>'
                    )
                with result_column.container(key="tile_result"):
                    if result is None:
                        st.html('<div class="tile-empty">처리 함수를 연결한 뒤 결과가 표시돼요.</div>')
                        st.html(f'<div class="tile-caption"><span>{method} 결과</span></div>')
                    else:
                        st.image(result, width="stretch")
                        st.html(
                            f'<div class="tile-caption"><span>{method} 결과</span>'
                            f'<span class="mono is-mint">×{factor:.1f}</span></div>'
                        )

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

        if original_bytes is None:
            st.html('<div class="notice">이 단면에 영상이 있을 때 쓸 수 있어요.</div>')
        elif roi_enabled:
            with Image.open(BytesIO(original_bytes)) as image:
                source = image.convert("RGB")

            gray = np.array(source.convert("L"))
            height, width = gray.shape

            roi_key = f"{viewer_id}_{slice_number}"
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

            if mode == "영상에서 드래그":
                with preview_column.container(key="tile_roi"):
                    bounds = select_roi_by_drag(source, roi_key)
                    st.html('<div class="tile-caption"><span>영상 위를 드래그해 상자를 그립니다</span></div>')
            else:
                x_key = f"roi_x_{roi_key}"
                y_key = f"roi_y_{roi_key}"
                st.session_state.setdefault(x_key, (width // 4, width - width // 4))
                st.session_state.setdefault(y_key, (height // 4, height - height // 4))
                x0, x1 = preview_column.slider("가로 범위 (x)", 0, width, key=x_key)
                y0, y1 = preview_column.slider("세로 범위 (y)", 0, height, key=y_key)
                bounds = x0, x1, y0, y1

            if bounds is None:
                stats_column.html(
                    '<div class="notice">CT 위에서 드래그해 관심 영역을 선택해 주세요.</div>'
                )
            elif bounds[0] >= bounds[1] or bounds[2] >= bounds[3]:
                stats_column.html(
                    '<div class="notice is-warning">가로와 세로 범위를 각각 한 픽셀 이상으로 골라 주세요.</div>'
                )
            else:
                x0, x1, y0, y1 = bounds
                roi = gray[y0:y1, x0:x1]

                if mode == "좌표 슬라이더":
                    preview = source.copy()
                    ImageDraw.Draw(preview).rectangle(
                        (x0, y0, x1 - 1, y1 - 1), outline=MINT, width=3,
                    )
                    with preview_column.container(key="tile_roi"):
                        st.image(preview, width="stretch")
                        st.html('<div class="tile-caption"><span>선택한 ROI</span></div>')

                roi_mean = roi.mean()
                stats_column.html(
                    '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px">'
                    '<div class="metric is-slice"><span class="overline">ROI 평균 밝기</span>'
                    f'<span class="metric-value">{roi_mean:.1f}<span class="metric-unit">/ 255</span></span></div>'
                    '<div class="metric" style="background: var(--surface-2); justify-content: center">'
                    '<span class="overline">선택 영역 (원본 픽셀)</span>'
                    f'<span class="coords">x {x0}–{x1 - 1} · y {y0}–{y1 - 1}<br>{x1 - x0} × {y1 - y0} 픽셀</span>'
                    "</div></div>"
                )

                counts = np.bincount(roi.ravel(), minlength=256)
                histogram = pd.DataFrame({"brightness": np.arange(256), "pixels": counts})
                bars = (
                    alt.Chart(histogram)
                    .mark_area(interpolate="step-after", color=TEAL, opacity=0.85)
                    .encode(
                        x=alt.X(
                            "brightness:Q",
                            title="픽셀 밝기 (0~255)",
                            scale=alt.Scale(domain=[0, 255], nice=False),
                            axis=alt.Axis(values=[0, 64, 128, 192, 255]),
                        ),
                        y=alt.Y("pixels:Q", title="픽셀 수"),
                        tooltip=[
                            alt.Tooltip("brightness:Q", title="밝기"),
                            alt.Tooltip("pixels:Q", title="픽셀 수"),
                        ],
                    )
                )
                mean_data = alt.Data(values=[{"mean": float(roi_mean), "label": f"평균 {roi_mean:.1f}"}])
                mean_rule = (
                    alt.Chart(mean_data)
                    .mark_rule(color=INK, strokeDash=[4, 3], strokeWidth=1.5)
                    .encode(x="mean:Q")
                )
                mean_label = (
                    alt.Chart(mean_data)
                    .mark_text(align="left", dx=6, font=MONO_FONT, fontSize=11, fontWeight=500, color=INK)
                    .encode(x="mean:Q", y=alt.value(8), text="label:N")
                )
                with stats_column.container(border=True, key="card_histogram"):
                    st.html('<span class="overline">밝기 분포</span>')
                    st.altair_chart(
                        chart_axis_style(alt.layer(bars, mean_rule, mean_label).properties(height=190)),
                        theme=None,
                        use_container_width=True,
                    )

    with st.container(border=True, key="card_memo", gap="medium"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html(
                section_heading(
                    "04",
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
