from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_setup_user
from app.auth.schemas import (
    LoginChallengeResponse,
    LoginRequest,
    MFAConfirmRequest,
    MFAEnrollResponse,
    MFALoginVerifyRequest,
    RefreshResponse,
    RegisterRequest,
    UserResponse,
)
from app.auth.service import AuthError, AuthService
from app.config import get_settings
from app.core.audit import log_audit_event
from app.db.session import get_db
from app.models.user import User


router = APIRouter(prefix="/api/auth", tags=["auth"])
auth_service = AuthService()


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.refresh_token_cookie_name,
        refresh_token,
        httponly=True,
        samesite="lax",
        secure=settings.enforce_https,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        path="/",
    )


def _set_access_cookie(response: Response, access_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.access_token_cookie_name,
        access_token,
        httponly=True,
        samesite="lax",
        secure=settings.enforce_https,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


@router.post("/register", response_model=UserResponse)
def register(payload: RegisterRequest, db: Annotated[Session, Depends(get_db)], response: Response) -> UserResponse:
    try:
        user = auth_service.register_factory_user(
            db,
            email=str(payload.email).lower(),
            full_name=payload.full_name,
            password=payload.password,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    log_audit_event(
        db,
        actor_user_id=user.id,
        action="user_registered",
        resource_type="user",
        resource_id=user.id,
        ip_address=None,
        metadata={"role": user.role},
    )
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        mfa_enabled=user.mfa_enabled,
        must_enroll_mfa=user.must_enroll_mfa,
    )


@router.post("/login", response_model=LoginChallengeResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)], response: Response) -> LoginChallengeResponse:
    try:
        user = auth_service.authenticate_password(db, email=str(payload.email).lower(), password=payload.password)
        result = auth_service.start_login(db, user=user)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if result.refresh_token:
        _set_access_cookie(response, result.access_token or "")
        _set_refresh_cookie(response, result.refresh_token)
    return result.model_copy(update={"refresh_token": None})


@router.post("/login/verify-mfa", response_model=RefreshResponse)
def verify_mfa_login(
    payload: MFALoginVerifyRequest,
    db: Annotated[Session, Depends(get_db)],
    response: Response,
) -> RefreshResponse:
    try:
        _, tokens = auth_service.verify_mfa_login(db, challenge_token=payload.challenge_token, code=payload.code)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    access_token, refresh_token = tokens
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token)
    return RefreshResponse(access_token=access_token)


@router.post("/mfa/enroll", response_model=MFAEnrollResponse)
def begin_mfa_enrollment(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_setup_user)],
) -> MFAEnrollResponse:
    _, secret, uri = auth_service.begin_mfa_enrollment(db, user=user)
    return MFAEnrollResponse(secret=secret, provisioning_uri=uri)


@router.post("/mfa/confirm", response_model=RefreshResponse)
def confirm_mfa(
    payload: MFAConfirmRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_setup_user)],
    response: Response,
) -> RefreshResponse:
    try:
        access_token, refresh_token = auth_service.confirm_mfa_enrollment(db, user=user, code=payload.code)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token)
    return RefreshResponse(access_token=access_token)


@router.post("/refresh", response_model=RefreshResponse)
def refresh_token(
    db: Annotated[Session, Depends(get_db)],
    response: Response,
    refresh_cookie: Annotated[str | None, Cookie(alias=get_settings().refresh_token_cookie_name)] = None,
) -> RefreshResponse:
    if not refresh_cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing.")

    try:
        _, tokens = auth_service.refresh_access(db, refresh_token=refresh_cookie)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    access_token, refresh_token = tokens
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token)
    return RefreshResponse(access_token=access_token)


@router.post("/logout")
def logout(
    db: Annotated[Session, Depends(get_db)],
    response: Response,
    refresh_cookie: Annotated[str | None, Cookie(alias=get_settings().refresh_token_cookie_name)] = None,
) -> dict:
    settings = get_settings()
    if refresh_cookie:
        auth_service.revoke_refresh_token(db, refresh_token=refresh_cookie)
    response.delete_cookie(settings.access_token_cookie_name, path="/")
    response.delete_cookie(settings.refresh_token_cookie_name, path="/")
    return {"status": "logged_out"}


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        mfa_enabled=user.mfa_enabled,
        must_enroll_mfa=user.must_enroll_mfa,
    )
