"""Boundary: вхідні шлюзи ШлюзEDI.прийнятиASN, ШлюзERP.отриматиЗамовлення,
ШлюзСлужбиДоставки.прийнятиСтатус, а також моніторинг outbox (FR-6.2, FR-6.3)."""
import datetime as dt
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api_deps import Roles, require_roles
from app.db import get_session
from app.entities import User
from app.modules.integration.manager import IntegrationManager
from app.modules.picking.manager import PickingManager
from app.modules.receiving.manager import ReceivingManager

router = APIRouter(prefix="/api/integration", tags=["integration — ERP / EDI / доставка (FR-6.2, FR-6.3)"])

SYS = (Roles.INTEGRATION, Roles.ADMIN, Roles.MANAGER)


class AsnLine(BaseModel):
    gtin: str | None = None
    product_code: str | None = None
    quantity: Decimal = Field(gt=0)
    batch_number: str | None = None
    expiry_date: date | None = None


class AsnIn(BaseModel):
    asn_number: str = Field(min_length=1, max_length=50)
    date: dt.date | None = None
    supplier: str = ""
    lines: list[AsnLine]


class OrderLineIn(BaseModel):
    product_code: str | None = None
    gtin: str | None = None
    quantity: Decimal = Field(gt=0)


class OrderIn(BaseModel):
    number: str = Field(min_length=1, max_length=50)
    client: str = ""
    lines: list[OrderLineIn]
    create_task: bool = Field(default=True, description="Одразу сформувати завдання на відбір (False — для хвиль)")


class DeliveryStatusIn(BaseModel):
    ttn: str
    status: str


@router.post("/edi/asn", summary="ШлюзEDI.прийнятиASN(документ) → зареєструватиASN (FR-1.1)")
def edi_asn(body: AsnIn, s: Session = Depends(get_session), u: User = Depends(require_roles(*SYS))):
    return ReceivingManager(s, u).register_asn(body.model_dump())


@router.post("/erp/orders", summary="ШлюзERP.отриматиЗамовлення() → прийнятиЗамовлення (UC-03)")
def erp_order(body: OrderIn, s: Session = Depends(get_session), u: User = Depends(require_roles(*SYS))):
    data = body.model_dump()
    return PickingManager(s, u).accept_order(data, create_task=data.pop("create_task"))


@router.get("/erp/stock", summary="Вивантаження залишків для ERP")
def erp_stock(s: Session = Depends(get_session), u: User = Depends(require_roles(*SYS, Roles.ACCOUNTANT))):
    return IntegrationManager(s, u).export_stock()


@router.post("/delivery/status", summary="ШлюзСлужбиДоставки.прийнятиСтатус(статус)")
def delivery_status(body: DeliveryStatusIn, s: Session = Depends(get_session), u: User = Depends(require_roles(*SYS))):
    return IntegrationManager(s, u).accept_delivery_status(body.ttn, body.status)


@router.get("/events", summary="Черга подій (outbox)")
def events(status: str | None = None, limit: int = 100, s: Session = Depends(get_session),
           u: User = Depends(require_roles(*SYS))):
    return IntegrationManager(s, u).list_events(status, min(limit, 500))


@router.post("/sync", summary="синхронізувати(): обробити чергу подій зараз")
def sync(force: bool = True, s: Session = Depends(get_session), u: User = Depends(require_roles(*SYS))):
    return IntegrationManager(s, u).synchronize(force=force)


@router.post("/events/{event_id}/retry", summary="Повторити подію")
def retry(event_id: int, s: Session = Depends(get_session), u: User = Depends(require_roles(*SYS))):
    return IntegrationManager(s, u).retry(event_id)
