"""Repository-шар: доступ до БД. Control-класи працюють із сутностями лише через репозиторії."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import db as dbmod
from app.entities import (
    Batch, Cell, Counter, Counterparty, Dispatch, Event, IdempotencyKey, Inventory, JournalEntry,
    Operation, Order, OrderLine, Product, Ramp, ReceiptScan, Reservation, Role, Rule, Shipment, Stock, Task,
    TaskLine, User, Zone, utcnow,
)


class StockRepository:
    """РепозиторійЗалишків: знайти(товар), змінити(залишок, кількість), зарезервувати(партія, кількість)."""

    def __init__(self, s: Session):
        self.s = s

    def find(self, product_id: int, zones: tuple[str, ...] | None = None) -> list[Stock]:
        q = (select(Stock).join(Stock.batch).join(Stock.cell)
             .where(Batch.product_id == product_id))
        if zones:
            q = q.where(Cell.zone.in_(zones))
        return list(self.s.scalars(q.order_by(Batch.expiry_date, Cell.address)))

    def find_all(self, zone: str | None = None, warehouse: str | None = None) -> list[Stock]:
        q = select(Stock).join(Stock.cell).where(Stock.quantity != 0)
        if zone:
            q = q.where(Cell.zone == zone)
        if warehouse:
            q = q.where(Cell.warehouse == warehouse)
        return list(self.s.scalars(q.order_by(Cell.address)))

    def find_in_cell(self, cell_id: int) -> list[Stock]:
        return list(self.s.scalars(select(Stock).where(Stock.cell_id == cell_id).order_by(Stock.id)))

    def get(self, stock_id: int) -> Stock | None:
        return self.s.get(Stock, stock_id)

    def get_or_create(self, batch: Batch, cell: Cell) -> Stock:
        st = self.s.scalar(select(Stock).where(Stock.batch_id == batch.id, Stock.cell_id == cell.id))
        if st is None:
            st = Stock(batch=batch, cell=cell, quantity=Decimal(0), reserved=Decimal(0))
            self.s.add(st)
            self.s.flush()
        return st

    def lock(self, stock: Stock) -> Stock:
        if dbmod.is_postgres():
            self.s.execute(select(Stock.id).where(Stock.id == stock.id).with_for_update())
            self.s.refresh(stock)
        return stock

    def change(self, stock: Stock, delta: Decimal) -> Stock:
        self.lock(stock)
        new_qty = Decimal(stock.quantity) + Decimal(delta)
        if new_qty < 0:
            raise ValueError("Залишок не може стати від'ємним")
        stock.quantity = new_qty
        return stock

    def reserve(self, stock: Stock, qty: Decimal) -> Stock:
        self.lock(stock)
        new_res = Decimal(stock.reserved) + Decimal(qty)
        if new_res > Decimal(stock.quantity) or new_res < 0:
            raise ValueError("Неможливо зарезервувати більше, ніж є в наявності")
        stock.reserved = new_res
        return stock

    def cell_load(self, cell_id: int) -> Decimal:
        """Поточне завантаження комірки, кг (кількість × вага товару)."""
        val = self.s.scalar(
            select(func.coalesce(func.sum(Stock.quantity * Product.weight), 0))
            .join(Batch, Stock.batch_id == Batch.id).join(Product, Batch.product_id == Product.id)
            .where(Stock.cell_id == cell_id))
        return Decimal(str(val or 0))

    def cell_summary(self) -> dict[int, dict]:
        """{cell_id: {'load': кг, 'products': {product_id}, 'batches': {batch_id}}} одним запитом."""
        rows = self.s.execute(
            select(Stock.cell_id, Batch.product_id, Stock.batch_id, Stock.quantity * Product.weight)
            .join(Batch, Stock.batch_id == Batch.id).join(Product, Batch.product_id == Product.id)
            .where(Stock.quantity > 0))
        out: dict[int, dict] = {}
        for cell_id, product_id, batch_id, kg in rows:
            d = out.setdefault(cell_id, {"load": Decimal(0), "products": set(), "batches": set()})
            d["load"] += Decimal(str(kg or 0))
            d["products"].add(product_id)
            d["batches"].add(batch_id)
        return out

    def candidates_fefo(self, product_id: int, min_expiry: date) -> list[Stock]:
        """Залишки товару, доступні для резервування, у порядку FEFO, потім FIFO."""
        q = (select(Stock).join(Stock.batch).join(Stock.cell)
             .where(Batch.product_id == product_id,
                    Cell.zone.in_((Zone.STORAGE, Zone.PICKING)), Cell.is_active.is_(True),
                    Stock.quantity > Stock.reserved,
                    or_(Batch.expiry_date.is_(None), Batch.expiry_date >= min_expiry))
             .order_by(Batch.expiry_date.is_(None), Batch.expiry_date, Batch.created_at, Batch.id,
                       Cell.zone, Cell.aisle, Cell.rack, Cell.level))
        return list(self.s.scalars(q))

    def add_reservation(self, r: Reservation) -> Reservation:
        self.s.add(r)
        self.s.flush()
        return r

    def reservations(self, order_line_ids: list[int], unassigned_only: bool = False) -> list[Reservation]:
        if not order_line_ids:
            return []
        q = select(Reservation).where(Reservation.order_line_id.in_(order_line_ids))
        if unassigned_only:
            q = q.where(Reservation.task_line_id.is_(None))
        return list(self.s.scalars(q.order_by(Reservation.id)))

    def add_operation(self, op: Operation) -> Operation:
        self.s.add(op)
        return op

    def operations_after(self, last_id: int, types: tuple[str, ...], limit: int = 5000) -> list[Operation]:
        return list(self.s.scalars(select(Operation).where(Operation.id > last_id, Operation.type.in_(types))
                                   .order_by(Operation.id).limit(limit)))

    def total_quantity(self) -> Decimal:
        return Decimal(str(self.s.scalar(select(func.coalesce(func.sum(Stock.quantity), 0))) or 0))

    def cell_count_occupied(self, zones: tuple[str, ...]) -> tuple[int, int]:
        total = self.s.scalar(select(func.count()).select_from(Cell).where(Cell.zone.in_(zones),
                                                                            Cell.is_active.is_(True))) or 0
        occupied = self.s.scalar(select(func.count(func.distinct(Stock.cell_id))).join(Cell, Stock.cell_id == Cell.id)
                                 .where(Cell.zone.in_(zones), Stock.quantity > 0)) or 0
        return int(occupied), int(total)

    def operations(self, start: datetime | None = None, end: datetime | None = None,
                   types: tuple[str, ...] | None = None) -> list[Operation]:
        q = select(Operation)
        if start:
            q = q.where(Operation.time >= start)
        if end:
            q = q.where(Operation.time < end)
        if types:
            q = q.where(Operation.type.in_(types))
        return list(self.s.scalars(q.order_by(Operation.time)))


class DocumentRepository:
    """РепозиторійДокументів: знайти(номер), зберегти(документ) — поставки, замовлення, відправлення, інвентаризації."""

    def __init__(self, s: Session):
        self.s = s

    def save(self, doc):
        self.s.add(doc)
        self.s.flush()
        return doc

    # поставки
    def find_shipment(self, number: str) -> Shipment | None:
        return self.s.scalar(select(Shipment).where(Shipment.asn_number == number))

    def list_shipments(self, status: str | None = None) -> list[Shipment]:
        q = select(Shipment)
        if status:
            q = q.where(Shipment.status == status)
        return list(self.s.scalars(q.order_by(Shipment.date.desc(), Shipment.id.desc())))

    def shipments_completed(self, start: datetime | None, end: datetime | None) -> list[Shipment]:
        q = select(Shipment).where(Shipment.completed_at.is_not(None))
        if start:
            q = q.where(Shipment.completed_at >= start)
        if end:
            q = q.where(Shipment.completed_at < end)
        return list(self.s.scalars(q))

    def scans(self, shipment_id: int) -> list[ReceiptScan]:
        return list(self.s.scalars(select(ReceiptScan).where(ReceiptScan.shipment_id == shipment_id)
                                   .order_by(ReceiptScan.id)))

    # замовлення
    def find_order(self, number: str) -> Order | None:
        return self.s.scalar(select(Order).where(Order.number == number))

    def get_shipment(self, shipment_id: int) -> Shipment | None:
        return self.s.get(Shipment, shipment_id)

    def get_order(self, order_id: int) -> Order | None:
        return self.s.get(Order, order_id)

    def get_order_line(self, line_id: int) -> OrderLine | None:
        return self.s.get(OrderLine, line_id)

    def list_orders(self, statuses: tuple[str, ...] | None = None) -> list[Order]:
        q = select(Order)
        if statuses:
            q = q.where(Order.status.in_(statuses))
        return list(self.s.scalars(q.order_by(Order.id.desc())))

    def orders_in_period(self, start: datetime | None, end: datetime | None) -> list[Order]:
        q = select(Order)
        if start:
            q = q.where(Order.created_at >= start)
        if end:
            q = q.where(Order.created_at < end)
        return list(self.s.scalars(q))

    # відправлення і рампи
    def find_dispatch(self, dispatch_id: int) -> Dispatch | None:
        return self.s.get(Dispatch, dispatch_id)

    def find_dispatch_by_sscc(self, sscc: str) -> Dispatch | None:
        return self.s.scalar(select(Dispatch).where(Dispatch.sscc == sscc))

    def list_dispatches(self) -> list[Dispatch]:
        return list(self.s.scalars(select(Dispatch).order_by(Dispatch.id.desc())))

    def ramps(self) -> list[Ramp]:
        return list(self.s.scalars(select(Ramp).order_by(Ramp.code)))

    def ramp_slots(self, ramp_id: int, since: datetime) -> list[datetime]:
        return [d for d in self.s.scalars(
            select(Dispatch.slot_start).where(Dispatch.ramp_id == ramp_id, Dispatch.slot_start >= since))]

    # інвентаризації
    def find_inventory(self, number: str) -> Inventory | None:
        return self.s.scalar(select(Inventory).where(Inventory.number == number))

    def find_inventory_by_id(self, inventory_id: int) -> Inventory | None:
        return self.s.get(Inventory, inventory_id)

    def list_inventories(self) -> list[Inventory]:
        return list(self.s.scalars(select(Inventory).order_by(Inventory.id.desc())))

    def counter(self, name: str) -> int:
        c = self.s.get(Counter, name)
        return c.value if c else 0

    def set_counter(self, name: str, value: int) -> None:
        c = self.s.get(Counter, name)
        if c is None:
            self.s.add(Counter(name=name, value=value))
        else:
            c.value = value
        self.s.flush()

    def dispatches_between(self, start: datetime | None, end: datetime | None) -> list[Dispatch]:
        q = select(Dispatch)
        if start:
            q = q.where(Dispatch.created_at >= start)
        if end:
            q = q.where(Dispatch.created_at < end)
        return list(self.s.scalars(q.order_by(Dispatch.id)))

    def next_number(self, name: str) -> int:
        q = select(Counter).where(Counter.name == name)
        if dbmod.is_postgres():
            q = q.with_for_update()
        c = self.s.scalar(q)
        if c is None:
            c = Counter(name=name, value=0)
            self.s.add(c)
        c.value += 1
        self.s.flush()
        return c.value


class TaskRepository:
    """РепозиторійЗавдань: знайти(номер), зберегти(завдання)."""

    def __init__(self, s: Session):
        self.s = s

    def find(self, number: str) -> Task | None:
        return self.s.scalar(select(Task).where(Task.number == number))

    def save(self, task: Task) -> Task:
        self.s.add(task)
        self.s.flush()
        return task

    def find_by_label(self, label: str, type_: str) -> Task | None:
        return self.s.scalar(select(Task).where(Task.label == label, Task.type == type_)
                             .order_by(Task.id.desc()))

    def list(self, type_: str | None = None, statuses: tuple[str, ...] | None = None,
             inventory_id: int | None = None, order_id: int | None = None,
             assignee_id: int | None = None) -> list[Task]:
        q = select(Task)
        if type_:
            q = q.where(Task.type == type_)
        if statuses:
            q = q.where(Task.status.in_(statuses))
        if inventory_id is not None:
            q = q.where(Task.inventory_id == inventory_id)
        if order_id is not None:
            q = q.where(Task.order_id == order_id)
        if assignee_id is not None:
            q = q.where(Task.assignee_id == assignee_id)
        return list(self.s.scalars(q.order_by(Task.id)))

    def lines_for_order_line(self, order_line_id: int) -> list[TaskLine]:
        return list(self.s.scalars(select(TaskLine).where(TaskLine.order_line_id == order_line_id)))

    def open_tasks_for_cell(self, cell_id: int, types: tuple[str, ...]) -> list[Task]:
        return list(self.s.scalars(select(Task).where(
            Task.cell_id == cell_id, Task.type.in_(types), Task.status.in_(("NEW", "IN_PROGRESS")))))

    def open_replenishment(self, product_id: int) -> Task | None:
        return self.s.scalar(select(Task).join(Task.lines).where(
            Task.type == "REPLENISH", Task.status.in_(("NEW", "IN_PROGRESS")),
            TaskLine.product_id == product_id))

    def created_between(self, start: datetime | None, end: datetime | None,
                        types: tuple[str, ...] | None = None) -> list[Task]:
        q = select(Task)
        if start:
            q = q.where(Task.created_at >= start)
        if end:
            q = q.where(Task.created_at < end)
        if types:
            q = q.where(Task.type.in_(types))
        return list(self.s.scalars(q.order_by(Task.id)))

    def get_line(self, line_id: int) -> TaskLine | None:
        return self.s.get(TaskLine, line_id)

    def completed(self, start: datetime | None, end: datetime | None) -> list[Task]:
        q = select(Task).where(Task.completed_at.is_not(None))
        if start:
            q = q.where(Task.completed_at >= start)
        if end:
            q = q.where(Task.completed_at < end)
        return list(self.s.scalars(q))


class DirectoryRepository:
    """РепозиторійДовідників: знайти(код), зберегти(запис)."""

    def __init__(self, s: Session):
        self.s = s

    MODELS = {"products": (Product, "code"), "cells": (Cell, "address"),
              "counterparties": (Counterparty, "code"), "rules": (Rule, "code"),
              "ramps": (Ramp, "code"), "users": (User, "login"), "roles": (Role, "name")}

    def find(self, kind: str, code: str):
        model, field = self.MODELS[kind]
        return self.s.scalar(select(model).where(getattr(model, field) == code))

    def get(self, kind: str, id_: int):
        return self.s.get(self.MODELS[kind][0], id_)

    def list(self, kind: str) -> list:
        model, field = self.MODELS[kind]
        return list(self.s.scalars(select(model).order_by(getattr(model, field))))

    def save(self, record):
        self.s.add(record)
        self.s.flush()
        return record

    # специфічні пошуки
    def product_by_gtin(self, gtin: str) -> Product | None:
        return self.s.scalar(select(Product).where(Product.gtin == gtin.zfill(14)))

    def product_by_any(self, code: str) -> Product | None:
        code = code.strip()
        return self.s.scalar(select(Product).where(
            or_(Product.code == code, Product.gtin == code.zfill(14) if code.isdigit() else False)))

    def search_products(self, text: str) -> list[Product]:
        """Пошук без урахування регістру (Unicode/кирилиця — однаково для SQLite і PostgreSQL)."""
        t = text.strip().casefold()
        return [p for p in self.all_products()
                if t in p.code.casefold() or t in p.name.casefold() or t in p.gtin]

    def all_products(self) -> list[Product]:
        return list(self.s.scalars(select(Product).order_by(Product.code)))

    def cell(self, address: str) -> Cell | None:
        return self.s.scalar(select(Cell).where(Cell.address == address.strip().upper()))

    def cells(self, zone: str | None = None, warehouse: str | None = None) -> list[Cell]:
        q = select(Cell).where(Cell.is_active.is_(True))
        if zone:
            q = q.where(Cell.zone == zone)
        if warehouse:
            q = q.where(Cell.warehouse == warehouse)
        return list(self.s.scalars(q.order_by(Cell.aisle, Cell.rack, Cell.level, Cell.address)))

    def first_cell(self, zone: str) -> Cell | None:
        return self.s.scalar(select(Cell).where(Cell.zone == zone, Cell.is_active.is_(True))
                             .order_by(Cell.address))

    def batch(self, product_id: int, number: str) -> Batch | None:
        return self.s.scalar(select(Batch).where(Batch.product_id == product_id, Batch.number == number))

    def get_or_create_batch(self, product: Product, number: str, expiry: date | None) -> Batch:
        b = self.batch(product.id, number)
        if b is None:
            b = Batch(product=product, product_id=product.id, number=number, expiry_date=expiry)
            self.s.add(b)
            self.s.flush()
        elif expiry and not b.expiry_date:
            b.expiry_date = expiry
        return b

    def rule(self, code: str, default: str) -> str:
        r = self.s.scalar(select(Rule).where(Rule.code == code))
        return r.value if r else default

    def user(self, login: str) -> User | None:
        return self.s.scalar(select(User).where(User.login == login))

    def users_with_role(self, role: str) -> list[User]:
        return list(self.s.scalars(select(User).join(User.roles).where(Role.name == role)))

    def role(self, name: str) -> Role | None:
        return self.s.scalar(select(Role).where(Role.name == name))


class JournalRepository:
    def __init__(self, s: Session):
        self.s = s

    def add(self, action: str, user_login: str | None, details: str = "", method: str | None = None,
            path: str | None = None, status_code: int | None = None) -> None:
        self.s.add(JournalEntry(action=action, user_login=user_login, details=details[:4000],
                                method=method, path=path, status_code=status_code))

    def list(self, limit: int = 200, user: str | None = None) -> list[JournalEntry]:
        q = select(JournalEntry)
        if user:
            q = q.where(JournalEntry.user_login == user)
        return list(self.s.scalars(q.order_by(JournalEntry.id.desc()).limit(limit)))

    # ідемпотентність
    def idem_get(self, key: str) -> IdempotencyKey | None:
        return self.s.get(IdempotencyKey, key)

    def idem_save(self, key: str, user: str | None, status: int, body: str) -> None:
        self.s.merge(IdempotencyKey(key=key, user_login=user, status_code=status, body=body))


class EventRepository:
    """Outbox: читання подій для воркера інтеграції."""

    def __init__(self, s: Session):
        self.s = s

    def add(self, ev: Event) -> Event:
        self.s.add(ev)
        return ev

    def due(self, limit: int = 20) -> list[Event]:
        q = (select(Event).where(Event.status == "PENDING", Event.next_attempt_at <= utcnow())
             .order_by(Event.id).limit(limit))
        if dbmod.is_postgres():
            q = q.with_for_update(skip_locked=True)
        return list(self.s.scalars(q))

    def list(self, limit: int = 100, status: str | None = None) -> list[Event]:
        q = select(Event)
        if status:
            q = q.where(Event.status == status)
        return list(self.s.scalars(q.order_by(Event.id.desc()).limit(limit)))

    def by_type(self, type_: str, start: datetime | None = None, end: datetime | None = None) -> list[Event]:
        q = select(Event).where(Event.type == type_)
        if start:
            q = q.where(Event.created_at >= start)
        if end:
            q = q.where(Event.created_at < end)
        return list(self.s.scalars(q.order_by(Event.id)))

    def get(self, event_id: int) -> Event | None:
        return self.s.get(Event, event_id)

    def count_by_status(self) -> dict[str, int]:
        return {k: v for k, v in self.s.execute(select(Event.status, func.count()).group_by(Event.status))}
