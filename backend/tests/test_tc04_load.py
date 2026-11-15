"""TC-04 Навантажувальний тест (NFR-1.1 ≤ 1 с для 95 % запитів ТЗД; NFR-1.2 ≥ 100 користувачів, ≥ 20 000 рядків/добу).

Тест на рівні застосунку (in-process). Для стенду з PostgreSQL є окремий сценарій loadtest/locustfile.py.
"""
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import gtin

pytestmark = pytest.mark.load


def p95(xs):
    return statistics.quantiles(xs, n=20)[18]


def test_tc04_tzd_response_time_p95(api, demo_asn):
    api.post(f"/api/receiving/shipments/{demo_asn}/start", login="receiver")
    times = []
    for i in range(150):
        t = time.perf_counter()
        if i % 3 == 0:
            r = api.post(f"/api/receiving/shipments/{demo_asn}/scan",
                         {"code": gtin(1), "quantity": 1, "batch_number": "LT1"}, login="receiver")
        elif i % 3 == 1:
            r = api.get("/api/stock/available?q=P-001", login="sales")
        else:
            r = api.get(f"/api/receiving/shipments/{demo_asn}", login="receiver")
        times.append(time.perf_counter() - t)
        assert r.status_code == 200
    assert p95(times) <= 1.0, f"p95={p95(times):.3f} с"


def test_tc04_100_concurrent_users(api):
    headers = [api.h(lg) for lg in ("sales", "manager", "driver", "packer", "receiver")]

    def user(i):
        c = TestClient(app)
        t = time.perf_counter()
        urls = ["/api/stock/available?q=P-00", "/api/picking/orders", "/api/putaway/tasks", "/api/shipping/ready",
                "/api/receiving/shipments"]
        r = c.get(urls[i % 5], headers=headers[i % 5])
        return r.status_code, time.perf_counter() - t

    with ThreadPoolExecutor(max_workers=100) as ex:
        results = list(ex.map(user, range(200)))
    assert all(code == 200 for code, _ in results), [c for c, _ in results if c != 200][:5]
    assert p95([t for _, t in results]) <= 5.0  # під паралельним навантаженням in-process (GIL) — запас


def test_tc04_order_lines_throughput(api):
    t = time.perf_counter()
    lines = 0
    for i in range(60):
        api.order(f"ORD-L{i}", [("P-006", 1), ("P-012", 1), ("P-008", 1), ("P-005", 1), ("P-002", 1)])
        lines += 5
    elapsed = time.perf_counter() - t
    per_day = lines / elapsed * 86400
    assert per_day >= 20_000, f"{per_day:.0f} рядків/добу"
