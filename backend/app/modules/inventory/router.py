"""Boundary: інвентаризація (UC-05, FR-5)."""
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api_deps import Roles, require_roles
from app.db import get_session
from app.entities import User
from app.modules.inventory.manager import InventoryManager

router = APIRouter(prefix="/api/inventory", tags=["inventory — інвентаризація (FR-5)"])

TZD = (Roles.WORKER, Roles.MANAGER)
VIEW = (Roles.MANAGER, Roles.ADMIN, Roles.ACCOUNTANT)


class PlanIn(BaseModel):
    zone: str | None = Field(default=None, description="Зона (STORAGE, PICKING, ...)")
    cells: list[str] | None = None
    threshold: Decimal = Field(default=Decimal(0), ge=0, description="Поріг розбіжності для повторного перерахунку")


class CountIn(BaseModel):
    cell: str
    quantity: Decimal = Field(ge=0)
    product: str | None = Field(default=None, description="Скан товару (якщо в комірці кілька позицій)")


@router.get("", summary="Інвентаризації")
def list_(s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW))):
    return InventoryManager(s, u).list()


@router.post("", summary="створитиПлан(зона)")
def create(body: PlanIn, s: Session = Depends(get_session), u: User = Depends(require_roles(Roles.MANAGER))):
    return InventoryManager(s, u).create_plan(body.zone, body.cells, body.threshold)


@router.get("/tasks/open", summary="Завдання на перерахунок для ТЗД (сліпий підрахунок)")
def open_tasks(s: Session = Depends(get_session), u: User = Depends(require_roles(*TZD))):
    return InventoryManager(s, u).open_tasks()


@router.post("/count", summary="прийнятиРезультат(комірка, кількість)")
def count(body: CountIn, s: Session = Depends(get_session), u: User = Depends(require_roles(*TZD))):
    return InventoryManager(s, u).accept_result(body.cell, body.quantity, body.product)


@router.get("/{number}", summary="Інвентаризація з завданнями і відомістю")
def get(number: str, s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW))):
    return InventoryManager(s, u).get(number)


@router.post("/{number}/approve", summary="затвердитиКоригування() — лише начальник складу (BRL-02)")
def approve(number: str, s: Session = Depends(get_session), u: User = Depends(require_roles(Roles.MANAGER))):
    return InventoryManager(s, u).approve(number)
