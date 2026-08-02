from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.security.cv_validation import (
    DOCX_MEDIA_TYPE,
    MAX_CV_SIZE,
    PDF_MEDIA_TYPE,
    InvalidCVError,
    validate_cv_data,
)


def create_test_docx() -> bytes:
    output = BytesIO()

    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<Types></Types>",
        )
        archive.writestr(
            "word/document.xml",
            "<document></document>",
        )

    return output.getvalue()


def test_valid_pdf_is_accepted_and_filename_is_sanitized() -> None:
    file_data = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"

    result = validate_cv_data(
        "../../candidate-resume.PDF",
        file_data,
    )

    assert result.original_filename == "candidate-resume.PDF"
    assert result.media_type == PDF_MEDIA_TYPE
    assert result.size_bytes == len(file_data)
    assert len(result.content_sha256) == 64
    assert result.file_data == file_data


def test_valid_docx_is_accepted() -> None:
    file_data = create_test_docx()

    result = validate_cv_data("candidate.docx", file_data)

    assert result.original_filename == "candidate.docx"
    assert result.media_type == DOCX_MEDIA_TYPE
    assert result.size_bytes == len(file_data)


@pytest.mark.parametrize(
    ("filename", "file_data"),
    [
        ("candidate.txt", b"resume"),
        ("candidate.pdf", b"not a PDF"),
        ("candidate.docx", b"not a DOCX"),
    ],
)
def test_unsupported_or_fake_files_are_rejected(
    filename: str,
    file_data: bytes,
) -> None:
    with pytest.raises(InvalidCVError):
        validate_cv_data(filename, file_data)


def test_oversized_cv_is_rejected() -> None:
    file_data = b"a" * (MAX_CV_SIZE + 1)

    with pytest.raises(InvalidCVError, match="cannot exceed"):
        validate_cv_data("candidate.pdf", file_data)
