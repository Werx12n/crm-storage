"""МенеджерІнвентаризації (control): створитиПлан(зона), прийнятиРезультат(комірка, кількість),
from __future__ import annotations

затвердитиКоригування(). UC-05, FR-5.1, FR-5.2, BRL-02."""
from datetime import date
from decimal import Decimal

from app.api_deps import Roles
from app.entities import Inventory, Task, TaskLine, utcnow
from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.modules.common import D, ManagerBase, iso, num
from app.services import gs1
from app.services.events import EventTypes

COUNT_TYPES = ("COUNT", "RECOUNT")


class InventoryManager(ManagerBase):

    # --- створитиПлан(зона) ---
    def create_plan(self, zone: str | None = None, cells: list[str] | None = None,
                    threshold=0) -> dict:
        if not zone and not cells:
            raise Invalid("Вкажіть зону або перелік комірок", code="empty_plan")
        if cells:
            selected = []
            for a in cells:
                c = self.dirs.cell(a)
                if c is None:
                    raise NotFound(f"Комірку {a} не знайдено", code="cell_not_found")
                selected.append(c)
        else:
            selected = [c for c in self.dirs.cells(zone) if self.stock.find_in_cell(c.id)]
        if not selected:
            raise Conflict("У вибраній зоні немає комірок із залишками", code="nothing_to_count")
        inv = Inventory(number=self.next_no("INV"), date=date.today(), status="COUNTING",
                        zone=zone, threshold=D(threshold))
        self.docs.save(inv)
        for c in selected:
            if self.tasks.open_tasks_for_cell(c.id, COUNT_TYPES):
                continue  # комірка вже в іншому відкритому перерахунку
            task = Task(number=self.next_no("CNT"), type="COUNT", status="NEW", inventory_id=inv.id, cell_id=c.id)
            for i, st in enumerate(self.stock.find_in_cell(c.id), start=1):
                task.lines.append(TaskLine(seq=i, product_id=st.batch.product_id, batch_id=st.batch_id,
                                           from_cell_id=c.id, stock_id=st.id,
                                           expected_quantity=D(st.quantity)))
            self.tasks.save(task)  # РепозиторійЗавдань.зберегти(завдання)
        self.journal.add("План інвентаризації створено", self.login, f"{inv.number}: {len(selected)} комірок")
        self.commit()
        return self.get(inv.number)

    def _inv(self, number: str) -> Inventory:
        inv = self.docs.find_inventory(number)
        if inv is None:
            raise NotFound(f"Інвентаризацію {number} не знайдено", code="inventory_not_found")
        return inv

    def open_tasks(self) -> list[dict]:
        """Завдання для ТЗД — «сліпий» перерахунок: облікові кількості не показуються."""
        out = []
        for t in self.tasks.list(None, ("NEW", "IN_PROGRESS")):
            if t.type in COUNT_TYPES:
                out.append({"number": t.number, "type": t.type, "cell": t.cell.address if t.cell else None,
                            "products": [{"product_code": ln.product.code, "product_name": ln.product.name,
                                          "batch": ln.batch.number if ln.batch else None,
                                          "status": ln.status} for ln in t.lines]})
        return out

    # --- прийнятиРезультат(комірка, кількість) ---
    def accept_result(self, cell_address: str, quantity, product_code: str | None = None) -> dict:
        cell = self.dirs.cell(cell_address)
        if cell is None:
            raise NotFound(f"Комірку {cell_address} не знайдено", code="cell_not_found")
        open_tasks = self.tasks.open_tasks_for_cell(cell.id, COUNT_TYPES)
        if not open_tasks:
            raise NotFound(f"Для комірки {cell.address} немає завдання на перерахунок", code="no_count_task")
        task = sorted(open_tasks, key=lambda t: (t.type != "RECOUNT", t.id))[0]
        inv = self.docs.find_inventory_by_id(task.inventory_id)
        qty = D(quantity)
        if qty < 0:
            raise Invalid("Кількість не може бути від'ємною", code="bad_quantity")
        pending = [ln for ln in task.lines if ln.status == "NEW"]
        line = None
        if product_code:
            parsed = gs1.parse(product_code)
            product = (self.dirs.product_by_gtin(parsed["gtin"]) if parsed["gtin"]
                       else self.dirs.product_by_any(product_code))
            if product is None:
                raise NotFound("Товар не знайдено", code="unknown_product")
            line = next((ln for ln in pending if ln.product_id == product.id
                         and (not parsed["batch"] or (ln.batch and ln.batch.number == parsed["batch"]))), None)
            if line is None:  # знайдено товар, якого немає в обліку комірки
                batch_no = parsed["batch"]
                batch = self.dirs.batch(product.id, batch_no) if batch_no else None
                if batch is None:
                    raise Invalid("Для неврахованого товару відскануйте GS1-код з номером партії (AI 10)",
                                  code="batch_required")
                line = TaskLine(seq=len(task.lines) + 1, product_id=product.id, batch_id=batch.id,
                                from_cell_id=cell.id, expected_quantity=Decimal(0))
                task.lines.append(line)
                self.s.flush()
        elif len(pending) == 1:
            line = pending[0]
        elif not pending:
            raise Conflict("Усі позиції комірки вже пораховано", code="already_counted")
        else:
            raise Invalid("У комірці кілька позицій — відскануйте товар", code="product_required",
                          products=[ln.product.code for ln in pending])

        st = self.stock.get(line.stock_id) if line.stock_id else None
        book = D(st.quantity) if st else Decimal(0)  # РепозиторійЗалишків.знайти — облікова кількість
        line.expected_quantity = book
        line.counted_quantity = qty
        diff = qty - book
        recount = False
        if task.type == "COUNT" and abs(diff) > D(inv.threshold):  # 4а: повторний перерахунок
            line.status = "RECOUNT"
            recount = True
            rt = next(iter(self.tasks.open_tasks_for_cell(cell.id, ("RECOUNT",))), None)
            if rt is None:
                rt = Task(number=self.next_no("CNT"), type="RECOUNT", status="NEW",
                          inventory_id=inv.id, cell_id=cell.id, note=f"Повторний перерахунок до {task.number}")
            rt.lines.append(TaskLine(seq=len(rt.lines) + 1, product_id=line.product_id, batch_id=line.batch_id,
                                     from_cell_id=cell.id, stock_id=line.stock_id, expected_quantity=book))
            self.tasks.save(rt)
        else:
            line.status = "COUNTED"
        self.op("COUNT", qty, st, task, details=f"{cell.address}: облік {num(book)}, факт {num(qty)}")
        task.status = "IN_PROGRESS"
        task.assignee_id = self.user.id if self.user else None
        if all(ln.status != "NEW" for ln in task.lines):
            task.status = "DONE"
            task.completed_at = utcnow()
        self.tasks.save(task)
        self._refresh_status(inv)
        self.commit()
        return {"task": task.number, "cell": cell.address, "product_code": line.product.code,
                "counted": num(qty), "recount": recount,
                "message": ("Розбіжність понад поріг — створено завдання на повторний перерахунок"
                            if recount else "Результат прийнято")}

    def _refresh_status(self, inv: Inventory) -> None:
        tasks = self.tasks.list(inventory_id=inv.id)
        if inv.status == "COUNTING" and tasks and all(t.status == "DONE" for t in tasks):
            inv.status = "AWAITING_APPROVAL"

    def _final_lines(self, inv: Inventory) -> list[TaskLine]:
        lines = []
        for t in self.tasks.list(inventory_id=inv.id):
            lines += [ln for ln in t.lines if ln.status == "COUNTED"]
        return lines

    def _statement(self, inv: Inventory) -> dict:
        rows = []
        for ln in self._final_lines(inv):
            book, fact = D(ln.expected_quantity), D(ln.counted_quantity)
            rows.append({"cell": ln.from_cell.address if ln.from_cell else None,
                         "product_code": ln.product.code, "product_name": ln.product.name,
                         "batch": ln.batch.number if ln.batch else None, "unit": ln.product.unit,
                         "book": num(book), "counted": num(fact), "difference": num(fact - book)})
        disc = [r for r in rows if r["difference"]]
        return {"number": f"ВР-{inv.number}", "inventory": inv.number, "date": str(inv.date),
                "zone": inv.zone, "lines": rows, "discrepancies": disc,
                "accuracy": round(100 * (len(rows) - len(disc)) / len(rows), 1) if rows else None}

    # --- затвердитиКоригування() ---
    def approve(self, number: str) -> dict:
        if Roles.MANAGER not in (self.user.role_names if self.user else []):  # BRL-02
            raise Forbidden("Коригування затверджує лише начальник складу", code="brl_02")
        inv = self._inv(number)
        if inv.status == "APPROVED":
            raise Conflict("Інвентаризацію вже затверджено", code="already_approved")
        if inv.status != "AWAITING_APPROVAL":
            raise Conflict("Не всі завдання на перерахунок виконано", code="counting_not_finished")
        adjustments = []
        for ln in self._final_lines(inv):
            diff = D(ln.counted_quantity) - D(ln.expected_quantity)
            if diff == 0:
                continue
            st = self.stock.get(ln.stock_id) if ln.stock_id else self.stock.get_or_create(ln.batch, ln.from_cell)
            if D(st.quantity) + diff < 0:
                diff = -D(st.quantity)
            self.stock.change(st, diff)  # змінити(залишок, різниця)
            if D(st.reserved) > D(st.quantity):
                st.reserved = st.quantity
            self.op("ADJUSTMENT", diff, st, details=f"Інвентаризація {inv.number}")
            adjustments.append({"cell": st.cell.address, "product_code": st.batch.product.code,
                                "batch": st.batch.number, "difference": num(diff)})
        statement = self._statement(inv)
        statement["approved_by"] = self.login
        inv.statement = statement
        inv.status = "APPROVED"
        inv.approved_by = self.login
        inv.approved_at = utcnow()
        if adjustments:
            self.publisher.publish(EventTypes.STOCK_ADJUSTED, {"inventory": inv.number, "lines": adjustments})
        self.journal.add("Коригування затверджено", self.login, f"{inv.number}: {len(adjustments)} коригувань")
        self.commit()
        return statement

    def list(self) -> list[dict]:
        return [{"number": i.number, "date": i.date, "status": i.status, "zone": i.zone,
                 "threshold": num(i.threshold), "approved_by": i.approved_by,
                 "approved_at": iso(i.approved_at)} for i in self.docs.list_inventories()]

    def get(self, number: str) -> dict:
        inv = self._inv(number)
        tasks = self.tasks.list(inventory_id=inv.id)
        return {"number": inv.number, "date": inv.date, "status": inv.status, "zone": inv.zone,
                "threshold": num(inv.threshold), "approved_by": inv.approved_by,
                "tasks": [{"number": t.number, "type": t.type, "status": t.status,
                           "cell": t.cell.address if t.cell else None,
                           "lines": [{"product_code": ln.product.code, "batch": ln.batch.number if ln.batch else None,
                                      "book": num(ln.expected_quantity), "counted": num(ln.counted_quantity),
                                      "status": ln.status} for ln in t.lines]} for t in tasks],
                "statement": inv.statement or (self._statement(inv) if inv.status != "COUNTING" else None)}
