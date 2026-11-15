"""СервісПравил: обратиКомірку(вантаж), обратиПартіїFEFO(рядок), маршрут відбору (FR-2.1, FR-3.1, FR-3.3)."""
from datetime import date, timedelta
from decimal import Decimal
from itertools import permutations

from app.entities import Batch, Cell, Product, Stock, Zone
from app.repositories import DirectoryRepository, StockRepository

AISLE_WIDTH = 3  # відстань між сусідніми проходами в «кроках стелажа»


class RulesService:
    def __init__(self, stock: StockRepository, dirs: DirectoryRepository):
        self.stock = stock
        self.dirs = dirs

    # ---------- FR-2.1 вибір комірки ----------
    def choose_cell(self, product: Product, qty: Decimal, batch: Batch | None = None,
                    exclude_ids: tuple[int, ...] = (), zone: str = Zone.STORAGE) -> Cell | None:
        """обратиКомірку(вантаж): зона зберігання → вільна місткість (габарити, кг) → ABC-клас →
        консолідація тієї ж партії → найближча до початку маршруту."""
        need = Decimal(qty) * Decimal(product.weight)
        summary = self.stock.cell_summary()
        best, best_key = None, None
        for c in self.dirs.cells(zone):
            if c.id in exclude_ids:
                continue
            info = summary.get(c.id, {"load": Decimal(0), "products": set(), "batches": set()})
            if Decimal(c.capacity) - info["load"] < need:
                continue
            same_batch = batch is not None and batch.id in info["batches"]
            other_products = bool(info["products"] - {product.id})
            abc_penalty = abs(ord((c.abc_class or "C")) - ord(product.abc_class or "C"))
            key = (0 if same_batch else 1, abc_penalty, 1 if other_products else 0,
                   c.aisle, c.rack, c.level)
            if best_key is None or key < best_key:
                best, best_key = c, key
        return best

    def check_cell(self, cell: Cell, product: Product, qty: Decimal) -> tuple[bool, str]:
        """Чи підходить комірка за правилами (зона, активність, місткість)."""
        if not cell.is_active:
            return False, "Комірка неактивна"
        if cell.zone not in (Zone.STORAGE, Zone.PICKING):
            return False, f"Комірка {cell.address} не в зоні зберігання"
        need = Decimal(qty) * Decimal(product.weight)
        free = Decimal(cell.capacity) - self.stock.cell_load(cell.id)
        if free < need:
            return False, f"Перевищення місткості комірки {cell.address}: вільно {free} кг, потрібно {need} кг"
        return True, ""

    # ---------- FR-3.1 / BRL-01 / BRL-03 ----------
    def min_expiry_date(self, today: date | None = None) -> date:
        days = int(self.dirs.rule("min_shelf_days", "30"))
        return (today or date.today()) + timedelta(days=days)

    def choose_batches_fefo(self, product_id: int, qty: Decimal) -> list[tuple[Stock, Decimal]]:
        """обратиПартіїFEFO(рядок): партії з найближчим терміном, але не меншим за мінімальний залишковий."""
        need = Decimal(qty)
        plan: list[tuple[Stock, Decimal]] = []
        for st in self.stock.candidates_fefo(product_id, self.min_expiry_date()):
            if need <= 0:
                break
            take = min(st.available, need)
            if take > 0:
                plan.append((st, take))
                need -= take
        return plan

    # ---------- FR-3.3 маршрут ----------
    @staticmethod
    def distance(a: tuple[int, int], b: tuple[int, int], racks: int) -> int:
        (a1, r1), (a2, r2) = a, b
        if a1 == a2:
            return abs(r1 - r2)
        # перехід між проходами через передній (rack 0) або задній (rack racks+1) поперечний прохід
        return min(r1 + r2, 2 * (racks + 1) - r1 - r2) + AISLE_WIDTH * abs(a1 - a2)

    @classmethod
    def route_length(cls, stops: list[tuple[int, int]], racks: int) -> int:
        path = [(0, 0), *stops, (0, 0)]
        return sum(cls.distance(path[i], path[i + 1], racks) for i in range(len(path) - 1))

    @classmethod
    def optimal_order(cls, stops: list[tuple[int, int]], racks: int) -> list[tuple[int, int]]:
        """Оптимальний обхід: точний Held–Karp до 10 зупинок, інакше «змійка» + 2-opt."""
        uniq = list(dict.fromkeys(stops))
        n = len(uniq)
        if n <= 1:
            return uniq
        d = lambda x, y: cls.distance(x, y, racks)  # noqa: E731
        depot = (0, 0)
        if n <= 10:
            full = (1 << n) - 1
            dp: dict[tuple[int, int], tuple[int, int]] = {}
            for i in range(n):
                dp[(1 << i, i)] = (d(depot, uniq[i]), -1)
            for mask in range(1, full + 1):
                for last in range(n):
                    if (mask, last) not in dp:
                        continue
                    cost, _ = dp[(mask, last)]
                    for nxt in range(n):
                        if mask & (1 << nxt):
                            continue
                        key = (mask | (1 << nxt), nxt)
                        c = cost + d(uniq[last], uniq[nxt])
                        if key not in dp or c < dp[key][0]:
                            dp[key] = (c, last)
            last = min(range(n), key=lambda i: dp[(full, i)][0] + d(uniq[i], depot))
            order, mask = [], full
            while last != -1:
                order.append(uniq[last])
                _, prev = dp[(mask, last)]
                mask &= ~(1 << last)
                last = prev
            return list(reversed(order))
        route = sorted(uniq, key=lambda p: (p[0], p[1] if p[0] % 2 else -p[1]))
        improved = True
        while improved:
            improved = False
            for i in range(len(route) - 1):
                for j in range(i + 2, len(route) + 1):
                    cand = route[:i] + route[i:j][::-1] + route[j:]
                    if cls.route_length(cand, racks) < cls.route_length(route, racks):
                        route, improved = cand, True
        return route

    def build_route(self, lines: list, cell_of) -> list:
        """Сортує рядки завдання за оптимальним маршрутом. cell_of(line) -> Cell."""
        if not lines:
            return lines
        racks = max([c.rack for c in self.dirs.cells()] + [1])
        stops = [(cell_of(ln).aisle, cell_of(ln).rack) for ln in lines]
        order = self.optimal_order(stops, racks)
        rank = {p: i for i, p in enumerate(order)}
        return sorted(lines, key=lambda ln: (rank[(cell_of(ln).aisle, cell_of(ln).rack)], cell_of(ln).level))


def brute_force_best(stops: list[tuple[int, int]], racks: int) -> int:
    """Еталон для тестів (TC-02)."""
    uniq = list(dict.fromkeys(stops))
    return min(RulesService.route_length(list(p), racks) for p in permutations(uniq))
