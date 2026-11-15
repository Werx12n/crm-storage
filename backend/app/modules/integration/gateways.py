"""Boundary-шлюзи вихідних викликів до зовнішніх систем: ШлюзERP, ШлюзСлужбиДоставки (FR-6.2, FR-6.3)."""
from collections.abc import Callable

import httpx

from app.config import settings

# Фабрика HTTP-клієнта; у тестах підміняється на TestClient(app), щоб викликати mock-сервіси in-process.
client_factory: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=settings.http_timeout)  # noqa: E731


class GatewayError(Exception):
    pass


def _post(url: str, payload: dict) -> dict:
    try:
        with client_factory() as c:
            r = c.post(url, json=payload)
    except httpx.HTTPError as e:
        raise GatewayError(f"Зовнішня система недоступна: {e}") from e
    if r.status_code >= 400:
        raise GatewayError(f"Зовнішня система відповіла {r.status_code}: {r.text[:200]}")
    return r.json() if r.content else {}


class ERPGateway:
    """ШлюзERP.надіслатиОперації(пакет). Вхідне отриматиЗамовлення() — див. router.py."""

    def send_operations(self, batch: dict) -> dict:
        return _post(f"{settings.erp_url}/operations", batch)


class DeliveryGateway:
    """ШлюзСлужбиДоставки.створитиВідправлення(дані). Вхідне прийнятиСтатус() — див. router.py."""

    def create_shipment(self, data: dict) -> str:
        res = _post(f"{settings.delivery_url}/shipments", data)
        ttn = res.get("ttn")
        if not ttn:
            raise GatewayError("Служба доставки не повернула номер ТТН")
        return ttn
