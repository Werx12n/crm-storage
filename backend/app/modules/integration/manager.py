"""МенеджерІнтеграції (control): обробитиПодію(подія), синхронізувати(). FR-6.2, FR-6.3, UC-04 4а."""
from __future__ import annotations

from datetime import timedelta

from app.entities import Event, utcnow
from app.config import settings
from app.errors import NotFound
from app.modules.common import ManagerBase, iso, num
from app.modules.integration.gateways import DeliveryGateway, ERPGateway, GatewayError
from app.services.events import EventTypes

ERP_EVENTS = {EventTypes.RECEIVING_COMPLETED, EventTypes.ORDER_STATUS, EventTypes.SHIPPED,
              EventTypes.STOCK_ADJUSTED}


def event_dict(e: Event) -> dict:
    return {"id": e.id, "type": e.type, "status": e.status, "attempts": e.attempts,
            "created_at": iso(e.created_at), "processed_at": iso(e.processed_at),
            "next_attempt_at": iso(e.next_attempt_at), "last_error": e.last_error, "payload": e.payload}


class IntegrationManager(ManagerBase):
    def __init__(self, session, user=None, erp: ERPGateway | None = None, delivery: DeliveryGateway | None = None):
        super().__init__(session, user)
        self.erp = erp or ERPGateway()
        self.delivery = delivery or DeliveryGateway()

    # --- обробитиПодію(подія) ---
    def process_event(self, ev: Event) -> bool:
        ev.attempts += 1
        try:
            if ev.type in ERP_EVENTS:
                self.erp.send_operations({"event_id": ev.id, "type": ev.type, "created_at": iso(ev.created_at),
                                          "warehouse": settings.warehouse_code, "payload": ev.payload})
            elif ev.type == EventTypes.DELIVERY_REQUESTED:
                ttn = self.delivery.create_shipment({**ev.payload, "request_id": f"wms-{ev.id}"})
                d = self.docs.find_dispatch(ev.payload["dispatch_id"])
                if d is not None:
                    d.ttn_number = ttn
                    d.status = "SENT"
                    self.journal.add("Отримано ТТН", None, f"{d.order.number}: {ttn}")
            ev.status = "PROCESSED"
            ev.processed_at = utcnow()
            ev.last_error = None
            ok = True
        except GatewayError as e:  # 4а: у черзі, повторна спроба з експоненційною затримкою
            ev.last_error = str(e)
            ev.next_attempt_at = utcnow() + timedelta(seconds=min(2 ** ev.attempts, 300))
            if ev.attempts >= settings.max_event_attempts:
                ev.status = "FAILED"
            ok = False
        self.commit()
        return ok

    # --- синхронізувати() ---
    def synchronize(self, limit: int = 50, force: bool = False) -> dict:
        if force:
            for ev in self.events.list(limit, "PENDING"):
                ev.next_attempt_at = utcnow()
            self.s.flush()
        due = self.events.due(limit)
        ok = sum(1 for ev in due if self.process_event(ev))
        return {"processed": ok, "failed": len(due) - ok, "pending": self.events.count_by_status().get("PENDING", 0)}

    def list_events(self, status: str | None = None, limit: int = 100) -> list[dict]:
        return [event_dict(e) for e in self.events.list(limit, status)]

    def retry(self, event_id: int) -> dict:
        ev = self.events.get(event_id)
        if ev is None:
            raise NotFound("Подію не знайдено", code="event_not_found")
        if ev.status != "PROCESSED":
            ev.status = "PENDING"
            ev.next_attempt_at = utcnow()
            self.commit()
        return event_dict(ev)

    # --- ШлюзСлужбиДоставки.прийнятиСтатус(статус) ---
    def accept_delivery_status(self, ttn: str, status: str) -> dict:
        d = next((x for x in self.docs.list_dispatches() if x.ttn_number == ttn), None)
        if d is None:
            raise NotFound(f"Відправлення з ТТН {ttn} не знайдено", code="ttn_not_found")
        d.status = status.upper()
        self.journal.add("Статус доставки", self.login, f"{ttn}: {status}")
        self.commit()
        return {"ttn": ttn, "status": d.status, "order_number": d.order.number}

    def export_stock(self) -> dict:
        """Вивантаження залишків для облікової системи (FR-6.2)."""
        rows: dict[tuple, dict] = {}
        for st in self.stock.find_all():
            k = (st.batch.product.code, st.batch.number)
            r = rows.setdefault(k, {"product_code": k[0], "gtin": st.batch.product.gtin, "batch": k[1],
                                    "expiry_date": str(st.batch.expiry_date or ""), "quantity": 0.0, "reserved": 0.0})
            r["quantity"] += num(st.quantity)
            r["reserved"] += num(st.reserved)
        return {"warehouse": settings.warehouse_code, "generated_at": iso(utcnow()), "items": list(rows.values())}
