"""МенеджерПриймання (control): зареєструватиASN(asn), почати(номер), зареєструватиСкан(код, кількість), завершити()."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.entities import ReceiptScan, Shipment, ShipmentLine, Task, TaskLine, Zone, utcnow
from app.errors import Conflict, Invalid, NotFound
from app.modules.common import D, ManagerBase, iso, num
from app.services import gs1
from app.services.events import EventTypes


def shipment_dict(sh: Shipment, with_lines: bool = True) -> dict:
    d = {"asn_number": sh.asn_number, "date": sh.date, "status": sh.status, "supplier": sh.supplier,
         "completed_at": iso(sh.completed_at), "has_discrepancies": bool(sh.discrepancy_act)}
    if with_lines:
        d["lines"] = [{
            "id": ln.id, "product_code": ln.product.code, "product_name": ln.product.name,
            "gtin": ln.product.gtin, "unit": ln.product.unit, "batch_number": ln.batch_number,
            "expiry_date": ln.expiry_date, "expected": num(ln.expected), "accepted": num(ln.accepted),
        } for ln in sh.lines]
    return d


class ReceivingManager(ManagerBase):

    # --- зареєструватиASN(asn) — викликається ШлюзомEDI / імпортом з ERP (FR-1.1) ---
    def register_asn(self, asn: dict) -> dict:
        number = asn["asn_number"].strip()
        if self.docs.find_shipment(number):
            raise Conflict(f"ASN {number} вже зареєстровано", code="duplicate_asn")
        if not asn.get("lines"):
            raise Invalid("ASN не містить рядків", code="empty_asn")
        sh = Shipment(asn_number=number, date=asn.get("date") or date.today(),
                      supplier=asn.get("supplier", ""), status="REGISTERED")
        for raw in asn["lines"]:
            product = None
            if raw.get("gtin"):
                if not gs1.is_valid_gtin(raw["gtin"]):
                    raise Invalid(f"Некоректний GTIN {raw['gtin']}", code="bad_gtin")
                product = self.dirs.product_by_gtin(raw["gtin"])
            elif raw.get("product_code"):
                product = self.dirs.find("products", raw["product_code"])
            if product is None:
                raise Invalid(f"Товар {raw.get('gtin') or raw.get('product_code')} відсутній у довіднику",
                              code="unknown_product")
            sh.lines.append(ShipmentLine(product=product, product_id=product.id,
                                         expected=D(raw["quantity"]), accepted=Decimal(0),
                                         batch_number=raw.get("batch_number"),
                                         expiry_date=raw.get("expiry_date")))
        self.docs.save(sh)
        self.journal.add("ASN зареєстровано", self.login, f"{number}: {len(sh.lines)} рядків")
        self.commit()
        return shipment_dict(sh)

    def list(self, status: str | None = None) -> list[dict]:
        return [shipment_dict(s, with_lines=False) for s in self.docs.list_shipments(status)]

    def get(self, number: str) -> dict:
        sh = self._find(number)
        d = shipment_dict(sh)
        d["scans"] = [{"product_code": sc.product.code, "batch": sc.batch_number, "expiry_date": sc.expiry_date,
                       "quantity": num(sc.quantity), "quarantine": sc.quarantine, "time": iso(sc.created_at)}
                      for sc in self.docs.scans(sh.id)]
        d["discrepancy_act"] = sh.discrepancy_act
        return d

    def _find(self, number: str) -> Shipment:
        sh = self.docs.find_shipment(number)
        if sh is None:
            raise NotFound(f"Поставку {number} не знайдено", code="asn_not_found")
        return sh

    # --- почати(номер) ---
    def start(self, number: str) -> dict:
        sh = self._find(number)
        if sh.status == "COMPLETED":
            raise Conflict(f"Приймання поставки {number} вже завершено", code="already_completed")
        if sh.status == "REGISTERED":
            sh.status = "IN_PROGRESS"
            self.journal.add("Приймання розпочато", self.login, number)
            self.commit()
        return shipment_dict(sh)

    # --- зареєструватиСкан(код, кількість) ---
    def register_scan(self, number: str, code: str, quantity=None, batch_number: str | None = None,
                      expiry_date: date | None = None) -> dict:
        sh = self._find(number)
        if sh.status == "COMPLETED":
            raise Conflict("Приймання вже завершено", code="already_completed")
        if sh.status == "REGISTERED":
            sh.status = "IN_PROGRESS"
        parsed = gs1.parse(code)
        if not parsed["gtin"]:
            raise Invalid("Штрихкод не є дійсним GS1 GTIN — товар без штрихкоду GS1 не приймається",
                          code="not_gs1")
        product = self.dirs.product_by_gtin(parsed["gtin"])
        if product is None:
            raise Invalid(f"Товар з GTIN {parsed['gtin']} відсутній у довіднику", code="unknown_product")
        qty = D(quantity if quantity is not None else (parsed["qty"] or 0))
        if qty <= 0:
            raise Invalid("Кількість має бути більшою за нуль", code="bad_quantity")
        batch = (batch_number or parsed["batch"] or "").strip()
        if not batch:
            raise Invalid("Вкажіть номер партії", code="batch_required")
        expiry = expiry_date or parsed["expiry"]

        line = next((ln for ln in sh.lines if ln.product_id == product.id and Decimal(ln.expected) > 0
                     and (not ln.batch_number or ln.batch_number == batch)), None)
        if line is None:
            line = next((ln for ln in sh.lines if ln.product_id == product.id and Decimal(ln.expected) > 0), None)
        warning, quarantine = None, False
        if line is None:  # 3а: штрихкод не знайдено в ASN → карантин
            quarantine = True
            warning = f"Товар {product.code} відсутній в ASN — приймається в зону карантину"
            line = next((ln for ln in sh.lines if ln.product_id == product.id), None)
            if line is None:
                line = ShipmentLine(product=product, product_id=product.id, expected=Decimal(0),
                                    accepted=Decimal(0), batch_number=batch, expiry_date=expiry)
                sh.lines.append(line)
                self.s.flush()
        line.accepted = D(line.accepted) + qty
        if not quarantine and D(line.accepted) > D(line.expected):
            warning = f"Прийнято більше, ніж очікувалось за ASN ({num(line.accepted)} > {num(line.expected)})"
        self.s.add(ReceiptScan(shipment_id=sh.id, line_id=line.id, product_id=product.id,
                               batch_number=batch, expiry_date=expiry, quantity=qty,
                               quarantine=quarantine, user_id=self.user.id if self.user else None))
        self.commit()
        return {"line": {"product_code": product.code, "product_name": product.name,
                         "expected": num(line.expected), "accepted": num(line.accepted)},
                "batch": batch, "expiry_date": expiry, "quantity": num(qty),
                "quarantine": quarantine, "warning": warning}

    # --- завершити() ---
    def complete(self, number: str) -> dict:
        sh = self._find(number)
        if sh.status == "COMPLETED":
            raise Conflict("Приймання вже завершено", code="already_completed")
        recv = self.dirs.first_cell(Zone.RECEIVING)
        quar = self.dirs.first_cell(Zone.QUARANTINE) or recv
        if recv is None:
            raise Conflict("Не налаштовано комірку зони приймання", code="no_receiving_cell")
        labels, event_lines = [], []
        for sc in self.docs.scans(sh.id):
            batch = self.dirs.get_or_create_batch(sc.product, sc.batch_number, sc.expiry_date)
            cell = quar if sc.quarantine else recv
            st = self.stock.get_or_create(batch, cell)
            self.stock.change(st, sc.quantity)  # РепозиторійЗалишків.змінити(залишок, кількість)
            self.op("RECEIPT", sc.quantity, st, details=f"ASN {sh.asn_number}"
                    + (" (карантин)" if sc.quarantine else ""))
            event_lines.append({"product_code": sc.product.code, "gtin": sc.product.gtin,
                                "batch": batch.number, "expiry_date": str(batch.expiry_date or ""),
                                "quantity": num(sc.quantity), "quarantine": sc.quarantine})
            if sc.quarantine:
                continue
            sscc = self.new_sscc()  # FR-1.4 етикетка вантажної одиниці
            task = Task(number=self.next_no("PUT"), type="PUTAWAY", status="NEW", shipment_id=sh.id,
                        label=sscc)
            task.lines.append(TaskLine(seq=1, product_id=sc.product_id, batch_id=batch.id,
                                       from_cell_id=cell.id, stock_id=st.id, quantity=sc.quantity))
            self.tasks.save(task)
            labels.append(self._label(sscc, sc.product, batch, sc.quantity, sh.asn_number, task.number))

        act = self._discrepancy_act(sh)
        sh.discrepancy_act = act
        sh.status = "COMPLETED"
        sh.completed_at = utcnow()
        self.publisher.publish(EventTypes.RECEIVING_COMPLETED, {
            "asn_number": sh.asn_number, "supplier": sh.supplier, "lines": event_lines,
            "discrepancies": act["lines"] if act else []})
        self.journal.add("Приймання завершено", self.login,
                         f"{sh.asn_number}: етикеток {len(labels)}, розбіжностей {len(act['lines']) if act else 0}")
        self.commit()
        return {"shipment": shipment_dict(sh), "discrepancy_act": act, "labels": labels}

    @staticmethod
    def _label(sscc: str, product, batch, qty, asn: str, task_no: str) -> dict:
        return {"sscc": sscc, "gs1": f"(00){sscc}", "product_code": product.code, "product_name": product.name,
                "gtin": product.gtin, "batch": batch.number, "expiry_date": batch.expiry_date,
                "quantity": num(qty), "unit": product.unit, "asn_number": asn, "putaway_task": task_no}

    def _discrepancy_act(self, sh: Shipment) -> dict | None:
        """FR-1.3 / ВП-03: акт розбіжностей за результатами приймання."""
        scans = self.docs.scans(sh.id)
        rows = []
        for ln in sh.lines:
            exp, acc = D(ln.expected), D(ln.accepted)
            if exp == acc:
                continue
            if exp == 0:
                kind = "Товар відсутній в ASN (карантин)"
            elif acc < exp:
                kind = "Недостача"
            else:
                kind = "Надлишок"
            rows.append({"product_code": ln.product.code, "product_name": ln.product.name,
                         "gtin": ln.product.gtin, "unit": ln.product.unit,
                         "expected": num(exp), "accepted": num(acc), "difference": num(acc - exp),
                         "kind": kind,
                         "batches": sorted({sc.batch_number for sc in scans if sc.line_id == ln.id})})
        if not rows:
            return None
        return {"number": f"АР-{sh.asn_number}", "date": str(date.today()), "asn_number": sh.asn_number,
                "supplier": sh.supplier, "lines": rows, "composed_by": self.login}

    def label(self, sscc: str) -> dict:
        task = self.tasks.find_by_label(sscc, "PUTAWAY")
        if task is None:
            raise NotFound(f"Етикетку {sscc} не знайдено", code="label_not_found")
        ln = task.lines[0]
        sh_no = self.docs.get_shipment(task.shipment_id).asn_number if task.shipment_id else ""
        return self._label(sscc, ln.product, ln.batch, ln.quantity, sh_no, task.number)
