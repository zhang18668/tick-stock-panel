from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import PLUGIN_DIR


def test_air_refueling_loads_as_custom_plugin() -> None:
    plugin_dir = PLUGIN_DIR
    strategy = StrategyEngine(strategy_dirs=[plugin_dir]).get("air_refueling")

    assert strategy.source == "custom"
    assert strategy.meta["visibility_group"] == "tianya"
    assert len(strategy.meta["params"]) == 21
    defaults = {item["id"]: item["default"] for item in strategy.meta["params"]}
    assert strategy.meta["version"] == "3.5.0"
    assert strategy.meta["execution_entry_fill"] == "close_t"
    assert strategy.meta["stop_loss_trigger"] == "close"
    assert strategy.basic_filter["boards"] == ["沪主板", "深主板"]
    assert strategy.stop_loss == -0.10
    assert strategy.take_profit == 0.30
    assert strategy.max_hold_days == 20
    assert defaults["signal_mode"] == "breakout"
    assert defaults["streak_mode"] == "higher_close"
    assert defaults["min_consolidation_days"] == 7
    assert defaults["max_consolidation_days"] == 15
    assert defaults["max_amplitude_pct"] == 15.0
    assert defaults["max_average_volume_ratio"] == 1.10
    assert defaults["close_support_tolerance_pct"] == 3.0
    assert defaults["late_volume_ratio"] == 1.30
    assert defaults["breakout_pct"] == 0.0
    assert defaults["confirmation_max_gain_pct"] == 4.0
    assert defaults["breakout_volume_ratio"] == 0.0
