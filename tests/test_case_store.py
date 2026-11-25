import pytest
from google.api_core.exceptions import AlreadyExists

from case_store import (
    INITIAL_REVIEW_STATUS,
    CaseAlreadyExistsError,
    CaseStoreError,
    CaseWriteRejectedError,
    FirestoreCaseRepository,
    InMemoryCaseRepository,
    LocalFileStorage,
    register_case,
)


class Upload:
    """Streamlit UploadedFile 대신 쓰는 파일 객체."""

    def __init__(self, name, data):
        self.name = name
        self.size = len(data)
        self._data = data

    def getvalue(self):
        return self._data


def uploads(count=3):
    return [Upload(f"1-{i:03d}.dcm", f"dicom-{i}".encode()) for i in range(1, count + 1)]


def case_dirs(root, case_id):
    folder = root / "cases" / case_id
    return sorted(folder.iterdir()) if folder.exists() else []


def leftover_incoming(root):
    incoming = root / ".incoming"
    return list(incoming.iterdir()) if incoming.exists() else []


# --- 파일 저장소 -------------------------------------------------------------


def test_save_upload_writes_all_files_under_case_folder(tmp_path):
    storage = LocalFileStorage(tmp_path)
    image_ref = storage.save_upload("HCC_025", uploads(3))

    assert image_ref.startswith("cases/HCC_025/")
    saved = sorted(p.name for p in (tmp_path / image_ref).iterdir())
    assert saved == ["0001.dcm", "0002.dcm", "0003.dcm"]
    assert (tmp_path / image_ref / "0002.dcm").read_bytes() == b"dicom-2"
    assert leftover_incoming(tmp_path) == []


def test_same_original_names_do_not_overwrite_each_other(tmp_path):
    storage = LocalFileStorage(tmp_path)
    image_ref = storage.save_upload("HCC_025", [Upload("a.dcm", b"one"), Upload("a.dcm", b"two")])
    assert (tmp_path / image_ref / "0001.dcm").read_bytes() == b"one"
    assert (tmp_path / image_ref / "0002.dcm").read_bytes() == b"two"


def test_each_upload_gets_its_own_folder(tmp_path):
    storage = LocalFileStorage(tmp_path)
    first = storage.save_upload("HCC_025", uploads(1))
    second = storage.save_upload("HCC_025", uploads(1))
    assert first != second
    assert len(case_dirs(tmp_path, "HCC_025")) == 2


@pytest.mark.parametrize("bad_id", ["../ESCAPE", "A/B", "", "hcc_lower"])
def test_save_upload_rejects_unsafe_case_id(tmp_path, bad_id):
    with pytest.raises(ValueError):
        LocalFileStorage(tmp_path).save_upload(bad_id, uploads(1))
    assert not (tmp_path / "cases").exists()


def test_write_failure_cleans_temp_folder(tmp_path):
    class Broken(Upload):
        def getvalue(self):
            raise OSError(28, "No space left on device")

    storage = LocalFileStorage(tmp_path)
    with pytest.raises(CaseStoreError, match="저장하지 못했어요"):
        storage.save_upload("HCC_025", [Upload("a.dcm", b"ok"), Broken("b.dcm", b"")])
    assert leftover_incoming(tmp_path) == []
    assert case_dirs(tmp_path, "HCC_025") == []


def test_delete_upload_refuses_paths_outside_root(tmp_path):
    storage = LocalFileStorage(tmp_path / "root")
    with pytest.raises(ValueError):
        storage.delete_upload("../outside")


# --- 등록 흐름 ---------------------------------------------------------------


def test_register_case_saves_files_then_document(tmp_path):
    repo, storage = InMemoryCaseRepository(), LocalFileStorage(tmp_path)
    saved = register_case(repo, storage, "HCC_025", "치료 전 CT", uploads(3))

    doc = repo.list_cases()["HCC_025"]
    assert doc["image_ref"] == saved["image_ref"]
    assert storage.exists(doc["image_ref"])
    assert doc["exam_type"] == "치료 전 CT"
    assert doc["slice_count"] == 3  # 단면 수 = 업로드한 파일 수
    assert doc["file_count"] == 3
    assert doc["total_bytes"] == sum(len(f"dicom-{i}") for i in (1, 2, 3))
    assert doc["review_status"] == INITIAL_REVIEW_STATUS
    assert doc["storage_backend"] == "jcloud_disk"
    assert doc["created_at"] is not None


def test_duplicate_registration_keeps_existing_and_removes_new_files(tmp_path):
    repo, storage = InMemoryCaseRepository(), LocalFileStorage(tmp_path)
    first = register_case(repo, storage, "HCC_025", "치료 전 CT", uploads(2))

    with pytest.raises(CaseAlreadyExistsError, match="이미 등록된"):
        register_case(repo, storage, "HCC_025", "치료 후 CT", uploads(5))

    doc = repo.list_cases()["HCC_025"]
    assert doc["exam_type"] == "치료 전 CT"  # 기존 문서는 그대로
    assert [p.name for p in case_dirs(tmp_path, "HCC_025")] == [first["image_ref"].rsplit("/", 1)[1]]


def test_rejected_write_rolls_back_only_this_upload(tmp_path):
    class FailingRepo(InMemoryCaseRepository):
        fail = False

        def create(self, case_id, data):
            if self.fail:
                raise CaseWriteRejectedError("permission denied")
            super().create(case_id, data)

    repo, storage = FailingRepo(), LocalFileStorage(tmp_path)
    kept = register_case(repo, storage, "HCC_001", "치료 전 CT", uploads(1))

    repo.fail = True
    with pytest.raises(CaseStoreError, match="업로드를 취소"):
        register_case(repo, storage, "HCC_002", "치료 전 CT", uploads(2))

    assert case_dirs(tmp_path, "HCC_002") == []
    assert storage.exists(kept["image_ref"])
    assert "HCC_002" not in repo.list_cases()


def test_ambiguous_error_keeps_files_even_if_document_not_yet_visible(tmp_path):
    """타임아웃 뒤 문서가 아직 안 보여도, 늦게 저장될 수 있으므로 파일을 지우지 않습니다."""

    class LateWriteRepo(InMemoryCaseRepository):
        def create(self, case_id, data):
            self.pending = (case_id, data)  # 아직 반영 전
            raise TimeoutError("deadline exceeded")

    repo, storage = LateWriteRepo(), LocalFileStorage(tmp_path)
    with pytest.raises(CaseStoreError, match="보존"):
        register_case(repo, storage, "HCC_025", "치료 전 CT", uploads(2))

    # 늦게 반영된 문서가 가리키는 파일이 그대로 있어야 합니다.
    InMemoryCaseRepository.create(repo, *repo.pending)
    assert storage.exists(repo.get("HCC_025")["image_ref"])


def test_rollback_failure_is_reported(tmp_path, monkeypatch):
    class FailingRepo(InMemoryCaseRepository):
        def create(self, case_id, data):
            raise CaseWriteRejectedError("invalid argument")

    storage = LocalFileStorage(tmp_path)

    def broken_delete(image_ref):
        raise OSError("locked")

    monkeypatch.setattr(storage, "delete_upload", broken_delete)
    with pytest.raises(CaseStoreError, match="정리도 실패"):
        register_case(FailingRepo(), storage, "HCC_003", "치료 전 CT", uploads(1))


class LostResponseRepo(InMemoryCaseRepository):
    """서버에는 저장됐지만 클라이언트는 오류를 받는 상황(응답 유실)을 흉내 냅니다."""

    def __init__(self, error=None, get_error=None):
        super().__init__()
        self.error = error or TimeoutError("deadline exceeded")
        self.get_error = get_error

    def create(self, case_id, data):
        super().create(case_id, data)
        raise self.error

    def get(self, case_id):
        if self.get_error:
            raise self.get_error
        return super().get(case_id)


def test_lost_response_after_successful_write_keeps_files(tmp_path):
    repo, storage = LostResponseRepo(), LocalFileStorage(tmp_path)
    saved = register_case(repo, storage, "HCC_025", "치료 전 CT", uploads(2))

    assert storage.exists(saved["image_ref"])
    assert repo.get("HCC_025")["image_ref"] == saved["image_ref"]


def test_retry_reporting_already_exists_for_own_write_keeps_files(tmp_path):
    repo = LostResponseRepo(error=CaseAlreadyExistsError("HCC_025"))
    storage = LocalFileStorage(tmp_path)
    saved = register_case(repo, storage, "HCC_025", "치료 전 CT", uploads(2))

    assert storage.exists(saved["image_ref"])


def test_unverifiable_write_keeps_files_and_reports_location(tmp_path):
    repo = LostResponseRepo(get_error=ConnectionError("network down"))
    storage = LocalFileStorage(tmp_path)

    with pytest.raises(CaseStoreError, match="보존") as excinfo:
        register_case(repo, storage, "HCC_025", "치료 전 CT", uploads(2))

    kept = case_dirs(tmp_path, "HCC_025")
    assert len(kept) == 1
    assert kept[0].name in str(excinfo.value)


def test_registered_case_is_found_again_with_new_storage_instance(tmp_path):
    """앱 재시작을 흉내 냅니다: 같은 저장소(문서)와 새 파일 저장소 객체로 다시 조회합니다."""
    repo = InMemoryCaseRepository()
    saved = register_case(repo, LocalFileStorage(tmp_path), "HCC_025", "치료 전 CT", uploads(2))

    reopened = LocalFileStorage(tmp_path)
    doc = repo.list_cases()["HCC_025"]
    assert doc["image_ref"] == saved["image_ref"]
    assert reopened.exists(doc["image_ref"])


# --- Firestore 어댑터 (가짜 클라이언트) -------------------------------------


class FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class FakeDocument:
    def __init__(self, store, doc_id):
        self._store, self._id = store, doc_id

    create_kwargs = []

    def create(self, data, **kwargs):
        FakeDocument.create_kwargs.append(kwargs)
        if self._id in self._store:
            raise AlreadyExists("exists")
        self._store[self._id] = dict(data)

    def get(self):
        snapshot = FakeSnapshot(self._id, self._store.get(self._id, {}))
        snapshot.exists = self._id in self._store
        return snapshot


class FakeCollection:
    def __init__(self):
        self.store = {}
        self.stream_calls = 0

    def document(self, doc_id):
        return FakeDocument(self.store, doc_id)

    def stream(self):
        self.stream_calls += 1
        return [FakeSnapshot(k, v) for k, v in self.store.items()]


class FakeClient:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        return self.collections.setdefault(name, FakeCollection())


def test_firestore_create_uses_server_timestamp_and_detects_duplicates():
    from google.cloud.firestore import SERVER_TIMESTAMP

    client = FakeClient()
    repo = FirestoreCaseRepository(client)
    repo.create("HCC_025", {"exam_type": "치료 전 CT"})

    stored = client.collections["cases"].store["HCC_025"]
    assert stored["created_at"] is SERVER_TIMESTAMP
    with pytest.raises(CaseAlreadyExistsError):
        repo.create("HCC_025", {"exam_type": "치료 후 CT"})
    assert client.collections["cases"].store["HCC_025"]["exam_type"] == "치료 전 CT"


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        ("PermissionDenied", CaseWriteRejectedError),
        ("InvalidArgument", CaseWriteRejectedError),
        ("ResourceExhausted", CaseWriteRejectedError),
        ("DeadlineExceeded", None),  # 결과 불명은 그대로 올라감
        ("ServiceUnavailable", None),
    ],
)
def test_firestore_maps_only_definite_rejections(monkeypatch, raised, expected):
    from google.api_core import exceptions as gexc

    error_type = getattr(gexc, raised)

    def failing_create(self, data, **kwargs):
        raise error_type("boom")

    monkeypatch.setattr(FakeDocument, "create", failing_create)
    repo = FirestoreCaseRepository(FakeClient())
    with pytest.raises(expected or error_type):
        repo.create("HCC_025", {})


def test_firestore_create_disables_automatic_retry():
    """재시도가 켜져 있으면 마지막 시도의 거절이 앞선 시도의 늦은 저장을 가릴 수 있습니다."""
    FakeDocument.create_kwargs.clear()
    FirestoreCaseRepository(FakeClient()).create("HCC_025", {})
    assert FakeDocument.create_kwargs == [{"retry": None}]


def test_firestore_get_reads_document_or_none():
    repo = FirestoreCaseRepository(FakeClient())
    assert repo.get("HCC_025") is None
    repo.create("HCC_025", {"image_ref": "cases/HCC_025/x"})
    assert repo.get("HCC_025")["image_ref"] == "cases/HCC_025/x"


def test_firestore_list_is_cached_and_invalidated_on_create():
    client = FakeClient()
    repo = FirestoreCaseRepository(client, ttl_seconds=60)
    collection = client.collection("cases")

    assert repo.list_cases() == {}
    assert repo.list_cases() == {}
    assert collection.stream_calls == 1  # 두 번째 조회는 캐시 사용

    repo.create("HCC_025", {"exam_type": "치료 전 CT"})
    assert "HCC_025" in repo.list_cases()
    assert collection.stream_calls == 2  # 생성 후에는 다시 읽음
