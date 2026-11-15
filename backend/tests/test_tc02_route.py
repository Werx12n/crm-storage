"""TC-02 Тест маршруту відбору (FR-3.3)."""
import random

from app.services.rules import RulesService, brute_force_best

RACKS = 6


def test_tc02_route_is_optimal_for_small_sets():
    rnd = random.Random(42)
    for _ in range(30):
        stops = list({(rnd.randint(0, 4), rnd.randint(1, RACKS)) for _ in range(rnd.randint(2, 7))})
        order = RulesService.optimal_order(stops, RACKS)
        assert sorted(order) == sorted(stops)
        assert RulesService.route_length(order, RACKS) == brute_force_best(stops, RACKS)


def test_tc02_route_large_not_worse_than_serpentine_and_input():
    rnd = random.Random(7)
    stops = list({(rnd.randint(0, 8), rnd.randint(1, RACKS)) for _ in range(25)})
    order = RulesService.optimal_order(stops, RACKS)
    serp = sorted(stops, key=lambda p: (p[0], p[1] if p[0] % 2 else -p[1]))
    assert RulesService.route_length(order, RACKS) <= RulesService.route_length(serp, RACKS)
    assert RulesService.route_length(order, RACKS) <= RulesService.route_length(stops, RACKS)


def test_tc02_pick_task_lines_follow_route(api):
    # замовлення з товарами в різних проходах: P-008 (прохід 4), P-001 (1), P-003 (3), P-005 (2)
    api.order("ORD-R1", [("P-008", 5), ("P-001", 5), ("P-003", 5), ("P-005", 5)])
    task = api.ok(api.post("/api/picking/tasks/next", login="picker"))["task"]
    cells = task["route"]
    assert len(cells) == 4
    # довжина маршруту завдання = оптимум за повним перебором
    from app.modules.common import ManagerBase  # noqa: F401
    coords = [(int(c.split("-")[1]), int(c.split("-")[2])) for c in cells]
    assert task["route_length"] == brute_force_best(coords, RACKS)
    assert task["route_length"] == RulesService.route_length(coords, RACKS)
