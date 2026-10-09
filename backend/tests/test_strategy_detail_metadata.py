from app.api.strategy import _strategy_detail
from app.strategy.engine import StrategyDef


def _strategy(meta: dict) -> StrategyDef:
    return StrategyDef(
        meta=meta,
        basic_filter={},
        entry_signals=["signal_entry"],
        exit_signals=["signal_exit"],
        stop_loss=-0.08,
        trailing_stop=None,
        trailing_take_profit_activate=None,
        trailing_take_profit_drawdown=None,
        max_hold_days=10,
        filter_fn=None,
        filter_history_fn=None,
        lookback_days=60,
        source="builtin",
        execution_backend="matrix_native",
    )


def test_strategy_detail_exposes_declared_rules_and_execution_contract():
    detail = _strategy_detail(
        _strategy(
            {
                "id": "known_builtin",
                "name": "已知策略",
                "rules": ["收盘价站上 20 日均线", {"condition": "量比 >= 1.5"}],
                "asset_types": ["stock"],
                "timeframes": ["1d"],
                "matching": "close_t",
                "minute_fill": True,
            }
        )
    )

    assert detail["rules"] == ["收盘价站上 20 日均线", {"condition": "量比 >= 1.5"}]
    assert detail["execution"] == {
        "backend": "matrix_native",
        "asset_types": ["stock"],
        "timeframes": ["1d"],
        "entry_signals": ["signal_entry"],
        "exit_signals": ["signal_exit"],
        "matching": "close_t",
        "entry_fill": None,
        "exit_fill": None,
        "minute_fill": True,
        "stop_loss": -0.08,
        "take_profit": None,
        "trailing_stop": None,
        "trailing_take_profit_activate": None,
        "trailing_take_profit_drawdown": None,
        "max_hold_days": 10,
    }


def test_strategy_detail_without_metadata_keeps_existing_contract():
    detail = _strategy_detail(_strategy({"id": "legacy_builtin", "name": "旧策略"}))

    assert detail["id"] == "legacy_builtin"
    assert detail["name"] == "旧策略"
    assert detail["description"] == ""
    assert detail["rules"] == []
    assert detail["execution"]["backend"] == "matrix_native"
    assert detail["execution"]["timeframes"] == ["1d"]
    assert detail["execution"]["minute_fill"] is False
