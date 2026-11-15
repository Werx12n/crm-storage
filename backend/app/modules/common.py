"""Спільна база для Control-класів (менеджерів) і серіалізатори відповідей."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import settings
from app.entities import Cell, Operation, Product, Stock, Task, User
from app.repositories import (
    DirectoryRepository, DocumentRepository, EventRepository, JournalRepository, StockRepository,
    TaskRepository,
)
from app.services import gs1
from app.services.events import EventPublisher
from app.services.rules import RulesService


def D(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x or 0))


def num(x) -> float | None:
    return None if x is None else float(x)


class ManagerBase:
    def __init__(self, session: Session, user: User | None = None):
        self.s = session
        self.user = user
        self.stock = StockRepository(session)
        self.docs = DocumentRepository(session)
        self.tasks = TaskRepository(session)
        self.dirs = DirectoryRepository(session)
        self.journal = JournalRepository(session)
        self.events = EventRepository(session)
        self.rules = RulesService(self.stock, self.dirs)
        self.publisher = EventPublisher(self.events)

    def commit(self) -> None:
        self.s.commit()

    @property
    def login(self) -> str | None:
        return self.user.login if self.user else None

    def op(self, type_: str, qty, stock: Stock | None = None, task: Task | None = None,
           details: str = "") -> Operation:
        return self.stock.add_operation(Operation(
            type=type_, quantity=D(qty), stock=stock, stock_id=stock.id if stock else None,
            task_id=task.id if task else None, user_id=self.user.id if self.user else None,
            details=details))

    def next_no(self, prefix: str) -> str:
        return f"{prefix}-{self.docs.next_number(prefix):06d}"

    def new_sscc(self) -> str:
        return gs1.make_sscc(settings.gs1_company_prefix, self.docs.next_number("SSCC"))


# ---------- серіалізатори ----------
def product_dict(p: Product) -> dict:
    return {"id": p.id, "code": p.code, "name": p.name, "gtin": p.gtin, "unit": p.unit,
            "weight": num(p.weight), "abc_class": p.abc_class, "min_pick_level": num(p.min_pick_level),
            "is_active": p.is_active}


def cell_dict(c: Cell | None) -> dict | None:
    if c is None:
        return None
    return {"id": c.id, "address": c.address, "zone": c.zone, "capacity": num(c.capacity),
            "abc_class": c.abc_class, "aisle": c.aisle, "rack": c.rack, "level": c.level,
            "warehouse": c.warehouse, "is_active": c.is_active}


def stock_dict(st: Stock) -> dict:
    return {"id": st.id, "product_code": st.batch.product.code, "product_name": st.batch.product.name,
            "batch": st.batch.number, "expiry_date": st.batch.expiry_date, "cell": st.cell.address,
            "zone": st.cell.zone, "quantity": num(st.quantity), "reserved": num(st.reserved),
            "available": num(st.available), "unit": st.batch.product.unit}


def task_dict(t: Task) -> dict:
    return {
        "number": t.number, "type": t.type, "status": t.status, "wave": t.wave, "label": t.label,
        "assignee": t.assignee.login if t.assignee else None, "note": t.note,
        "cell": t.cell.address if t.cell else None,
        "created_at": t.created_at, "completed_at": t.completed_at,
        "lines": [{
            "id": ln.id, "seq": ln.seq, "product_code": ln.product.code, "product_name": ln.product.name,
            "gtin": ln.product.gtin, "batch": ln.batch.number if ln.batch else None,
            "expiry_date": ln.batch.expiry_date if ln.batch else None,
            "from_cell": ln.from_cell.address if ln.from_cell else None,
            "to_cell": ln.to_cell.address if ln.to_cell else None,
            "quantity": num(ln.quantity), "done_quantity": num(ln.done_quantity),
            "counted_quantity": num(ln.counted_quantity), "status": ln.status,
        } for ln in t.lines],
    }


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
