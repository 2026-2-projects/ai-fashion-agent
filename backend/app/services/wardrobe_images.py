"""사용자별 로컬 옷장 이미지 저장 및 검증 (개발 환경용)."""

import os
import re
import tempfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
SUPPORTED = {
    ".jpg": ("image/jpeg", "JPEG", "jpg"),
    ".jpeg": ("image/jpeg", "JPEG", "jpg"),
    ".png": ("image/png", "PNG", "png"),
    ".webp": ("image/webp", "WEBP", "webp"),
}
KEY_PATTERN = re.compile(r"^wardrobe/([1-9][0-9]*)/([0-9a-f]{32})\.(jpg|png|webp)$")
BACKEND_ROOT = Path(__file__).resolve().parents[3]
MEDIA_ROOT = Path(os.environ.get("WARDROBE_MEDIA_ROOT", str(BACKEND_ROOT / ".wardrobe_media")))


def image_path(key: str | None, user_id: int) -> Path | None:
    if not key:
        return None
    match = KEY_PATTERN.fullmatch(key)
    if not match or int(match.group(1)) != user_id:
        return None
    return MEDIA_ROOT / str(user_id) / f"{match.group(2)}.{match.group(3)}"


def remove_image(key: str | None, user_id: int) -> None:
    path = image_path(key, user_id)
    if path:
        path.unlink(missing_ok=True)


def remove_user_images(user_id: int) -> None:
    """회원 탈퇴 직후 해당 사용자 이미지 제거 (DB 삭제 성공 후 호출)."""
    if user_id <= 0:
        return
    folder = MEDIA_ROOT / str(user_id)
    if not folder.is_dir() or folder.is_symlink():
        return
    for file in folder.iterdir():
        if file.is_file() and not file.is_symlink():
            file.unlink(missing_ok=True)
    folder.rmdir()


async def validate_image(file: UploadFile) -> tuple[bytes, str]:
    ext = Path(file.filename or "").suffix.lower()
    spec = SUPPORTED.get(ext)
    if spec is None or file.content_type != spec[0]:
        raise HTTPException(status_code=422, detail="JPG, PNG, WEBP 이미지만 업로드할 수 있습니다.")

    data = await file.read(MAX_IMAGE_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(status_code=422, detail="이미지 파일이 비어 있습니다.")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="이미지 크기는 최대 5MB입니다.")

    try:
        with Image.open(BytesIO(data)) as img:
            if img.format != spec[1] or img.width * img.height > MAX_IMAGE_PIXELS:
                raise ValueError("잘못된 이미지 형식 또는 해상도")
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise HTTPException(
        status_code=422,
        detail="손상되었거나 유효하지 않은 이미지입니다.",
        ) from None

    return data, spec[2]


def store_image(data: bytes, ext: str, user_id: int) -> str:
    """DB의 image_url에는 공개 URL이 아닌 상대 저장키를 보관한다."""
    directory = MEDIA_ROOT / str(user_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = f"{uuid4().hex}.{ext}"
    target = directory / name
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as tmp:
            temp_name = tmp.name
            tmp.write(data)
        os.replace(temp_name, target)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return f"wardrobe/{user_id}/{name}"
