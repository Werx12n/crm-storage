"""TC-04 на стенді: навантаження ТЗД/АРМ (NFR-1.1, NFR-1.2).

pip install locust
locust -f loadtest/locustfile.py --host http://localhost:8088 -u 100 -r 10 -t 5m --headless
Критерій: 95-й перцентиль запитів ТЗД ≤ 1000 мс при 100 користувачах.
"""
import random

from locust import HttpUser, between, task

LOGINS = ["sales", "manager", "picker", "driver", "receiver", "packer"]


class WmsUser(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        r = self.client.post("/api/auth/login", json={"login": random.choice(LOGINS), "password": "demo123"})
        self.client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    @task(5)
    def available(self):
        self.client.get(f"/api/stock/available?q=P-00{random.randint(1, 9)}", name="/api/stock/available")

    @task(2)
    def orders(self):
        self.client.get("/api/picking/orders")

    @task(1)
    def health(self):
        self.client.get("/health")
