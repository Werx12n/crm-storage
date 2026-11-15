"""МенеджерЗвітності (control): сформуватиЗвіт(тип, період), розрахуватиKPI(). UC-06, FR-7.

Показники — за табл. 1.1 курсової; вихідні повідомлення — ВП-01…ВП-10 (п. 2 курсової).
"""
from __future__ import annotations

import io
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from app.entities import Zone, utcnow
from app.errors import Conflict, Invalid
from app.modules.common import D, ManagerBase, iso, num
from app.services.barcodes import find_font
from app.services.events import EventTypes

# тип звіту → (код ВП, назва)
REPORTS = {
    "stock": ("ВП-01", "Звіт про залишки товарів"),
    "movement": ("ВП-02", "Звіт про рух товарів за період"),
    "receiving": ("ВП-03", "Акт розбіжностей при прийманні"),
    "inventory": ("ВП-04", "Інвентаризаційний опис і відомість розбіжностей"),
    "productivity": ("ВП-05", "Звіт про продуктивність персоналу"),
    "kpi": ("ВП-06", "Панель KPI складу"),
    "tasks": ("ВП-07", "Завдання на розміщення, відбір і перерахунок"),
    "packing": ("ВП-08", "Пакувальні листи і етикетки SSCC"),
    "erp_files": ("ВП-09", "Файли підтверджених складських операцій для ERP"),
    "delivery": ("ВП-10", "Заявки на відправлення"),
    "abc_xyz": ("FR-7.2", "ABC/XYZ-аналіз номенклатури"),
}

OP_TITLES = {"RECEIPT": "Приймання", "PUTAWAY": "Розміщення", "PICK": "Відбір", "PICK_ERROR": "Помилка відбору",
             "SHIPMENT": "Відвантаження", "COUNT": "Перерахунок", "ADJUSTMENT": "Коригування",
             "REPLENISH": "Поповнення"}
TASK_TITLES = {"PUTAWAY": "Розміщення", "PICK": "Відбір", "COUNT": "Перерахунок", "RECOUNT": "Повторний перерахунок",
               "REPLENISH": "Поповнення"}
LINE_OPS = ("RECEIPT", "PUTAWAY", "PICK", "SHIPMENT", "COUNT", "REPLENISH")  # «оброблені рядки» (KPI 6)
KPI_REFRESH_SECONDS = 300  # ВП-06: оновлення кожні 5 хв
_LINES_RE = re.compile(r"\[lines:([\d,]+)\]")


def _period(start: date | None, end: date | None) -> tuple[datetime, datetime]:
    end = end or date.today()
    start = start or (end - timedelta(days=30))
    if start > end:
        raise Invalid("Початок періоду пізніше за кінець", code="bad_period")
    return datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)


def _line_ids(details: str) -> set[int]:
    m = _LINES_RE.search(details or "")
    return {int(x) for x in m.group(1).split(",") if x} if m else set()


def _hour(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


class ReportsManager(ManagerBase):

    # --- сформуватиЗвіт(тип, період) ---
    def generate(self, type_: str, start: date | None = None, end: date | None = None, costs=None) -> dict:
        if type_ not in REPORTS:
            raise Invalid(f"Невідомий тип звіту {type_}", code="bad_report", types=list(REPORTS))
        t0, t1 = _period(start, end)
        code, title = REPORTS[type_]
        if type_ == "kpi":
            columns, rows = self._r_kpi(start, end, costs)
        else:
            columns, rows = getattr(self, f"_r_{type_}")(t0, t1)
        return {"type": type_, "code": code, "title": f"{code}. {title}",
                "period": {"from": str(t0.date()), "to": str((t1 - timedelta(days=1)).date())},
                "columns": [{"key": k, "title": t} for k, t in columns], "rows": rows,
                "message": None if rows else "За вибраний період немає даних",
                "generated_at": iso(utcnow())}

    # ВП-01
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

    # ВП-02
    def _r_movement(self, t0, t1):
        cols = [("time", "Час"), ("type", "Операція"), ("product_code", "Код"), ("batch", "Партія"),
                ("cell", "Комірка"), ("quantity", "Кількість"), ("user", "Виконавець"), ("details", "Деталі")]
        rows = []
        for op in self.stock.operations(t0, t1):
            st = op.stock
            rows.append({"time": op.time.strftime("%Y-%m-%d %H:%M"), "type": OP_TITLES.get(op.type, op.type),
                         "product_code": st.batch.product.code if st else "", "batch": st.batch.number if st else "",
                         "cell": st.cell.address if st else "", "quantity": num(op.quantity),
                         "user": op.user.login if op.user else "", "details": _LINES_RE.sub("", op.details).strip()})
        return cols, rows

    # ВП-03
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

    # ВП-04: опис (усі пораховані позиції) + різниця
    def _r_inventory(self, t0, t1):
        cols = [("inventory", "Інвентаризація"), ("cell", "Комірка"), ("product_code", "Код"),
                ("product_name", "Товар"), ("batch", "Партія"), ("book", "За обліком"), ("counted", "Фактично"),
                ("difference", "Різниця"), ("result", "Результат")]
        rows = []
        for inv in self.docs.list_inventories():
            if inv.status != "APPROVED" or not inv.approved_at or not (t0 <= inv.approved_at < t1):
                continue
            for ln in (inv.statement or {}).get("lines", []):
                d = ln["difference"] or 0
                rows.append({"inventory": inv.number, **{k: ln.get(k) for k in
                                                         ("cell", "product_code", "product_name", "batch", "book",
                                                          "counted", "difference")},
                             "result": "збіг" if not d else ("надлишок" if d > 0 else "нестача")})
        return cols, rows

    # ВП-05
    def _r_productivity(self, t0, t1):
        cols = [("user", "Працівник"), ("full_name", "ПІБ"), ("receipts", "Приймання"), ("putaways", "Розміщення"),
                ("picks", "Відбір рядків"), ("pick_errors", "Помилки відбору"), ("counts", "Перерахунки"),
                ("shipments", "Відвантаження"), ("hours", "Людино-годин"), ("lines_per_hour", "Рядків/люд-год")]
        key = {"RECEIPT": "receipts", "PUTAWAY": "putaways", "PICK": "picks", "PICK_ERROR": "pick_errors",
               "COUNT": "counts", "SHIPMENT": "shipments", "REPLENISH": "putaways"}
        agg: dict[str, dict] = {}
        hours: dict[str, set] = defaultdict(set)
        for op in self.stock.operations(t0, t1):
            if not op.user or op.type not in key:
                continue
            r = agg.setdefault(op.user.login, {"user": op.user.login, "full_name": op.user.full_name,
                                               **{v: 0 for v in set(key.values())}})
            r[key[op.type]] += 1
            hours[op.user.login].add(_hour(op.time))
        rows = []
        for login, r in sorted(agg.items()):
            h = len(hours[login]) or 1
            lines = r["receipts"] + r["putaways"] + r["picks"] + r["counts"] + r["shipments"]
            rows.append({**r, "hours": h, "lines_per_hour": round(lines / h, 1)})
        return cols, rows

    # ВП-06
    def _r_kpi(self, start, end, costs):
        k = self.kpi(start, end, costs)
        cols = [("title", "Показник"), ("value", "Значення"), ("unit", "Од."), ("target", "Ціль"),
                ("formula", "Формула (табл. 1.1)")]
        return cols, [{c: (x[c] if x[c] is not None else "n/a") for c, _ in cols} for x in k["kpi"]]

    # ВП-07
    def _r_tasks(self, t0, t1):
        cols = [("number", "Завдання"), ("type", "Тип"), ("status", "Статус"), ("assignee", "Виконавець"),
                ("lines", "Рядків"), ("route", "Комірки / маршрут"), ("created_at", "Створено"),
                ("completed_at", "Виконано")]
        rows = []
        for t in self.tasks.created_between(t0, t1, tuple(TASK_TITLES)):
            cells = [ln.to_cell.address if t.type == "PUTAWAY" and ln.to_cell else
                     (ln.from_cell.address if ln.from_cell else "") for ln in t.lines]
            rows.append({"number": t.number, "type": TASK_TITLES[t.type], "status": t.status,
                         "assignee": t.assignee.login if t.assignee else "", "lines": len(t.lines),
                         "route": " → ".join(dict.fromkeys(c for c in cells if c)) or (t.cell.address if t.cell else ""),
                         "created_at": t.created_at.strftime("%Y-%m-%d %H:%M"),
                         "completed_at": t.completed_at.strftime("%Y-%m-%d %H:%M") if t.completed_at else ""})
        return cols, rows

    # ВП-08
    def _r_packing(self, t0, t1):
        cols = [("packing_list", "Пакувальний лист"), ("order", "Замовлення"), ("client", "Клієнт"),
                ("sscc", "SSCC"), ("lines", "Рядків"), ("weight", "Вага, кг"), ("ramp", "Рампа"),
                ("slot", "Слот"), ("ttn", "ТТН"), ("dispatch_id", "№ відправлення")]
        rows = []
        for d in self.docs.dispatches_between(t0, t1):
            pl = d.packing_list or {}
            rows.append({"packing_list": pl.get("number", ""), "order": d.order.number, "client": d.order.client,
                         "sscc": d.sscc, "lines": len(pl.get("lines", [])), "weight": pl.get("total_weight"),
                         "ramp": d.ramp.code if d.ramp else "", "slot": iso(d.slot_start) or "",
                         "ttn": d.ttn_number or "", "dispatch_id": d.id})
        return cols, rows

    # ВП-09
    def _r_erp_files(self, t0, t1):
        cols = [("file_name", "Файл"), ("count", "Операцій"), ("range", "Операції №"), ("generated_at", "Сформовано"),
                ("status", "Статус передачі"), ("processed_at", "Передано в ERP"), ("id", "ID")]
        rows = []
        for e in self.events.by_type(EventTypes.OPERATIONS_FILE, t0, t1):
            p = e.payload
            rows.append({"file_name": p.get("file_name"), "count": p.get("count"),
                         "range": f"{p.get('from_operation')}–{p.get('to_operation')}",
                         "generated_at": p.get("generated_at"), "status": e.status,
                         "processed_at": iso(e.processed_at) or "", "id": e.id})
        return cols, rows

    # ВП-10
    def _r_delivery(self, t0, t1):
        cols = [("request_id", "Заявка"), ("order", "Замовлення"), ("client", "Клієнт"), ("sscc", "SSCC"),
                ("weight", "Вага, кг"), ("ramp", "Рампа"), ("slot", "Слот"), ("status", "Статус заявки"),
                ("attempts", "Спроб"), ("ttn", "ТТН")]
        rows = []
        for e in self.events.by_type(EventTypes.DELIVERY_REQUESTED, t0, t1):
            p = e.payload
            d = self.docs.find_dispatch(p.get("dispatch_id")) if p.get("dispatch_id") else None
            rows.append({"request_id": f"wms-{e.id}", "order": p.get("order_number"), "client": p.get("client"),
                         "sscc": p.get("sscc"), "weight": p.get("weight"), "ramp": p.get("ramp") or "",
                         "slot": p.get("slot_start") or "", "status": e.status, "attempts": e.attempts,
                         "ttn": (d.ttn_number if d else None) or ""})
        return cols, rows

    # FR-7.2 ABC/XYZ
    def _r_abc_xyz(self, t0, t1):
        cols = [("product_code", "Код"), ("product_name", "Товар"), ("shipped", "Відвантажено"),
                ("share", "Частка, %"), ("abc", "ABC"), ("cv", "Коеф. варіації, %"), ("xyz", "XYZ")]
        by_product: dict[str, dict] = {}
        weeks = max(1, (t1 - t0).days // 7)
        for op in self.stock.operations(t0, t1, ("SHIPMENT",)):
            p = op.stock.batch.product
            r = by_product.setdefault(p.code, {"product_code": p.code, "product_name": p.name,
                                               "shipped": Decimal(0), "weekly": [0.0] * weeks})
            r["shipped"] += D(op.quantity)
            r["weekly"][min(weeks - 1, (op.time - t0).days // 7)] += float(op.quantity)
        total = sum((r["shipped"] for r in by_product.values()), Decimal(0))
        rows, cum = [], Decimal(0)
        for r in sorted(by_product.values(), key=lambda r: r["shipped"], reverse=True):
            share = r["shipped"] / total * 100 if total else Decimal(0)
            abc = "A" if cum < 80 else ("B" if cum < 95 else "C")
            cum += share
            mean = statistics.mean(r["weekly"])
            cv = statistics.pstdev(r["weekly"]) / mean * 100 if mean else 0
            rows.append({"product_code": r["product_code"], "product_name": r["product_name"],
                         "shipped": num(r["shipped"]), "share": round(float(share), 1), "abc": abc,
                         "cv": round(cv, 1), "xyz": "X" if cv <= 10 else ("Y" if cv <= 25 else "Z")})
        return cols, rows

    # --- розрахуватиKPI(): показники табл. 1.1 ---
    def kpi(self, start: date | None = None, end: date | None = None, costs=None) -> dict:
        t0, t1 = _period(start, end)
        now = utcnow()
        ops = self.stock.operations(t0, t1)

        def pct(a, b):
            return round(100 * a / b, 1) if b else None

        def avg(xs):
            return round(sum(xs) / len(xs), 2) if xs else None

        # 1. Точність комплектації: безпомилкові рядки / усі рядки × 100 %
        picked_lines, error_lines = set(), set()
        for o in ops:
            if o.type == "PICK":
                picked_lines |= _line_ids(o.details)
            elif o.type == "PICK_ERROR":
                error_lines |= _line_ids(o.details)
        all_lines = picked_lines | error_lines
        picking_accuracy = pct(len(all_lines - error_lines), len(all_lines))

        # 2. Точність обліку запасів: позиції без розбіжностей / перевірені позиції × 100 %
        checked = ok_positions = 0
        for inv in self.docs.list_inventories():
            if inv.statement and inv.approved_at and t0 <= inv.approved_at < t1:
                checked += len(inv.statement["lines"])
                ok_positions += len(inv.statement["lines"]) - len(inv.statement["discrepancies"])

        # 3. OTIF: замовлення вчасно і в повному обсязі / усі замовлення × 100 %
        orders = self.docs.orders_in_period(t0, t1)
        evaluable = [o for o in orders if o.shipped_at or (o.due_at and o.due_at < now)]
        otif = [o for o in evaluable if o.shipped_at and (not o.due_at or o.shipped_at <= o.due_at)
                and all(D(ln.picked) >= D(ln.quantity) for ln in o.lines)]

        # 4. Час виконання замовлення: середній час від реєстрації до відвантаження
        shipped = [o for o in orders if o.shipped_at]
        cycle = [(o.shipped_at - o.created_at).total_seconds() / 3600 for o in shipped]

        # 5. Dock-to-stock: від прибуття товару (перший скан приймання) до розміщення в комірці
        dock, arrival = [], {}
        for t in self.tasks.completed(t0, t1):
            if t.type == "PUTAWAY" and t.shipment_id:
                if t.shipment_id not in arrival:
                    scans = self.docs.scans(t.shipment_id)
                    arrival[t.shipment_id] = scans[0].created_at if scans else None
                if arrival[t.shipment_id]:
                    dock.append((t.completed_at - arrival[t.shipment_id]).total_seconds() / 3600)

        # 6. Продуктивність праці: оброблені рядки / людино-години
        line_ops = [o for o in ops if o.type in LINE_OPS and o.user_id]
        man_hours = len({(o.user_id, _hour(o.time)) for o in line_ops})

        # 7. Використання місткості: зайняті місця / усі місця × 100 %
        occupied, places = self.stock.cell_count_occupied((Zone.STORAGE, Zone.PICKING))

        # 8. Оборотність запасів: відвантаження за період / середній запас
        shipped_qty = sum((D(o.quantity) for o in ops if o.type == "SHIPMENT"), Decimal(0))
        end_stock = self.stock.total_quantity()
        net = Decimal(0)
        for o in ops:
            if o.type == "RECEIPT":
                net += D(o.quantity)
            elif o.type == "SHIPMENT":
                net -= D(o.quantity)
            elif o.type == "ADJUSTMENT":
                net += D(o.quantity)
        avg_stock = (end_stock + (end_stock - net)) / 2
        turnover = round(float(shipped_qty / avg_stock), 4) if avg_stock > 0 else None

        # 9. Вартість обробки замовлення: витрати за період / кількість замовлень
        if costs is None:
            raw = self.dirs.rule("handling_costs_period", "").strip().replace(",", ".")
            try:
                costs = Decimal(raw) if raw else None
            except InvalidOperation:
                costs = None
        cost_per_order = round(float(D(costs) / len(shipped)), 2) if costs is not None and shipped else None

        items = [
            ("picking_accuracy", "Точність комплектації", picking_accuracy, "%", 99.5, "max",
             "безпомилкові рядки / усі рядки × 100 %"),
            ("inventory_accuracy", "Точність обліку запасів", pct(ok_positions, checked), "%", 99, "max",
             "позиції без розбіжностей / перевірені позиції × 100 %"),
            ("otif", "OTIF (вчасно і в повному обсязі)", pct(len(otif), len(evaluable)), "%", 95, "max",
             "замовлення вчасно і в повному обсязі / усі замовлення × 100 %"),
            ("order_cycle_time", "Час виконання замовлення", avg(cycle), "год", 24, "min",
             "середній час від реєстрації до відвантаження"),
            ("dock_to_stock", "Dock-to-stock", avg(dock), "год", 4, "min",
             "середній час від прибуття товару до розміщення в комірці"),
            ("labor_productivity", "Продуктивність праці",
             round(len(line_ops) / man_hours, 1) if man_hours else None, "рядк/люд-год", 60, "max",
             "оброблені рядки / людино-години"),
            ("capacity_utilization", "Використання місткості", pct(occupied, places), "%", 85, "min",
             "зайняті місця / усі місця × 100 %"),
            ("inventory_turnover", "Оборотність запасів", turnover, "раз за період", 1, "max",
             "відвантаження за період / середній запас"),
            ("order_handling_cost", "Вартість обробки замовлення", cost_per_order, "грн/замовл.", None, "min",
             "витрати за період / кількість замовлень (витрати — правило handling_costs_period або параметр costs)"),
        ]
        return {"period": {"from": str(t0.date()), "to": str((t1 - timedelta(days=1)).date())},
                "generated_at": iso(now), "refresh_seconds": KPI_REFRESH_SECONDS,
                "kpi": [{"code": c, "title": t, "value": v, "unit": u, "target": tg, "better": b, "formula": f}
                        for c, t, v, u, tg, b, f in items],
                "counters": {"orders": len(orders), "orders_shipped": len(shipped), "orders_otif": len(otif),
                             "pick_lines": len(all_lines), "pick_error_lines": len(error_lines),
                             "checked_positions": checked, "occupied_places": occupied, "places": places,
                             "man_hours": man_hours, "processed_lines": len(line_ops),
                             "shipped_qty": num(shipped_qty), "avg_stock": num(avg_stock),
                             "events_pending": self.events.count_by_status().get("PENDING", 0),
                             "events_failed": self.events.count_by_status().get("FAILED", 0)}}

    # --- експорт XLSX / PDF ---
    def export_xlsx(self, report: dict) -> bytes:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        wb = Workbook()
        ws = wb.active
        ws.title = report["code"].replace(".", "-")
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
        """PDF з вбудованим TTF-шрифтом DejaVuSans (кирилиця)."""
        from fpdf import FPDF
        font, bold = find_font(), find_font(bold=True)
        if font is None:
            raise Conflict("Не знайдено шрифт з кирилицею для PDF", code="no_pdf_font")
        pdf = FPDF(orientation="L", unit="mm", format="A4")
        pdf.add_font("U", "", font)
        pdf.add_font("U", "B", bold or font)
        pdf.add_page()
        pdf.set_font("U", "B", size=13)
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
