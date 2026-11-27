"""UI 다국어(한국어/영어) 표시 레이어.

내부 저장소(Firestore), session_state, case_list 로직은 기존 정식 키
("전체", "검토 대기", "검토 중", "검토 완료", "치료 전 CT" 등)를 그대로 유지하고,
화면 출력 직전에만 현재 언어(ko | en)로 변환합니다.
"""

from __future__ import annotations

from case_list import ALL_STATUSES, case_display_name

LANG_KO = "ko"
LANG_EN = "en"
LANG_CHOICES = ("KO", "EN")

_CHOICE_TO_LANG = {"KO": LANG_KO, "EN": LANG_EN}
_LANG_TO_CHOICE = {LANG_KO: "KO", LANG_EN: "EN"}

STATUS_LABELS = {
    ALL_STATUSES: {LANG_KO: "전체", LANG_EN: "All"},
    "검토 대기": {LANG_KO: "검토 대기", LANG_EN: "Waiting"},
    "검토 중": {LANG_KO: "검토 중", LANG_EN: "In Review"},
    "검토 완료": {LANG_KO: "검토 완료", LANG_EN: "Done"},
}

EXAM_LABELS = {
    "치료 전 CT": {LANG_KO: "치료 전 CT", LANG_EN: "Pre-Tx CT"},
    "치료 후 CT": {LANG_KO: "치료 후 CT", LANG_EN: "Post-Tx CT"},
    "치료 전 CT · 합성 실험용": {
        LANG_KO: "치료 전 CT · 합성 실험용",
        LANG_EN: "Pre-Tx CT · Synthetic",
    },
    "CT 검사": {LANG_KO: "CT 검사", LANG_EN: "CT Exam"},
}

SOURCE_LABELS = {
    "dicom": {LANG_KO: "DICOM CT", LANG_EN: "DICOM CT"},
    "synthetic_dicom": {LANG_KO: "합성 DICOM CT", LANG_EN: "Synthetic DICOM"},
    "mock": {LANG_KO: "모의 CT", LANG_EN: "Mock CT"},
    "uploaded_png": {LANG_KO: "첨부한 PNG", LANG_EN: "Uploaded PNG"},
}

PROCESSING_METHOD_LABELS = {
    "CLAHE 대비 보정": {LANG_KO: "CLAHE 대비 보정", LANG_EN: "CLAHE Contrast"},
    "양방향 필터": {LANG_KO: "양방향 필터", LANG_EN: "Bilateral Filter"},
    "Canny 경계 검출": {LANG_KO: "Canny 경계 검출", LANG_EN: "Canny Edge"},
    "2D 연결 성분 분석": {LANG_KO: "2D 연결 성분 분석", LANG_EN: "2D Connected Comp."},
    "밝기 보정": {LANG_KO: "밝기 보정", LANG_EN: "Brightness Adjust"},
}

PROCESSING_METHOD_CAPTIONS = {
    "CLAHE 대비 보정": {
        LANG_KO: "CT의 부분별 명암 차이를 강조해요.",
        LANG_EN: "Enhances local CT contrast across regions.",
    },
    "양방향 필터": {
        LANG_KO: "경계를 유지하면서 잔잔한 노이즈를 줄여요.",
        LANG_EN: "Reduces fine noise while preserving edges.",
    },
    "Canny 경계 검출": {
        LANG_KO: "밝기가 급격히 바뀌는 부분을 선으로 표시해요.",
        LANG_EN: "Highlights sharp intensity transitions as edges.",
    },
    "2D 연결 성분 분석": {
        LANG_KO: "현재 단면의 종양 SEG를 사용해 영역별 면적을 계산할 예정이에요.",
        LANG_EN: "Separates disconnected tumor components to inspect areas.",
    },
}

ROI_MODE_LABELS = {
    "영상에서 드래그": {LANG_KO: "영상에서 드래그", LANG_EN: "Drag on CT"},
    "좌표 슬라이더": {LANG_KO: "좌표 슬라이더", LANG_EN: "Coord Sliders"},
}

STRINGS = {
    "app_title": {LANG_KO: "간 CT 검토실", LANG_EN: "LIVER CT STUDIO"},
    "app_badge": {
        LANG_KO: "교육용 · 세션 유지",
        LANG_EN: "SESSION MODE",
    },
    "nav_aria": {LANG_KO: "현재 위치", LANG_EN: "Breadcrumb"},
    "section_nav_aria": {LANG_KO: "섹션 이동", LANG_EN: "Section Navigation"},
    "nav_01_viewer": {LANG_KO: "01 뷰어", LANG_EN: "01 Viewer"},
    "nav_02_compare": {LANG_KO: "02 비교", LANG_EN: "02 Compare"},
    "nav_03_roi": {LANG_KO: "03 ROI", LANG_EN: "03 ROI"},
    "nav_04_summary": {LANG_KO: "04 요약", LANG_EN: "04 Summary"},
    "nav_05_memo": {LANG_KO: "05 메모", LANG_EN: "05 Memo"},
    "nav_cases_tab": {LANG_KO: "케이스 목록", LANG_EN: "Cases"},
    "nav_viewer_tab": {LANG_KO: "CT 뷰어", LANG_EN: "CT Viewer"},
    "dock_aria": {LANG_KO: "빠른 이동 도구 바", LANG_EN: "Quick Navigation Dock"},
    "dock_cases": {LANG_KO: "케이스 목록", LANG_EN: "Cases"},
    "dock_search": {LANG_KO: "케이스 검색", LANG_EN: "Search Cases"},
    "dock_compare": {LANG_KO: "02 원본·처리 비교", LANG_EN: "02 Compare"},
    "dock_viewer": {LANG_KO: "01 CT 뷰어", LANG_EN: "01 Viewer"},
    "dock_open_viewer": {LANG_KO: "선택 케이스 열기", LANG_EN: "Open Viewer"},
    "dock_roi": {LANG_KO: "03 ROI 분석", LANG_EN: "03 ROI Analysis"},
    "dock_memo": {LANG_KO: "05 검토 메모", LANG_EN: "05 Review Memo"},
    "dock_viewer_only": {LANG_KO: "케이스를 열면 활성화돼요", LANG_EN: "Open a case to use"},
    "lang_aria": {LANG_KO: "언어 선택", LANG_EN: "Language"},
    "case_list_title": {LANG_KO: "케이스 목록", LANG_EN: "Case Directory"},
    "case_list_desc": {
        LANG_KO: "검토할 케이스를 고르면 오른쪽에 요약이 나오고, 뷰어에서 단면을 엽니다.",
        LANG_EN: "Select a case to preview details and launch the axial CT viewer.",
    },
    "register_case": {LANG_KO: "케이스 등록", LANG_EN: "Register Case"},
    "register_new_id": {LANG_KO: "새 케이스 ID", LANG_EN: "New Case ID"},
    "register_id_placeholder": {LANG_KO: "예: HCC_025", LANG_EN: "e.g. HCC_025"},
    "exam_type": {LANG_KO: "검사 종류", LANG_EN: "Exam Type"},
    "ct_dicom_files": {LANG_KO: "CT DICOM 파일", LANG_EN: "CT DICOM Files"},
    "ct_dicom_help": {
        LANG_KO: "한 시리즈의 .dcm 파일을 여러 개 함께 선택할 수 있어요.",
        LANG_EN: "Select multiple .dcm files belonging to a single CT series.",
    },
    "submit_register": {LANG_KO: "등록", LANG_EN: "Register"},
    "register_spinner": {
        LANG_KO: "CT 파일을 저장하고 시리즈를 확인하고 있어요…",
        LANG_EN: "Saving CT files and validating the series…",
    },
    "storage_not_connected": {
        LANG_KO: "저장소에 연결되지 않아 등록할 수 없어요. ({error})",
        LANG_EN: "Unable to register because storage is disconnected. ({error})",
    },
    "register_unexpected_error": {
        LANG_KO: "등록 중 예상하지 못한 오류가 났어요. 파일과 기록을 저장하지 않았어요. ({error})",
        LANG_EN: "Unexpected error during registration. Nothing was saved. ({error})",
    },
    "register_summary": {
        LANG_KO: "CT 단면 {slice_count}장(파일 {file_count}개 · {total_mb:.1f} MB)을 확인하고 서버 디스크에 저장했어요.",
        LANG_EN: "Verified {slice_count} CT slices ({file_count} files · {total_mb:.1f} MB) and stored on disk.",
    },
    "register_success_persistent": {
        LANG_KO: "{case_id} 케이스를 등록했어요. {summary} 케이스 정보는 Firestore에 기록했어요.",
        LANG_EN: "Registered {case_id}. {summary} Metadata saved to Firestore.",
    },
    "register_success_session": {
        LANG_KO: "{case_id} 케이스를 이 세션에 등록했어요. {summary}\n\nFirestore가 연결되지 않아 케이스 정보는 새로고침하면 사라져요.",
        LANG_EN: "Registered {case_id} for this session. {summary}\n\nFirestore is disconnected; metadata resets on refresh.",
    },
    "firestore_disconnected_caption": {
        LANG_KO: "Firestore 미연결 · 등록한 케이스 정보는 이 세션 동안만 유지돼요.",
        LANG_EN: "Firestore disconnected · Registered cases persist for this session only.",
    },
    "search_label": {LANG_KO: "케이스 ID 검색", LANG_EN: "Search Case ID"},
    "search_placeholder": {
        LANG_KO: "케이스 ID 검색 · 예: 012",
        LANG_EN: "Search Case ID… e.g. 012",
    },
    "status_filter_label": {LANG_KO: "검토 상태 필터", LANG_EN: "Review Status Filter"},
    "refresh_help": {
        LANG_KO: "저장소에서 케이스 목록을 다시 불러와요.",
        LANG_EN: "Reload case list from storage.",
    },
    "col_case_id": {LANG_KO: "케이스 ID", LANG_EN: "Case ID"},
    "col_exam_type": {LANG_KO: "검사 종류", LANG_EN: "Exam Type"},
    "col_slice_count": {LANG_KO: "단면 수", LANG_EN: "Slices"},
    "col_review_status": {LANG_KO: "검토 상태", LANG_EN: "Status"},
    "slice_count_format": {LANG_KO: "%d장", LANG_EN: "%d"},
    "slice_count_text": {LANG_KO: "{count}장", LANG_EN: "{count} slices"},
    "empty_cases_title": {
        LANG_KO: "검색 조건에 맞는 케이스가 없어요",
        LANG_EN: "No matching cases found",
    },
    "empty_cases_desc": {
        LANG_KO: "검색어를 지우거나 상태 필터를 ‘전체’로 바꿔 보세요.",
        LANG_EN: "Clear your search query or switch the status filter to All.",
    },
    "cases_caption_left": {
        LANG_KO: "케이스 {count}개 · 행을 눌러 고릅니다",
        LANG_EN: "{count} cases · Select a row to preview",
    },
    "cases_caption_cards": {
        LANG_KO: "케이스 {count}개 · 카드를 눌러 요약 확인",
        LANG_EN: "{count} cases · Select a card to preview",
    },
    "cases_total_inline": {LANG_KO: "전체 {count}", LANG_EN: "{count} Cases"},
    "view_mode_label": {LANG_KO: "보기 방식", LANG_EN: "View Mode"},
    "view_grid": {LANG_KO: "카드", LANG_EN: "Grid"},
    "view_list": {LANG_KO: "목록", LANG_EN: "List"},
    "card_tag_ai": {LANG_KO: "AI 생성", LANG_EN: "AI GEN"},
    "card_tag_dicom": {LANG_KO: "DICOM", LANG_EN: "DICOM"},
    "card_tag_mock": {LANG_KO: "모의 CT", LANG_EN: "MOCK CT"},
    "card_no_preview": {LANG_KO: "미리보기 없음", LANG_EN: "No preview slice"},
    "card_select": {LANG_KO: "선택", LANG_EN: "Select"},
    "card_selected": {LANG_KO: "선택됨", LANG_EN: "Selected"},
    "card_open_viewer": {LANG_KO: "열기", LANG_EN: "Open"},
    "card_subtitle_synthetic": {LANG_KO: "합성", LANG_EN: "Synthetic"},
    "card_subtitle_mock": {LANG_KO: "모의", LANG_EN: "Mock"},
    "card_subtitle_dicom": {LANG_KO: "DICOM", LANG_EN: "DICOM"},
    "max_area_label": {LANG_KO: "최대 단면 면적", LANG_EN: "Max Area"},
    "selected_case_overline": {LANG_KO: "선택한 케이스", LANG_EN: "SELECTED CASE"},
    "select_case_prompt": {
        LANG_KO: "표에서 케이스를 고르면 요약이 나와요",
        LANG_EN: "Select a case to preview its summary",
    },
    "dicom_image_label": {LANG_KO: "DICOM 영상", LANG_EN: "DICOM Series"},
    "mock_image_label": {LANG_KO: "모의 영상", LANG_EN: "Mock Slices"},
    "cannot_open": {LANG_KO: "열 수 없음", LANG_EN: "Unavailable"},
    "none": {LANG_KO: "없음", LANG_EN: "None"},
    "mock_slices_text": {LANG_KO: "{slices}번", LANG_EN: "#{slices}"},
    "tumor_volume_label": {LANG_KO: "종양 부피", LANG_EN: "Tumor Volume"},
    "mock_volume_label": {LANG_KO: "모의 부피", LANG_EN: "Mock Volume"},
    "key_slice_chip": {
        LANG_KO: "{current} / {total} · 대표 단면",
        LANG_EN: "{current} / {total} · KEY SLICE",
    },
    "thumb_alt": {
        LANG_KO: "{name} {number}번 단면 미리보기",
        LANG_EN: "{name} slice {number} preview",
    },
    "no_dicom_preview": {LANG_KO: "DICOM 미리보기 없음", LANG_EN: "No DICOM preview"},
    "no_attached_image": {LANG_KO: "첨부된 영상 없음", LANG_EN: "No attached image"},
    "open_viewer": {LANG_KO: "뷰어 열기", LANG_EN: "Open Viewer"},
    "back_to_list": {LANG_KO: "케이스 목록", LANG_EN: "Cases"},
    "meta_slices": {LANG_KO: "{count} 단면", LANG_EN: "{count} Slices"},
    "meta_mock_measurements": {LANG_KO: "모의 측정값 있음", LANG_EN: "Mock metrics"},
    "attach_png": {LANG_KO: "현재 단면에 PNG 첨부", LANG_EN: "Attach PNG"},
    "mock_ct_png": {LANG_KO: "모의 CT PNG", LANG_EN: "Mock CT PNG"},
    "attach_submit": {LANG_KO: "첨부", LANG_EN: "Attach"},
    "attach_warning": {
        LANG_KO: "첨부할 PNG를 선택해 주세요.",
        LANG_EN: "Please select a PNG file to attach.",
    },
    "attach_invalid": {
        LANG_KO: "이미지를 읽을 수 없어요. 정상적인 PNG 파일을 선택해 주세요.",
        LANG_EN: "Could not read image. Please upload a valid PNG file.",
    },
    "attach_success": {
        LANG_KO: "{case_id}의 {slice_number}번 단면에 PNG를 첨부했어요.",
        LANG_EN: "Attached PNG to slice #{slice_number} of {case_id}.",
    },
    "start_review": {LANG_KO: "검토 시작", LANG_EN: "Start Review"},
    "complete_review": {LANG_KO: "검토 완료", LANG_EN: "Complete Review"},
    "dicom_open_error": {
        LANG_KO: "등록된 DICOM CT를 열 수 없어요. {error}",
        LANG_EN: "Unable to open registered DICOM CT. {error}",
    },
    "dicom_fallback_warning": {
        LANG_KO: "원본 DICOM을 열 수 없어 모의 영상을 표시해요. {error}",
        LANG_EN: "Showing mock image because original DICOM failed to load. {error}",
    },
    "area_title_dicom": {LANG_KO: "종양 면적", LANG_EN: "Tumor Area"},
    "area_title_mock": {LANG_KO: "모의 종양 면적", LANG_EN: "Mock Tumor Area"},
    "slice_prefix": {LANG_KO: "단면", LANG_EN: "SLICE"},
    "contour_on_dicom": {LANG_KO: "종양 윤곽 켜짐", LANG_EN: "CONTOUR ON"},
    "contour_on_mock": {LANG_KO: "종양 윤곽 표시 중", LANG_EN: "CONTOUR ON"},
    "zoom_out": {LANG_KO: "− 축소", LANG_EN: "−"},
    "zoom_in": {LANG_KO: "+ 확대", LANG_EN: "+"},
    "zoom_reset": {LANG_KO: "초기화", LANG_EN: "Reset"},
    "zoom_out_aria": {LANG_KO: "축소", LANG_EN: "Zoom out"},
    "zoom_in_aria": {LANG_KO: "확대", LANG_EN: "Zoom in"},
    "zoom_controls_aria": {LANG_KO: "CT 보기 조작", LANG_EN: "CT Viewport Controls"},
    "zoom_readout_aria": {LANG_KO: "현재 배율", LANG_EN: "Current zoom"},
    "ct_image_aria": {LANG_KO: "CT 영상", LANG_EN: "CT Slice"},
    "ct_image_alt": {LANG_KO: "CT 단면", LANG_EN: "Axial CT slice"},
    "stage_empty_title": {
        LANG_KO: "{slice_number}번 단면에 표시할 영상이 없어요",
        LANG_EN: "No image available for slice #{slice_number}",
    },
    "stage_empty_available": {
        LANG_KO: "{available}번 단면에서 모의 CT를 볼 수 있어요. 이 단면에 PNG를 첨부할 수도 있어요.",
        LANG_EN: "Mock CT slices are available on #{available}. You can also attach a PNG here.",
    },
    "stage_empty_upload": {
        LANG_KO: "위의 ‘현재 단면에 PNG 첨부’로 모의 CT를 올려 보세요.",
        LANG_EN: "Use ‘Attach PNG’ above to upload a mock CT slice.",
    },
    "prev_slice": {LANG_KO: "이전 단면", LANG_EN: "Previous slice"},
    "next_slice": {LANG_KO: "다음 단면", LANG_EN: "Next slice"},
    "slice_slider_label": {LANG_KO: "단면 번호", LANG_EN: "Slice Number"},
    "area_chart_title": {LANG_KO: "단면별 {area_title}", LANG_EN: "SLICE {area_title}"},
    "area_chart_hint": {
        LANG_KO: "슬라이더와 같은 가로축 · 막대를 누르면 그 단면으로 이동",
        LANG_EN: "Aligned with slice slider · Click any bar to jump",
    },
    "tooltip_slice": {LANG_KO: "단면", LANG_EN: "Slice"},
    "max_area_button": {
        LANG_KO: "최대 면적 단면 보기 · {slice_number}번",
        LANG_EN: "Jump to Peak · #{slice_number}",
    },
    "no_measurement": {LANG_KO: "측정값 없음", LANG_EN: "No data"},
    "no_seg_this_slice": {
        LANG_KO: "이 단면에 SEG로 표시된 종양 영역이 없어요.",
        LANG_EN: "No SEG tumor mask on this slice.",
    },
    "no_seg_connected": {
        LANG_KO: "이 케이스에 연결된 DICOM SEG가 없어요.",
        LANG_EN: "No DICOM SEG linked to this case.",
    },
    "empty_seg_mask": {
        LANG_KO: "이 SEG의 종양 마스크가 비어 있어요.",
        LANG_EN: "The tumor mask in this SEG is empty.",
    },
    "uploaded_no_measurement": {
        LANG_KO: "첨부한 PNG에는 연결된 종양 측정값이 없어요.",
        LANG_EN: "Uploaded PNG slices do not have linked tumor metrics.",
    },
    "measured_slices_hint": {
        LANG_KO: "{slices}번 단면에 측정값이 있어요",
        LANG_EN: "Measurements available on slices #{slices}",
    },
    "no_mock_measurements": {
        LANG_KO: "이 케이스에는 모의 측정값이 없어요",
        LANG_EN: "No mock measurements for this case",
    },
    "this_slice_overline": {
        LANG_KO: "이 단면 · {current} / {total}",
        LANG_EN: "SLICE AREA · {current} / {total}",
    },
    "whole_case_overline": {LANG_KO: "케이스 전체", LANG_EN: "TOTAL VOLUME"},
    "volume_caption_dicom": {LANG_KO: "전체 종양 부피", LANG_EN: "Total tumor volume"},
    "volume_caption_mock": {
        LANG_KO: "모의 전체 종양 부피 · 단면을 바꿔도 그대로",
        LANG_EN: "Mock total volume · Constant across slices",
    },
    "contour_toggle": {LANG_KO: "종양 윤곽", LANG_EN: "Tumor Contour"},
    "contour_caption_dicom": {
        LANG_KO: "이 단면의 SEG 종양 윤곽을 겹쳐 봅니다",
        LANG_EN: "Overlays the DICOM SEG tumor contour on this slice",
    },
    "contour_caption_dicom_none": {
        LANG_KO: "이 단면에는 종양 윤곽이 없어요",
        LANG_EN: "No tumor contour on this slice",
    },
    "contour_caption_mock": {
        LANG_KO: "이 단면의 모의 윤곽을 겹쳐 봅니다",
        LANG_EN: "Overlays the mock tumor contour on this slice",
    },
    "contour_caption_mock_available": {
        LANG_KO: "{slices}번 단면에서 쓸 수 있어요",
        LANG_EN: "Available on slice #{slices}",
    },
    "contour_caption_none": {
        LANG_KO: "이 케이스에는 윤곽 오버레이가 없어요",
        LANG_EN: "No contour overlay available for this case",
    },
    "jump_overline": {LANG_KO: "아래로 이어지는 도구", LANG_EN: "ANALYSIS TOOLS"},
    "display_controls_overline": {LANG_KO: "표시 설정", LANG_EN: "DISPLAY CONTROLS"},
    "quick_metrics_overline": {LANG_KO: "빠른 수치 & 메모", LANG_EN: "QUICK METRICS & NOTES"},
    "quick_roi_value": {
        LANG_KO: "ROI 평균 {mean:.1f} · {w}×{h} px",
        LANG_EN: "Mean {mean:.1f} · {w}×{h} px",
    },
    "quick_roi_empty": {
        LANG_KO: "선택된 ROI 없음",
        LANG_EN: "No ROI selected yet",
    },
    "quick_memo_empty": {LANG_KO: "저장된 메모 없음", LANG_EN: "No notes saved yet"},
    "quick_open_memo": {LANG_KO: "메모 열기", LANG_EN: "Open Memo"},
    "quick_open_roi": {LANG_KO: "ROI 분석", LANG_EN: "Open ROI"},
    "roi_reset_btn": {LANG_KO: "ROI 초기화", LANG_EN: "Reset ROI"},
    "roi_kpi_mean": {LANG_KO: "평균 밝기", LANG_EN: "MEAN INTENSITY"},
    "roi_kpi_size": {LANG_KO: "선택 크기", LANG_EN: "ROI SIZE"},
    "roi_kpi_area": {LANG_KO: "ROI 면적", LANG_EN: "ROI AREA"},
    "roi_kpi_pixels": {LANG_KO: "픽셀 수", LANG_EN: "PIXELS"},
    "roi_hud_coords": {
        LANG_KO: "x: {x0}–{x1} · y: {y0}–{y1} px",
        LANG_EN: "x: {x0}–{x1} · y: {y0}–{y1} px",
    },
    "roi_drag_hint_saved": {
        LANG_KO: "새 영역을 드래그하거나 초기화할 수 있어요",
        LANG_EN: "Drag to redraw ROI or click Reset ROI",
    },
    "sec_02_title": {LANG_KO: "원본·처리 비교", LANG_EN: "Original · Processed Comparison"},
    "sec_02_desc": {
        LANG_KO: "영상처리 도구를 바꿔 가며 원본과 결과를 나란히 봅니다",
        LANG_EN: "Adjust enhancement filters and compare side-by-side",
    },
    "sec_03_title": {LANG_KO: "관심 영역(ROI) 분석", LANG_EN: "ROI Analysis"},
    "sec_03_desc": {
        LANG_KO: "영역을 고르면 평균 밝기와 분포가 바로 갱신됩니다",
        LANG_EN: "Select a region on the CT slice to inspect pixel intensity",
    },
    "sec_04_title": {LANG_KO: "현재 단면 측정 요약", LANG_EN: "Slice Measurement Summary"},
    "sec_04_desc": {
        LANG_KO: "현재 단면의 종양 수치와 ROI 결과를 검토 기록용으로 저장합니다",
        LANG_EN: "Review slice metrics and save a snapshot to the review record",
    },
    "sec_05_title": {LANG_KO: "검토 메모", LANG_EN: "Review Memo"},
    "sec_05_desc": {
        LANG_KO: "저장하면 현재 단면 번호가 함께 남습니다",
        LANG_EN: "Notes are automatically tagged with the active slice number",
    },
    "toggle_compare": {LANG_KO: "비교 열기", LANG_EN: "Active"},
    "need_slice_image": {
        LANG_KO: "이 단면에 영상이 있을 때 쓸 수 있어요.",
        LANG_EN: "Available when an image exists for this slice.",
    },
    "use_brightness": {LANG_KO: "기본 밝기 보정 사용", LANG_EN: "Basic Brightness"},
    "processing_tool": {LANG_KO: "영상처리 도구", LANG_EN: "Processing Filter"},
    "brightness_factor": {LANG_KO: "밝기 배율", LANG_EN: "Brightness Scale"},
    "brightness_hint": {
        LANG_KO: "1.0으로 돌리면 원본과 같아요.",
        LANG_EN: "Set to 1.0 to match the original image.",
    },
    "brightness_reset": {LANG_KO: "밝기 초기화", LANG_EN: "Reset"},
    "clahe_clip": {LANG_KO: "대비 제한값", LANG_EN: "Clip Limit"},
    "clahe_tile": {LANG_KO: "가로·세로 타일 수", LANG_EN: "Tile Grid Size"},
    "bilateral_sigma": {LANG_KO: "밝기 차이 허용 정도", LANG_EN: "Intensity Sigma"},
    "canny_thresh": {LANG_KO: "경계 임계값", LANG_EN: "Edge Threshold"},
    "cc_caption": {
        LANG_KO: "현재 단면의 종양 SEG를 사용해 영역별 면적을 계산할 예정이에요.",
        LANG_EN: "Computes per-component areas using the active tumor SEG mask.",
    },
    "tile_original": {
        LANG_KO: "원본 · 단면 {slice_number}",
        LANG_EN: "Original · Slice {slice_number}",
    },
    "tile_result": {
        LANG_KO: "{method} 결과 · 단면 {slice_number}",
        LANG_EN: "{method} · Slice {slice_number}",
    },
    "tile_empty": {
        LANG_KO: "처리 함수를 연결한 뒤 결과가 표시돼요.",
        LANG_EN: "Connect the processing pipeline to preview results here.",
    },
    "toggle_roi": {LANG_KO: "분석 열기", LANG_EN: "Active"},
    "roi_mode_label": {LANG_KO: "ROI 지정 방식", LANG_EN: "ROI Selection Mode"},
    "roi_x_range": {LANG_KO: "가로 범위 (x)", LANG_EN: "X Range"},
    "roi_y_range": {LANG_KO: "세로 범위 (y)", LANG_EN: "Y Range"},
    "roi_drag_caption": {
        LANG_KO: "영상 위를 드래그해 상자를 그립니다",
        LANG_EN: "Drag across the CT slice to draw an ROI box",
    },
    "roi_prompt": {
        LANG_KO: "CT 위에서 드래그해 관심 영역을 선택해 주세요.",
        LANG_EN: "Drag on the CT image to define a region of interest.",
    },
    "roi_min_warning": {
        LANG_KO: "가로와 세로 범위를 각각 한 픽셀 이상으로 골라 주세요.",
        LANG_EN: "Select at least 1 pixel along both X and Y axes.",
    },
    "roi_selected_caption": {
        LANG_KO: "{slice_number}번 단면 · 선택한 ROI",
        LANG_EN: "Slice {slice_number} · Selected ROI",
    },
    "roi_mean_label": {LANG_KO: "평균 밝기", LANG_EN: "Mean Intensity"},
    "roi_size_label": {LANG_KO: "선택 크기", LANG_EN: "Selection"},
    "roi_pixel_total": {LANG_KO: "총 {count:,}픽셀", LANG_EN: "{count:,} px"},
    "roi_hist_heading": {LANG_KO: "밝기 분포", LANG_EN: "Brightness Distribution"},
    "roi_mean_legend": {LANG_KO: "평균", LANG_EN: "Mean"},
    "axis_brightness": {LANG_KO: "픽셀 밝기", LANG_EN: "Intensity (0–255)"},
    "axis_pixels": {LANG_KO: "픽셀 수", LANG_EN: "Pixel Count"},
    "tooltip_brightness": {LANG_KO: "밝기", LANG_EN: "Intensity"},
    "tooltip_pixels": {LANG_KO: "픽셀 수", LANG_EN: "Pixels"},
    "roi_details_expander": {LANG_KO: "ROI 상세정보", LANG_EN: "ROI Technical Details"},
    "roi_bounds_caption": {
        LANG_KO: "선택 범위 · x {x0}–{x1}, y {y0}–{y1}",
        LANG_EN: "Bounds · x {x0}–{x1}, y {y0}–{y1}",
    },
    "roi_area_caption": {
        LANG_KO: "사각형 ROI 면적 · {area:,.2f} mm²",
        LANG_EN: "Rectangular ROI Area · {area:,.2f} mm²",
    },
    "summary_caption_line": {
        LANG_KO: "{name} · {slice_number}번 단면 · {source}",
        LANG_EN: "{name} · Slice {slice_number} · {source}",
    },
    "summary_metric_area": {LANG_KO: "현재 단면의 종양 면적", LANG_EN: "SLICE TUMOR AREA"},
    "summary_metric_volume": {LANG_KO: "케이스 전체 종양 부피", LANG_EN: "TOTAL TUMOR VOLUME"},
    "summary_metric_roi": {LANG_KO: "관심 영역(ROI) 요약", LANG_EN: "ROI SUMMARY"},
    "summary_saved_badge": {
        LANG_KO: "저장됨 · {slice_number}번 단면",
        LANG_EN: "Saved · Slice #{slice_number}",
    },
    "summary_no_roi": {LANG_KO: "선택한 ROI 없음", LANG_EN: "No ROI selected"},
    "summary_roi_line": {
        LANG_KO: "사각형 ROI · x {x0}–{x1}, y {y0}–{y1} · {pixels:,}픽셀 · 평균 밝기 {mean:.1f} / 255",
        LANG_EN: "Rect ROI · x {x0}–{x1}, y {y0}–{y1} · {pixels:,} px · Mean {mean:.1f} / 255",
    },
    "summary_roi_area_suffix": {
        LANG_KO: " · ROI 면적 {area:,.2f} mm²",
        LANG_EN: " · ROI Area {area:,.2f} mm²",
    },
    "summary_need_image": {
        LANG_KO: "영상이 있는 단면에서 측정값을 선택할 수 있어요.",
        LANG_EN: "Select measurements on a slice with an image.",
    },
    "select_measurement_btn": {
        LANG_KO: "검토 기록에 사용할 측정값 선택",
        LANG_EN: "Save to Review Record",
    },
    "saved_measurement_expander": {
        LANG_KO: "검토 기록용 측정값 · {slice_number}번 단면",
        LANG_EN: "Saved Review Measurement · Slice #{slice_number}",
    },
    "memo_content_label": {LANG_KO: "메모 내용", LANG_EN: "Note Content"},
    "memo_slice_tag": {
        LANG_KO: "{slice_number}번 단면에 저장",
        LANG_EN: "Save to Slice #{slice_number}",
    },
    "memo_placeholder": {
        LANG_KO: "이 단면에서 확인한 내용을 적어 주세요",
        LANG_EN: "Document clinical observations for this slice…",
    },
    "memo_submit": {LANG_KO: "메모 저장", LANG_EN: "Save Note"},
    "memo_saved": {LANG_KO: "메모를 저장했어요.", LANG_EN: "Note saved."},
    "memo_empty_warning": {
        LANG_KO: "메모 내용을 입력해 주세요.",
        LANG_EN: "Please enter note content.",
    },
    "memo_count": {LANG_KO: "메모 {count}개", LANG_EN: "{count} Notes"},
    "memo_slice_badge": {LANG_KO: "{slice_number}번", LANG_EN: "#{slice_number}"},
    "memo_order_caption": {
        LANG_KO: "최근 저장한 메모가 위에 옵니다",
        LANG_EN: "Newest notes appear first",
    },
    "memo_empty_title": {LANG_KO: "아직 저장한 메모가 없어요", LANG_EN: "No notes saved yet"},
    "memo_empty_desc": {
        LANG_KO: "단면을 보며 확인한 내용을 왼쪽에 적어 저장해 보세요.",
        LANG_EN: "Write your slice observations on the left and save them.",
    },
}


def normalize_lang(value: str | None) -> str:
    if not value:
        return LANG_KO
    cleaned = str(value).strip().upper()
    if cleaned in _CHOICE_TO_LANG:
        return _CHOICE_TO_LANG[cleaned]
    lowered = cleaned.lower()
    return LANG_EN if lowered == LANG_EN else LANG_KO


def lang_to_choice(lang: str) -> str:
    return _LANG_TO_CHOICE.get(normalize_lang(lang), "KO")


def t(key: str, lang: str = LANG_KO, **kwargs) -> str:
    lang_code = normalize_lang(lang)
    entry = STRINGS.get(key)
    if entry is None:
        return key
    template = entry.get(lang_code) or entry.get(LANG_KO, key)
    return template.format(**kwargs) if kwargs else template


def label_status(status: str, lang: str = LANG_KO) -> str:
    lang_code = normalize_lang(lang)
    entry = STATUS_LABELS.get(status)
    return entry[lang_code] if entry else str(status)


def label_exam(exam: str, lang: str = LANG_KO) -> str:
    lang_code = normalize_lang(lang)
    entry = EXAM_LABELS.get(exam)
    return entry[lang_code] if entry else str(exam)


def label_source(source_kind: str, lang: str = LANG_KO) -> str:
    lang_code = normalize_lang(lang)
    entry = SOURCE_LABELS.get(source_kind)
    return entry[lang_code] if entry else str(source_kind)


def label_method(method: str, lang: str = LANG_KO) -> str:
    lang_code = normalize_lang(lang)
    entry = PROCESSING_METHOD_LABELS.get(method)
    return entry[lang_code] if entry else str(method)


def method_caption(method: str, lang: str = LANG_KO) -> str:
    lang_code = normalize_lang(lang)
    entry = PROCESSING_METHOD_CAPTIONS.get(method)
    return entry[lang_code] if entry else ""


def label_roi_mode(mode: str, lang: str = LANG_KO) -> str:
    lang_code = normalize_lang(lang)
    entry = ROI_MODE_LABELS.get(mode)
    return entry[lang_code] if entry else str(mode)


def label_case_name(case: dict, lang: str = LANG_KO) -> str:
    raw = case_display_name(case)
    if normalize_lang(lang) == LANG_EN and case.get("synthetic"):
        base_id = str(case["case_id"]).removeprefix("demo:")
        return f"{base_id} (AI Synthetic)"
    return raw
