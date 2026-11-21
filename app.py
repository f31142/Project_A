import streamlit as st

st.title("간 CT 검토실")

cases = {
    "HCC_004": {"exam": "치료 전 CT", "slice_count": 79},
}

left, right = st.columns(2)
selected_id = left.selectbox("케이스 선택", list(cases))
selected_case = cases[selected_id]