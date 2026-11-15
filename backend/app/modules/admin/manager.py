"""МенеджерДовідників (control): зберегтиЗапис(запис), призначитиРоль(користувач, роль). UC-08, FR-6.1, FR-6.4."""
from __future__ import annotations

from decimal import Decimal

from app.api_deps import ROLE_TITLES, Roles
from app.entities import Cell, Counterparty, Product, Ramp, Rule, User
from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.modules.common import ManagerBase, cell_dict, iso, product_dict
from app.security import create_token, hash_password, verify_password
from app.services import gs1

KINDS = ("products", "cells", "counterparties", "rules", "ramps", "users")


def user_dict(u: User) -> dict:
    return {"id": u.id, "login": u.login, "full_name": u.full_name, "is_active": u.is_active,
            "roles": u.role_names}


def record_dict(kind: str, r) -> dict:
    if kind == "products":
        return product_dict(r)
    if kind == "cells":
        return cell_dict(r)
    if kind == "users":
        return user_dict(r)
    if kind == "counterparties":
        return {"id": r.id, "code": r.code, "name": r.name, "kind": r.kind}
    if kind == "rules":
        return {"id": r.id, "code": r.code, "value": r.value, "description": r.description}
    if kind == "ramps":
        return {"id": r.id, "code": r.code, "name": r.name}
    raise ValueError(kind)


FIELDS = {
    "products": {"code", "name", "gtin", "unit", "weight", "abc_class", "min_pick_level", "is_active"},
    "cells": {"address", "zone", "capacity", "abc_class", "aisle", "rack", "level", "warehouse", "is_active"},
    "counterparties": {"code", "name", "kind"},
    "rules": {"code", "value", "description"},
    "ramps": {"code", "name"},
    "users": {"login", "full_name", "is_active", "password"},
}
MODELS = {"products": Product, "cells": Cell, "counterparties": Counterparty, "rules": Rule, "ramps": Ramp,
          "users": User}
ZONES = ("RECEIVING", "QUARANTINE", "STORAGE", "PICKING", "SHIPPING")


class DirectoryManager(ManagerBase):

    def _check_kind(self, kind: str) -> None:
        if kind not in KINDS:
            raise NotFound(f"Довідник {kind} не існує", code="unknown_directory")

    def list(self, kind: str) -> list[dict]:
        self._check_kind(kind)
        return [record_dict(kind, r) for r in self.dirs.list(kind)]

    # --- зберегтиЗапис(запис) ---
    def save_record(self, kind: str, data: dict, record_id: int | None = None) -> dict:
        self._check_kind(kind)
        if kind == "users" and Roles.ADMIN not in self.user.role_names:
            raise Forbidden("Користувачів веде лише адміністратор", code="admin_only")
        key_field = self.dirs.MODELS[kind][1]
        data = {k: v for k, v in data.items() if k in FIELDS[kind]}
        record = None
        if record_id is not None:
            record = self.dirs.get(kind, record_id)
            if record is None:
                raise NotFound("Запис не знайдено", code="not_found")
        elif not data.get(key_field):
            raise Invalid(f"Поле {key_field} обов'язкове", code="required")
        if kind == "cells" and "address" in data:
            data["address"] = data["address"].strip().upper()
        if kind == "cells" and "zone" in data and data["zone"] not in ZONES:
            raise Invalid(f"Зона має бути однією з {', '.join(ZONES)}", code="bad_zone")
        if kind == "products" and "gtin" in data:
            if not gs1.is_valid_gtin(str(data["gtin"])):
                raise Invalid("GTIN не відповідає стандарту GS1 (контрольна цифра)", code="bad_gtin")
            data["gtin"] = gs1.normalize_gtin(str(data["gtin"]))
            dup = self.dirs.product_by_gtin(data["gtin"])
            if dup and dup is not record:
                raise Conflict(f"GTIN {data['gtin']} вже використовується товаром {dup.code}", code="duplicate")
        # 3а: перевірка унікальності — РепозиторійДовідників.знайти(код)
        if key_field in data:
            dup = self.dirs.find(kind, data[key_field])
            if dup is not None and dup is not record:
                raise Conflict(f"Запис з {key_field} = {data[key_field]} вже існує", code="duplicate")
        password = data.pop("password", None)
        if record is None:
            if kind == "users" and not password:
                raise Invalid("Для нового користувача потрібен пароль", code="password_required")
            record = MODELS[kind]()
        for k, v in data.items():
            if k in ("weight", "capacity", "min_pick_level") and v is not None:
                v = Decimal(str(v))
            setattr(record, k, v)
        if password:
            if len(password) < 6:
                raise Invalid("Пароль має містити щонайменше 6 символів", code="weak_password")
            record.password_hash = hash_password(password)
        self.dirs.save(record)
        self.journal.add(f"Довідник {kind}: {'зміна' if record_id else 'додавання'}", self.login,
                         f"{getattr(record, key_field)}")
        self.commit()
        return record_dict(kind, record)

    # --- призначитиРоль(користувач, роль) ---
    def assign_role(self, login: str, role: str, revoke: bool = False) -> dict:
        if Roles.ADMIN not in self.user.role_names:  # обмеження UC-08
            raise Forbidden("Змінювати ролі може лише адміністратор", code="admin_only")
        user = self.dirs.user(login)
        if user is None:
            raise NotFound(f"Користувача {login} не знайдено", code="user_not_found")
        r = self.dirs.role(role)
        if r is None:
            raise NotFound(f"Роль {role} не існує", code="role_not_found")
        if revoke:
            if r in user.roles:
                if len(user.roles) == 1:
                    raise Invalid("Користувач повинен мати щонайменше одну роль", code="last_role")
                user.roles.remove(r)
        elif r not in user.roles:
            user.roles.append(r)
        self.dirs.save(user)
        self.journal.add("Роль відкликано" if revoke else "Роль призначено", self.login, f"{login}: {role}")
        self.commit()
        return user_dict(user)

    def roles(self) -> list[dict]:
        return [{"name": r.name, "title": r.title or ROLE_TITLES.get(r.name, r.name), "permissions": r.permissions}
                for r in self.dirs.list("roles")]

    def journal_list(self, limit: int = 200, user: str | None = None) -> list[dict]:
        return [{"id": j.id, "time": iso(j.time), "user": j.user_login, "action": j.action, "method": j.method,
                 "path": j.path, "status": j.status_code, "details": j.details}
                for j in self.journal.list(limit, user)]


class AuthManager(ManagerBase):
    """Автентифікація користувача (NFR-3.1) з журналюванням входів."""

    def login(self, login: str, password: str, path: str) -> dict | None:
        user = self.dirs.user(login)
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            self.journal.add("Невдала спроба входу", login, method="POST", path=path, status_code=401)
            self.commit()
            return None
        self.journal.add("Вхід у систему", user.login, method="POST", path=path, status_code=200)
        self.commit()
        return {"access_token": create_token(user.login, user.role_names), "token_type": "bearer",
                "user": user_dict(user)}
