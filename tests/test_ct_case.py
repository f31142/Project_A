import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest.mock import patch, sentinel

import ct_case


class CTCaseTests(unittest.TestCase):
    def test_keeps_absolute_paths_on_windows_and_linux(self):
        cases = (
            (PureWindowsPath, r"D:\Project_A", r"C:\storage\cases\HCC_025\upload"),
            (PurePosixPath, "/srv/Project_A", "/home/storage/cases/HCC_025/upload"),
        )
        for path_type, app_dir, reference in cases:
            with (
                self.subTest(reference=reference),
                patch.object(ct_case, "APP_DIR", path_type(app_dir)),
                patch.object(ct_case, "Path", path_type),
                patch.object(path_type, "expanduser", lambda path: path, create=True),
            ):
                self.assertEqual(ct_case.case_dicom_path(reference), path_type(reference))

    def test_keeps_native_absolute_path_and_resolves_relative_path(self):
        reference = ct_case.APP_DIR.parent / "data" / "cases" / "HCC_025"
        for path in (reference, str(reference)):
            with self.subTest(path=path):
                self.assertEqual(ct_case.case_dicom_path(path), reference)
        self.assertEqual(ct_case.case_dicom_path("data/cases"), ct_case.APP_DIR / "data/cases")

    def test_demo_metadata_without_reference_keys_is_not_registered(self):
        demo = {"source": "demo", "exam": "치료 전 CT", "slice_count": 1, "file_count": None}
        self.assertFalse(ct_case.has_case_ct_reference(demo))
        self.assertEqual(ct_case.load_case_ct("DEMO_001", demo), ((), None))

    def test_registered_case_without_series_uid_returns_a_message(self):
        registered = {
            "source": "stored",
            "image_ref": str(ct_case.APP_DIR / "data/cases/HCC_025/upload"),
            "exam": "치료 전 CT",
            "slice_count": 79,
        }
        self.assertTrue(ct_case.has_case_ct_reference(registered))
        with patch.object(ct_case, "load_ct_series") as load_series:
            self.assertEqual(
                ct_case.load_case_ct("HCC_025", registered),
                ((), "등록된 CT 시리즈 UID가 없어요."),
            )
        load_series.assert_not_called()

    def test_passes_the_server_folder_and_uid_to_the_reader(self):
        folder = (Path(ct_case.APP_DIR) / "data/cases/HCC_025/upload").resolve()
        uid = "1.2.3.4"
        registered = {"image_ref": str(folder), "series_uid": uid, "storage_ref": "cases/HCC_025/upload"}
        with patch.object(ct_case, "load_ct_series", return_value=(sentinel.ct_slice,)) as load_series:
            self.assertEqual(ct_case.load_case_ct("HCC_025", registered), ((sentinel.ct_slice,), None))
        load_series.assert_called_once_with(folder, expected_series_uid=uid)
