"""Checks on uploaded resumes, and safe names for downloading them."""

import re
import unicodedata
import zipfile
from pathlib import PurePath

from rest_framework.exceptions import ValidationError

MAX_RESUME_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_RESUMES_PER_CANDIDATE = 5

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

WRONG_TYPE = "Upload a PDF (.pdf) or Word (.docx) file."
NOT_PDF = "This file is named .pdf but is not a PDF document."
NOT_DOCX = "This file is named .docx but is not a Word document."


def extension_of(name):
    return PurePath(name or "").suffix.lower().lstrip(".")


def check_resume_upload(upload):
    """Return "pdf" or "docx" if the upload really is one; else raise a 400.

    The extension says what the file claims to be. The first bytes must agree:
    a PDF starts with %PDF-, and a .docx is a zip holding word/document.xml.
    The browser's Content-Type is ignored, since the client chooses it freely.
    """
    kind = extension_of(upload.name)
    if kind not in CONTENT_TYPES:
        raise ValidationError(WRONG_TYPE)
    if upload.size == 0:
        raise ValidationError("The file is empty.")
    if upload.size > MAX_RESUME_BYTES:
        size_mb = upload.size / (1024 * 1024)
        raise ValidationError(f"The file is {size_mb:.1f} MB. The limit is 5 MB.")

    upload.seek(0)
    try:
        if kind == "pdf":
            if upload.read(5) != b"%PDF-":
                raise ValidationError(NOT_PDF)
        else:
            # Only the zip's table of contents is read. Nothing is extracted,
            # so a "zip bomb" can't use up memory or disk here.
            try:
                with zipfile.ZipFile(upload) as archive:
                    names = set(archive.namelist())
            except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError):
                names = set()
            if "word/document.xml" not in names:
                raise ValidationError(NOT_DOCX)
    finally:
        upload.seek(0)
    return kind


def clean_original_name(name):
    """The uploaded name as shown back to the user: no path, no control chars."""
    name = PurePath((name or "").replace("\\", "/")).name
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    return name.strip()[:255] or "resume"


def safe_download_name(original_name, kind):
    """A filename safe to put in Content-Disposition.

    Letters (any language), digits, spaces, dots, dashes and underscores are
    kept; anything else (quotes, slashes, control or direction-override
    characters) becomes "_". The extension always comes from the stored file,
    never from the user's name.
    """
    stem = PurePath(clean_original_name(original_name)).stem
    stem = re.sub(r"[^\w .-]+", "_", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" ._-")[:100] or "resume"
    return f"{stem}.{kind}"
