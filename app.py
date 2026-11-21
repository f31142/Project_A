import streamlit as st

st.title("간 CT 검토실")

cases = {
    "HCC_004": {"exam": "치료 전 CT", "slice_count": 79},
    "HCC_012": {"exam": "치료 후 CT", "slice_count": 86},
    "HCC_018": {"exam": "치료 전 CT", "slice_count": 72},
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

    slice_number = st.slider(
        "단면 번호",
        min_value=1,
        max_value=total_slices,
        key=slice_key,
    )
    st.write(f"현재 단면: {slice_number} / {total_slices}")
