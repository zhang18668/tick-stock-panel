from app.strategy_optimizer.contracts import ParameterSpec
from app.strategy_optimizer.neighborhood import generate_neighbors
from app.strategy_optimizer.search import Candidate


def test_neighbor_values_are_one_grid_step_and_keep_parameter_types():
    spec = ParameterSpec("x", "x", "float", 1.4, 1.3, 1.5, 0.1)

    rows = generate_neighbors(Candidate({"x": 1.4}), (spec,), (), {})

    assert [row.parameters for row in rows] == [{"x": 1.3}, {"x": 1.5}]
    assert all(type(row.parameters["x"]) is float for row in rows)


def test_bool_is_not_toggled_and_parameter_order_does_not_change_output():
    x = ParameterSpec("x", "x", "int", 2, 1, 3, 1)
    y = ParameterSpec("y", "y", "int", 5, 4, 6, 1)
    flag = ParameterSpec("flag", "Flag", "bool", True)
    center = Candidate({"x": 2, "y": 5, "flag": True})

    forward = generate_neighbors(center, (x, y, flag), (), {})
    reverse = generate_neighbors(center, (flag, y, x), (), {})

    assert [row.key for row in forward] == [row.key for row in reverse]
    assert all(row.parameters["flag"] is True for row in forward)
    assert len(forward) == 4


def test_cross_parameter_constraints_filter_neighbors_and_limit_is_stable():
    fast = ParameterSpec("fast", "Fast", "int", 2, 1, 3, 1)
    slow = ParameterSpec("slow", "Slow", "int", 3, 2, 4, 1)
    constraint = {"left": "fast", "op": "lt", "right": "slow"}

    rows = generate_neighbors(
        Candidate({"fast": 2, "slow": 3}),
        (slow, fast),
        (constraint,),
        {},
        limit=2,
    )

    assert [row.parameters for row in rows] == [
        {"fast": 1, "slow": 3},
        {"fast": 2, "slow": 4},
    ]


def test_integer_neighborhood_is_empty_at_upper_boundary():
    spec = ParameterSpec("x", "x", "int", 3, 1, 3, 1)

    rows = generate_neighbors(Candidate({"x": 3}), (spec,), (), {})

    assert [row.parameters for row in rows] == [{"x": 2}]
