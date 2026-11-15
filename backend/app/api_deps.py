"""API-шлюз: залежності FastAPI для перевірки токена і ролі (FR-6.4, NFR-3.1)."""
from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.entities import User
from app.security import decode_token

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


class Roles:
    ADMIN = "admin"                   # Адміністратор системи
    MANAGER = "warehouse_manager"     # Начальник складу
    ACCOUNTANT = "accountant"         # Бухгалтер
    SALES = "sales_manager"           # Менеджер з продажу
    RECEIVER = "receiver"             # Комірник-приймальник
    FORKLIFT = "forklift_driver"      # Водій навантажувача
    PICKER = "picker"                 # Комплектувальник
    PACKER = "packer"                 # Контролер-пакувальник
    WORKER = "stock_worker"           # Працівник складу (інвентаризація)
    INTEGRATION = "integration"       # Технічний обліковий запис ERP/EDI


ROLE_TITLES = {
    Roles.ADMIN: "Адміністратор системи",
    Roles.MANAGER: "Начальник складу",
    Roles.ACCOUNTANT: "Бухгалтер",
    Roles.SALES: "Менеджер з продажу",
    Roles.RECEIVER: "Комірник-приймальник",
    Roles.FORKLIFT: "Водій навантажувача",
    Roles.PICKER: "Комплектувальник",
    Roles.PACKER: "Контролер-пакувальник",
    Roles.WORKER: "Працівник складу",
    Roles.INTEGRATION: "Інтеграція (ERP/EDI)",
}

_UNAUTH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Потрібна автентифікація",
    headers={"WWW-Authenticate": "Bearer"},
)


def current_user(request: Request, token: str | None = Depends(oauth2),
                 session: Session = Depends(get_session)) -> User:
    if not token:
        raise _UNAUTH
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Термін дії токена минув",
                            headers={"WWW-Authenticate": "Bearer"})
    except jwt.PyJWTError:
        raise _UNAUTH
    user = session.scalar(select(User).where(User.login == payload.get("sub")))
    if user is None or not user.is_active:
        raise _UNAUTH
    request.state.user_login = user.login
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    """Перевірка ролі на рівні API-шлюзу."""
    def dep(user: User = Depends(current_user)) -> User:
        if roles and not set(roles) & set(user.role_names):
            raise HTTPException(status_code=403, detail="Недостатньо прав для операції")
        return user
    return dep
