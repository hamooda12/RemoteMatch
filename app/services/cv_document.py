from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cv_document import CVDocument
from app.repositories.cv_document import CVDocumentRepository
from app.security.cv_validation import ValidatedCV


class CVDocumentNotFoundError(Exception):
    """Raised when a user has not uploaded a CV."""


class CVDocumentService:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database
        self.documents = CVDocumentRepository(database)

    async def get_document(self, user_id: UUID) -> CVDocument:
        document = await self.documents.get_by_user_id(user_id)

        if document is None:
            raise CVDocumentNotFoundError

        return document

    async def save_document(
        self,
        user_id: UUID,
        validated_cv: ValidatedCV,
    ) -> CVDocument:
        values: dict[str, object] = {
            "original_filename": validated_cv.original_filename,
            "media_type": validated_cv.media_type,
            "size_bytes": validated_cv.size_bytes,
            "content_sha256": validated_cv.content_sha256,
            "file_data": validated_cv.file_data,
            "parse_status": "pending",
            "extracted_text": None,
        }

        document = await self.documents.get_by_user_id(user_id)

        if document is None:
            document = await self.documents.create(
                user_id=user_id,
                values=values,
            )
        else:
            document = self.documents.update(document, values)

        await self.database.commit()
        await self.database.refresh(document)

        return document
