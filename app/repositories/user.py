from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def get_by_email(self, email: str) -> User | None:
        result = await self.database.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self.database.get(User, user_id)

    async def create(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
    ) -> User:
        user = User(
            email=email,
            display_name=display_name,
            password_hash=password_hash,
        )
        self.database.add(user)
        await self.database.flush()
        return user
