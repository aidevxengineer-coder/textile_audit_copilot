from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1]
    return authorization


def _decode_user_token(
    db: Session,
    *,
    authorization: str | None,
    access_cookie: str | None,
    allowed_types: set[str],
) -> User:
    token = _extract_bearer_token(authorization) or access_cookie
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    try:
        payload = decode_token(token)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token.") from exc

    if payload.get("type") not in allowed_types:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type.")

    user = db.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    return user


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    access_cookie: Annotated[str | None, Cookie(alias=get_settings().access_token_cookie_name)] = None,
) -> User:
    return _decode_user_token(db, authorization=authorization, access_cookie=access_cookie, allowed_types={"access"})


def get_setup_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    access_cookie: Annotated[str | None, Cookie(alias=get_settings().access_token_cookie_name)] = None,
) -> User:
    return _decode_user_token(
        db,
        authorization=authorization,
        access_cookie=access_cookie,
        allowed_types={"mfa_setup", "access"},
    )


def require_role(*roles: str):
    def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return user

    return dependency
