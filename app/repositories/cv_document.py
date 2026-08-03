from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cv_document import CVDocument


class CVDocumentRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def get_by_user_id(
        self,
        user_id: UUID,
    ) -> CVDocument | None:
        return await self.database.get(CVDocument, user_id)

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
