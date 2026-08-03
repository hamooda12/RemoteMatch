from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.schemas.cv import CVDocumentResponse
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
