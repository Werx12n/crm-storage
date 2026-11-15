"""Boundary: комплектація (UC-03, FR-3)."""
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api_deps import Roles, require_roles
from app.db import get_session
from app.entities import User
from app.modules.picking.manager import PickingManager

router = APIRouter(prefix="/api/picking", tags=["picking — комплектація (FR-3)"])

TZD = (Roles.PICKER, Roles.MANAGER, Roles.ADMIN)
ARM = (Roles.MANAGER, Roles.ADMIN)
VIEW = ARM + (Roles.SALES, Roles.ACCOUNTANT, Roles.PACKER)


class PickIn(BaseModel):
    cell: str = Field(description="Скан штрихкоду комірки")
    product: str = Field(description="Скан штрихкоду товару (GTIN / GS1)")
    quantity: Decimal | None = Field(default=None, gt=0)


class WaveIn(BaseModel):
    orders: list[str] | None = Field(default=None, description="Номери замовлень; порожньо — усі зарезервовані")
    wave: bool = True


class ReplConfirmIn(BaseModel):
    cell: str


@router.get("/orders", summary="Замовлення")
def orders(status: str | None = None, s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW))):
    return PickingManager(s, u).list_orders(status)


@router.get("/orders/{number}", summary="Замовлення з рядками")
def order(number: str, s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW))):
    return PickingManager(s, u).get_order(number)


@router.post("/waves", summary="сформуватиЗавдання(): згрупувати замовлення у хвилю (FR-3.2)")
def waves(body: WaveIn, s: Session = Depends(get_session), u: User = Depends(require_roles(*ARM))):
    return PickingManager(s, u).form_tasks(body.orders, body.wave)


@router.get("/tasks", summary="Завдання (усі типи)")
def tasks(type: str | None = None, status: str | None = None, s: Session = Depends(get_session),
          u: User = Depends(require_roles(*VIEW))):
    return PickingManager(s, u).list_tasks(type, status)


@router.post("/tasks/next", summary="отриматиЗавдання(виконавець): завдання з маршрутом")
def next_task(s: Session = Depends(get_session), u: User = Depends(require_roles(*TZD))):
    return PickingManager(s, u).get_task()


@router.get("/tasks/{number}", summary="Завдання на відбір з маршрутом")
def task(number: str, s: Session = Depends(get_session), u: User = Depends(require_roles(*TZD, *VIEW))):
    return PickingManager(s, u).view(number)


@router.post("/tasks/{number}/confirm", summary="підтвердитиВідбір(код): скан комірки і товару")
def confirm(number: str, body: PickIn, s: Session = Depends(get_session), u: User = Depends(require_roles(*TZD))):
    return PickingManager(s, u).confirm_pick(number, body.cell, body.product, body.quantity)


@router.post("/replenishment/check", summary="Створити завдання на поповнення за мін. рівнем (FR-3.4)")
def repl_check(s: Session = Depends(get_session), u: User = Depends(require_roles(*ARM))):
    return PickingManager(s, u).run_replenishment()


@router.post("/replenishment/{number}/confirm", summary="Підтвердити поповнення (скан комірки відбору)")
def repl_confirm(number: str, body: ReplConfirmIn, s: Session = Depends(get_session),
                 u: User = Depends(require_roles(Roles.FORKLIFT, *ARM))):
    return PickingManager(s, u).confirm_replenishment(number, body.cell)
