from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)


class RegisterRequest(BaseModel):
    email: EmailStr

    display_name: str = Field(
        min_length=2,
        max_length=120,
    )

    password: SecretStr = Field(
        min_length=12,
        max_length=128,
    )

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return " ".join(value.split())


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)


class MessageResponse(BaseModel):
    message: str


class CsrfTokenResponse(BaseModel):
    csrf_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str
    auth_provider: str
    created_at: datetime
