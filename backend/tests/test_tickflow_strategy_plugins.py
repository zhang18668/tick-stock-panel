import shutil

from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import PLUGIN_DIR

IMPORTED_IDS = {'three_yang_breakout', 'air_refueling', 'board_pullback_late', 'limit_up_double_volume_bearish', 'double_limit_up_ma5_reclaim', 'triple_volume_bullish_first_breakout', 'limit_up_bull_chip', 'board_pullback_first', 'limit_up_ma10_volume_reversal', 'night_grass_close_enhanced', 'three_armies_cannon', 'overnight_dragon', 'limit_up_breakout_retest', 'triple_volume_ma_spread', 'board_pullback_midpoint', 'board_pullback_reclaim5', 'double_line_high_multiple', 'board_pullback_shallow', 'board_pullback_kdj', 'double_dragon_playing_water', 'board_pullback_macd', 'board_pullback_volume', 'double_limit_up_golden_pullback', 'limit_up_bearish_volume_ma_startup', 'leader_first_bearish_ma5_ma10', 'platform_breakout', 'board_pullback_trend', 'board_pullback_ma10', 'double_limit_up_cannon', 'gap_up_recoil', 'magpies_on_plum', 'board_pullback_deep', 'strategy_520', 'board_pullback_momentum', 'left_peak_volume_retest', 'custom_msnabhqp', 'concave_multi_cannon', 'strategy_2560', 'double_volume_bullish_breakout', 'triple_volume_pullback_double_bull', 'limit_up_ma_consolidation_breakout'}


def test_imported_pack_shares_registry_without_duplicates():
    builtin = PLUGIN_DIR.parents[2] / "backend/app/strategy/builtin"
    original = StrategyEngine([builtin])
    combined = StrategyEngine([builtin, PLUGIN_DIR])
    assert not original.load_errors()
    assert not combined.load_errors()
    definitions = combined.strategy_definitions()
    assert {s.meta["id"] for s in definitions} == {
        s.meta["id"] for s in original.strategy_definitions()
    } | IMPORTED_IDS
    assert all(combined.get(sid).source == "custom" for sid in IMPORTED_IDS)
    assert len({s.meta["name"] for s in definitions}) == len(definitions)


def test_strategy_can_be_disabled_and_restored_by_reload(tmp_path):
    active = tmp_path / "custom"
    active.mkdir()
    path = active / "strategy_520.py"
    shutil.copy2(PLUGIN_DIR / path.name, path)
    engine = StrategyEngine([active])
    assert engine.has("strategy_520")
    disabled = active / "_strategy_520.py"
    path.rename(disabled)
    engine.reload()
    assert not engine.has("strategy_520")
    disabled.rename(path)
    engine.reload()
    assert engine.has("strategy_520")
    assert not engine.load_errors()
