"""Classify, decode and validate input files (shared by the Slack bot and the local CLI).

Rule: PDF / image = this week's meeting material (required),
      .md / .txt   = background notes: past feedback and progress (optional).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .errors import UserError


class Kind(str, Enum):
    MATERIAL = "material"
    BACKGROUND = "background"


@dataclass(frozen=True)
class InputFile:
    name: str
    kind: Kind
    media_type: str
    data: bytes
    link: str | None = None  # Slack permalink; shown as "미팅 자료: <link>"

    @property
    def is_pdf(self) -> bool:
        return self.media_type == "application/pdf"


_BY_EXTENSION: dict[str, tuple[Kind, str]] = {
    ".pdf": (Kind.MATERIAL, "application/pdf"),
    ".png": (Kind.MATERIAL, "image/png"),
    ".jpg": (Kind.MATERIAL, "image/jpeg"),
    ".jpeg": (Kind.MATERIAL, "image/jpeg"),
    ".gif": (Kind.MATERIAL, "image/gif"),
    ".webp": (Kind.MATERIAL, "image/webp"),
    ".md": (Kind.BACKGROUND, "text/plain"),
    ".markdown": (Kind.BACKGROUND, "text/plain"),
    ".txt": (Kind.BACKGROUND, "text/plain"),
}
_BY_MIMETYPE: dict[str, tuple[Kind, str]] = {
    "application/pdf": (Kind.MATERIAL, "application/pdf"),
    "image/png": (Kind.MATERIAL, "image/png"),
    "image/jpeg": (Kind.MATERIAL, "image/jpeg"),
    "image/gif": (Kind.MATERIAL, "image/gif"),
    "image/webp": (Kind.MATERIAL, "image/webp"),
    "text/plain": (Kind.BACKGROUND, "text/plain"),
    "text/markdown": (Kind.BACKGROUND, "text/plain"),
    "text/x-markdown": (Kind.BACKGROUND, "text/plain"),
}


def classify(name: str, mimetype: str | None = None) -> tuple[Kind, str]:
    """Return (kind, media type sent to the API); extension wins, mimetype is the fallback."""
    ext = os.path.splitext(name)[1].lower()
    if ext in _BY_EXTENSION:
        return _BY_EXTENSION[ext]
    mime = (mimetype or "").split(";")[0].strip().lower()
    if mime in _BY_MIMETYPE:
        return _BY_MIMETYPE[mime]
    raise UserError(
        f"지원하지 않는 파일 형식입니다: {name}\n미팅자료는 PDF나 이미지로, 피드백 노트는 .md / .txt로 올려 주세요."
    )


def decode_text(data: bytes) -> str:
    """Decode a background note; tolerate a BOM and Korean Windows encoding (cp949)."""
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def validate(files: Sequence[InputFile], *, max_file_bytes: int, max_total_bytes: int) -> None:
    if not any(f.kind is Kind.MATERIAL for f in files):
        raise UserError("이번 주 미팅자료(PDF 또는 이미지)를 함께 첨부해 주세요.")
    for f in files:
        if len(f.data) > max_file_bytes:
            raise UserError(f"파일이 너무 큽니다: {f.name} (최대 {max_file_bytes // (1024 * 1024)}MB)")
    if sum(len(f.data) for f in files) > max_total_bytes:
        raise UserError(f"첨부 파일 합계가 너무 큽니다 (최대 {max_total_bytes // (1024 * 1024)}MB)")


def load_local(path: Path) -> InputFile:
    kind, media_type = classify(path.name)
    return InputFile(name=path.name, kind=kind, media_type=media_type, data=path.read_bytes())
