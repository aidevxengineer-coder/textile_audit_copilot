from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import sanitize_text


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return sanitize_text(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginChallengeResponse(BaseModel):
    mfa_required: bool = False
    mfa_enrollment_required: bool = False
    challenge_token: str | None = None
    setup_token: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    user: dict


class MFALoginVerifyRequest(BaseModel):
    challenge_token: str
    code: str = Field(min_length=6, max_length=8)


class MFAEnrollResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MFAConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: str
    mfa_enabled: bool
    must_enroll_mfa: bool
