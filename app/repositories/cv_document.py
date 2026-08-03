from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.models.cv_document import CVDocument


class CVDocumentRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def get_by_user_id(
        self,
        user_id: UUID,
    ) -> CVDocument | None:
        return await self.database.get(CVDocument, user_id)

    async def get_with_file_data(
        self,
        user_id: UUID,
    ) -> CVDocument | None:
        result = await self.database.execute(
            select(CVDocument)
            .options(undefer(CVDocument.file_data))
            .where(CVDocument.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_with_extracted_text(
        self,
        user_id: UUID,
    ) -> CVDocument | None:
        result = await self.database.execute(
            select(CVDocument)
            .options(undefer(CVDocument.extracted_text))
            .where(CVDocument.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: UUID,
        values: dict[str, object],
    ) -> CVDocument:
        document = CVDocument(
            user_id=user_id,
            **values,
        )
        self.database.add(document)
        return document

    @staticmethod
    def update(
        document: CVDocument,
        values: dict[str, object],
    ) -> CVDocument:
        for field_name, value in values.items():
            setattr(document, field_name, value)

        return document

    async def delete(self, document: CVDocument) -> None:
        await self.database.delete(document)
