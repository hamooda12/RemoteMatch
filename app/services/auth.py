from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest
from app.security.passwords import hash_password, verify_password


class EmailAlreadyRegisteredError(Exception):
    """Raised when an email address is already registered."""


class InvalidCredentialsError(Exception):
    """Raised when login credentials are invalid."""


class AuthService:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database
        self.users = UserRepository(database)

    async def register(self, payload: RegisterRequest) -> User:
        email = str(payload.email).lower()

        existing_user = await self.users.get_by_email(email)
        if existing_user is not None:
            raise EmailAlreadyRegisteredError

        try:
            user = await self.users.create(
                email=email,
                display_name=payload.display_name,
                password_hash=hash_password(payload.password.get_secret_value()),
            )
            await self.database.commit()
        except IntegrityError as error:
            await self.database.rollback()
            raise EmailAlreadyRegisteredError from error

        await self.database.refresh(user)
        return user

    async def authenticate(self, payload: LoginRequest) -> User:
        email = str(payload.email).lower()
        user = await self.users.get_by_email(email)

        if (
            user is None
            or user.password_hash is None
            or not verify_password(
                payload.password.get_secret_value(),
                user.password_hash,
            )
        ):
            raise InvalidCredentialsError

        user.last_login_at = datetime.now(UTC)

        await self.database.commit()
        await self.database.refresh(user)

        return user
