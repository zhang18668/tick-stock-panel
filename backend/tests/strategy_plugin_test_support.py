import sys
from pathlib import Path

from app.strategy.engine import StrategyEngine

PLUGIN_DIR = Path(__file__).parents[2] / "data/strategies/custom"


def load_plugin_module(name):
    StrategyEngine._load_file(PLUGIN_DIR / f"{name}.py")
    return sys.modules[name]
