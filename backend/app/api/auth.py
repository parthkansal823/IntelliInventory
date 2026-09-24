from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlmodel import select

from app.hooks.bus import bus
from app.models import Role, User
from app.security import AdminUser, CurrentUser, DbSession, authenticate, create_access_token, hash_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
users_router = APIRouter(prefix="/api/users", tags=["users"])


def user_out(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat(),
    }


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(session: DbSession, form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> dict:
    """OAuth2 password flow (form fields `username` + `password`)."""
    return _login(session, form.username, form.password)


@router.post("/token")
def login_json(session: DbSession, body: LoginIn) -> dict:
    return _login(session, body.email, body.password)


def _login(session, email: str, password: str) -> dict:
    user = authenticate(session, email, password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    bus.emit("user.login", {"email": user.email, "role": user.role}, source=f"user:{user.email}")
    return {"access_token": create_access_token(user), "token_type": "bearer", "user": user_out(user)}


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return user_out(user)


class UserIn(BaseModel):
    email: EmailStr
    name: str
    role: Role = Role.STAFF
    password: str


class UserPatch(BaseModel):
    name: str | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = None


@users_router.get("")
def list_users(session: DbSession, _: CurrentUser) -> list[dict]:
    return [user_out(u) for u in session.exec(select(User).order_by(User.id))]


@users_router.post("", status_code=201)
def create_user(session: DbSession, body: UserIn, admin: AdminUser) -> dict:
    if session.exec(select(User).where(User.email == body.email.lower())).first():
        raise HTTPException(409, "A user with that email already exists")
    user = User(email=body.email.lower(), name=body.name, role=body.role, password_hash=hash_password(body.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    bus.emit("user.created", {"email": user.email, "role": user.role}, source=f"user:{admin.email}")
    return user_out(user)


@users_router.patch("/{user_id}")
def update_user(session: DbSession, user_id: int, body: UserPatch, admin: AdminUser) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if body.name is not None:
        user.name = body.name
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        if user.id == admin.id and not body.is_active:
            raise HTTPException(400, "You cannot deactivate yourself")
        user.is_active = body.is_active
    if body.password:
        user.password_hash = hash_password(body.password)
    session.add(user)
    session.commit()
    return user_out(user)
