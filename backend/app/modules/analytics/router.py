"""Boundary: звіти і KPI (UC-06, FR-7)."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api_deps import Roles, require_roles
from app.db import get_session
from app.entities import User
from app.modules.analytics.manager import REPORTS, ReportsManager

router = APIRouter(prefix="/api/analytics", tags=["analytics — звіти і KPI (FR-7)"])

VIEW = (Roles.MANAGER, Roles.ACCOUNTANT, Roles.ADMIN)


@router.get("/reports", summary="Перелік звітів ВП-01…ВП-10")
def reports(u: User = Depends(require_roles(*VIEW))):
    return [{"type": k, "code": c, "title": t} for k, (c, t) in REPORTS.items()]


@router.get("/kpi", summary="розрахуватиKPI() — панель KPI (FR-7.1)")
def kpi(date_from: date | None = None, date_to: date | None = None,
        costs: Decimal | None = Query(None, ge=0, description="Витрати складу за період, грн (KPI 9)"),
        s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW))):
    return ReportsManager(s, u).kpi(date_from, date_to, costs)


@router.get("/reports/{type_}", summary="сформуватиЗвіт(тип, період)")
def report(type_: str, date_from: date | None = None, date_to: date | None = None,
           format: str = Query("json", pattern="^(json|xlsx|pdf)$"),
           costs: Decimal | None = Query(None, ge=0),
           s: Session = Depends(get_session), u: User = Depends(require_roles(*VIEW))):
    m = ReportsManager(s, u)
    rep = m.generate(type_, date_from, date_to, costs)
    if format == "json":
        return rep
    name = f"{rep['code']}_{rep['period']['from']}_{rep['period']['to']}"
    if format == "xlsx":
        return Response(m.export_xlsx(rep),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{type_}_{rep["period"]["from"]}.xlsx"',
                                 "X-Report-Name": name.encode("utf-8").hex()})
    return Response(m.export_pdf(rep), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{type_}_{rep["period"]["from"]}.pdf"'})
