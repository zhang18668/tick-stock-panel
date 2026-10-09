from app.strategy_optimizer.scoring import score_candidates, select_top_candidates


def test_scoring_excludes_missing_metrics_and_hard_gate_failures():
    rows = [
        {
            "parameters": {"x": 1},
            "oos_metrics": {
                "oos_return": 0.4,
                "drawdown_improvement": -0.8,
                "win_rate": 0.7,
                "trade_count": 30,
            },
        },
        {
            "parameters": {"x": 2},
            "oos_metrics": {
                "oos_return": 0.3,
                "drawdown_improvement": -0.2,
                "win_rate": 0.6,
                "trade_count": 30,
            },
        },
        {
            "parameters": {"x": 3},
            "oos_metrics": {"oos_return": 0.2, "drawdown_improvement": -0.1, "win_rate": 0.6},
        },
    ]
    ranked = score_candidates(rows, max_drawdown=0.5, min_trades=5)
    assert [row["parameters"]["x"] for row in ranked] == [2]


def test_top_selection_deduplicates_parameter_and_signal_pairs():
    rows = [
        {"parameters": {"x": 1}, "buy_signals": ["a"], "sell_signals": [], "score": 0.9},
        {"parameters": {"x": 1}, "buy_signals": ["a"], "sell_signals": [], "score": 0.8},
        {"parameters": {"x": 2}, "buy_signals": ["a"], "sell_signals": [], "score": 0.7},
    ]
    assert len(select_top_candidates(rows)) == 2
