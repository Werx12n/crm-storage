"""МенеджерВідвантаження (control): перевіритиКомплектність(код), оформитиВідвантаження(). UC-04, FR-4."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.entities import Dispatch, Order, Zone, utcnow
from app.errors import Conflict, Invalid, NotFound
from app.modules.common import D, ManagerBase, iso, num
from app.services import gs1
from app.services.events import EventTypes

SLOT_MINUTES = 30


def dispatch_dict(d: Dispatch) -> dict:
    return {"id": d.id, "order_number": d.order.number, "client": d.order.client, "sscc": d.sscc,
            "ttn_number": d.ttn_number, "status": d.status, "ramp": d.ramp.code if d.ramp else None,
            "slot_start": iso(d.slot_start), "created_at": iso(d.created_at), "packing_list": d.packing_list}


class ShippingManager(ManagerBase):

    def _order(self, number: str) -> Order:
        o = self.docs.find_order(number)  # РепозиторійДокументів.знайти(замовлення)
        if o is None:
            raise NotFound(f"Замовлення {number} не знайдено", code="order_not_found")
        return o

    @staticmethod
    def _completeness(o: Order) -> dict:
        lines, missing = [], []
        for ln in o.lines:
            row = {"product_code": ln.product.code, "product_name": ln.product.name, "gtin": ln.product.gtin,
                   "quantity": num(ln.quantity), "picked": num(ln.picked), "checked": num(ln.checked),
                   "missing": num(D(ln.quantity) - D(ln.checked))}
            lines.append(row)
            if D(ln.checked) < D(ln.quantity):
                missing.append(row)
        return {"order_number": o.number, "status": o.status, "complete": not missing,
                "lines": lines, "missing": missing}

    # --- перевіритиКомплектність(код) ---
    def check_completeness(self, number: str, code: str | None = None, quantity=None) -> dict:
        o = self._order(number)
        if o.status == "SHIPPED":
            raise Conflict("Замовлення вже відвантажено", code="already_shipped")
        if o.status not in ("PICKED",):
            raise Conflict("Замовлення ще не скомплектовано", code="not_picked", status=o.status)
        warning = None
        if code:
            parsed = gs1.parse(code)
            product = (self.dirs.product_by_gtin(parsed["gtin"]) if parsed["gtin"]
                       else self.dirs.product_by_any(code))
            line = next((ln for ln in o.lines if product and ln.product_id == product.id), None)
            if line is None:
                raise Invalid("Товар не входить до замовлення", code="not_in_order")
            qty = D(quantity if quantity is not None else (parsed["qty"] or 1))
            if D(line.checked) + qty > D(line.picked):
                raise Invalid(f"Перевищено відібрану кількість {line.product.code}: "
                              f"{num(D(line.checked) + qty)} > {num(line.picked)}", code="over_check")
            line.checked = D(line.checked) + qty
            self.commit()
        res = self._completeness(o)
        if not res["complete"] and all(D(ln.checked) >= D(ln.picked) for ln in o.lines):
            warning = "Бракує позицій — відвантаження заблоковано до докомплектації"
        res["warning"] = warning
        return res

    # --- оформитиВідвантаження() ---
    def ship(self, number: str) -> dict:
        o = self._order(number)
        if o.status != "PICKED":
            raise Conflict("Відвантажити можна лише скомплектоване замовлення", code="not_picked")
        comp = self._completeness(o)
        if not comp["complete"]:  # 2а / обмеження: без повної перевірки скануванням заборонено
            raise Conflict("Комплектність не підтверджена скануванням — відвантаження заблоковано",
                           code="incomplete", missing=comp["missing"])
        ship_cell = self.dirs.first_cell(Zone.SHIPPING)
        pl_lines, writeoffs, total_weight = [], [], Decimal(0)
        for ln in o.lines:
            for tl in self.tasks.lines_for_order_line(ln.id):
                qty = D(tl.done_quantity)
                if qty <= 0:
                    continue
                st = self.stock.get_or_create(tl.batch, ship_cell)
                self.stock.reserve(st, -qty)
                self.stock.change(st, -qty)  # змінити(залишок, −кількість)
                self.op("SHIPMENT", qty, st, details=f"Замовлення {o.number}")
                w = qty * D(ln.product.weight)
                total_weight += w
                pl_lines.append({"product_code": ln.product.code, "product_name": ln.product.name,
                                 "gtin": ln.product.gtin, "batch": tl.batch.number,
                                 "expiry_date": str(tl.batch.expiry_date or ""), "quantity": num(qty),
                                 "unit": ln.product.unit, "weight": num(w)})
                writeoffs.append({"product_code": ln.product.code, "batch": tl.batch.number,
                                  "quantity": num(qty)})
        sscc = self.new_sscc()
        ramp, slot = self._plan_ramp()
        packing = {"number": f"ПЛ-{o.number}", "date": str(utcnow().date()), "order_number": o.number,
                   "client": o.client, "sscc": sscc, "lines": pl_lines, "total_weight": num(total_weight),
                   "ramp": ramp.code if ramp else None, "slot_start": iso(slot)}
        d = Dispatch(order_id=o.id, sscc=sscc, status="AWAITING_TTN", ramp_id=ramp.id if ramp else None,
                     slot_start=slot, packing_list=packing)
        self.docs.save(d)
        o.status = "SHIPPED"
        o.shipped_at = utcnow()
        self.publisher.publish(EventTypes.SHIPPED, {"order_number": o.number, "client": o.client,
                                                    "sscc": sscc, "writeoffs": writeoffs})
        self.publisher.publish(EventTypes.DELIVERY_REQUESTED, {
            "dispatch_id": d.id, "order_number": o.number, "client": o.client, "sscc": sscc,
            "weight": num(total_weight), "places": 1, "ramp": packing["ramp"], "slot_start": iso(slot)})
        self.journal.add("Відвантаження оформлено", self.login, f"{o.number}: SSCC {sscc}")
        self.commit()
        return {"dispatch": dispatch_dict(d), "packing_list": packing, "sscc": sscc,
                "message": "Відвантаження оформлено; заявку в службу доставки поставлено в чергу"}

    def _plan_ramp(self):
        """FR-4.3: найраніший вільний 30-хвилинний слот серед рамп."""
        ramps = self.docs.ramps()
        if not ramps:
            return None, None
        now = utcnow().replace(second=0, microsecond=0)
        start = now + timedelta(minutes=(SLOT_MINUTES - now.minute % SLOT_MINUTES) % SLOT_MINUTES)
        best = None
        for r in ramps:
            busy = set(self.docs.ramp_slots(r.id, start))
            slot = start
            while slot in busy:
                slot += timedelta(minutes=SLOT_MINUTES)
            if best is None or slot < best[1]:
                best = (r, slot)
        return best

    def list(self) -> list[dict]:
        return [dispatch_dict(d) for d in self.docs.list_dispatches()]

    def get(self, dispatch_id: int) -> Dispatch:
        d = self.docs.find_dispatch(dispatch_id)
        if d is None:
            raise NotFound("Відправлення не знайдено", code="dispatch_not_found")
        return d

    def ramp_schedule(self) -> list[dict]:
        since = utcnow() - timedelta(hours=12)
        out = []
        for r in self.docs.ramps():
            slots = sorted(self.docs.ramp_slots(r.id, since))
            out.append({"ramp": r.code, "name": r.name, "slots": [iso(s) for s in slots]})
        return out

    def ready_orders(self) -> list[dict]:
        return [self._completeness(o) for o in self.docs.list_orders(("PICKED",))]
