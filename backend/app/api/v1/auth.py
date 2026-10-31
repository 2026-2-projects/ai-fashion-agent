from datetime import datetime
from secrets import compare_digest, token_urlsafe
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(prefix="/auth", tags=["Auth"])
password_hash = PasswordHash.recommended()


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class SignupResponse(BaseModel):
    id: int
    email: EmailStr
    created_at: datetime


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(
    payload: SignupRequest,
    db: Annotated[Session, Depends(get_db)],
) -> SignupResponse:
    email = str(payload.email).lower()
    hashed = password_hash.hash(payload.password)

    try:
        result = db.execute(
            text("""
                INSERT INTO users (email, password_hash)
                VALUES (:email, :password_hash)
                RETURNING id, email, created_at
            """),
            {"email": email, "password_hash": hashed},
        )
        user = result.mappings().one()
        db.commit()

    except IntegrityError as exc:
        db.rollback()

        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(
                status_code=409,
                detail="이미 등록된 이메일입니다.",
            ) from exc

        raise

    return SignupResponse(**user)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SessionUserResponse(BaseModel):
    id: int
    email: EmailStr
    csrf_token: str


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    user_id = request.session.get("user_id")

    if not isinstance(user_id, int):
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다.",
        )

    user = (
        db.execute(
            text("SELECT id, email FROM users WHERE id = :id"),
            {"id": user_id},
        )
        .mappings()
        .first()
    )

    if user is None:
        request.session.clear()
        raise HTTPException(
            status_code=401,
            detail="유효하지 않은 사용자입니다.",
        )

    return dict(user)


def require_csrf(
    request: Request,
    csrf_token: Annotated[
        str | None,
        Header(alias="X-CSRF-Token"),
    ] = None,
) -> None:
    expected = request.session.get("csrf_token")

    if (
        not request.session.get("user_id")
        or not isinstance(expected, str)
        or not isinstance(csrf_token, str)
        or not compare_digest(expected, csrf_token)
    ):
        raise HTTPException(
            status_code=403,
            detail="CSRF 검증에 실패했습니다.",
        )


@router.post("/login", response_model=SessionUserResponse)
def login(
    request: Request,
    payload: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> SessionUserResponse:
    email = str(payload.email).lower()

    user = (
        db.execute(
            text("""
            SELECT id, email, password_hash
            FROM users
            WHERE email = :email
        """),
            {"email": email},
        )
        .mappings()
        .first()
    )

    if user is None or not password_hash.verify(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=401,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )

    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["csrf_token"] = token_urlsafe(32)

    return SessionUserResponse(
        id=user["id"],
        email=user["email"],
        csrf_token=request.session["csrf_token"],
    )


@router.get("/me", response_model=SessionUserResponse)
def me(
    request: Request,
    user: Annotated[dict, Depends(get_current_user)],
) -> SessionUserResponse:
    return SessionUserResponse(
        **user,
        csrf_token=request.session["csrf_token"],
    )


@router.post(
    "/logout",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=204)


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1)


@router.delete(
    "/account",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
def delete_account(
    request: Request,
    payload: DeleteAccountRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[dict, Depends(get_current_user)],
) -> Response:
    user_id = user["id"]

    account = (
        db.execute(
            text("""
            SELECT password_hash
            FROM users
            WHERE id = :user_id
            FOR UPDATE
        """),
            {"user_id": user_id},
        )
        .mappings()
        .first()
    )

    if account is None:
        request.session.clear()
        raise HTTPException(
            status_code=401,
            detail="존재하지 않는 사용자입니다.",
        )

    if not password_hash.verify(
        payload.password,
        account["password_hash"],
    ):
        raise HTTPException(
            status_code=403,
            detail="비밀번호가 올바르지 않습니다.",
        )

    db.execute(
        text("DELETE FROM users WHERE id = :user_id"),
        {"user_id": user_id},
    )

    db.commit()
    request.session.clear()

    return Response(status_code=204)
