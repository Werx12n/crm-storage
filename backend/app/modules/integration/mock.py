"""Mock-сервіси зовнішніх систем: облікова система (ERP) і служба доставки.

Живуть у тому ж процесі API за префіксом /mock і не потребують автентифікації (імітація сторонніх API).
"""
import random
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/mock", tags=["mock — зовнішні системи"])

_lock = threading.Lock()
STATE = {"erp_operations": [], "erp_available": True, "delivery_shipments": [], "delivery_available": True}


class Availability(BaseModel):
    available: bool


def reset() -> None:
    with _lock:
        STATE.update(erp_operations=[], erp_available=True, delivery_shipments=[], delivery_available=True)


@router.post("/erp/operations", summary="Mock ERP: прийняти пакет операцій")
def erp_operations(batch: dict):
    if not STATE["erp_available"]:
        raise HTTPException(503, "ERP недоступна")
    with _lock:
        if not any(o.get("event_id") == batch.get("event_id") for o in STATE["erp_operations"]):
            STATE["erp_operations"].append(batch)  # ідемпотентно за event_id
    return {"accepted": True, "event_id": batch.get("event_id")}


@router.get("/erp/operations", summary="Mock ERP: отримані операції")
def erp_operations_list():
    return STATE["erp_operations"]


@router.post("/erp/config", summary="Mock ERP: увімкнути/вимкнути доступність")
def erp_config(body: Availability):
    STATE["erp_available"] = body.available
    return body


@router.post("/delivery/shipments", summary="Mock служби доставки: створити відправлення → ТТН")
def delivery_create(data: dict):
    if not STATE["delivery_available"]:
        raise HTTPException(503, "API служби доставки недоступне")
    with _lock:
        existing = next((x for x in STATE["delivery_shipments"] if x["request_id"] == data.get("request_id")), None)
        if existing:
            return existing
        ttn = "2045" + "".join(random.choices("0123456789", k=10))
        rec = {"request_id": data.get("request_id"), "ttn": ttn, "status": "CREATED", "data": data}
        STATE["delivery_shipments"].append(rec)
    return rec


@router.get("/delivery/shipments", summary="Mock служби доставки: створені відправлення")
def delivery_list():
    return STATE["delivery_shipments"]


@router.post("/delivery/config", summary="Mock служби доставки: увімкнути/вимкнути доступність (UC-04 4а)")
def delivery_config(body: Availability):
    STATE["delivery_available"] = body.available
    return body
