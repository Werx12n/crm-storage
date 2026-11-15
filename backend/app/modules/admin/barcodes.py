"""Етикетки і штрихкоди: Control (МенеджерЕтикеток) + Boundary (роутер). FR-1.2, FR-1.4."""
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api_deps import Roles, current_user, require_roles
from app.db import get_session
from app.entities import User
from app.errors import Invalid, NotFound
from app.modules.common import ManagerBase
from app.services import barcodes, gs1

router = APIRouter(prefix="/api/barcodes", tags=["barcodes — штрихкоди й етикетки (FR-1.2, FR-1.4)"])

PRINT = (Roles.ADMIN, Roles.MANAGER, Roles.RECEIVER, Roles.PACKER)


class SheetIn(BaseModel):
    products: list[str] = Field(default_factory=list, description="Коди товарів → EAN-13 (GTIN)")
    cells: list[str] = Field(default_factory=list, description="Адреси комірок → Code128")
    sscc: list[str] = Field(default_factory=list, description="Наявні SSCC → GS1-128 (AI 00)")
    new_sscc: int = Field(default=0, ge=0, le=100, description="Згенерувати N нових SSCC для палет")
    tasks: list[str] = Field(default_factory=list, description="Номери завдань → QR")
    copies: int = Field(default=1, ge=1, le=20)


class LabelManager(ManagerBase):
    def build(self, req: SheetIn) -> list[dict]:
        labels: list[dict] = []
        for code in req.products:
            p = self.dirs.product_by_any(code)
            if p is None:
                raise NotFound(f"Товар {code} не знайдено", code="unknown_product")
            labels.append({"kind": "ean13", "value": p.gtin[1:] if p.gtin.startswith("0") else p.gtin,
                           "title": f"{p.code} {p.name}", "subtitle": f"GTIN {p.gtin} · {p.unit}"})
        for addr in req.cells:
            c = self.dirs.cell(addr)
            if c is None:
                raise NotFound(f"Комірку {addr} не знайдено", code="cell_not_found")
            labels.append({"kind": "code128", "value": c.address, "title": f"Комірка {c.address}",
                           "subtitle": f"Зона {c.zone} · склад {c.warehouse}"})
        for s in req.sscc:
            if not gs1.is_valid_sscc(s):
                raise Invalid(f"{s}: невірний SSCC", code="bad_check_digit")
            labels.append({"kind": "sscc", "value": s, "title": "Вантажна одиниця (SSCC)", "subtitle": ""})
        if req.new_sscc:
            for _ in range(req.new_sscc):
                s = self.new_sscc()
                labels.append({"kind": "sscc", "value": s, "title": "Палета (SSCC)", "subtitle": "нова"})
            self.journal.add("Згенеровано SSCC", self.login, f"{req.new_sscc} шт.")
            self.commit()
        for n in req.tasks:
            t = self.tasks.find(n)
            if t is None:
                raise NotFound(f"Завдання {n} не знайдено", code="task_not_found")
            labels.append({"kind": "qr", "value": t.number, "title": f"Завдання {t.number}", "subtitle": t.type})
        return [lb for lb in labels for _ in range(req.copies)]


@router.get("/validate", summary="Перевірка скану і контрольної цифри GS1")
def validate(code: str, u: User = Depends(current_user)):
    p = gs1.parse(code)
    return {"code": code, "valid": bool(p["gtin"] or p["sscc"]), "gtin": p["gtin"], "sscc": p["sscc"],
            "batch": p["batch"], "expiry": p["expiry"], "qty": p["qty"]}


@router.get("/{kind}/{value}.{fmt}", summary="Зображення штрихкоду: ean13|code128|sscc|gs1|qr, svg|png",
            response_class=Response)
def image(kind: str, value: str, fmt: str):
    # Публічний ендпоінт: зображення кодує лише передане значення (для <img> без заголовка авторизації).
    data, media = barcodes.render(kind, value, fmt)
    return Response(data, media_type=media, headers={"Cache-Control": "public, max-age=86400"})


@router.post("/sheet", summary="PDF-аркуш етикеток (reportlab) для товарів, комірок, SSCC, завдань",
             response_class=Response)
def sheet(body: SheetIn, s: Session = Depends(get_session), u: User = Depends(require_roles(*PRINT))):
    labels = LabelManager(s, u).build(body)
    return Response(barcodes.labels_pdf(labels), media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="labels.pdf"'})


@router.post("/sheet/preview", summary="Список етикеток для перегляду в АРМ (без PDF)")
def sheet_preview(body: SheetIn, s: Session = Depends(get_session), u: User = Depends(require_roles(*PRINT))):
    return LabelManager(s, u).build(body)
