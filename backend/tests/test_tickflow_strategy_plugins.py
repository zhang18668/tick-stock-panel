import shutil

from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import PLUGIN_DIR


def test_imported_pack_shares_registry_without_duplicates():
    builtin = PLUGIN_DIR.parents[2] / "backend/app/strategy/builtin"
    original = StrategyEngine([builtin])
    custom = StrategyEngine([PLUGIN_DIR])
    combined = StrategyEngine([builtin, PLUGIN_DIR])
    assert not original.load_errors()
    assert not custom.load_errors()
    assert not combined.load_errors()
    custom_ids = {strategy.meta["id"] for strategy in custom.strategy_definitions()}
    definitions = combined.strategy_definitions()
    assert {s.meta["id"] for s in definitions} == {
        s.meta["id"] for s in original.strategy_definitions()
    } | custom_ids
    assert all(combined.get(sid).source == "custom" for sid in custom_ids)
    assert len({s.meta["id"] for s in definitions}) == len(definitions)


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
