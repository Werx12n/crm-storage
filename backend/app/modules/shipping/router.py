"""Boundary: відвантаження (UC-04, FR-4)."""
from decimal import Decimal

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api_deps import Roles, require_roles
from app.db import get_session
from app.entities import User
from app.modules.labels import document_html, label_html
from app.modules.shipping.manager import ShippingManager

router = APIRouter(prefix="/api/shipping", tags=["shipping — відвантаження (FR-4)"])

TZD = (Roles.PACKER, Roles.MANAGER, Roles.ADMIN)
VIEW = TZD + (Roles.ACCOUNTANT, Roles.SALES)


class CheckIn(BaseModel):
    code: str | None = Field(default=None, description="Скан вантажного місця / товару (GTIN, GS1 з AI 37)")
    quantity: Decimal | None = Field(default=None, gt=0)


@router.get("/ready", summary="Скомплектовані замовлення, готові до контролю")
def ready(s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW))):
    return ShippingManager(s, u).ready_orders()


@router.post("/orders/{number}/check", summary="перевіритиКомплектність(код) — FR-4.1")
def check(number: str, body: CheckIn, s: Session = Depends(get_session), u: User = Depends(require_roles(*TZD))):
    return ShippingManager(s, u).check_completeness(number, body.code, body.quantity)


@router.post("/orders/{number}/ship", summary="оформитиВідвантаження(): списання, SSCC, пакувальний лист, рампа")
def ship(number: str, s: Session = Depends(get_session), u: User = Depends(require_roles(*TZD))):
    return ShippingManager(s, u).ship(number)


@router.get("/dispatches", summary="Відправлення (ТТН, статуси)")
def dispatches(s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW))):
    return ShippingManager(s, u).list()


@router.get("/ramps", summary="Розклад рамп (FR-4.3)")
def ramps(s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW))):
    return ShippingManager(s, u).ramp_schedule()


@router.get("/dispatches/{dispatch_id}/packing-list", response_class=HTMLResponse,
            summary="Пакувальний лист (FR-4.2)")
def packing_list(dispatch_id: int, s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW))):
    d = ShippingManager(s, u).get(dispatch_id)
    pl = d.packing_list or {}
    return document_html(
        f"Пакувальний лист {pl.get('number', '')}",
        [("Замовлення", d.order.number), ("Клієнт", d.order.client), ("Дата", pl.get("date", "")),
         ("SSCC", d.sscc), ("ТТН", d.ttn_number or "очікується"), ("Рампа", pl.get("ramp") or "—"),
         ("Слот", pl.get("slot_start") or "—")],
        ["Код", "Товар", "Партія", "Придатний до", "К-сть", "Од.", "Вага, кг"],
        [[x["product_code"], x["product_name"], x["batch"], x["expiry_date"], x["quantity"], x["unit"], x["weight"]]
         for x in pl.get("lines", [])],
        footer=f"Загальна вага: {pl.get('total_weight', 0)} кг", barcode=d.sscc)


@router.get("/dispatches/{dispatch_id}/label", response_class=HTMLResponse, summary="Етикетка SSCC відправлення")
def dispatch_label(dispatch_id: int, s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW))):
    d = ShippingManager(s, u).get(dispatch_id)
    pl = d.packing_list or {}
    return label_html(d.sscc, [("Замовлення", d.order.number), ("Клієнт", d.order.client),
                               ("ТТН", d.ttn_number or "очікується"), ("Вага, кг", pl.get("total_weight", ""))],
                      title="Етикетка відправлення (SSCC)")
