"""Демо-дані (узагальнені, без прив'язки до реальної компанії): товари, комірки, партії, залишки,
користувачі з ролями, контрагенти, правила, рампи, ASN і замовлення.

Запуск: python -m app.seed  (застосовує міграції Alembic і заповнює порожню БД)."""
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db
from app.api_deps import ROLE_TITLES, Roles
from app.entities import Batch, Cell, Counterparty, Product, Ramp, Role, Rule, Stock, User, Zone
from app.security import hash_password
from app.services.gs1 import make_gtin13

DEMO_PASSWORD = "demo123"
GTIN_PREFIX = "4820000"  # узагальнений префікс для демо (482 — GS1 Україна)

PRODUCTS = [
    # код, назва, од., вага кг, ABC, мін. рівень у зоні відбору
    ("P-001", "Молоко ультрапастеризоване 2,5% 1 л", "шт", "1.05", "A", 20),
    ("P-002", "Кефір 1% 900 г", "шт", "0.95", "A", 0),
    ("P-003", "Йогурт питний 2% 500 г", "шт", "0.52", "B", 0),
    ("P-004", "Сир твердий 50% 200 г", "шт", "0.21", "B", 0),
    ("P-005", "Масло вершкове 82% 180 г", "шт", "0.19", "A", 0),
    ("P-006", "Вода мінеральна 1,5 л", "шт", "1.55", "A", 0),
    ("P-007", "Сік яблучний 1 л", "шт", "1.08", "B", 0),
    ("P-008", "Печиво вівсяне 300 г", "шт", "0.31", "C", 0),
    ("P-009", "Кава мелена 250 г", "шт", "0.26", "C", 0),
    ("P-010", "Засіб для миття посуду 500 мл", "шт", "0.55", "C", 0),
    ("P-011", "Папір туалетний, 4 рулони", "уп", "0.40", "C", 0),
    ("P-012", "Крупа гречана 1 кг", "шт", "1.00", "B", 0),
]

USERS = [
    ("admin", "Адміністратор Системи", [Roles.ADMIN]),
    ("manager", "Петренко Олена (начальник складу)", [Roles.MANAGER]),
    ("accountant", "Коваль Ірина (бухгалтер)", [Roles.ACCOUNTANT]),
    ("sales", "Мельник Андрій (менеджер з продажу)", [Roles.SALES]),
    ("receiver", "Шевчук Тарас (комірник-приймальник)", [Roles.RECEIVER]),
    ("driver", "Бондар Сергій (водій навантажувача)", [Roles.FORKLIFT]),
    ("picker", "Кравець Марія (комплектувальник)", [Roles.PICKER]),
    ("packer", "Ткаченко Дмитро (контролер-пакувальник)", [Roles.PACKER]),
    ("counter", "Лисенко Наталія (працівник складу)", [Roles.WORKER]),
    ("erp", "Інтеграція ERP/EDI", [Roles.INTEGRATION]),
]

PERMISSIONS = {
    Roles.ADMIN: "довідники, користувачі, ролі, журнал, інтеграція",
    Roles.MANAGER: "усі складські операції, план і затвердження інвентаризації, звіти, довідники",
    Roles.ACCOUNTANT: "звіти, KPI, залишки",
    Roles.SALES: "доступні залишки",
    Roles.RECEIVER: "приймання (ТЗД)",
    Roles.FORKLIFT: "розміщення, поповнення (ТЗД)",
    Roles.PICKER: "відбір (ТЗД)",
    Roles.PACKER: "контроль комплектності, відвантаження (ТЗД)",
    Roles.WORKER: "перерахунок (ТЗД)",
    Roles.INTEGRATION: "API обміну ERP / EDI / доставка",
}


def gtin(i: int) -> str:
    return make_gtin13(GTIN_PREFIX, i).zfill(14)


def seed(s: Session, with_documents: bool = True) -> bool:
    if s.scalar(select(User).limit(1)) is not None:
        return False
    today = date.today()
    roles = {}
    for name, title in ROLE_TITLES.items():
        roles[name] = Role(name=name, title=title, permissions=PERMISSIONS.get(name, ""))
        s.add(roles[name])
    pw = hash_password(DEMO_PASSWORD)
    for login, full_name, rs in USERS:
        s.add(User(login=login, full_name=full_name, password_hash=pw, roles=[roles[r] for r in rs]))

    products = {}
    for i, (code, name, unit, w, abc, minlvl) in enumerate(PRODUCTS, start=1):
        products[code] = Product(code=code, name=name, gtin=gtin(i), unit=unit, weight=Decimal(w),
                                 abc_class=abc, min_pick_level=Decimal(minlvl))
        s.add(products[code])

    cells = {}

    def cell(addr, zone, cap, abc=None, aisle=0, rack=0, level=1):
        cells[addr] = Cell(address=addr, zone=zone, capacity=Decimal(cap), abc_class=abc, aisle=aisle,
                           rack=rack, level=level)
        s.add(cells[addr])

    cell("RCV-01", Zone.RECEIVING, 20000)
    cell("RCV-02", Zone.RECEIVING, 20000)
    cell("QRT-01", Zone.QUARANTINE, 5000)
    cell("SHP-01", Zone.SHIPPING, 20000)
    cell("SHP-02", Zone.SHIPPING, 20000)
    for r in range(1, 7):
        cell(f"PK-00-{r:02d}", Zone.PICKING, 300, "A", 0, r, 1)
    abc_by_aisle = {1: "A", 2: "A", 3: "B", 4: "C"}
    for a in range(1, 5):
        for r in range(1, 7):
            for lv in (1, 2):
                cell(f"ST-{a:02d}-{r:02d}-{lv}", Zone.STORAGE, 800, abc_by_aisle[a], a, r, lv)
    s.flush()

    def stock(code, batch_no, days, addr, qty):
        p = products[code]
        b = s.scalar(select(Batch).where(Batch.product_id == p.id, Batch.number == batch_no))
        if b is None:
            b = Batch(product_id=p.id, number=batch_no,
                      expiry_date=(today + timedelta(days=days)) if days is not None else None)
            s.add(b)
            s.flush()
        s.add(Stock(batch_id=b.id, cell_id=cells[addr].id, quantity=Decimal(qty), reserved=Decimal(0)))

    stock("P-001", "L2611A", 20, "ST-01-01-1", 60)    # короткий термін — не резервується (BRL-03)
    stock("P-001", "L2612B", 75, "ST-01-02-1", 200)
    stock("P-001", "L2701C", 120, "ST-01-03-1", 240)
    stock("P-001", "L2612B", 75, "PK-00-01", 30)
    stock("P-002", "K2612A", 45, "ST-01-04-1", 150)
    stock("P-003", "Y2701A", 60, "ST-03-01-1", 180)
    stock("P-004", "C2703A", 150, "ST-03-02-1", 120)
    stock("P-005", "M2702A", 90, "ST-02-01-1", 300)
    stock("P-006", "W2801A", 365, "ST-02-02-1", 240)
    stock("P-006", "W2802B", 400, "ST-02-03-1", 240)
    stock("P-007", "J2709A", 240, "ST-03-03-1", 150)
    stock("P-008", "B2705A", 180, "ST-04-01-1", 200)
    stock("P-009", "F2801A", 360, "ST-04-02-1", 100)
    stock("P-010", "D-001", None, "ST-04-03-1", 120)
    stock("P-011", "T-001", None, "ST-04-04-1", 200)
    stock("P-012", "G2801A", 300, "ST-03-04-1", 250)

    for code, name, kind in [("SUP-001", "Постачальник молочної продукції", "SUPPLIER"),
                             ("SUP-002", "Постачальник бакалії", "SUPPLIER"),
                             ("CL-001", "Мережа магазинів «Клієнт 1»", "CLIENT"),
                             ("CL-002", "Інтернет-магазин «Клієнт 2»", "CLIENT"),
                             ("CAR-001", "Служба доставки (mock)", "CARRIER")]:
        s.add(Counterparty(code=code, name=name, kind=kind))
    for code, value, desc in [("min_shelf_days", "30", "BRL-03: мінімальний залишковий термін придатності, днів"),
                              ("inventory_threshold", "2", "Поріг розбіжності для повторного перерахунку, од."),
                              ("order_lead_hours", "24", "KPI OTIF: нормативний строк виконання замовлення, год"),
                              ("handling_costs_period", "", "KPI 9: витрати складу за період, грн (вводяться вручну)"),
                              ("putaway_strategy", "zone,capacity,abc,consolidation",
                               "FR-2.1: порядок правил вибору комірки")]:
        s.add(Rule(code=code, value=value, description=desc))
    s.add(Ramp(code="R1", name="Рампа 1"))
    s.add(Ramp(code="R2", name="Рампа 2"))
    s.commit()

    if with_documents:
        _demo_documents(s)
    return True


def _demo_documents(s: Session) -> None:
    from app.modules.picking.manager import PickingManager
    from app.modules.receiving.manager import ReceivingManager
    erp = s.scalar(select(User).where(User.login == "erp"))
    today = date.today()
    ReceivingManager(s, erp).register_asn({
        "asn_number": "ASN-0001", "date": today, "supplier": "Постачальник молочної продукції",
        "lines": [{"gtin": gtin(1), "quantity": 100, "batch_number": "L2702D", "expiry_date": today + timedelta(days=90)},
                  {"gtin": gtin(5), "quantity": 50, "batch_number": "M2703B", "expiry_date": today + timedelta(days=100)},
                  {"gtin": gtin(2), "quantity": 40, "batch_number": "K2701B", "expiry_date": today + timedelta(days=40)}]})
    ReceivingManager(s, erp).register_asn({
        "asn_number": "ASN-0002", "date": today, "supplier": "Постачальник бакалії",
        "lines": [{"gtin": gtin(8), "quantity": 60, "batch_number": "B2708B"},
                  {"gtin": gtin(12), "quantity": 80, "batch_number": "G2803B"}]})
    pm = PickingManager(s, erp)
    pm.accept_order({"number": "ORD-1001", "client": "Мережа магазинів «Клієнт 1»",
                     "lines": [{"product_code": "P-001", "quantity": 40}, {"product_code": "P-006", "quantity": 12},
                               {"product_code": "P-008", "quantity": 10}]})
    pm.accept_order({"number": "ORD-1002", "client": "Інтернет-магазин «Клієнт 2»",
                     "lines": [{"product_code": "P-005", "quantity": 20}, {"product_code": "P-012", "quantity": 5}]},
                    create_task=False)
    pm.accept_order({"number": "ORD-1003", "client": "Інтернет-магазин «Клієнт 2»",
                     "lines": [{"product_code": "P-003", "quantity": 15}, {"product_code": "P-009", "quantity": 4}]},
                    create_task=False)


def upgrade_schema() -> None:
    from alembic import command
    from alembic.config import Config
    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")


def main() -> None:
    upgrade_schema()
    with db.SessionLocal() as s:
        created = seed(s, with_documents="--no-docs" not in sys.argv)
    print("Демо-дані створено" if created else "БД уже містить дані — сід пропущено")


if __name__ == "__main__":
    main()
