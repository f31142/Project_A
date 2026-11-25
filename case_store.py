"""케이스 저장·조회 계층.

- CT 원본 파일: JCloud 영구 디스크(로컬 폴더)에 저장합니다. (Firebase 무료 요금제는 Storage 사용 불가)
- 케이스 메타데이터: Cloud Firestore `cases/{case_id}` 문서에 저장합니다.

등록 순서는 "파일 저장 → 문서 생성"이며, 문서 쓰기가 확정 실패일 때만 이번 업로드 폴더를 지웁니다.
Streamlit에 의존하지 않아 pytest로 바로 검사할 수 있습니다.
"""

import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from case_validation import validate_case_id_format

INITIAL_REVIEW_STATUS = "검토 대기"
STORAGE_BACKEND = "jcloud_disk"


class CaseAlreadyExistsError(Exception):
    """같은 케이스 ID의 문서가 이미 있습니다."""


class CaseStoreError(Exception):
    """파일 저장 또는 문서 생성에 실패했습니다. 화면에 보여 줄 문구를 담습니다."""


class CaseWriteRejectedError(Exception):
    """서버가 문서 쓰기를 확실히 거절했습니다(권한·형식·할당량 등). 나중에 저장될 가능성이 없습니다.

    저장소 구현은 이 예외와 CaseAlreadyExistsError만 "확정 실패"로 올립니다.
    단일 시도(자동 재시도 없음)의 결과일 때만 이 예외를 올려야 합니다.
    그 밖의 예외(타임아웃·연결 끊김 등)는 쓰기가 늦게라도 반영될 수 있는 "결과 불명"으로 다룹니다.
    """


# ---------------------------------------------------------------------------
# 파일 저장소: JCloud 영구 디스크
# ---------------------------------------------------------------------------


class LocalFileStorage:
    """root 아래 `cases/{case_id}/{upload_id}/`에 업로드 한 번의 파일을 저장합니다.

    image_ref는 root 기준 상대 경로(posix)입니다. 예: "cases/HCC_025/20261124T0130_ab12cd34"
    """

    def __init__(self, root):
        self.root = Path(root).resolve()

    def _resolve(self, image_ref):
        path = (self.root / image_ref).resolve()
        if self.root not in path.parents:
            raise ValueError(f"저장소 밖의 경로예요: {image_ref}")
        return path

    def save_upload(self, case_id, files):
        """파일을 임시 폴더에 모두 쓴 뒤 최종 위치로 옮깁니다. image_ref를 돌려줍니다."""
        if not case_id or validate_case_id_format(case_id):
            raise ValueError(f"저장할 수 없는 케이스 ID예요: {case_id!r}")

        upload_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
        image_ref = f"cases/{case_id}/{upload_id}"
        temp_dir = self.root / ".incoming" / upload_id
        final_dir = self._resolve(image_ref)

        try:
            temp_dir.mkdir(parents=True)
            # 원본 파일명은 겹칠 수 있으므로 선택 순서대로 번호를 붙여 저장합니다.
            for index, file in enumerate(files, start=1):
                (temp_dir / f"{index:04d}.dcm").write_bytes(file.getvalue())
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            temp_dir.replace(final_dir)
        except OSError as error:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise CaseStoreError(f"CT 파일을 저장하지 못했어요. ({error.strerror or error})") from error

        return image_ref

    def delete_upload(self, image_ref):
        shutil.rmtree(self._resolve(image_ref), ignore_errors=False)

    def exists(self, image_ref):
        return self._resolve(image_ref).is_dir()


# ---------------------------------------------------------------------------
# 메타데이터 저장소: Firestore / 메모리(테스트·미연결용)
# ---------------------------------------------------------------------------


class InMemoryCaseRepository:
    """Firestore 없이 같은 동작을 흉내 냅니다. 테스트와 Firebase 미설정 환경에서 사용합니다."""

    is_persistent = False

    def __init__(self):
        self._docs = {}

    def create(self, case_id, data):
        if case_id in self._docs:
            raise CaseAlreadyExistsError(case_id)
        stored = dict(data)
        stored["created_at"] = datetime.now(timezone.utc)
        self._docs[case_id] = stored

    def get(self, case_id):
        doc = self._docs.get(case_id)
        return dict(doc) if doc is not None else None

    def list_cases(self):
        return {case_id: dict(doc) for case_id, doc in self._docs.items()}


class FirestoreCaseRepository:
    """Cloud Firestore `cases` 컬렉션.

    무료 요금제의 하루 읽기 한도(5만 회)를 아끼기 위해 목록을 ttl초 동안 캐시하고,
    이 인스턴스에서 문서를 만들면 캐시를 비웁니다.
    """

    is_persistent = True

    def __init__(self, client, collection="cases", ttl_seconds=30):
        self._collection = client.collection(collection)
        self._ttl = ttl_seconds
        self._cache = None
        self._cached_at = 0.0
        self._lock = threading.Lock()

    def create(self, case_id, data):
        from google.api_core import exceptions as gexc
        from google.cloud.firestore import SERVER_TIMESTAMP

        # 요청 자체가 거절되어 나중에 반영될 수 없는 오류들입니다.
        definite_rejections = (
            gexc.PermissionDenied,
            gexc.Unauthenticated,
            gexc.InvalidArgument,
            gexc.FailedPrecondition,
            gexc.ResourceExhausted,
        )

        stored = dict(data)
        stored["created_at"] = SERVER_TIMESTAMP
        try:
            # create()는 문서가 이미 있으면 실패하므로, 동시에 같은 ID로 등록해도 하나만 성공합니다.
            # retry=None: 자동 재시도를 끕니다. 재시도가 있으면 앞선 시도가 늦게 반영됐는데
            # 마지막 시도만 거절되는 경우가 생겨, 거절을 "확정 실패"로 믿을 수 없게 됩니다.
            self._collection.document(case_id).create(stored, retry=None)
        except gexc.AlreadyExists as error:
            raise CaseAlreadyExistsError(case_id) from error
        except definite_rejections as error:
            raise CaseWriteRejectedError(str(error)) from error
        finally:
            with self._lock:
                self._cache = None

    def get(self, case_id):
        """캐시를 거치지 않고 서버에서 문서를 직접 읽습니다. 없으면 None."""
        snapshot = self._collection.document(case_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def list_cases(self):
        with self._lock:
            if self._cache is not None and time.monotonic() - self._cached_at < self._ttl:
                return dict(self._cache)
        cases = {snapshot.id: snapshot.to_dict() for snapshot in self._collection.stream()}
        with self._lock:
            self._cache = cases
            self._cached_at = time.monotonic()
        return dict(cases)


def make_firestore_repository(service_account_info):
    """서비스 계정 정보(dict)로 Firestore 저장소를 만듭니다."""
    import firebase_admin
    from firebase_admin import credentials, firestore

    app_name = "case_store"
    try:
        app = firebase_admin.get_app(app_name)
    except ValueError:
        app = firebase_admin.initialize_app(credentials.Certificate(dict(service_account_info)), name=app_name)
    return FirestoreCaseRepository(firestore.client(app))


# ---------------------------------------------------------------------------
# 등록
# ---------------------------------------------------------------------------


def register_case(repository, storage, case_id, exam_type, files, created_by=None):
    """파일 저장 → 문서 생성 순서로 케이스를 등록합니다.

    입력 검사(case_validation)는 호출 전에 끝났다고 가정합니다.
    단면 수는 사람이 입력하지 않고 업로드한 DICOM 파일 수로 정합니다(파일 1개 = 단면 1장).
    문서 쓰기가 확정 실패(중복·거절)일 때만 이번 업로드 폴더를 지우고, 결과 불명이면 파일을 보존합니다.
    """
    files = list(files)
    # 실패할 수 있는 값 계산은 파일을 쓰기 전에 끝내 둡니다.
    data = {
        "case_id": case_id,
        "exam_type": exam_type,
        "slice_count": len(files),
        "storage_backend": STORAGE_BACKEND,
        "file_count": len(files),
        "total_bytes": sum(len(file.getvalue()) for file in files),
        "review_status": INITIAL_REVIEW_STATUS,
        "assignee_uid": None,
        # 로그인(D 담당)이 연결되면 등록자 UID를 넣습니다.
        "created_by": created_by,
    }
    image_ref = storage.save_upload(case_id, files)
    data["image_ref"] = image_ref

    # 파일 정리 원칙: 쓰기가 "확정 실패"일 때만 이번 업로드를 지웁니다.
    # 타임아웃처럼 결과를 알 수 없는 오류는 쓰기가 늦게 반영될 수 있으므로 파일을 보존합니다.
    # (이 경우 문서 없는 파일이 남을 수는 있지만, 문서가 가리키는 파일이 사라지는 일은 없습니다.)
    try:
        repository.create(case_id, data)
    except CaseAlreadyExistsError as error:
        # 재시도 때문에 자기 자신의 쓰기와 부딪혔을 수 있으므로 누구의 문서인지 확인합니다.
        try:
            existing = repository.get(case_id)
        except Exception as check_error:
            raise _kept_files_error(image_ref) from check_error
        if existing is not None and existing.get("image_ref") == image_ref:
            return data  # 이번 업로드의 문서가 이미 저장되어 있습니다.
        # 다른 업로드의 문서가 먼저 있으므로 이번 create는 앞으로도 반영될 수 없습니다.
        note = _discard_upload(storage, image_ref)
        raise CaseAlreadyExistsError(f"이미 등록된 케이스 ID예요.{note}") from error
    except CaseWriteRejectedError as error:
        note = _discard_upload(storage, image_ref)
        raise CaseStoreError(f"케이스 정보 저장이 거절되어 업로드를 취소했어요. ({error}){note}") from error
    except Exception as error:
        # 결과 불명: 이미 반영됐는지만 확인하고, 반영 전이어도 파일은 지우지 않습니다.
        try:
            existing = repository.get(case_id)
        except Exception:
            existing = None
        if existing is not None and existing.get("image_ref") == image_ref:
            return data  # 응답만 유실됐고 저장은 성공했습니다.
        raise _kept_files_error(image_ref) from error

    return data


def _discard_upload(storage, image_ref):
    """이번 업로드 폴더를 지웁니다. 실패하면 화면에 덧붙일 안내 문구를 돌려줍니다."""
    try:
        storage.delete_upload(image_ref)
    except OSError:
        return f" 업로드한 파일 정리도 실패했어요. 관리자가 {image_ref} 폴더를 확인해야 해요."
    return ""


def _kept_files_error(image_ref):
    return CaseStoreError(
        "케이스 정보 저장 결과를 확인하지 못했어요. 늦게 저장될 수 있어 파일은 지우지 않고 보존했어요. "
        f"잠시 뒤 목록을 새로고침해 확인해 주세요. (보존 위치: {image_ref})"
    )
