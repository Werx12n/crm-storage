"""МенеджерЗвітності (control): сформуватиЗвіт(тип, період), розрахуватиKPI(). UC-06, FR-7.

Нумерація звітів ВП-01…ВП-06 (вихідні повідомлення курсової): ВП-01 залишки, ВП-02 рух товарів,
ВП-03 акти розбіжностей приймання, ВП-04 відомості інвентаризації, ВП-05 продуктивність, ВП-06 ABC/XYZ.
"""
import io
import os
import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.entities import Zone, utcnow
from app.errors import Conflict, Invalid
from app.modules.common import D, ManagerBase, iso, num

REPORTS = {
    "stock": ("ВП-01", "Залишки «товар — партія — комірка»"),
    "movement": ("ВП-02", "Рух товарів (операції)"),
    "receiving": ("ВП-03", "Акти розбіжностей приймання"),
    "inventory": ("ВП-04", "Відомості розбіжностей інвентаризації"),
    "productivity": ("ВП-05", "Продуктивність персоналу"),
    "abc_xyz": ("ВП-06", "ABC/XYZ-аналіз номенклатури"),
}

OP_TITLES = {"RECEIPT": "Приймання", "PUTAWAY": "Розміщення", "PICK": "Відбір", "PICK_ERROR": "Помилка відбору",
             "SHIPMENT": "Відвантаження", "COUNT": "Перерахунок", "ADJUSTMENT": "Коригування",
             "REPLENISH": "Поповнення"}

FONT_CANDIDATES = [
    os.environ.get("PDF_FONT", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]


def _period(start: date | None, end: date | None) -> tuple[datetime, datetime]:
    end = end or date.today()
    start = start or (end - timedelta(days=30))
    if start > end:
        raise Invalid("Початок періоду пізніше за кінець", code="bad_period")
    return datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)


class ReportsManager(ManagerBase):

    # --- сформуватиЗвіт(тип, період) ---
    def generate(self, type_: str, start: date | None = None, end: date | None = None) -> dict:
        if type_ not in REPORTS:
            raise Invalid(f"Невідомий тип звіту {type_}", code="bad_report", types=list(REPORTS))
        t0, t1 = _period(start, end)
        code, title = REPORTS[type_]
        columns, rows = getattr(self, f"_r_{type_}")(t0, t1)
        return {"type": type_, "code": code, "title": f"{code}. {title}",
                "period": {"from": str(t0.date()), "to": str((t1 - timedelta(days=1)).date())},
                "columns": [{"key": k, "title": t} for k, t in columns], "rows": rows,
                "message": None if rows else "За вибраний період немає даних",
                "generated_at": iso(utcnow())}

    def _r_stock(self, t0, t1):
        cols = [("cell", "Комірка"), ("zone", "Зона"), ("product_code", "Код"), ("product_name", "Товар"),
                ("batch", "Партія"), ("expiry_date", "Придатний до"), ("quantity", "Кількість"),
                ("reserved", "Резерв"), ("available", "Доступно")]
        rows = [{"cell": st.cell.address, "zone": st.cell.zone, "product_code": st.batch.product.code,
                 "product_name": st.batch.product.name, "batch": st.batch.number,
                 "expiry_date": str(st.batch.expiry_date or ""), "quantity": num(st.quantity),
                 "reserved": num(st.reserved), "available": num(st.available)}
                for st in self.stock.find_all()]
        return cols, rows

    def _r_movement(self, t0, t1):
        cols = [("time", "Час"), ("type", "Операція"), ("product_code", "Код"), ("batch", "Партія"),
                ("cell", "Комірка"), ("quantity", "Кількість"), ("user", "Виконавець"), ("details", "Деталі")]
        rows = []
        for op in self.stock.operations(t0, t1):
            st = op.stock
            rows.append({"time": op.time.strftime("%Y-%m-%d %H:%M"), "type": OP_TITLES.get(op.type, op.type),
                         "product_code": st.batch.product.code if st else "", "batch": st.batch.number if st else "",
                         "cell": st.cell.address if st else "", "quantity": num(op.quantity),
                         "user": op.user.login if op.user else "", "details": op.details})
        return cols, rows

    def _r_receiving(self, t0, t1):
        cols = [("act", "Акт"), ("asn", "ASN"), ("supplier", "Постачальник"), ("product_code", "Код"),
                ("product_name", "Товар"), ("expected", "Очікувано"), ("accepted", "Прийнято"),
                ("difference", "Різниця"), ("kind", "Тип")]
        rows = []
        for sh in self.docs.shipments_completed(t0, t1):
            act = sh.discrepancy_act
            for ln in (act or {}).get("lines", []):
                rows.append({"act": act["number"], "asn": sh.asn_number, "supplier": sh.supplier, **{
                    k: ln[k] for k in ("product_code", "product_name", "expected", "accepted", "difference", "kind")}})
        return cols, rows

    def _r_inventory(self, t0, t1):
        cols = [("inventory", "Інвентаризація"), ("cell", "Комірка"), ("product_code", "Код"),
                ("batch", "Партія"), ("book", "Облік"), ("counted", "Факт"), ("difference", "Різниця")]
        rows = []
        for inv in self.docs.list_inventories():
            if inv.status != "APPROVED" or not inv.approved_at or not (t0 <= inv.approved_at < t1):
                continue
            for ln in (inv.statement or {}).get("discrepancies", []):
                rows.append({"inventory": inv.number, **{k: ln[k] for k in
                                                         ("cell", "product_code", "batch", "book", "counted",
                                                          "difference")}})
        return cols, rows

    def _r_productivity(self, t0, t1):
        cols = [("user", "Працівник"), ("full_name", "ПІБ"), ("receipts", "Приймання"), ("putaways", "Розміщення"),
                ("picks", "Відбір рядків"), ("pick_errors", "Помилки відбору"), ("counts", "Перерахунки"),
                ("shipments", "Відвантаження"), ("hours", "Активних годин"), ("ops_per_hour", "Операцій/год")]
        agg: dict[str, dict] = {}
        hours: dict[str, set] = defaultdict(set)
        key = {"RECEIPT": "receipts", "PUTAWAY": "putaways", "PICK": "picks", "PICK_ERROR": "pick_errors",
               "COUNT": "counts", "SHIPMENT": "shipments"}
        for op in self.stock.operations(t0, t1):
            if not op.user or op.type not in key:
                continue
            r = agg.setdefault(op.user.login, {"user": op.user.login, "full_name": op.user.full_name,
                                               **{v: 0 for v in key.values()}})
            r[key[op.type]] += 1
            hours[op.user.login].add(op.time.replace(minute=0, second=0, microsecond=0))
        rows = []
        for login, r in sorted(agg.items()):
            h = len(hours[login]) or 1
            total = sum(r[v] for v in key.values())
            rows.append({**r, "hours": h, "ops_per_hour": round(total / h, 1)})
        return cols, rows

    def _r_abc_xyz(self, t0, t1):
        cols = [("product_code", "Код"), ("product_name", "Товар"), ("shipped", "Відвантажено"),
                ("share", "Частка, %"), ("abc", "ABC"), ("cv", "Коеф. варіації"), ("xyz", "XYZ")]
        by_product: dict[str, dict] = {}
        weeks = max(1, (t1 - t0).days // 7)
        for op in self.stock.operations(t0, t1, ("SHIPMENT",)):
            p = op.stock.batch.product
            r = by_product.setdefault(p.code, {"product_code": p.code, "product_name": p.name,
                                               "shipped": Decimal(0), "weekly": [0.0] * weeks})
            r["shipped"] += D(op.quantity)
            w = min(weeks - 1, (op.time - t0).days // 7)
            r["weekly"][w] += float(op.quantity)
        total = sum((r["shipped"] for r in by_product.values()), Decimal(0))
        rows, cum = [], Decimal(0)
        for r in sorted(by_product.values(), key=lambda r: r["shipped"], reverse=True):
            share = r["shipped"] / total * 100 if total else Decimal(0)
            cum += share
            abc = "A" if cum - share < 80 else ("B" if cum - share < 95 else "C")
            mean = statistics.mean(r["weekly"])
            cv = statistics.pstdev(r["weekly"]) / mean * 100 if mean else 0
            xyz = "X" if cv <= 10 else ("Y" if cv <= 25 else "Z")
            rows.append({"product_code": r["product_code"], "product_name": r["product_name"],
                         "shipped": num(r["shipped"]), "share": round(float(share), 1), "abc": abc,
                         "cv": round(cv, 1), "xyz": xyz})
        return cols, rows

    # --- розрахуватиKPI() ---
    def kpi(self, start: date | None = None, end: date | None = None) -> dict:
        t0, t1 = _period(start, end)
        ops = self.stock.operations(t0, t1)
        picks = sum(1 for o in ops if o.type == "PICK")
        errors = sum(1 for o in ops if o.type == "PICK_ERROR")
        orders = self.docs.orders_in_period(t0, t1)
        shipped = [o for o in orders if o.shipped_at]
        cycle = [(o.shipped_at - o.created_at).total_seconds() / 3600 for o in shipped]
        perfect = [o for o in shipped if all(D(ln.picked) >= D(ln.quantity) for ln in o.lines)]
        shipments = self.docs.shipments_completed(t0, t1)
        with_disc = [s for s in shipments if s.discrepancy_act]
        dock = []
        for t in self.tasks.completed(t0, t1):
            if t.type == "PUTAWAY" and t.shipment_id:
                sh = self.docs.get_shipment(t.shipment_id)
                if sh and sh.completed_at:
                    dock.append((t.completed_at - sh.completed_at).total_seconds() / 3600)
        inv_lines = inv_ok = 0
        for inv in self.docs.list_inventories():
            if inv.statement and inv.approved_at and t0 <= inv.approved_at < t1:
                inv_lines += len(inv.statement["lines"])
                inv_ok += len(inv.statement["lines"]) - len(inv.statement["discrepancies"])
        load = capacity = Decimal(0)
        summary = self.stock.cell_summary()
        for c in self.dirs.cells(Zone.STORAGE):
            capacity += D(c.capacity)
            load += summary.get(c.id, {}).get("load", Decimal(0))
        active_hours = len({o.time.replace(minute=0, second=0, microsecond=0) for o in ops if o.type == "PICK"}) or 1
        open_orders = len(self.docs.list_orders(("NEW", "RESERVED", "PARTIAL", "IN_PICKING", "PICKED")))
        events = self.events.count_by_status()

        def pct(a, b):
            return round(100 * a / b, 1) if b else None

        def avg(xs):
            return round(sum(xs) / len(xs), 2) if xs else None

        items = [
            ("picking_accuracy", "Точність відбору", pct(picks, picks + errors), "%", 99.5),
            ("perfect_orders", "Ідеальні замовлення (повністю зібрані)", pct(len(perfect), len(shipped)), "%", 98),
            ("order_cycle_time", "Час виконання замовлення", avg(cycle), "год", 24),
            ("dock_to_stock", "Dock-to-stock (приймання → розміщення)", avg(dock), "год", 4),
            ("receiving_discrepancy_rate", "Поставки з розбіжностями", pct(len(with_disc), len(shipments)), "%", 5),
            ("inventory_accuracy", "Точність залишків (інвентаризація)", pct(inv_ok, inv_lines), "%", 99),
            ("storage_utilization", "Заповненість зони зберігання", pct(load, capacity), "%", 85),
            ("pick_lines_per_hour", "Рядків відбору за годину", round(picks / active_hours, 1) if picks else None,
             "рядк/год", 60),
        ]
        return {"period": {"from": str(t0.date()), "to": str((t1 - timedelta(days=1)).date())},
                "generated_at": iso(utcnow()),
                "kpi": [{"code": c, "title": t, "value": v, "unit": u, "target": tg} for c, t, v, u, tg in items],
                "counters": {"orders_shipped": len(shipped), "orders_open": open_orders,
                             "shipments_received": len(shipments), "pick_lines": picks, "pick_errors": errors,
                             "events_pending": events.get("PENDING", 0), "events_failed": events.get("FAILED", 0)}}

    # --- експорт XLSX / PDF ---
    def export_xlsx(self, report: dict) -> bytes:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        wb = Workbook()
        ws = wb.active
        ws.title = report["code"]
        ws.append([report["title"]])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append([f"Період: {report['period']['from']} — {report['period']['to']}"])
        ws.append([])
        ws.append([c["title"] for c in report["columns"]])
        for cell in ws[4]:
            cell.font = Font(bold=True)
        for r in report["rows"]:
            ws.append([r.get(c["key"]) for c in report["columns"]])
        if not report["rows"]:
            ws.append([report["message"]])
        for i, c in enumerate(report["columns"], start=1):
            ws.column_dimensions[ws.cell(row=4, column=i).column_letter].width = max(12, len(c["title"]) + 4)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def export_pdf(self, report: dict) -> bytes:
        from fpdf import FPDF
        font = next((f for f in FONT_CANDIDATES if f and os.path.exists(f)), None)
        if font is None:
            raise Conflict("Не знайдено шрифт з кирилицею для PDF (встановіть DejaVuSans або задайте PDF_FONT)",
                           code="no_pdf_font")
        pdf = FPDF(orientation="L", unit="mm", format="A4")
        pdf.add_font("U", "", font)
        pdf.add_font("U", "B", font)
        pdf.add_page()
        pdf.set_font("U", size=13)
        pdf.cell(0, 8, report["title"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("U", size=9)
        pdf.cell(0, 6, f"Період: {report['period']['from']} — {report['period']['to']}",
                 new_x="LMARGIN", new_y="NEXT")
        if not report["rows"]:
            pdf.cell(0, 8, report["message"], new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("U", size=7 if len(report["columns"]) > 7 else 8)
            with pdf.table() as table:
                hdr = table.row()
                for c in report["columns"]:
                    hdr.cell(c["title"])
                for r in report["rows"]:
                    row = table.row()
                    for c in report["columns"]:
                        v = r.get(c["key"])
                        row.cell("" if v is None else str(v))
        return bytes(pdf.output())
