from uuid import UUID

from anyio import to_thread
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cv_document import CVDocument
from app.repositories.cv_document import CVDocumentRepository
from app.security.cv_validation import ValidatedCV
from app.services.cv_text_extractor import (
    CVTextExtractionError,
    extract_cv_text,
)


class CVDocumentNotFoundError(Exception):
    """Raised when a user has not uploaded a CV."""


class CVDocumentNotProcessedError(Exception):
    """Raised when extracted CV text is unavailable."""


class CVDocumentParsingError(Exception):
    """Raised when CV text extraction fails."""


class CVDocumentService:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database
        self.documents = CVDocumentRepository(database)

    async def get_document(self, user_id: UUID) -> CVDocument:
        document = await self.documents.get_by_user_id(user_id)

        if document is None:
            raise CVDocumentNotFoundError

        return document

    async def get_download_document(
        self,
        user_id: UUID,
    ) -> CVDocument:
        document = await self.documents.get_with_file_data(user_id)

        if document is None:
            raise CVDocumentNotFoundError

        return document

    async def get_extracted_text(self, user_id: UUID) -> str:
        document = await self.documents.get_with_extracted_text(user_id)

        if document is None:
            raise CVDocumentNotFoundError

        if document.parse_status != "processed" or not document.extracted_text:
            raise CVDocumentNotProcessedError

        return document.extracted_text

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

    async def parse_document(self, user_id: UUID) -> str:
        document = await self.documents.get_with_file_data(user_id)

        if document is None:
            raise CVDocumentNotFoundError

        try:
            extracted_text = await to_thread.run_sync(
                extract_cv_text,
                document.file_data,
                document.media_type,
            )
        except CVTextExtractionError as error:
            document.parse_status = "failed"
            document.extracted_text = None
            await self.database.commit()

            raise CVDocumentParsingError(str(error)) from error

        document.extracted_text = extracted_text
        document.parse_status = "processed"

        await self.database.commit()

        return extracted_text

    async def delete_document(self, user_id: UUID) -> None:
        document = await self.documents.get_by_user_id(user_id)

        if document is None:
            raise CVDocumentNotFoundError

        await self.documents.delete(document)
        await self.database.commit()
