from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..cache import cache
from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import RefreshToken, User, utcnow
from ..schemas import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut
from ..security import (create_access_token, create_refresh_token, decode_token,
                        hash_password, verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _issue(db: Session, user_id: int, family_id: str | None = None) -> TokenOut:
    refresh, jti, fam, exp = create_refresh_token(user_id, family_id)
    db.add(RefreshToken(jti=jti, family_id=fam, user_id=user_id, expires_at=exp))
    db.commit()
    return TokenOut(access_token=create_access_token(user_id), refresh_token=refresh)


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(email=email, full_name=body.full_name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return _issue(db, user.id)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    key = f"rl:login:{request.client.host if request.client else 'x'}:{email}"
    if cache.incr(key, 60) > settings.login_rate_limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again in a minute.")
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return _issue(db, user.id)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    """Rotating refresh tokens. Presenting a token that was already rotated means it leaked,
    so the entire family is revoked and the caller must log in again."""
    data = decode_token(body.refresh_token, "refresh")
    row = db.scalar(select(RefreshToken).where(RefreshToken.jti == data["jti"]))
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown refresh token")
    if row.revoked:
        db.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id).values(revoked=True))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token reuse detected; session revoked")
    if row.expires_at < utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token expired")
    row.revoked = True
    db.flush()
    return _issue(db, row.user_id, row.family_id)


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, db: Session = Depends(get_db)):
    data = decode_token(body.refresh_token, "refresh")
    db.execute(update(RefreshToken).where(RefreshToken.family_id == data["fam"]).values(revoked=True))
    db.commit()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
