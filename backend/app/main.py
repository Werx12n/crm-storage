"""WMS API — точка входу. Трирівнева архітектура: клієнти → API-шлюз (FastAPI) → модулі → PostgreSQL."""
import json
import logging

import jwt
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app import db
from app.config import settings
from app.errors import DomainError, domain_error_handler
from app.modules.admin import barcodes
from app.modules.admin.router import auth_router, router as admin_router
from app.modules.analytics.router import router as analytics_router
from app.modules.integration import mock
from app.modules.integration.router import router as integration_router
from app.modules.inventory.router import router as inventory_router
from app.modules.picking.router import router as picking_router
from app.modules.putaway.router import router as putaway_router
from app.modules.receiving.router import router as receiving_router
from app.modules.shipping.router import router as shipping_router
from app.repositories import JournalRepository
from app.security import decode_token

log = logging.getLogger("wms")

app = FastAPI(
    title="WMS — інформаційна система управління складом",
    version="0.1.0",
    description="Прототип WMS за курсовою роботою. Модулі: receiving (FR-1), putaway (FR-2), picking (FR-3), "
                "shipping (FR-4), inventory (FR-5), admin (FR-6.1, FR-6.4), integration (FR-6.2, FR-6.3), "
                "analytics (FR-7). OpenAPI 3 генерується автоматично (FR-6.2).",
)
app.add_exception_handler(DomainError, domain_error_handler)


def _login_from(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            return decode_token(auth[7:]).get("sub")
        except jwt.PyJWTError:
            return None
    return None


MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


class JournalAndIdempotencyMiddleware(BaseHTTPMiddleware):
    """FR-6.4: журнал усіх операцій, що змінюють дані.
    NFR-2.3: заголовок Idempotency-Key робить повторну синхронізацію офлайн-черги ТЗД безпечною."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method not in MUTATING or not path.startswith("/api/") or path.startswith("/api/auth"):
            return await call_next(request)
        login = _login_from(request)
        key = request.headers.get("idempotency-key")
        if key:
            key = f"{login}:{key}"[:80]
            with db.SessionLocal() as s:
                stored = JournalRepository(s).idem_get(key)
                if stored is not None:
                    return Response(stored.body, status_code=stored.status_code, media_type="application/json",
                                    headers={"Idempotent-Replay": "true"})
        response = await call_next(request)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            with db.SessionLocal() as s:
                repo = JournalRepository(s)
                detail = ""
                if response.status_code >= 400:
                    try:
                        detail = str(json.loads(body).get("detail", ""))[:500]
                    except Exception:
                        detail = ""
                repo.add("API: " + request.method + " " + path, login, detail, method=request.method,
                         path=path, status_code=response.status_code)
                if key and response.status_code < 500:
                    repo.idem_save(key, login, response.status_code, body.decode("utf-8", "replace"))
                s.commit()
        except Exception:  # журнал не повинен ламати операцію
            log.exception("journal write failed")
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(body, status_code=response.status_code, headers=headers, media_type=response.media_type)


app.add_middleware(JournalAndIdempotencyMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_methods=["*"],
                   allow_headers=["*"], expose_headers=["Idempotent-Replay"])

for r in (auth_router, receiving_router, putaway_router, picking_router, shipping_router, inventory_router,
          admin_router, barcodes.router, integration_router, analytics_router, mock.router):
    app.include_router(r)


@app.get("/health", tags=["health"], summary="Перевірка доступності (NFR-2.1)")
def health():
    try:
        with db.engine.connect() as c:
            c.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok", "dialect": db.engine.dialect.name}
    except Exception as e:  # pragma: no cover
        return JSONResponse({"status": "degraded", "db": str(e)[:200]}, status_code=503)
