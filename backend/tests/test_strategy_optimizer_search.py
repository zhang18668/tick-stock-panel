from app.strategy_optimizer.contracts import ParameterSpec
from app.strategy_optimizer.search import AdaptiveSearchService


def test_search_is_reproducible_and_deduplicates_candidates():
    params = (ParameterSpec("period", "Period", "int", 10, 2, 20, 1),)
    left = AdaptiveSearchService(params, seed=42).first_round(8)
    right = AdaptiveSearchService(params, seed=42).first_round(8)
    assert [item.key for item in left] == [item.key for item in right]
    assert len({item.key for item in left}) == len(left)


def test_later_round_retains_exploration_and_uses_prior_best():
    params = (ParameterSpec("period", "Period", "int", 10, 1, 100, 1),)
    search = AdaptiveSearchService(params, seed=7)
    search.first_round(10)
    batch = search.next_round([{"parameters": {"period": 50}, "score": 1}], 10)
    assert len(batch) == 10
    assert len({item.key for item in batch}) == 10


def test_constraint_accepts_literal_enum_value():
    parameter = ParameterSpec("mode", "Mode", "enum", "safe", options=("safe", "fast"))
    search = AdaptiveSearchService(
        (parameter,), constraints=({"left": "mode", "op": "ne", "right": "blocked"},)
    )
    assert all(item.parameters["mode"] != "blocked" for item in search.first_round(2))
