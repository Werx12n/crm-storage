"""Boundary: розміщення (UC-02) і запит доступних залишків (UC-07)."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_deps import Roles, require_roles
from app.db import get_session
from app.entities import User
from app.modules.putaway.manager import PutawayManager, StockManager

router = APIRouter(tags=["putaway — розміщення і залишки (FR-2)"])

TZD = (Roles.FORKLIFT, Roles.MANAGER, Roles.ADMIN)
STOCK_VIEW = (Roles.SALES, Roles.MANAGER, Roles.ADMIN, Roles.ACCOUNTANT)


class ConfirmIn(BaseModel):
    cell: str
    confirm_replace: bool = False


@router.get("/api/putaway/tasks", summary="Відкриті завдання на розміщення")
def tasks(s: Session = Depends(get_session), u: User = Depends(require_roles(*TZD))):
    return PutawayManager(s, u).list_open()


@router.post("/api/putaway/{label}/suggest", summary="підібратиКомірку(вантаж): скан етикетки SSCC")
def suggest(label: str, s: Session = Depends(get_session), u: User = Depends(require_roles(*TZD))):
    return PutawayManager(s, u).suggest_cell(label)


@router.post("/api/putaway/{label}/confirm", summary="підтвердитиРозміщення(комірка)")
def confirm(label: str, body: ConfirmIn, s: Session = Depends(get_session),
            u: User = Depends(require_roles(*TZD))):
    return PutawayManager(s, u).confirm(label, body.cell, body.confirm_replace)


@router.get("/api/stock/available", summary="доступнийЗалишок(товар) — UC-07")
def available(q: str = Query(..., description="Код, GTIN або назва товару"),
              s: Session = Depends(get_session), u: User = Depends(require_roles(*STOCK_VIEW))):
    return StockManager(s, u).available(q)


@router.get("/api/stock", summary="Залишки «товар — партія — комірка» (FR-2.3)")
def stock(zone: str | None = None, s: Session = Depends(get_session),
          u: User = Depends(require_roles(*STOCK_VIEW))):
    return StockManager(s, u).stock_list(zone)
