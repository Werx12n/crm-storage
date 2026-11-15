"""ПублікаторПодій: опублікувати(подія) — запис у outbox у тій самій транзакції, що й операція."""
from app.entities import Event
from app.repositories import EventRepository


class EventTypes:
    RECEIVING_COMPLETED = "ReceivingCompleted"   # ПрийманняЗавершено → ERP
    ORDER_STATUS = "OrderStatus"                 # статус замовлення (зокрема «частково») → ERP
    SHIPPED = "Shipped"                          # Відвантажено (списання) → ERP
    DELIVERY_REQUESTED = "DeliveryRequested"     # заявка → служба доставки
    STOCK_ADJUSTED = "StockAdjusted"             # коригування інвентаризації → ERP
    OPERATIONS_FILE = "OperationsFile"           # ВП-09: файл підтверджених операцій → ERP (кожні 15 хв)


class EventPublisher:
    def __init__(self, events: EventRepository):
        self.events = events

    def publish(self, type_: str, payload: dict) -> Event:
        return self.events.add(Event(type=type_, payload=payload))
