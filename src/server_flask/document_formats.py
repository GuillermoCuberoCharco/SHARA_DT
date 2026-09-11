"""Validation policy for teacher-uploaded subject documents."""

import io
import os
import zipfile
from pathlib import Path, PurePosixPath

ALLOWED_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".pptx"})
CANONICAL_DOCUMENT_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

_ALLOWED_MIME_TYPES = {
    ".pdf": frozenset({
        "application/octet-stream",
        "application/pdf",
        "application/x-pdf",
    }),
    ".pptx": frozenset({
        "application/octet-stream",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/zip",
        "application/x-zip-compressed",
    }),
}

MAX_UPLOAD_MB = int(os.getenv("SUBJECT_DOCUMENT_MAX_MB", "15"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_PPTX_ARCHIVE_FILES = 5000
MAX_PPTX_EXPANDED_BYTES = MAX_UPLOAD_BYTES * 20
MAX_PPTX_CONTENT_TYPES_BYTES = 1024 * 1024

_PPTX_REQUIRED_FILES = frozenset({
    "[Content_Types].xml",
    "_rels/.rels",
    "ppt/presentation.xml",
})
_PPTX_PRESENTATION_CONTENT_TYPE = (
    b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
)


class DocumentFormatError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def get_document_upload_constraints() -> dict:
    return {
        "allowed_extensions": sorted(ALLOWED_DOCUMENT_EXTENSIONS),
        "max_size_mb": MAX_UPLOAD_MB,
    }


def _normalize_content_type(content_type: str) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _validate_pdf(file_bytes: bytes):
    if b"%PDF-" not in file_bytes[:1024]:
        raise DocumentFormatError("El archivo no contiene un PDF valido")


def _validate_pptx(file_bytes: bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_PPTX_ARCHIVE_FILES:
                raise DocumentFormatError("La presentacion PPTX contiene demasiados elementos", 413)

            normalized_names = set()
            expanded_size = 0
            for entry in entries:
                normalized_name = entry.filename.replace("\\", "/")
                path = PurePosixPath(normalized_name)
                if normalized_name.startswith("/") or ".." in path.parts:
                    raise DocumentFormatError("La presentacion PPTX contiene rutas no validas")
                if entry.flag_bits & 0x1:
                    raise DocumentFormatError("No se admiten presentaciones PPTX cifradas")

                normalized_names.add(normalized_name)
                expanded_size += entry.file_size

            if expanded_size > MAX_PPTX_EXPANDED_BYTES:
                raise DocumentFormatError("La presentacion PPTX es demasiado grande al descomprimirse", 413)

            if not _PPTX_REQUIRED_FILES.issubset(normalized_names):
                raise DocumentFormatError("El archivo no contiene una presentacion PPTX valida")

            content_types_info = archive.getinfo("[Content_Types].xml")
            if content_types_info.file_size > MAX_PPTX_CONTENT_TYPES_BYTES:
                raise DocumentFormatError("La presentacion PPTX contiene metadatos no validos")

            content_types = archive.read(content_types_info)
            if _PPTX_PRESENTATION_CONTENT_TYPE not in content_types:
                raise DocumentFormatError("El archivo no contiene una presentacion PPTX valida")
    except DocumentFormatError:
        raise
    except (KeyError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise DocumentFormatError("El archivo no contiene una presentacion PPTX valida") from exc


def validate_document_format(filename: str, content_type: str, file_bytes: bytes) -> str:
    """Validate extension, declared MIME type and basic binary structure."""
    extension = Path(filename or "").suffix.lower()
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise DocumentFormatError(
            "Formato no permitido. Solo se admiten archivos PDF (.pdf) y PowerPoint (.pptx)",
            415,
        )

    normalized_content_type = _normalize_content_type(content_type)
    if normalized_content_type and normalized_content_type not in _ALLOWED_MIME_TYPES[extension]:
        raise DocumentFormatError(
            "El tipo de contenido no coincide con un archivo PDF o PPTX permitido",
            415,
        )

    if extension == ".pdf":
        _validate_pdf(file_bytes)
    else:
        _validate_pptx(file_bytes)

    return extension
