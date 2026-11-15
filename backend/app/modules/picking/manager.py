"""МенеджерКомплектації (control): прийнятиЗамовлення(замовлення), сформуватиЗавдання(),
from __future__ import annotations

отриматиЗавдання(виконавець), підтвердитиВідбір(код). FR-3.1…FR-3.4, UC-03."""
from decimal import Decimal

from app.entities import Order, OrderLine, Reservation, Task, TaskLine, Zone, utcnow
from app.errors import Conflict, Invalid, NotFound
from app.modules.common import D, ManagerBase, num, task_dict
from app.services import gs1
from app.services.events import EventTypes
from app.services.rules import RulesService

OPEN = ("NEW", "IN_PROGRESS")


def order_dict(o: Order) -> dict:
    return {"number": o.number, "client": o.client, "status": o.status, "wave": o.wave,
            "created_at": o.created_at, "picked_at": o.picked_at, "shipped_at": o.shipped_at,
            "partial": any(D(ln.reserved) < D(ln.quantity) for ln in o.lines),
            "lines": [{"id": ln.id, "product_code": ln.product.code, "product_name": ln.product.name,
                       "gtin": ln.product.gtin, "unit": ln.product.unit, "quantity": num(ln.quantity),
                       "reserved": num(ln.reserved), "picked": num(ln.picked), "checked": num(ln.checked)}
                      for ln in o.lines]}


class PickingManager(ManagerBase):

    # --- прийнятиЗамовлення(замовлення): викликає ШлюзERP ---
    def accept_order(self, data: dict, create_task: bool = True) -> dict:
        number = data["number"].strip()
        if self.docs.find_order(number):
            raise Conflict(f"Замовлення {number} вже отримано", code="duplicate_order")
        if not data.get("lines"):
            raise Invalid("Замовлення не містить рядків", code="empty_order")
        order = Order(number=number, client=data.get("client", ""), status="NEW")
        for raw in data["lines"]:
            key = raw.get("product_code") or raw.get("gtin") or ""
            product = self.dirs.product_by_any(key)
            if product is None:
                raise Invalid(f"Товар {key} відсутній у довіднику", code="unknown_product")
            if D(raw["quantity"]) <= 0:
                raise Invalid("Кількість у рядку замовлення має бути > 0", code="bad_quantity")
            order.lines.append(OrderLine(product=product, product_id=product.id, quantity=D(raw["quantity"])))
        self.docs.save(order)
        partial = False
        for ln in order.lines:  # резервування за FEFO (BRL-01, BRL-03)
            reserved = Decimal(0)
            for st, take in self.rules.choose_batches_fefo(ln.product_id, D(ln.quantity)):
                self.stock.reserve(st, take)  # РепозиторійЗалишків.зарезервувати(партія, кількість)
                self.stock.add_reservation(Reservation(order_line_id=ln.id, stock_id=st.id, quantity=take))
                reserved += take
            ln.reserved = reserved
            partial = partial or reserved < D(ln.quantity)
        order.status = "PARTIAL" if partial else "RESERVED"
        self.publisher.publish(EventTypes.ORDER_STATUS, {  # 2а: ERP отримує статус «частково»
            "order_number": order.number, "status": "частково" if partial else "зарезервовано",
            "code": order.status,
            "lines": [{"product_code": ln.product.code, "quantity": num(ln.quantity),
                       "reserved": num(ln.reserved)} for ln in order.lines]})
        self.journal.add("Замовлення прийнято", self.login, f"{number}: {order.status}")
        result_tasks = []
        if create_task:
            result_tasks = self._form_tasks([order], wave=False)
        self.commit()
        res = order_dict(order)
        res["tasks"] = [t.number for t in result_tasks]
        return res

    # --- сформуватиЗавдання() (FR-3.2: хвилі) ---
    def form_tasks(self, order_numbers: list[str] | None = None, wave: bool = True) -> dict:
        if order_numbers:
            orders = []
            for n in order_numbers:
                o = self.docs.find_order(n)
                if o is None:
                    raise NotFound(f"Замовлення {n} не знайдено", code="order_not_found")
                orders.append(o)
        else:
            orders = self.docs.list_orders(("RESERVED", "PARTIAL"))
        orders = [o for o in orders if o.status in ("RESERVED", "PARTIAL")]
        if not orders:
            raise Conflict("Немає зарезервованих замовлень без завдань", code="nothing_to_wave")
        tasks = self._form_tasks(orders, wave=wave)
        self.commit()
        return {"wave": tasks[0].wave if tasks and wave else None,
                "orders": [o.number for o in orders], "tasks": [task_dict(t) for t in tasks]}

    def _form_tasks(self, orders: list[Order], wave: bool) -> list[Task]:
        groups = [orders] if wave else [[o] for o in orders]
        wave_no = self.next_no("WAVE") if wave else None
        created = []
        for group in groups:
            res = self.stock.reservations([ln.id for o in group for ln in o.lines], unassigned_only=True)
            if not res:
                continue
            task = Task(number=self.next_no("PICK"), type="PICK", status="NEW", wave=wave_no,
                        order_id=group[0].id if len(group) == 1 else None)
            lines = []
            for r in res:
                lines.append((r, TaskLine(product_id=r.order_line.product_id, batch_id=r.stock.batch_id,
                                          from_cell_id=r.stock.cell_id, stock_id=r.stock_id,
                                          order_line_id=r.order_line_id, quantity=r.quantity)))
            # FR-3.3: оптимальний маршрут обходу комірок
            ordered = self.rules.build_route(lines, lambda pair: pair[0].stock.cell)
            for i, (r, tl) in enumerate(ordered, start=1):
                tl.seq = i
                task.lines.append(tl)
            self.tasks.save(task)
            for r, tl in ordered:
                r.task_line_id = tl.id
            for o in group:
                o.status = "IN_PICKING"
                o.wave = wave_no
            created.append(task)
        return created

    # --- отриматиЗавдання(виконавець) ---
    def get_task(self) -> dict:
        mine = [t for t in self.tasks.list("PICK", ("IN_PROGRESS",), assignee_id=self.user.id)]
        task = mine[0] if mine else next(iter(self.tasks.list("PICK", ("NEW",))), None)
        if task is None:
            return {"task": None, "message": "Немає завдань на відбір"}
        if task.status == "NEW":
            task.status = "IN_PROGRESS"
            task.assignee_id = self.user.id
            self.tasks.save(task)
            self.commit()
        return {"task": self._task_view(task)}

    def _task_view(self, task: Task) -> dict:
        d = task_dict(task)
        racks = max([c.rack for c in self.dirs.cells()] + [1])
        stops = [(ln.from_cell.aisle, ln.from_cell.rack) for ln in task.lines if ln.from_cell]
        d["route"] = [ln.from_cell.address for ln in task.lines if ln.from_cell]
        d["route_length"] = RulesService.route_length(list(dict.fromkeys(stops)), racks)
        nxt = next((ln for ln in task.lines if ln.status != "DONE"), None)
        d["next_line_id"] = nxt.id if nxt else None
        return d

    def view(self, number: str) -> dict:
        task = self.tasks.find(number)
        if task is None:
            raise NotFound(f"Завдання {number} не знайдено", code="task_not_found")
        return self._task_view(task)

    # --- підтвердитиВідбір(код) ---
    def confirm_pick(self, task_number: str, cell_code: str, product_code: str, quantity=None) -> dict:
        task = self.tasks.find(task_number)
        if task is None or task.type != "PICK":
            raise NotFound(f"Завдання на відбір {task_number} не знайдено", code="task_not_found")
        if task.status == "DONE":
            raise Conflict("Завдання вже виконано", code="already_done")
        cell = self.dirs.cell(cell_code)
        if cell is None:
            raise NotFound(f"Комірку {cell_code} не знайдено", code="cell_not_found")
        open_lines = [ln for ln in task.lines if ln.status != "DONE" and ln.from_cell_id == cell.id]
        if not open_lines:
            raise Invalid(f"У комірці {cell.address} немає невиконаних рядків завдання", code="wrong_cell")
        parsed = gs1.parse(product_code)
        product = (self.dirs.product_by_gtin(parsed["gtin"]) if parsed["gtin"]
                   else self.dirs.product_by_any(product_code))
        line = next((ln for ln in open_lines if product and ln.product_id == product.id
                     and (not parsed["batch"] or (ln.batch and ln.batch.number == parsed["batch"]))), None)
        if line is None:  # 5а: блокування підтвердження
            self.op("PICK_ERROR", 0, task=task, details=f"Скан {product_code} у {cell.address}")
            self.commit()
            raise Invalid("Відскановано не той товар — підтвердження заблоковано", code="wrong_product",
                          expected=[ln.product.code for ln in open_lines])
        remaining = D(line.quantity) - D(line.done_quantity)
        qty = D(quantity) if quantity is not None else remaining
        if qty <= 0 or qty > remaining:
            raise Invalid(f"Кількість має бути від 0 до {num(remaining)}", code="bad_quantity")
        ship_cell = self.dirs.first_cell(Zone.SHIPPING)
        if ship_cell is None:
            raise Conflict("Не налаштовано зону відвантаження", code="no_shipping_cell")
        src = self.stock.get(line.stock_id)
        self.stock.reserve(src, -qty)
        self.stock.change(src, -qty)
        dst = self.stock.get_or_create(line.batch, ship_cell)
        self.stock.change(dst, qty)
        self.stock.reserve(dst, qty)
        self.op("PICK", qty, dst, task, details=f"{cell.address} → {ship_cell.address}")
        line.done_quantity = D(line.done_quantity) + qty
        if line.done_quantity >= D(line.quantity):
            line.status = "DONE"
        ol = self.docs.get_order_line(line.order_line_id)
        ol.picked = D(ol.picked) + qty
        message = f"Рядок зібрано: {line.product.code} × {num(qty)}"
        if all(ln.status == "DONE" for ln in task.lines):
            task.status = "DONE"
            task.completed_at = utcnow()
            message += ". Завдання виконано — замовлення передано в зону відвантаження"
        self.s.flush()
        for oid in {self.docs.get_order_line(ln.order_line_id).order_id for ln in task.lines}:
            order = self.docs.get_order(oid)
            if all(D(x.picked) >= D(x.reserved) for x in order.lines):
                order.status = "PICKED"
                order.picked_at = utcnow()
        self.tasks.save(task)
        self.check_replenishment(line.product_id)
        self.commit()
        return {"message": message, "task": self._task_view(task)}

    # --- FR-3.4: поповнення зони відбору ---
    def check_replenishment(self, product_id: int | None = None) -> list[str]:
        products = ([self.dirs.get("products", product_id)] if product_id else self.dirs.all_products())
        created = []
        for p in products:
            if p is None or D(p.min_pick_level) <= 0 or self.tasks.open_replenishment(p.id):
                continue
            pick_stock = self.stock.find(p.id, (Zone.PICKING,))
            level = sum((D(st.quantity) for st in pick_stock), Decimal(0))
            if level >= D(p.min_pick_level):
                continue
            target_qty = D(p.min_pick_level) * 2 - level
            sources = [st for st in self.stock.candidates_fefo(p.id, self.rules.min_expiry_date())
                       if st.cell.zone == Zone.STORAGE]
            if not sources:
                continue
            src = sources[0]
            qty = min(src.available, target_qty)
            dest = pick_stock[0].cell if pick_stock else self.rules.choose_cell(p, qty, src.batch,
                                                                                zone=Zone.PICKING)
            if dest is None or qty <= 0:
                continue
            self.stock.reserve(src, qty)
            task = Task(number=self.next_no("REPL"), type="REPLENISH", status="NEW",
                        note=f"Рівень у зоні відбору {num(level)} < мінімум {num(p.min_pick_level)}")
            task.lines.append(TaskLine(seq=1, product_id=p.id, batch_id=src.batch_id, from_cell_id=src.cell_id,
                                       to_cell_id=dest.id, stock_id=src.id, quantity=qty))
            self.tasks.save(task)
            created.append(task.number)
            self.journal.add("Створено завдання на поповнення", self.login, f"{task.number}: {p.code}")
        return created

    def run_replenishment(self) -> dict:
        created = self.check_replenishment()
        self.commit()
        return {"created": created}

    def confirm_replenishment(self, number: str, cell_address: str) -> dict:
        task = self.tasks.find(number)
        if task is None or task.type != "REPLENISH" or task.status == "DONE":
            raise NotFound(f"Відкрите завдання на поповнення {number} не знайдено", code="task_not_found")
        ln = task.lines[0]
        cell = self.dirs.cell(cell_address)
        if cell is None or cell.id != ln.to_cell_id:
            raise Invalid(f"Очікується комірка {ln.to_cell.address}", code="wrong_cell")
        src = self.stock.get(ln.stock_id)
        qty = D(ln.quantity)
        self.stock.reserve(src, -qty)
        self.stock.change(src, -qty)
        dst = self.stock.get_or_create(ln.batch, cell)
        self.stock.change(dst, qty)
        self.op("REPLENISH", qty, dst, task, details=f"{src.cell.address} → {cell.address}")
        ln.done_quantity, ln.status = qty, "DONE"
        task.status, task.completed_at, task.assignee_id = "DONE", utcnow(), self.user.id
        self.tasks.save(task)
        self.commit()
        return {"task": task.number, "status": "DONE"}

    def list_orders(self, status: str | None = None) -> list[dict]:
        return [order_dict(o) for o in self.docs.list_orders((status,) if status else None)]

    def get_order(self, number: str) -> dict:
        o = self.docs.find_order(number)
        if o is None:
            raise NotFound(f"Замовлення {number} не знайдено", code="order_not_found")
        d = order_dict(o)
        d["tasks"] = [t.number for t in self.tasks.list(order_id=o.id)]
        return d

    def list_tasks(self, type_: str | None = None, status: str | None = None) -> list[dict]:
        return [task_dict(t) for t in self.tasks.list(type_, (status,) if status else None)]
