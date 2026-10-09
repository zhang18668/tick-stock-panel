from datetime import date

import pytest

from app.strategy_optimizer.contracts import (
    ParameterSpec,
    StrategyOptimizationContract,
)
from app.strategy_optimizer.validation import validate_run_config


def test_valid_contract_and_run_config_are_normalized():
    contract = StrategyOptimizationContract(
        strategy_id="demo",
        name="Demo",
        asset_type="stock",
        parameters=(ParameterSpec("window", "Window", "int", 10, minimum=2, maximum=30, step=1),),
        buy_signals=("buy_a",),
        sell_signals=("sell_a",),
    )
    config = validate_run_config(
        {
            "strategy_id": "demo",
            "asset_type": "stock",
            "start": "2025-01-01",
            "end": "2025-03-01",
            "parameters": {"window": {"min": 5, "max": 20, "step": 5}},
            "buy_signals": ["buy_a"],
            "sell_signals": ["sell_a"],
            "seed": 7,
        },
        contract,
    )
    assert config.start == date(2025, 1, 1)
    assert config.parameters["window"] == {"min": 5, "max": 20, "step": 5}


def test_invalid_contract_and_unknown_fields_are_rejected():
    with pytest.raises(ValueError, match="default"):
        StrategyOptimizationContract(
            strategy_id="demo",
            name="Demo",
            asset_type="stock",
            parameters=(
                ParameterSpec("window", "Window", "int", 40, minimum=2, maximum=30, step=1),
            ),
        )
    contract = StrategyOptimizationContract(
        strategy_id="demo",
        name="Demo",
        asset_type="stock",
        parameters=(ParameterSpec("window", "Window", "int", 10, minimum=2, maximum=30, step=1),),
    )
    with pytest.raises(ValueError, match="unknown field"):
        validate_run_config(
            {
                "strategy_id": "demo",
                "asset_type": "stock",
                "start": "2025-01-01",
                "end": "2025-02-01",
                "parameters": {},
                "extra": 1,
            },
            contract,
        )
