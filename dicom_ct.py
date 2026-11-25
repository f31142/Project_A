from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps
from pydicom import dcmread
from pydicom.errors import InvalidDicomError
from pydicom.pixels import apply_modality_lut

CT_PREVIEW_COLUMNS = 8


class DicomReadError(ValueError):
    """A CT series or slice cannot be used by the viewer."""


@dataclass(frozen=True)
class CTSlice:
    path: Path
    sop_instance_uid: str
    position_mm: float
    pixel_spacing_mm: tuple[float, float]
    series_instance_uid: str
    frame_of_reference_uid: str
    image_position_patient: tuple[float, ...]
    image_orientation_patient: tuple[float, ...]
    shape: tuple[int, int]


def load_ct_series(
    directory: Path, *, expected_series_uid: str | None = None
) -> tuple[CTSlice, ...]:
    """Validate a single-frame CT series and order its slices by position."""
    try:
        files = sorted(
            path for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() == ".dcm"
        )
    except OSError as exc:
        raise DicomReadError("CT 폴더를 열 수 없어요. 다운로드 위치를 확인해 주세요.") from exc
    if not files:
        raise DicomReadError("CT 폴더에 .dcm 파일이 없어요.")

    series_uid = expected_series_uid
    reference_orientation = None
    reference_shape = None
    normal = None
    seen_uids = set()
    slices = []
    tags = [
        "Modality", "NumberOfFrames", "SeriesInstanceUID", "SOPInstanceUID",
        "FrameOfReferenceUID", "ImageOrientationPatient", "ImagePositionPatient",
        "PixelSpacing", "Rows", "Columns",
    ]

    for path in files:
        try:
            ds = dcmread(path, stop_before_pixels=True, specific_tags=tags)
            modality = str(ds.Modality)
            frame_count = int(ds.get("NumberOfFrames", 1))
            current_series_uid = str(ds.SeriesInstanceUID or "")
            sop_instance_uid = str(ds.SOPInstanceUID or "")
            frame_of_reference_uid = str(ds.get("FrameOfReferenceUID") or "")
            orientation = np.asarray(ds.ImageOrientationPatient, dtype=float)
            position = np.asarray(ds.ImagePositionPatient, dtype=float)
            spacing = tuple(float(value) for value in ds.PixelSpacing)
            shape = (int(ds.Rows), int(ds.Columns))
        except (InvalidDicomError, OSError, AttributeError, TypeError, ValueError) as exc:
            raise DicomReadError(f"{path.name}의 DICOM 정보가 없거나 형식이 올바르지 않아요.") from exc

        if modality != "CT" or frame_count != 1:
            raise DicomReadError(f"{path.name}은 단일 프레임 CT 파일이 아니에요.")
        if not current_series_uid or not sop_instance_uid:
            raise DicomReadError(f"{path.name}에 시리즈 또는 단면 UID가 없어요.")
        if series_uid is None:
            series_uid = current_series_uid
        if current_series_uid != series_uid:
            raise DicomReadError(f"{path.name}은 선택한 CT 시리즈에 속하지 않아요.")
        if sop_instance_uid in seen_uids:
            raise DicomReadError(f"{path.name}과 UID가 같은 단면이 두 개 이상 있어요.")
        if (
            orientation.shape != (6,)
            or position.shape != (3,)
            or len(spacing) != 2
            or not np.isfinite(orientation).all()
            or not np.isfinite(position).all()
            or not np.isfinite(spacing).all()
            or min(spacing) <= 0
            or min(shape) <= 0
        ):
            raise DicomReadError(f"{path.name}의 단면 좌표, 픽셀 간격 또는 영상 크기가 올바르지 않아요.")

        if reference_orientation is None:
            row, column = orientation[:3], orientation[3:]
            normal = np.cross(row, column)
            length = np.linalg.norm(normal)
            if length < 1e-6:
                raise DicomReadError(f"{path.name}의 촬영 방향으로 단면 순서를 정할 수 없어요.")
            normal /= length
            reference_orientation = orientation
            reference_shape = shape
        elif shape != reference_shape or not np.allclose(
            orientation, reference_orientation, atol=1e-4, rtol=0
        ):
            raise DicomReadError(f"{path.name}의 영상 크기 또는 촬영 방향이 다른 단면과 달라요.")

        seen_uids.add(sop_instance_uid)
        slices.append(
            CTSlice(
                path=path,
                sop_instance_uid=sop_instance_uid,
                position_mm=float(position @ normal),
                pixel_spacing_mm=spacing,
                series_instance_uid=current_series_uid,
                frame_of_reference_uid=frame_of_reference_uid,
                image_position_patient=tuple(position.tolist()),
                image_orientation_patient=tuple(orientation.tolist()),
                shape=shape,
            )
        )

    slices.sort(key=lambda item: item.position_mm)
    if any(b.position_mm - a.position_mm < 0.001 for a, b in zip(slices, slices[1:])):
        raise DicomReadError("같은 위치에 CT 단면이 두 개 이상 있어요.")
    return tuple(slices)


def _ct_display_image(path: Path) -> Image.Image:
    try:
        ds = dcmread(path)
        hu = apply_modality_lut(ds.pixel_array, ds)
        photometric = str(ds.PhotometricInterpretation)
    except (InvalidDicomError, OSError, AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise DicomReadError(f"{path.name}의 CT 픽셀 데이터를 읽을 수 없어요.") from exc

    if hu.ndim != 2 or photometric not in ("MONOCHROME1", "MONOCHROME2"):
        raise DicomReadError(f"{path.name}은 단일 프레임 흑백 CT로 표시할 수 없어요.")

    # Fixed display range used in the team's CT comparison examples.
    lower_hu, upper_hu = -125.0, 225.0
    windowed = np.clip(hu, lower_hu, upper_hu)
    pixels = ((windowed - lower_hu) / (upper_hu - lower_hu) * 255).astype(np.uint8)
    if photometric == "MONOCHROME1":
        pixels = 255 - pixels
    return Image.fromarray(pixels)


def render_ct_png(path: Path) -> bytes:
    """Render one CT slice without overwriting the DICOM file."""
    buffer = BytesIO()
    _ct_display_image(path).save(buffer, format="PNG")
    return buffer.getvalue()


def _draw_tumor_contour(image: Image.Image, mask: np.ndarray) -> Image.Image:
    if mask.shape != (image.height, image.width):
        raise DicomReadError("종양 마스크와 CT 영상의 크기가 달라요.")

    mask_image = Image.fromarray(mask.astype(np.uint8) * 255)
    # Remove the interior so the outline stays inside the aligned mask.
    interior = ImageOps.expand(mask_image, border=2, fill=0).filter(ImageFilter.MinFilter(5))
    interior = interior.crop((2, 2, image.width + 2, image.height + 2))
    outline = ImageChops.subtract(mask_image, interior)
    result = image.convert("RGB")
    result.paste("#5CE7C4", mask=outline)
    return result


def render_ct_contour_png(image_bytes: bytes, mask: np.ndarray) -> bytes:
    """Draw the registered tumor boundary over a display image."""
    with Image.open(BytesIO(image_bytes)) as image:
        result = _draw_tumor_contour(image, mask)
    buffer = BytesIO()
    result.save(buffer, format="PNG")
    return buffer.getvalue()


def render_ct_preview_sheet(
    paths: tuple[Path, ...], tile_size: int, *, masks: Mapping[Path, np.ndarray] | None = None
) -> bytes:
    """Pack reduced CT previews into one image in the supplied slice order."""
    columns = min(CT_PREVIEW_COLUMNS, len(paths))
    rows = (len(paths) + columns - 1) // columns
    sheet = Image.new("RGB" if masks else "L", (columns * tile_size, rows * tile_size))
    for index, path in enumerate(paths):
        image = _ct_display_image(path)
        mask = masks.get(path) if masks else None
        if mask is not None:
            image = _draw_tumor_contour(image, mask)
        tile = ImageOps.pad(image, (tile_size, tile_size), Image.Resampling.BILINEAR)
        row, column = divmod(index, columns)
        sheet.paste(tile, (column * tile_size, row * tile_size))
    buffer = BytesIO()
    sheet.save(buffer, format="JPEG", quality=82, subsampling=0)
    return buffer.getvalue()
