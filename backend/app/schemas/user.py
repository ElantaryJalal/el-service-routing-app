from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import Role


class UserRead(BaseModel):
    """Public view of a user; password_hash is never exposed."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    name: str
    role: Role
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str
    role: Role


class UserUpdate(BaseModel):
    """Only provided fields are applied (PATCH)."""

    name: str | None = None
    role: Role | None = None
    is_active: bool | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # Included so the client doesn't need an immediate /auth/me round-trip.
    user: UserRead
