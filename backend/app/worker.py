"""Фоновий воркер інтеграції: читає outbox і надсилає події в ERP / службу доставки (UC-01 крок 7, UC-04 4а)."""
import logging
import signal
import time

from app import db
from app.config import settings
from app.modules.integration.manager import IntegrationManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(levelname)s %(message)s")
log = logging.getLogger("wms.worker")
_running = True


def _stop(*_):
    global _running
    _running = False


def run_once() -> dict:
    with db.SessionLocal() as s:
        return IntegrationManager(s).synchronize()


def build_erp_file() -> dict | None:
    with db.SessionLocal() as s:
        return IntegrationManager(s).build_operations_file()


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("старт, інтервал %.1f с, ERP=%s, доставка=%s", settings.worker_interval, settings.erp_url,
             settings.delivery_url)
    last_file = 0.0
    while _running:
        if time.monotonic() - last_file >= settings.erp_file_interval:  # ВП-09 кожні 15 хв
            last_file = time.monotonic()
            try:
                f = build_erp_file()
                if f:
                    log.info("файл операцій для ERP: %s (%s операцій)", f["file_name"], f["count"])
            except Exception:
                log.exception("помилка формування файлу операцій")
        try:
            res = run_once()
            if res["processed"] or res["failed"]:
                log.info("оброблено %s, помилок %s, у черзі %s", res["processed"], res["failed"], res["pending"])
        except Exception:
            log.exception("помилка циклу воркера (повтор через інтервал)")
        time.sleep(settings.worker_interval)
    log.info("зупинено")


if __name__ == "__main__":
    main()
