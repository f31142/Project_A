# Project_A
Hello A
dddd

## 로컬 CT 뷰어 실행

1. TCIA에서 받은 `hcc_tace_seg` 폴더를 이 저장소 폴더와 같은 상위 폴더에 둡니다. 뷰어는 아래 `HCC_004` CT 시리즈를 읽습니다.

   ```text
   hcc_tace_seg/HCC_004/1997-10-06-LIVER_PELVIS-14785/5-Recon 3_ LIVER 3 PHASE (AP)-40661/
   ```

   종양 윤곽은 같은 검사 폴더의 `300-Segmentation-39561/`에 들어 있는 DICOM SEG를 읽습니다. 파일을 다른 위치에 뒀다면 `PROJECT_A_CT_DIR`에는 CT 폴더를, `PROJECT_A_SEG_PATH`에는 SEG `.dcm` 파일을 지정합니다.
2. 저장소 폴더에서 앱을 실행합니다.

   ```bash
   uv run --no-project --managed-python --python 3.12 --with-requirements requirements.txt python -B -m streamlit run app.py
   ```

3. 케이스 목록에서 `HCC_004`를 선택하고 **뷰어 열기**를 누릅니다. 영상 위에 **DICOM CT**가 표시되는지 확인하고 기존 슬라이더로 **1 / 79**와 **79 / 79**를 엽니다.
4. 마우스 버튼을 누른 채 슬라이더를 움직여 단면 번호와 CT 미리보기가 함께 바뀌는지 확인합니다. 마우스를 놓으면 선택한 단면이 원래 해상도로 표시되고 비교·ROI·메모가 그 단면에 맞춰집니다.
5. 기본 배율 100%에서 **− 축소**를 눌러 75%, 50%로 줄입니다. **초기화**를 누르면 현재 단면이 중앙에 100%로 표시됩니다. **+ 확대**로 키운 영상을 드래그한 뒤, 단면을 넘기거나 같은 케이스를 다시 열어도 배율과 위치가 이어지는지 확인합니다.
6. **비교 열기**를 켜고 단면을 넘깁니다. 원본과 처리 결과 아래에 같은 단면 번호가 표시되는지 확인합니다.
7. 슬라이더로 `HCC_004`의 41번 단면을 선택하고 **종양 윤곽**을 켭니다. 민트색 윤곽은 `HCC_004`의 28~53번 단면에 표시됩니다. 27번이나 54번에서도 토글을 켠 채 단면을 탐색할 수 있습니다.
8. 영상 아래 면적 그래프에서 41번 막대를 누릅니다. 뷰어가 같은 단면을 열고 오른쪽 카드에서 단면 면적 31.9 cm²와 전체 종양 부피 154.8 mL를 확인할 수 있습니다.

지원 형식은 단일 프레임 CT DICOM(`.dcm`) 시리즈입니다. 촬영 위치와 방향을 기준으로 단면을 정렬합니다. 화면은 HU로 변환한 뒤 팀 설계안의 −125~225 HU 범위로 표시하며, 원본 `.dcm`은 읽기만 합니다. 종양 윤곽은 BINARY DICOM SEG의 `Mass` 프레임을 CT 시리즈·단면 UID, 좌표계, 위치, 방향, 픽셀 간격과 영상 크기로 대조한 뒤 겹칩니다.

### A에서 등록한 CT 열기

케이스 목록에 넘기는 `cases`의 각 케이스 ID에 영상 참조를 담으면, 목록과 뷰어는 그 레코드의 CT를 엽니다.

```python
st.session_state["cases"][case_id] = {
    "image_ref": str(ct_directory),
    "series_uid": str(series_uid),
    "exam": "치료 전 CT",
    "slice_count": len(ct_slices),
}
```

`image_ref`는 앱 서버에서 읽을 수 있는 단일 CT 시리즈의 DICOM 폴더입니다. 상대 경로는 `app.py`가 있는 폴더를 기준으로 해석합니다. `series_uid`는 그 시리즈의 DICOM SeriesInstanceUID입니다. 목록의 검사 이름과 단면 수는 각각 `exam`과 `slice_count`로 전달할 수 있습니다. 뷰어는 DICOM에서 읽은 실제 단면 수를 표시합니다. 정합을 확인할 DICOM SEG가 있으면 `seg_ref`에 서버가 읽을 수 있는 SEG 파일 경로를 지정합니다.

JCloud 디스크에 저장하면 그 폴더 경로를 넘깁니다. Firebase Storage를 사용하면 저장된 DICOM 파일을 서버의 읽기 가능한 폴더로 가져온 뒤 그 경로를 넘깁니다.

### CT 뷰어에서 분석으로 넘기는 값

`ct_analysis.build_analysis_slices(ct_slices, masks)`가 CT 정렬 순서대로 분석용 단면을 제공합니다.

| 값 | 접근 방법 |
| --- | --- |
| 화면 단면 번호 | `item.slice_no` (1부터 시작) |
| 원본 표시 영상 | `item.display_png()` (윤곽을 합성하기 전 8비트 흑백 PNG) |
| 영상 UID | `item.ct_slice.sop_instance_uid` |
| 정렬된 마스크 | `item.tumor_mask` (CT 픽셀과 대응하는 불리언 배열 또는 `None`) |
| 행·열 픽셀 간격 | `item.ct_slice.pixel_spacing_mm` (mm) |
| 단면 위치 | `item.ct_slice.position_mm` (단면 법선에 투영한 위치, mm) |

`measure_tumor()`는 마스크의 픽셀 수에 행·열 픽셀 간격을 곱해 단면별 `areas_mm2`를 반환합니다. 전체 CT 단면 간격이 일정하면 면적 합계에 그 간격을 곱해 `volume_ml`을 계산합니다. 뷰어는 면적을 cm²로 표시하며, 단면 간격을 확인할 수 없으면 부피 카드에 이유를 표시합니다.

CT 단면 정렬, 표시 변환, SEG 정합 및 면적·부피 계산은 아래 명령으로 검사할 수 있습니다.

```bash
uv run --no-project --managed-python --python 3.12 --with-requirements requirements.txt python -B -m unittest discover -s tests -v
```

데이터는 교육용 공개 비식별 [HCC-TACE-Seg](https://doi.org/10.7937/TCIA.5FNA-0924) 자료를 사용합니다. 배포처는 The Cancer Imaging Archive이며 이용 조건은 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)입니다.
