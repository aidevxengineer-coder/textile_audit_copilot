from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyotp
from sqlalchemy.orm import Session

from app.auth.schemas import LoginChallengeResponse, UserResponse
from app.config import get_settings
from app.core.encryption import decrypt_text, encrypt_text
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import RefreshToken, User


class AuthError(ValueError):
    pass


class AuthService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _user_payload(self, user: User) -> dict:
        return UserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            mfa_enabled=user.mfa_enabled,
            must_enroll_mfa=user.must_enroll_mfa,
        ).model_dump()

    def register_factory_user(self, db: Session, *, email: str, full_name: str, password: str) -> User:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            raise AuthError("Email is already registered.")
        user = User(
            email=email,
            full_name=full_name,
            password_hash=hash_password(password),
            role="factory_user",
            is_active=True,
            mfa_enabled=False,
            must_enroll_mfa=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def authenticate_password(self, db: Session, *, email: str, password: str) -> User:
        user = db.query(User).filter(User.email == email).first()
        if not user or not verify_password(password, user.password_hash):
            raise AuthError("Invalid email or password.")
        if not user.is_active:
            raise AuthError("Account is disabled.")
        return user

    def start_login(self, db: Session, *, user: User) -> LoginChallengeResponse:
        if user.role == "admin" and not user.mfa_enabled:
            setup_token = create_token(user.id, "mfa_setup", timedelta(minutes=10))
            return LoginChallengeResponse(
                mfa_enrollment_required=True,
                setup_token=setup_token,
                user=self._user_payload(user),
            )

        if user.mfa_enabled:
            challenge_token = create_token(user.id, "mfa_challenge", timedelta(minutes=10))
            return LoginChallengeResponse(
                mfa_required=True,
                challenge_token=challenge_token,
                user=self._user_payload(user),
            )

        access_token, refresh_token = self.issue_tokens(db, user=user)
        return LoginChallengeResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=self._user_payload(user),
        )

    def issue_tokens(self, db: Session, *, user: User) -> tuple[str, str]:
        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token(user.id)
        decoded = decode_token(refresh_token)
        db.add(
            RefreshToken(
                user_id=user.id,
                token_jti=decoded["jti"],
                expires_at=datetime.fromtimestamp(decoded["exp"], UTC),
            )
        )
        db.commit()
        return access_token, refresh_token

    def verify_mfa_login(self, db: Session, *, challenge_token: str, code: str) -> tuple[User, tuple[str, str]]:
        payload = decode_token(challenge_token)
        if payload.get("type") != "mfa_challenge":
            raise AuthError("Invalid MFA challenge token.")
        user = db.get(User, payload["sub"])
        if not user or not user.mfa_secret:
            raise AuthError("User does not have MFA configured.")
        secret = decrypt_text(user.mfa_secret)
        if not pyotp.TOTP(secret).verify(code):
            raise AuthError("Invalid MFA code.")
        tokens = self.issue_tokens(db, user=user)
        return user, tokens

    def ensure_setup_token(self, db: Session, *, setup_token: str) -> User:
        payload = decode_token(setup_token)
        if payload.get("type") != "mfa_setup":
            raise AuthError("Invalid MFA setup token.")
        user = db.get(User, payload["sub"])
        if not user:
            raise AuthError("User not found.")
        return user

    def begin_mfa_enrollment(self, db: Session, *, user: User) -> tuple[User, str, str]:
        secret = decrypt_text(user.mfa_secret) if user.mfa_secret else pyotp.random_base32()
        if not user.mfa_secret:
            user.mfa_secret = encrypt_text(secret)
            db.add(user)
            db.commit()
            db.refresh(user)
        provisioning_uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=self.settings.app_name)
        return user, secret, provisioning_uri

    def confirm_mfa_enrollment(self, db: Session, *, user: User, code: str) -> tuple[str, str]:
        if not user.mfa_secret:
            raise AuthError("MFA enrollment has not been started.")
        secret = decrypt_text(user.mfa_secret)
        if not pyotp.TOTP(secret).verify(code):
            raise AuthError("Invalid MFA code.")
        user.mfa_enabled = True
        user.must_enroll_mfa = False
        db.add(user)
        db.commit()
        db.refresh(user)
        return self.issue_tokens(db, user=user)

    def refresh_access(self, db: Session, *, refresh_token: str) -> tuple[User, tuple[str, str]]:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise AuthError("Invalid refresh token.")
        record = db.query(RefreshToken).filter(RefreshToken.token_jti == payload["jti"]).first()
        if not record or record.revoked_at is not None:
            raise AuthError("Refresh token is invalid or expired.")
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            # Some drivers can return naive datetimes; stored values are UTC.
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(UTC):
            raise AuthError("Refresh token is invalid or expired.")
        user = db.get(User, payload["sub"])
        if not user:
            raise AuthError("User not found.")
        # The refresh token is intentionally NOT rotated here: Next.js server
        # components refresh on behalf of the browser but cannot set cookies,
        # so revoking on use would strand the browser with a dead cookie.
        # Tokens are revoked on logout and expire naturally.
        access_token = create_access_token(user.id)
        return user, (access_token, refresh_token)

    def revoke_refresh_token(self, db: Session, *, refresh_token: str) -> None:
        try:
            payload = decode_token(refresh_token)
        except Exception:
            return
        record = db.query(RefreshToken).filter(RefreshToken.token_jti == payload.get("jti")).first()
        if record and record.revoked_at is None:
            record.revoked_at = datetime.now(UTC)
            db.add(record)
            db.commit()
