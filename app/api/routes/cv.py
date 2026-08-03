from typing import Annotated
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.schemas.cv import CVDocumentResponse, CVTextResponse
from app.security.authentication import get_current_user
from app.security.csrf import verify_csrf_token
from app.security.cv_validation import (
    MAX_CV_SIZE,
    CVTooLargeError,
    InvalidCVError,
    UnsupportedCVTypeError,
    validate_cv_data,
)
from app.services.cv_document import (
    CVDocumentNotFoundError,
    CVDocumentNotProcessedError,
    CVDocumentParsingError,
    CVDocumentService,
)

router = APIRouter(
    prefix="/cv",
    tags=["CV"],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CsrfProtection = Annotated[None, Depends(verify_csrf_token)]
UploadedCV = Annotated[
    UploadFile,
    File(description="A PDF or DOCX CV, maximum 5 MiB."),
]


@router.get("", response_model=CVDocumentResponse)
async def get_cv(
    current_user: CurrentUser,
    database: DatabaseSession,
) -> CVDocumentResponse:
    try:
        document = await CVDocumentService(database).get_document(current_user.id)
    except CVDocumentNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV not found.",
        ) from error

    return CVDocumentResponse.model_validate(document)


@router.get("/download")
async def download_cv(
    current_user: CurrentUser,
    database: DatabaseSession,
) -> Response:
    try:
        document = await CVDocumentService(database).get_download_document(current_user.id)
    except CVDocumentNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV not found.",
        ) from error

    encoded_filename = quote(
        document.original_filename,
        safe="",
    )

    return Response(
        content=document.file_data,
        media_type=document.media_type,
        headers={
            "Content-Disposition": (f"attachment; filename*=UTF-8''{encoded_filename}"),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/text", response_model=CVTextResponse)
async def get_cv_text(
    response: Response,
    current_user: CurrentUser,
    database: DatabaseSession,
) -> CVTextResponse:
    try:
        extracted_text = await CVDocumentService(database).get_extracted_text(current_user.id)
    except CVDocumentNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV not found.",
        ) from error
    except CVDocumentNotProcessedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CV text is not available.",
        ) from error

    response.headers["Cache-Control"] = "private, no-store"

    return CVTextResponse(
        user_id=current_user.id,
        parse_status="processed",
        extracted_text=extracted_text,
        character_count=len(extracted_text),
    )


@router.post("/parse", response_model=CVTextResponse)
async def parse_cv(
    response: Response,
    current_user: CurrentUser,
    database: DatabaseSession,
    _csrf: CsrfProtection,
) -> CVTextResponse:
    try:
        extracted_text = await CVDocumentService(database).parse_document(current_user.id)
    except CVDocumentNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV not found.",
        ) from error
    except CVDocumentParsingError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    response.headers["Cache-Control"] = "private, no-store"

    return CVTextResponse(
        user_id=current_user.id,
        parse_status="processed",
        extracted_text=extracted_text,
        character_count=len(extracted_text),
    )


@router.post("", response_model=CVDocumentResponse)
async def upload_cv(
    file: UploadedCV,
    current_user: CurrentUser,
    database: DatabaseSession,
    _csrf: CsrfProtection,
) -> CVDocumentResponse:
    try:
        file_data = await file.read(MAX_CV_SIZE + 1)
        validated_cv = validate_cv_data(
            file.filename or "",
            file_data,
        )
    except CVTooLargeError as error:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(error),
        ) from error
    except UnsupportedCVTypeError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error),
        ) from error
    except InvalidCVError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    finally:
        await file.close()

    document = await CVDocumentService(database).save_document(
        current_user.id,
        validated_cv,
    )

    return CVDocumentResponse.model_validate(document)


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_cv(
    current_user: CurrentUser,
    database: DatabaseSession,
    _csrf: CsrfProtection,
) -> Response:
    try:
        await CVDocumentService(database).delete_document(current_user.id)
    except CVDocumentNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV not found.",
        ) from error

    return Response(status_code=status.HTTP_204_NO_CONTENT)
