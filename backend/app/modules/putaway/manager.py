"""МенеджерРозміщення (UC-02, FR-2.1, FR-2.2) і МенеджерЗалишків (UC-07, FR-2.3)."""
import difflib
from decimal import Decimal

from app.api_deps import Roles
from app.entities import Task, Zone, utcnow
from app.errors import Conflict, Invalid, NotFound
from app.modules.common import D, ManagerBase, cell_dict, num, task_dict


class PutawayManager(ManagerBase):

    def _task(self, label: str) -> Task:
        label = label.strip()
        if label.startswith("(00)"):
            label = label[4:]
        if label.startswith("00") and len(label) == 20:
            label = label[2:]
        task = self.tasks.find_by_label(label, "PUTAWAY") or self.tasks.find(label)
        if task is None or task.type != "PUTAWAY":
            raise NotFound(f"Завдання на розміщення для етикетки {label} не знайдено", code="task_not_found")
        if task.status == "DONE":
            raise Conflict(f"Вантажну одиницю {label} вже розміщено", code="already_done")
        return task

    def list_open(self) -> list[dict]:
        return [task_dict(t) for t in self.tasks.list("PUTAWAY", ("NEW", "IN_PROGRESS", "ESCALATED"))]

    # --- підібратиКомірку(вантаж) ---
    def suggest_cell(self, label: str) -> dict:
        task = self._task(label)
        ln = task.lines[0]
        cell = self.rules.choose_cell(ln.product, D(ln.quantity), ln.batch,
                                      exclude_ids=(ln.from_cell_id,))  # СервісПравил.обратиКомірку
        if cell is None:  # 2а: немає вільної комірки → начальнику складу
            managers = self.dirs.users_with_role(Roles.MANAGER)
            task.status = "ESCALATED"
            task.assignee_id = managers[0].id if managers else None
            task.note = "Немає вільної комірки, що відповідає правилам — передано начальнику складу"
            self.tasks.save(task)
            self.journal.add("Розміщення ескальовано", self.login, task.number)
            self.commit()
            raise Conflict(task.note, code="no_free_cell", task=task.number)
        ln.to_cell_id = cell.id
        task.status = "IN_PROGRESS"
        task.assignee_id = self.user.id if self.user else None
        self.tasks.save(task)
        self.commit()
        return {"task": task.number, "label": task.label, "cell": cell_dict(cell),
                "product_code": ln.product.code, "product_name": ln.product.name,
                "batch": ln.batch.number if ln.batch else None, "quantity": num(ln.quantity)}

    # --- підтвердитиРозміщення(комірка) ---
    def confirm(self, label: str, cell_address: str, confirm_replace: bool = False) -> dict:
        task = self._task(label)
        ln = task.lines[0]
        cell = self.dirs.cell(cell_address)
        if cell is None:
            raise NotFound(f"Комірку {cell_address} не знайдено", code="cell_not_found")
        ok, reason = self.rules.check_cell(cell, ln.product, D(ln.quantity))
        if not ok:
            raise Invalid(reason, code="cell_not_suitable")
        if ln.to_cell_id != cell.id and not confirm_replace:  # 4а
            suggested = ln.to_cell.address if ln.to_cell else None
            raise Conflict(f"Відскановано іншу комірку ({cell.address}) замість {suggested or '—'}. "
                           f"Комірка підходить за правилами — підтвердіть заміну.",
                           code="confirm_replace", suggested=suggested, scanned=cell.address)
        src = self.stock.get(ln.stock_id)
        qty = D(ln.quantity)
        if src is None or D(src.quantity) - D(src.reserved) < qty:
            raise Conflict("Недостатньо залишку в зоні приймання для розміщення", code="no_source_stock")
        self.stock.change(src, -qty)
        dst = self.stock.get_or_create(ln.batch, cell)
        self.stock.change(dst, qty)
        self.op("PUTAWAY", qty, dst, task, details=f"{src.cell.address} → {cell.address}")
        ln.to_cell_id = cell.id
        ln.done_quantity = qty
        ln.status = "DONE"
        task.status = "DONE"
        task.completed_at = utcnow()
        if task.assignee_id is None and self.user:
            task.assignee_id = self.user.id
        self.tasks.save(task)
        self.journal.add("Розміщення підтверджено", self.login, f"{task.number}: {cell.address}")
        self.commit()
        return {"task": task.number, "status": "DONE", "cell": cell.address,
                "message": f"Розміщення підтверджено: {ln.product.code} × {num(qty)} → {cell.address}"}


class StockManager(ManagerBase):
    """МенеджерЗалишків: доступнийЗалишок(товар)."""

    def available(self, query: str) -> dict:
        query = (query or "").strip()
        if not query:
            raise Invalid("Введіть код, GTIN або назву товару", code="empty_query")
        exact = self.dirs.product_by_any(query)
        products = [exact] if exact else self.dirs.search_products(query)
        if not products:  # 1а: пропонуємо схожі позиції
            q = query.casefold()
            scored = []
            for p in self.dirs.all_products():
                words = [p.code.casefold(), *p.name.casefold().replace(",", " ").split()]
                score = max(difflib.SequenceMatcher(None, w, x).ratio()
                            for w in q.split() for x in words)
                if score >= 0.6:
                    scored.append((score, p))
            sugg = [{"code": p.code, "name": p.name, "gtin": p.gtin}
                    for _, p in sorted(scored, key=lambda t: -t[0])[:5]]
            return {"found": False, "message": f"Товар «{query}» не знайдено", "suggestions": sugg,
                    "items": []}
        min_exp = self.rules.min_expiry_date()
        items = []
        for p in products:
            stocks = self.stock.find(p.id)  # РепозиторійЗалишків.знайти(товар)
            batches: dict[int, dict] = {}
            totals = {"quantity": Decimal(0), "reserved": Decimal(0), "available": Decimal(0),
                      "quarantine": Decimal(0), "receiving": Decimal(0)}
            for st in stocks:
                b = st.batch
                sellable = b.expiry_date is None or b.expiry_date >= min_exp
                row = batches.setdefault(b.id, {
                    "batch": b.number, "expiry_date": b.expiry_date, "sellable": sellable,
                    "quantity": Decimal(0), "reserved": Decimal(0), "available": Decimal(0), "cells": []})
                row["quantity"] += D(st.quantity)
                row["reserved"] += D(st.reserved)
                totals["quantity"] += D(st.quantity)
                totals["reserved"] += D(st.reserved)
                avail = Decimal(0)
                if st.cell.zone == Zone.QUARANTINE:
                    totals["quarantine"] += D(st.quantity)
                elif st.cell.zone == Zone.RECEIVING:
                    totals["receiving"] += D(st.quantity)
                elif st.cell.zone in (Zone.STORAGE, Zone.PICKING) and sellable:
                    avail = st.available
                row["available"] += avail
                totals["available"] += avail
                if D(st.quantity):
                    row["cells"].append({"cell": st.cell.address, "zone": st.cell.zone,
                                         "quantity": num(st.quantity), "reserved": num(st.reserved)})
            items.append({
                "product": {"code": p.code, "name": p.name, "gtin": p.gtin, "unit": p.unit},
                **{k: num(v) for k, v in totals.items()},
                "batches": [{**r, "quantity": num(r["quantity"]), "reserved": num(r["reserved"]),
                             "available": num(r["available"])}
                            for r in sorted(batches.values(), key=lambda r: (r["expiry_date"] is None,
                                                                             r["expiry_date"]))
                            if r["quantity"]],
            })
        return {"found": True, "items": items, "min_expiry_date": min_exp,
                "message": "Доступно = залишок − резерв (без карантину, зони приймання і партій з "
                           "недостатнім терміном придатності)"}

    def stock_list(self, zone: str | None = None) -> list[dict]:
        from app.modules.common import stock_dict
        return [stock_dict(st) for st in self.stock.find_all(zone)]
