"""Boundary: автентифікація, довідники, ролі, журнал (UC-08, FR-6.1, FR-6.4)."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_deps import Roles, current_user, require_roles
from app.db import get_session
from app.entities import User
from app.modules.admin.manager import AuthManager, DirectoryManager, user_dict

auth_router = APIRouter(prefix="/api/auth", tags=["auth — автентифікація (NFR-3.1)"])
router = APIRouter(prefix="/api/admin", tags=["admin — довідники, ролі, журнал (FR-6.1, FR-6.4)"])

DIR_EDIT = (Roles.ADMIN, Roles.MANAGER)


class LoginIn(BaseModel):
    login: str
    password: str


class RoleIn(BaseModel):
    role: str
    revoke: bool = False


def _login(session: Session, request: Request, login: str, password: str) -> dict:
    res = AuthManager(session).login(login, password, str(request.url.path))
    if res is None:
        raise HTTPException(status_code=401, detail="Невірний логін або пароль")
    return res


@auth_router.post("/login", summary="Вхід (JSON) → JWT")
def login(body: LoginIn, request: Request, s: Session = Depends(get_session)):
    return _login(s, request, body.login, body.password)


@auth_router.post("/token", summary="OAuth2 password flow (для Swagger UI)")
def token(request: Request, form: OAuth2PasswordRequestForm = Depends(), s: Session = Depends(get_session)):
    return _login(s, request, form.username, form.password)


@auth_router.get("/me", summary="Поточний користувач")
def me(u: User = Depends(current_user)):
    return user_dict(u)


@router.get("/directories/{kind}", summary="відкрити довідник: products|cells|counterparties|rules|ramps|users")
def list_dir(kind: str, s: Session = Depends(get_session),
             u: User = Depends(require_roles(*DIR_EDIT, Roles.ACCOUNTANT, Roles.SALES))):
    if kind == "users" and not set(u.role_names) & {Roles.ADMIN, Roles.MANAGER}:
        raise HTTPException(403, "Недостатньо прав для операції")
    return DirectoryManager(s, u).list(kind)


@router.post("/directories/{kind}", summary="зберегтиЗапис(запис): новий запис")
def create_rec(kind: str, body: dict[str, Any], s: Session = Depends(get_session),
               u: User = Depends(require_roles(*DIR_EDIT))):
    return DirectoryManager(s, u).save_record(kind, body)


@router.put("/directories/{kind}/{record_id}", summary="зберегтиЗапис(запис): зміна запису")
def update_rec(kind: str, record_id: int, body: dict[str, Any], s: Session = Depends(get_session),
               u: User = Depends(require_roles(*DIR_EDIT))):
    return DirectoryManager(s, u).save_record(kind, body, record_id)


@router.get("/roles", summary="Ролі")
def roles(s: Session = Depends(get_session), u: User = Depends(require_roles(*DIR_EDIT))):
    return DirectoryManager(s, u).roles()


@router.post("/users/{login}/roles", summary="призначитиРоль(користувач, роль) — лише адміністратор")
def assign(login: str, body: RoleIn, s: Session = Depends(get_session), u: User = Depends(require_roles(Roles.ADMIN))):
    return DirectoryManager(s, u).assign_role(login, body.role, body.revoke)


@router.get("/journal", summary="Журнал операцій (FR-6.4)")
def journal(limit: int = 200, user: str | None = None, s: Session = Depends(get_session),
            u: User = Depends(require_roles(Roles.ADMIN, Roles.MANAGER))):
    return DirectoryManager(s, u).journal_list(min(limit, 1000), user)
