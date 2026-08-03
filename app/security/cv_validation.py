import hashlib
from dataclasses import dataclass
from io import BytesIO
from zipfile import BadZipFile, ZipFile

MAX_CV_SIZE = 5 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_SIZE = 25 * 1024 * 1024
MAX_DOCX_ENTRIES = 1000

PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class InvalidCVError(ValueError):
    """Raised when an uploaded CV is unsafe or unsupported."""


class CVTooLargeError(InvalidCVError):
    """Raised when an uploaded CV exceeds the size limit."""


class UnsupportedCVTypeError(InvalidCVError):
    """Raised when a CV has an unsupported extension."""


@dataclass(frozen=True, slots=True)
class ValidatedCV:
    original_filename: str
    media_type: str
    size_bytes: int
    content_sha256: str
    file_data: bytes


def validate_cv_data(
    filename: str,
    file_data: bytes,
) -> ValidatedCV:
    clean_filename = _sanitize_filename(filename)

    if not file_data:
        raise InvalidCVError("The uploaded CV is empty.")

    if len(file_data) > MAX_CV_SIZE:
        raise CVTooLargeError("The CV cannot exceed 5 MiB.")

    extension = clean_filename.rsplit(".", maxsplit=1)[-1].lower()

    if extension == "pdf":
        _validate_pdf(file_data)
        media_type = PDF_MEDIA_TYPE
    elif extension == "docx":
        _validate_docx(file_data)
        media_type = DOCX_MEDIA_TYPE
    else:
        raise UnsupportedCVTypeError("Only PDF and DOCX files are supported.")

    return ValidatedCV(
        original_filename=clean_filename,
        media_type=media_type,
        size_bytes=len(file_data),
        content_sha256=hashlib.sha256(file_data).hexdigest(),
        file_data=file_data,
    )


def _sanitize_filename(filename: str) -> str:
    normalized_filename = filename.replace("\\", "/")
    clean_filename = normalized_filename.rsplit("/", maxsplit=1)[-1].strip()

    if not clean_filename or clean_filename in {".", ".."} or "\x00" in clean_filename:
        raise InvalidCVError("The CV filename is invalid.")

    if len(clean_filename) > 255:
        raise InvalidCVError("The CV filename is too long.")

    return clean_filename


def _validate_pdf(file_data: bytes) -> None:
    if not file_data.startswith(b"%PDF-"):
        raise InvalidCVError("The file content is not a valid PDF.")

    if b"%%EOF" not in file_data[-2048:]:
        raise InvalidCVError("The PDF is incomplete or invalid.")


def _validate_docx(file_data: bytes) -> None:
    try:
        with ZipFile(BytesIO(file_data)) as archive:
            entries = archive.infolist()

            if len(entries) > MAX_DOCX_ENTRIES:
                raise InvalidCVError("The DOCX contains too many files.")

            if any(entry.flag_bits & 0x1 for entry in entries):
                raise InvalidCVError("Encrypted DOCX files are not supported.")

            if sum(entry.file_size for entry in entries) > MAX_DOCX_UNCOMPRESSED_SIZE:
                raise InvalidCVError("The uncompressed DOCX is too large.")

            entry_names = {entry.filename for entry in entries}

            required_entries = {
                "[Content_Types].xml",
                "word/document.xml",
            }

            if not required_entries.issubset(entry_names):
                raise InvalidCVError("The file content is not a valid DOCX.")

            if any(entry_name.lower() == "word/vbaproject.bin" for entry_name in entry_names):
                raise InvalidCVError("Macro-enabled documents are not supported.")

            for entry_name in entry_names:
                normalized_name = entry_name.replace("\\", "/")
                parts = normalized_name.split("/")

                if normalized_name.startswith("/") or ".." in parts:
                    raise InvalidCVError("The DOCX contains unsafe paths.")
    except BadZipFile:
        raise InvalidCVError("The file content is not a valid DOCX.") from None
