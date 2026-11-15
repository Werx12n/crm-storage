"""Entity-шар (BCE): моделі SQLAlchemy відповідно до діаграми класів сутностей (п. 3.3).

Ідентифікатори в коді англійською, у коментарях — назви з моделі EA.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Table, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

QTY = Numeric(14, 3)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- Зони комірок ---
class Zone:
    RECEIVING = "RECEIVING"     # зона приймання
    QUARANTINE = "QUARANTINE"   # зона карантину (UC-01 3а)
    STORAGE = "STORAGE"         # зона зберігання
    PICKING = "PICKING"         # зона відбору (FR-3.4)
    SHIPPING = "SHIPPING"       # зона відвантаження


user_roles = Table(
    "user_roles", Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    """Роль: назва, права."""
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    title: Mapped[str] = mapped_column(String(100), default="")
    permissions: Mapped[str] = mapped_column(String(500), default="")


class User(Base):
    """Користувач: логін, ПІБ. Користувач [0..*] — Роль [1..*]."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(50), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")

    @property
    def role_names(self) -> list[str]:
        return sorted(r.name for r in self.roles)


class Product(Base):
    """Товар: код, назва, gtin, одиниця, вага."""
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    gtin: Mapped[str] = mapped_column(String(14), unique=True)
    unit: Mapped[str] = mapped_column(String(20), default="шт")
    weight: Mapped[Decimal] = mapped_column(QTY, default=Decimal("1"))  # кг за одиницю
    abc_class: Mapped[str] = mapped_column(String(1), default="C")
    min_pick_level: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))  # FR-3.4
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Batch(Base):
    """Партія: номер, термін придатності. Партія [0..*] — Товар [1]."""
    __tablename__ = "batches"
    __table_args__ = (UniqueConstraint("product_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(50))
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    product: Mapped[Product] = relationship(lazy="joined")


class Cell(Base):
    """Комірка: адреса, зона, місткість (кг)."""
    __tablename__ = "cells"
    id: Mapped[int] = mapped_column(primary_key=True)
    address: Mapped[str] = mapped_column(String(30), unique=True)
    zone: Mapped[str] = mapped_column(String(20))
    capacity: Mapped[Decimal] = mapped_column(QTY, default=Decimal("1000"))
    abc_class: Mapped[str | None] = mapped_column(String(1), nullable=True)
    aisle: Mapped[int] = mapped_column(Integer, default=0)
    rack: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    warehouse: Mapped[str] = mapped_column(String(20), default="WH1")  # NFR-5.3
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Stock(Base):
    """Залишок: кількість, зарезервовано. Залишок — Партія [1], — Комірка [1]."""
    __tablename__ = "stock"
    __table_args__ = (UniqueConstraint("batch_id", "cell_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    cell_id: Mapped[int] = mapped_column(ForeignKey("cells.id"))
    quantity: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    reserved: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    batch: Mapped[Batch] = relationship(lazy="joined")
    cell: Mapped[Cell] = relationship(lazy="joined")

    @property
    def available(self) -> Decimal:
        return Decimal(self.quantity) - Decimal(self.reserved)


class Shipment(Base):
    """Поставка (ASN): номерASN, дата, статус."""
    __tablename__ = "shipments"
    id: Mapped[int] = mapped_column(primary_key=True)
    asn_number: Mapped[str] = mapped_column(String(50), unique=True)
    date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="REGISTERED")
    supplier: Mapped[str] = mapped_column(String(200), default="")
    discrepancy_act: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ВП-03
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lines: Mapped[list["ShipmentLine"]] = relationship(
        back_populates="shipment", cascade="all, delete-orphan", order_by="ShipmentLine.id")


class ShipmentLine(Base):
    """РядокПоставки: очікувано, прийнято. Агрегація з Поставкою."""
    __tablename__ = "shipment_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    accepted: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    shipment: Mapped[Shipment] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship(lazy="joined")


class ReceiptScan(Base):
    """Скан приймання (технічна сутність для кроків 3–5 UC-01)."""
    __tablename__ = "receipt_scans"
    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id", ondelete="CASCADE"))
    line_id: Mapped[int | None] = mapped_column(ForeignKey("shipment_lines.id"), nullable=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_number: Mapped[str] = mapped_column(String(50))
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(QTY)
    quarantine: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    product: Mapped[Product] = relationship(lazy="joined")


class Order(Base):
    """Замовлення: номер, клієнт, статус."""
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(50), unique=True)
    client: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="NEW")
    wave: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    picked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderLine.id")


class OrderLine(Base):
    """РядокЗамовлення: кількість (+ резерв, відібрано, перевірено)."""
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    reserved: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    picked: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    checked: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    order: Mapped[Order] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship(lazy="joined")


class Reservation(Base):
    """Резерв партії під рядок замовлення (FR-3.1): зарезервувати(партія, кількість)."""
    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_line_id: Mapped[int] = mapped_column(ForeignKey("order_lines.id", ondelete="CASCADE"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stock.id"))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    task_line_id: Mapped[int | None] = mapped_column(ForeignKey("task_lines.id"), nullable=True)
    stock: Mapped[Stock] = relationship(lazy="joined")
    order_line: Mapped["OrderLine"] = relationship(lazy="joined")


class Inventory(Base):
    """Інвентаризація: номер, дата, статус."""
    __tablename__ = "inventories"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="COUNTING")
    zone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    threshold: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    approved_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    statement: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ВП-04


class Task(Base):
    """Завдання: номер, тип, статус. Виконавець [0..1], Замовлення/Поставка/Інвентаризація [0..1]."""
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    type: Mapped[str] = mapped_column(String(20))  # PUTAWAY | PICK | COUNT | RECOUNT | REPLENISH
    status: Mapped[str] = mapped_column(String(20), default="NEW")  # NEW|IN_PROGRESS|DONE|ESCALATED
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    shipment_id: Mapped[int | None] = mapped_column(ForeignKey("shipments.id"), nullable=True)
    inventory_id: Mapped[int | None] = mapped_column(ForeignKey("inventories.id"), nullable=True)
    cell_id: Mapped[int | None] = mapped_column(ForeignKey("cells.id"), nullable=True)
    wave: Mapped[str | None] = mapped_column(String(30), nullable=True)
    label: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)  # SSCC
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lines: Mapped[list["TaskLine"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskLine.seq")
    assignee: Mapped[User | None] = relationship(lazy="joined")
    cell: Mapped[Cell | None] = relationship(lazy="joined")


class TaskLine(Base):
    """Рядок завдання (що, звідки, куди, скільки)."""
    __tablename__ = "task_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer, default=0)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"), nullable=True)
    from_cell_id: Mapped[int | None] = mapped_column(ForeignKey("cells.id"), nullable=True)
    to_cell_id: Mapped[int | None] = mapped_column(ForeignKey("cells.id"), nullable=True)
    order_line_id: Mapped[int | None] = mapped_column(ForeignKey("order_lines.id"), nullable=True)
    stock_id: Mapped[int | None] = mapped_column(ForeignKey("stock.id"), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    done_quantity: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    expected_quantity: Mapped[Decimal | None] = mapped_column(QTY, nullable=True)
    counted_quantity: Mapped[Decimal | None] = mapped_column(QTY, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="NEW")
    task: Mapped[Task] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship(lazy="joined")
    batch: Mapped[Batch | None] = relationship(lazy="joined")
    from_cell: Mapped[Cell | None] = relationship(foreign_keys=[from_cell_id], lazy="joined")
    to_cell: Mapped[Cell | None] = relationship(foreign_keys=[to_cell_id], lazy="joined")


class Operation(Base):
    """Операція: тип, кількість, час. Операція — Завдання «фіксує», — Залишок «змінює»."""
    __tablename__ = "operations"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[Decimal] = mapped_column(QTY, default=Decimal("0"))
    time: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    stock_id: Mapped[int | None] = mapped_column(ForeignKey("stock.id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    details: Mapped[str] = mapped_column(String(500), default="")
    stock: Mapped[Stock | None] = relationship(lazy="joined")
    user: Mapped[User | None] = relationship(lazy="joined")


class Ramp(Base):
    """Рампа (FR-4.3)."""
    __tablename__ = "ramps"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))


class Dispatch(Base):
    """Відправлення: номерТТН, sscc, статус. Відправлення [0..*] — Замовлення [1]."""
    __tablename__ = "dispatches"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    ttn_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sscc: Mapped[str] = mapped_column(String(18), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="AWAITING_TTN")
    ramp_id: Mapped[int | None] = mapped_column(ForeignKey("ramps.id"), nullable=True)
    slot_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    packing_list: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    order: Mapped[Order] = relationship(lazy="joined")
    ramp: Mapped[Ramp | None] = relationship(lazy="joined")


class Counterparty(Base):
    """Контрагент (FR-6.1)."""
    __tablename__ = "counterparties"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="CLIENT")  # SUPPLIER | CLIENT | CARRIER


class Rule(Base):
    """Довідник правил (мін. термін придатності, поріг інвентаризації тощо)."""
    __tablename__ = "rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    value: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(300), default="")


class Event(Base):
    """Таблиця подій (outbox) для асинхронної інтеграції."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class JournalEntry(Base):
    """Журнал усіх операцій (FR-6.4)."""
    __tablename__ = "journal"
    id: Mapped[int] = mapped_column(primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_login: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")


class Counter(Base):
    """Лічильники нумерації документів і SSCC."""
    __tablename__ = "counters"
    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class IdempotencyKey(Base):
    """Ключі ідемпотентності для повторної синхронізації офлайн-черги ТЗД (NFR-2.3)."""
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_login: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status_code: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
