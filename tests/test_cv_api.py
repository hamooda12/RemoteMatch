from collections.abc import Iterator
from io import BytesIO
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.cv_document import CVDocument
from app.models.user import User
from app.security.cv_validation import (
    DOCX_MEDIA_TYPE,
    MAX_CV_SIZE,
    PDF_MEDIA_TYPE,
)

CV_API_TEST_VALUE = "d" * 16
TEST_PDF_DATA = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


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


def csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200

    return {
        "X-CSRF-Token": response.json()["csrf_token"],
    }


def register_and_login(
    client: TestClient,
    email: str,
) -> str:
    registration_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": "CV User",
            "password": CV_API_TEST_VALUE,
        },
    )
    assert registration_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": CV_API_TEST_VALUE,
        },
    )
    assert login_response.status_code == 200

    return registration_response.json()["id"]


@pytest.fixture
def created_emails() -> Iterator[list[str]]:
    emails: list[str] = []
    yield emails

    if not emails:
        return

    engine = create_engine(get_settings().database_url)

    with Session(engine) as database:
        database.execute(delete(User).where(User.email.in_(emails)))
        database.commit()

    engine.dispose()


@pytest.fixture(autouse=True)
def clear_cv_cookies(client: TestClient) -> Iterator[None]:
    client.cookies.clear()
    yield
    client.cookies.clear()


def test_cv_endpoints_require_authentication(
    client: TestClient,
) -> None:
    get_response = client.get("/api/v1/cv")

    upload_response = client.post(
        "/api/v1/cv",
        files={
            "file": (
                "resume.pdf",
                TEST_PDF_DATA,
                PDF_MEDIA_TYPE,
            ),
        },
    )

    assert get_response.status_code == 401
    assert upload_response.status_code == 401


def test_cv_upload_requires_csrf_token(
    client: TestClient,
    created_emails: list[str],
) -> None:
    email = f"cv-csrf-{uuid4()}@example.com"
    created_emails.append(email)
    register_and_login(client, email)

    response = client.post(
        "/api/v1/cv",
        files={
            "file": (
                "resume.pdf",
                TEST_PDF_DATA,
                PDF_MEDIA_TYPE,
            ),
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid or missing CSRF token."}


def test_upload_and_get_pdf_cv(
    client: TestClient,
    created_emails: list[str],
) -> None:
    email = f"cv-pdf-{uuid4()}@example.com"
    created_emails.append(email)

    user_id = register_and_login(client, email)
    headers = csrf_headers(client)

    upload_response = client.post(
        "/api/v1/cv",
        headers=headers,
        files={
            "file": (
                "candidate-resume.pdf",
                TEST_PDF_DATA,
                PDF_MEDIA_TYPE,
            ),
        },
    )

    assert upload_response.status_code == 200

    response_data = upload_response.json()

    assert response_data["user_id"] == user_id
    assert response_data["original_filename"] == "candidate-resume.pdf"
    assert response_data["media_type"] == PDF_MEDIA_TYPE
    assert response_data["size_bytes"] == len(TEST_PDF_DATA)
    assert response_data["parse_status"] == "pending"

    assert "file_data" not in response_data
    assert "content_sha256" not in response_data
    assert "extracted_text" not in response_data

    get_response = client.get("/api/v1/cv")

    assert get_response.status_code == 200
    assert get_response.json() == response_data
    download_response = client.get("/api/v1/cv/download")

    assert download_response.status_code == 200
    assert download_response.content == TEST_PDF_DATA
    assert download_response.headers["content-type"] == PDF_MEDIA_TYPE
    assert "attachment" in download_response.headers["content-disposition"]
    assert "candidate-resume.pdf" in download_response.headers["content-disposition"]
    assert download_response.headers["cache-control"] == "private, no-store"
    assert download_response.headers["x-content-type-options"] == "nosniff"
    engine = create_engine(get_settings().database_url)

    with Session(engine) as database:
        stored_document = database.get(
            CVDocument,
            UUID(user_id),
        )

        assert stored_document is not None
        assert stored_document.file_data == TEST_PDF_DATA
        assert len(stored_document.content_sha256) == 64

    engine.dispose()


def test_reupload_replaces_previous_cv(
    client: TestClient,
    created_emails: list[str],
) -> None:
    email = f"cv-replace-{uuid4()}@example.com"
    created_emails.append(email)

    user_id = register_and_login(client, email)
    headers = csrf_headers(client)

    first_response = client.post(
        "/api/v1/cv",
        headers=headers,
        files={
            "file": (
                "old-resume.pdf",
                TEST_PDF_DATA,
                PDF_MEDIA_TYPE,
            ),
        },
    )
    assert first_response.status_code == 200

    docx_data = create_test_docx()

    replacement_response = client.post(
        "/api/v1/cv",
        headers=headers,
        files={
            "file": (
                "new-resume.docx",
                docx_data,
                DOCX_MEDIA_TYPE,
            ),
        },
    )

    assert replacement_response.status_code == 200
    assert replacement_response.json()["user_id"] == user_id
    assert replacement_response.json()["original_filename"] == "new-resume.docx"
    assert replacement_response.json()["media_type"] == DOCX_MEDIA_TYPE
    assert replacement_response.json()["size_bytes"] == len(docx_data)
    assert replacement_response.json()["parse_status"] == "pending"

    get_response = client.get("/api/v1/cv")

    assert get_response.status_code == 200
    assert get_response.json()["original_filename"] == "new-resume.docx"


def test_invalid_cv_files_are_rejected(
    client: TestClient,
    created_emails: list[str],
) -> None:
    email = f"cv-invalid-{uuid4()}@example.com"
    created_emails.append(email)

    register_and_login(client, email)
    headers = csrf_headers(client)

    fake_pdf_response = client.post(
        "/api/v1/cv",
        headers=headers,
        files={
            "file": (
                "fake.pdf",
                b"not a real PDF",
                PDF_MEDIA_TYPE,
            ),
        },
    )
    assert fake_pdf_response.status_code == 400

    unsupported_response = client.post(
        "/api/v1/cv",
        headers=headers,
        files={
            "file": (
                "resume.txt",
                b"resume",
                "text/plain",
            ),
        },
    )
    assert unsupported_response.status_code == 415

    oversized_response = client.post(
        "/api/v1/cv",
        headers=headers,
        files={
            "file": (
                "huge.pdf",
                b"a" * (MAX_CV_SIZE + 1),
                PDF_MEDIA_TYPE,
            ),
        },
    )
    assert oversized_response.status_code == 413

    get_response = client.get("/api/v1/cv")
    assert get_response.status_code == 404


def test_cv_documents_are_isolated_between_users(
    client: TestClient,
    created_emails: list[str],
) -> None:
    first_email = f"cv-first-{uuid4()}@example.com"
    second_email = f"cv-second-{uuid4()}@example.com"
    created_emails.extend([first_email, second_email])

    register_and_login(client, first_email)
    first_headers = csrf_headers(client)

    upload_response = client.post(
        "/api/v1/cv",
        headers=first_headers,
        files={
            "file": (
                "private-resume.pdf",
                TEST_PDF_DATA,
                PDF_MEDIA_TYPE,
            ),
        },
    )
    assert upload_response.status_code == 200

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers=first_headers,
    )
    assert logout_response.status_code == 200

    register_and_login(client, second_email)

    second_user_response = client.get("/api/v1/cv")

    assert second_user_response.status_code == 404
    assert second_user_response.json() == {"detail": "CV not found."}
    second_download_response = client.get("/api/v1/cv/download")
    assert second_download_response.status_code == 404


def test_delete_cv_requires_csrf_and_removes_document(
    client: TestClient,
    created_emails: list[str],
) -> None:
    email = f"cv-delete-{uuid4()}@example.com"
    created_emails.append(email)

    register_and_login(client, email)
    headers = csrf_headers(client)

    upload_response = client.post(
        "/api/v1/cv",
        headers=headers,
        files={
            "file": (
                "delete-me.pdf",
                TEST_PDF_DATA,
                PDF_MEDIA_TYPE,
            ),
        },
    )
    assert upload_response.status_code == 200

    missing_csrf_response = client.delete("/api/v1/cv")
    assert missing_csrf_response.status_code == 403

    invalid_csrf_response = client.delete(
        "/api/v1/cv",
        headers={"X-CSRF-Token": "invalid"},
    )
    assert invalid_csrf_response.status_code == 403

    delete_response = client.delete(
        "/api/v1/cv",
        headers=headers,
    )

    assert delete_response.status_code == 204
    assert delete_response.content == b""

    assert client.get("/api/v1/cv").status_code == 404
    assert client.get("/api/v1/cv/download").status_code == 404

    second_delete_response = client.delete(
        "/api/v1/cv",
        headers=headers,
    )
    assert second_delete_response.status_code == 404
