"""JWT authentication and role-based access control."""

from datetime import timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_session
from app.models import Role, User, utcnow

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

ROLE_RANK = {Role.VIEWER: 0, Role.STAFF: 1, Role.MANAGER: 2, Role.ADMIN: 3}


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user: User) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "name": user.name,
        "exp": utcnow() + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def authenticate(session: Session, email: str, password: str) -> User | None:
    user = session.exec(select(User).where(User.email == email.lower().strip())).first()
    if user and user.is_active and verify_password(password, user.password_hash):
        return user
    return None


def _decode(token: str, session: Session) -> User:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    user = session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    session: Annotated[Session, Depends(get_session)],
    access_token: Annotated[str | None, Query(include_in_schema=False)] = None,
) -> User:
    # EventSource can't set headers, so SSE endpoints may pass ?access_token=
    token = token or access_token
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return _decode(token, session)


def require_role(minimum: Role):
    def dependency(user: Annotated[User, Depends(current_user)]) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {minimum} role or higher")
        return user

    return dependency


CurrentUser = Annotated[User, Depends(current_user)]
StaffUser = Annotated[User, Depends(require_role(Role.STAFF))]
ManagerUser = Annotated[User, Depends(require_role(Role.MANAGER))]
AdminUser = Annotated[User, Depends(require_role(Role.ADMIN))]
DbSession = Annotated[Session, Depends(get_session)]


def actor(user: User) -> str:
    return f"user:{user.email}"
