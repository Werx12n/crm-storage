"""Boundary: API приймання для ЕкранТЗД / ВебІнтерфейсАРМ (UC-01, FR-1)."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api_deps import Roles, require_roles
from app.db import get_session
from app.entities import User
from app.modules.labels import label_html
from app.modules.receiving.manager import ReceivingManager

router = APIRouter(prefix="/api/receiving", tags=["receiving — приймання (FR-1)"])

TZD = (Roles.RECEIVER, Roles.MANAGER, Roles.ADMIN)
VIEW = TZD + (Roles.ACCOUNTANT,)


class ScanIn(BaseModel):
    code: str = Field(description="Скан штрихкоду GS1: GTIN або рядок з AI (01)(10)(17)(37)")
    quantity: Decimal | None = Field(default=None, gt=0)
    batch_number: str | None = None
    expiry_date: date | None = None


def mgr(session: Session, user: User) -> ReceivingManager:
    return ReceivingManager(session, user)


@router.get("/shipments", summary="Список поставок (ASN)")
def list_shipments(status: str | None = None, s: Session = Depends(get_session),
                   u: User = Depends(require_roles(*VIEW))):
    return mgr(s, u).list(status)


@router.get("/shipments/{number}", summary="Поставка з рядками, сканами і актом розбіжностей")
def get_shipment(number: str, s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW))):
    return mgr(s, u).get(number)


@router.post("/shipments/{number}/start", summary="почати(номер): відкрити поставку на ТЗД")
def start(number: str, s: Session = Depends(get_session), u: User = Depends(require_roles(*TZD))):
    return mgr(s, u).start(number)


@router.post("/shipments/{number}/scan", summary="зареєструватиСкан(код, кількість)")
def scan(number: str, body: ScanIn, s: Session = Depends(get_session), u: User = Depends(require_roles(*TZD))):
    return mgr(s, u).register_scan(number, body.code, body.quantity, body.batch_number, body.expiry_date)


@router.post("/shipments/{number}/complete", summary="завершити(): залишки, етикетки SSCC, акт розбіжностей")
def complete(number: str, s: Session = Depends(get_session), u: User = Depends(require_roles(*TZD))):
    return mgr(s, u).complete(number)


@router.get("/labels/{sscc}", summary="Дані етикетки SSCC вантажної одиниці (FR-1.4)")
def label(sscc: str, s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW, Roles.FORKLIFT))):
    return mgr(s, u).label(sscc)


@router.get("/labels/{sscc}/print", response_class=HTMLResponse, summary="Друкована етикетка SSCC (HTML)")
def label_print(sscc: str, s: Session = Depends(get_session),
                u: User = Depends(require_roles(*VIEW, Roles.FORKLIFT))):
    d = mgr(s, u).label(sscc)
    return label_html(d["sscc"], [("Товар", f"{d['product_code']} {d['product_name']}"),
                                  ("GTIN", d["gtin"]), ("Партія", d["batch"]),
                                  ("Придатний до", str(d["expiry_date"] or "—")),
                                  ("Кількість", f"{d['quantity']} {d['unit']}"), ("ASN", d["asn_number"])])
