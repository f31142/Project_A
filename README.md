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

목록과 뷰어는 `app.py`의 `cases`(`case_ui.load_cases()`가 Firestore 문서와 모의 케이스를 합친 dict)를 읽습니다. 등록된 케이스의 레코드는 아래 형식입니다.

```python
cases[case_id] = {
    "exam": "치료 전 CT",
    "slice_count": 79,                        # DICOM에서 읽은 실제 단면 수
    "image_ref": "/srv/uploads/cases/HCC_025/20261125T0100_ab12cd34",  # 서버 폴더 절대 경로
    "series_uid": "1.3.6.1.4...",             # DICOM SeriesInstanceUID
    ...
}
```

뷰어는 `image_ref`·`series_uid` 키가 있으면 등록된 CT로 보고 그 폴더를 엽니다. 모의 케이스에는 두 키가 없습니다. 정합을 확인할 DICOM SEG가 있으면 `seg_ref`에 서버가 읽을 수 있는 SEG 파일 경로를 지정합니다.

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


데이터는 교육용 공개 비식별 [HCC-TACE-Seg](https://doi.org/10.7937/TCIA.5FNA-0924) 자료를 사용합니다. 배포처는 The Cancer Imaging Archive이며 이용 조건은 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)입니다.

## ROI 분석과 검토용 측정값 선택 (C)

### 모의 케이스로 확인하기

1. 케이스 목록에서 `HCC_004`를 선택하고 **뷰어 열기**를 누릅니다. 아래 수치는 뷰어에 **모의 CT**가 표시될 때의 예시입니다.
2. **최대 면적 단면 보기 · 41번**을 누릅니다. **관심 영역(ROI) 분석**에서 **분석 열기**를 켜고 영상 위를 드래그해 사각형을 그립니다. **좌표 슬라이더**로 범위를 지정할 수도 있습니다.
3. **현재 단면 측정 요약**에서 41번 단면의 종양 면적 **31.9 cm²**, 케이스 전체 종양 부피 **154.8 mL**, 선택한 ROI의 픽셀 수와 평균 밝기를 확인합니다.
4. **검토 기록에 사용할 측정값 선택**을 누른 뒤 50번 단면으로 이동합니다. 현재 요약에 50번의 면적 **15.7 cm²**가 표시됩니다. **검토 기록용 측정값 · 41번 단면**을 펼치면 앞서 선택한 41번의 면적과 ROI를 확인할 수 있습니다.

사각형 ROI는 사용자가 밝기를 살펴보기 위해 선택한 범위입니다. DICOM CT에서 ROI의 실제 면적은 mm²로 표시합니다. 연결된 종양 SEG에서 계산한 단면별 종양 면적과 케이스 전체 종양 부피도 각각 확인할 수 있습니다.

검토용 측정값은 현재 세션에서 케이스별로 한 건씩 보관합니다. 다른 단면으로 이동해도 선택한 값은 유지됩니다. 선택 버튼을 다시 누르면 그 시점의 측정값으로 교체됩니다.

## 케이스 등록·저장·검색 (A)

### 저장 구조

| 무엇을 | 어디에 | 설정 |
| --- | --- | --- |
| CT 원본 `.dcm` | 앱 서버 디스크 (JCloud 영구 디스크) | `secrets.toml`의 `[storage] root` 또는 환경 변수 `CASE_STORAGE_ROOT`. 없으면 `data/uploads` |
| 케이스 정보 | Cloud Firestore `cases/{case_id}` 문서 | `secrets.toml`의 `[firebase]` (서비스 계정 키) |

`.streamlit/secrets.toml.example`을 `.streamlit/secrets.toml`로 복사해 값을 채웁니다. `secrets.toml`과 서비스 계정 JSON은 `.gitignore`에 있어 커밋되지 않습니다. `[firebase]`가 없으면 **Firestore 미연결 모드**로 실행되어, 등록한 케이스 정보는 그 브라우저 세션 동안만 유지됩니다.

원본은 업로드 한 번마다 `{root}/cases/{case_id}/{upload_id}/0001.dcm, 0002.dcm, …`에 저장됩니다. 원본 파일명은 겹칠 수 있어 선택 순서대로 번호를 붙입니다.

### 등록 순서

1. 입력 검사 (`case_validation.py`): 케이스 ID 형식(영문 대문자·숫자·`_`·`-`)·중복, 파일 선택 여부, `.dcm` 확장자, 빈 파일
2. 원본 저장: 임시 폴더에 모두 쓴 뒤 최종 폴더로 옮깁니다
3. 시리즈 검사: B의 `dicom_ct.load_ct_series`로 저장 폴더를 읽어 한 CT 시리즈인지 확인합니다. 실패하면 이번 업로드 폴더를 지우고 B의 안내 문구를 보여 줍니다
4. Firestore 문서 생성: `create()`라서 같은 ID가 이미 있으면 실패하고, 기존 문서는 덮어쓰지 않습니다
   - 중복·권한 거절처럼 **확정 실패**면 이번 업로드 폴더를 지웁니다
   - 타임아웃처럼 **결과를 알 수 없으면** 늦게 저장될 수 있어 파일을 보존하고 안내합니다

### Firestore 문서 필드 (`cases/{case_id}`)

| 필드 | 값 |
| --- | --- |
| `case_id`, `exam_type` | 케이스 ID, 검사 종류 (`치료 전 CT` / `치료 후 CT`) |
| `image_ref` | 저장 폴더 기준 상대 경로 (예: `cases/HCC_025/20261125T0100_ab12cd34`). 화면에서 서버 절대 경로로 바꿔 뷰어에 넘깁니다 |
| `series_uid`, `slice_count` | 시리즈 검사에서 읽은 SeriesInstanceUID와 실제 단면 수 |
| `file_count`, `total_bytes`, `storage_backend` | 업로드 파일 수·크기, 저장 방식 (`jcloud_disk`) |
| `review_status`, `assignee_uid` | 검토 상태(처음 `검토 대기`), 담당자 — D 담당이 갱신 |
| `created_by`, `created_at` | 등록자 UID (D의 로그인 연결 후), 서버 기록 시각 |

### 목록·검색

- 모든 접속자가 Firestore 목록을 30초 동안 함께 캐시해 읽기 횟수를 줄입니다. 다른 사람이 방금 등록한 케이스는 표 오른쪽 위 새로고침 버튼으로 바로 불러옵니다.
- 케이스 ID 부분 일치(대소문자 무시)와 검토 상태로 거릅니다. 계산은 `case_list.py`에 있어 Streamlit 없이 테스트합니다.
- 문서 값이 빠지거나 형식이 잘못돼도 목록이 깨지지 않도록 기본값을 채웁니다.

### 파일 구성

| 파일 | 역할 |
| --- | --- |
| `case_ui.py` | Streamlit 화면 조각. `app.py`는 `load_cases`, `render_storage_notice`, `render_register_form`, `render_case_table`만 부릅니다 |
| `case_validation.py` | 등록 입력 검사 |
| `case_store.py` | 원본 저장(`LocalFileStorage`), Firestore 저장소, 등록 순서(`register_case`) |
| `case_list.py` | 문서 → 목록 레코드 변환, 검색·필터·상태별 개수 |

## 테스트

아래 명령으로 전체 테스트를 실행합니다. ROI 통계, DICOM 픽셀 간격을 적용한 ROI 면적, 첨부한 PNG의 측정값 처리는 [tests/test_roi_analysis.py](tests/test_roi_analysis.py)에서 확인할 수 있습니다.

```bash
uv run --no-project --managed-python --python 3.12 --with-requirements requirements.txt --with pytest python -B -m pytest -q
```
