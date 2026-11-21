import streamlit as st
from pathlib import Path
import altair as alt

st.title("간 CT 검토실")

cases = {
    "HCC_004": {"exam": "치료 전 CT", "slice_count": 79},
    "HCC_012": {"exam": "치료 후 CT", "slice_count": 86},
    "HCC_018": {"exam": "치료 전 CT", "slice_count": 72},
}

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

left, right = st.columns(2)
selected_id = left.selectbox("케이스 선택", list(cases))
selected_case = cases[selected_id]

right.subheader("케이스 상세")
right.write(f"케이스 ID: {selected_id}")
right.write(f"검사 종류: {selected_case['exam']}")
right.write(f"단면 수: {selected_case['slice_count']}장")

if right.button("뷰어 열기"):
    st.session_state["viewer_case_id"] = selected_id

if "viewer_case_id" in st.session_state:
    viewer_id = st.session_state["viewer_case_id"]
    total_slices = cases[viewer_id]["slice_count"]
    slice_key = f"slice_{viewer_id}"

    st.divider()
    st.subheader(f"{viewer_id} 단면 뷰어")

    if st.button("예시 단면 41번으로 이동"):
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

    case_images = mock_ct_images.get(viewer_id, {})
    file_name = case_images.get(slice_number)

    if file_name:
        image_path = Path(__file__).parent / "assets" / "mock_ct" / file_name

        if image_path.is_file():
            image_column, controls_column = st.columns([3, 1])
            overlay_path = image_path.with_name(f"{image_path.stem}_overlay.png")
            if overlay_path.is_file():
                show_overlay = controls_column.toggle("종양 윤곽 표시")
                if show_overlay:
                    image_path = overlay_path

            image_column.image(
                str(image_path),
                caption=f"모의 CT · {viewer_id} · {slice_number}번 단면",
                width="stretch",
            )
        else:
            st.info(f"표시할 이미지 파일: {file_name}")

    else:
        st.info("HCC_004의 34·41·50번 단면에서 모의 CT를 볼 수 있어요.")


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
