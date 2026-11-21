from io import BytesIO
from pathlib import Path

import altair as alt
import numpy as np
import streamlit as st
from PIL import Image

st.title("간 CT 검토실")

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


def set_review_status(case_id, status):
    st.session_state["review_statuses"][case_id] = status


left, right = st.columns([2, 1])
left.subheader("케이스 목록")

with left.popover("케이스 등록"):
    with st.form("register_case"):
        case_id_input = st.text_input("새 케이스 ID", placeholder="예: HCC_025")
        exam_type = st.selectbox("검사 종류", ["치료 전 CT", "치료 후 CT"])
        new_slice_count = st.number_input("단면 수", min_value=1, value=1)
        submitted = st.form_submit_button("등록")

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

query = left.text_input("케이스 ID 검색", placeholder="예: 012").strip().casefold()
status_filter = left.selectbox(
    "검토 상태 필터",
    ["전체", "검토 대기", "검토 중", "검토 완료"],
)

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
    event = left.dataframe(
        rows,
        key=table_key,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )

    selected_rows = event.selection.rows
    selected_index = selected_rows[0] if selected_rows else 0
    selected_case = rows[selected_index]
    selected_id = selected_case["케이스 ID"]

    right.subheader("케이스 상세")
    right.write(f"케이스 ID: {selected_id}")
    right.write(f"검사 종류: {selected_case['검사 종류']}")
    right.write(f"단면 수: {selected_case['단면 수']}장")
    right.write(f"검토 상태: {selected_case['검토 상태']}")

    if right.button("뷰어 열기"):
        st.session_state["viewer_case_id"] = selected_id
else:
    left.info("검색 조건에 맞는 케이스가 없어요.")

if "viewer_case_id" in st.session_state:
    viewer_id = st.session_state["viewer_case_id"]
    total_slices = cases[viewer_id]["slice_count"]
    slice_key = f"slice_{viewer_id}"
    case_images = mock_ct_images.get(viewer_id, {})

    st.divider()
    st.subheader(f"{viewer_id} 단면 뷰어")

    viewer_status = review_statuses.get(viewer_id, "검토 대기")
    status_column, status_actions = st.columns([2, 1])
    status_column.write(f"검토 상태: {viewer_status}")
    if viewer_status == "검토 대기":
        status_actions.button(
            "검토 시작",
            key=f"start_review_{viewer_id}",
            on_click=set_review_status,
            args=(viewer_id, "검토 중"),
        )
    elif viewer_status == "검토 중":
        status_actions.button(
            "검토 완료",
            key=f"complete_review_{viewer_id}",
            on_click=set_review_status,
            args=(viewer_id, "검토 완료"),
        )

    if 41 in case_images and st.button("예시 단면 41번으로 이동"):
        st.session_state[slice_key] = 41

    measurement = mock_measurements.get(viewer_id)
    if measurement is not None:
        measurements = [
            {"slice_number": number, "area_cm2": area}
            for number, area in measurement["areas_cm2"].items()
        ]
        current_slice = st.session_state.get(slice_key, 1)
        chart_key = f"area_chart_{viewer_id}_{current_slice}"

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

        chart = (
            alt.Chart(alt.Data(values=measurements))
            .mark_circle(size=155, color="#176C67", opacity=1, cursor="pointer")
            .encode(
                x=alt.X("slice_number:Q", title="CT 단면 번호", scale=alt.Scale(zero=False)),
                y=alt.Y("area_cm2:Q", title="종양 면적 (cm²)"),
                tooltip=["slice_number:Q", "area_cm2:Q"],
            )
            .add_params(point_selection)
        )

        st.subheader("단면별 모의 종양 면적")
        st.altair_chart(chart, key=chart_key, on_select=move_to_selected_slice)

    if total_slices == 1:
        slice_number = 1
    else:
        slice_number = st.slider(
            "단면 번호",
            min_value=1,
            max_value=total_slices,
            key=slice_key,
        )
    st.write(f"현재 단면: {slice_number} / {total_slices}")

    if measurement is not None:
        current_area = measurement["areas_cm2"].get(slice_number)
        area_text = "측정값 없음"
        if current_area is not None:
            area_text = f"{current_area:.1f} cm²"

        area_column, volume_column = st.columns(2)
        area_column.metric("현재 단면 모의 면적", area_text)
        volume_column.metric("모의 전체 종양 부피", f"{measurement['volume_ml']:.1f} mL")

    uploads_by_case = st.session_state.setdefault("uploaded_ct_images", {})
    uploaded_slices = uploads_by_case.setdefault(viewer_id, {})

    with st.popover("현재 단면에 PNG 첨부"):
        with st.form(f"attach_ct_{viewer_id}_{slice_number}", clear_on_submit=True):
            png_file = st.file_uploader("모의 CT PNG", type=["png"])
            attach_clicked = st.form_submit_button("첨부")

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

    caption = f"모의 CT · {viewer_id} · {slice_number}번 단면"
    uploaded_image = uploaded_slices.get(slice_number)
    original_bytes = uploaded_image
    file_name = case_images.get(slice_number)

    if uploaded_image is not None:
        st.image(uploaded_image, caption=f"첨부한 {caption}", width="stretch")
    elif file_name:
        image_path = Path(__file__).parent / "assets" / "mock_ct" / file_name

        if image_path.is_file():
            original_bytes = image_path.read_bytes()
            image_column, controls_column = st.columns([3, 1])
            overlay_path = image_path.with_name(f"{image_path.stem}_overlay.png")
            if overlay_path.is_file():
                show_overlay = controls_column.toggle("종양 윤곽 표시")
                if show_overlay:
                    image_path = overlay_path

            image_column.image(
                str(image_path),
                caption=caption,
                width="stretch",
            )
        else:
            st.info(f"표시할 이미지 파일: {file_name}")

    elif case_images:
        available_slices = "·".join(str(number) for number in sorted(case_images))
        st.info(f"{viewer_id}의 {available_slices}번 단면에서 모의 CT를 볼 수 있어요.")
    else:
        st.info("현재 단면에 표시할 영상이 없어요.")

    if original_bytes is not None:
        compare_enabled = st.toggle(
            "원본·처리 결과 비교",
            key=f"compare_processing_{viewer_id}",
        )

        if compare_enabled:
            method = st.selectbox(
                "영상처리 도구",
                [
                    "밝기 보정",
                    "CLAHE 대비 보정",
                    "가우시안 노이즈 완화",
                    "Canny 경계 검출",
                ],
                key=f"processing_method_{viewer_id}",
            )

            with Image.open(BytesIO(original_bytes)) as image:
                original = np.array(image.convert("RGB"))

            result = None

            if method == "밝기 보정":
                factor = st.slider(
                    "밝기 배율",
                    min_value=0.5,
                    max_value=2.0,
                    value=1.0,
                    step=0.1,
                    key=f"brightness_{viewer_id}",
                )
                scaled = original.astype(np.float32) * factor
                result = np.clip(scaled, 0, 255).astype(np.uint8)

            elif method == "CLAHE 대비 보정":
                st.slider("대비 제한값", 1.0, 5.0, 2.0, 0.1)
                st.select_slider("가로·세로 타일 수", options=[4, 8, 16], value=8)

            elif method == "가우시안 노이즈 완화":
                st.select_slider("커널 크기", options=[3, 5, 7, 9], value=5)

            elif method == "Canny 경계 검출":
                st.slider("경계 임계값", 0, 255, (50, 150))

            original_column, result_column = st.columns(2)
            original_column.image(original, caption="원본", width="stretch")

            if result is None:
                result_column.info("처리 함수를 연결한 뒤 결과가 표시돼요.")
            else:
                result_column.image(result, caption=f"{method} 결과", width="stretch")

    st.divider()
    st.subheader("검토 메모")

    notes_by_case = st.session_state.setdefault("review_notes", {})
    case_notes = notes_by_case.setdefault(viewer_id, [])

    with st.form(f"review_note_{viewer_id}", clear_on_submit=True):
        note = st.text_area("메모 내용")
        submitted = st.form_submit_button("메모 저장")

    if submitted:
        note = note.strip()
        if note:
            case_notes.append({"slice_number": slice_number, "text": note})
            st.success("메모를 저장했어요.")
        else:
            st.warning("메모 내용을 입력해 주세요.")

    for saved_note in reversed(case_notes):
        st.text(f"{saved_note['slice_number']}번 단면 · {saved_note['text']}")
