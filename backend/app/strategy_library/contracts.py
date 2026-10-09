from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum


class BacktestPeriod(StrEnum):
    THREE_MONTHS = "3m"
    SIX_MONTHS = "6m"
    TWELVE_MONTHS = "12m"

    @property
    def months(self) -> int:
        return {self.THREE_MONTHS: 3, self.SIX_MONTHS: 6, self.TWELVE_MONTHS: 12}[self]


class StrategyLibraryTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class BacktestWindow:
    period: BacktestPeriod
    requested_start: date
    requested_end: date
    actual_start: date | None = None
    actual_end: date | None = None
    availability: str = "pending"
    reason: str | None = None


@dataclass(frozen=True)
class StrategyGroup:
    id: str
    name: str
    order: int
    strategy_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict) -> StrategyGroup:
        group_id = value.get("id")
        name = value.get("name")
        order = value.get("order", 0)
        strategy_ids = value.get("strategy_ids", [])
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError("group id must be a non-empty string")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("group name must be a non-empty string")
        if type(order) is not int:
            raise ValueError("group order must be an integer")
        if not isinstance(strategy_ids, (list, tuple)) or any(
            not isinstance(strategy_id, str) or not strategy_id.strip()
            for strategy_id in strategy_ids
        ):
            raise ValueError("strategy_ids must contain non-empty strings")
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("strategy_ids must be unique within a group")
        return cls(group_id.strip(), name.strip(), order, tuple(strategy_ids))

    def to_dict(self) -> dict:
        return {**asdict(self), "strategy_ids": list(self.strategy_ids)}


@dataclass(frozen=True)
class StrategyResultSummary:
    period: BacktestPeriod
    actual_start: date | None = None
    actual_end: date | None = None
    status: str = "completed"
    reason: str | None = None
    total_return: float | None = None
    max_drawdown: float | None = None
    sharpe: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    benchmark_return: float | None = None
    excess_return: float | None = None
    trade_count: int | None = None
    config_fingerprint: str | None = None
    source_fingerprint: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict, period: BacktestPeriod | None = None) -> StrategyResultSummary:
        selected_period = period or BacktestPeriod(value["period"])
        return cls(
            period=selected_period,
            actual_start=_as_date(value.get("actual_start")),
            actual_end=_as_date(value.get("actual_end")),
            status=str(value.get("status", "completed")),
            reason=value.get("reason") if isinstance(value.get("reason"), str) else None,
            total_return=_as_number(value.get("total_return")),
            max_drawdown=_as_number(value.get("max_drawdown")),
            sharpe=_as_number(value.get("sharpe")),
            win_rate=_as_number(value.get("win_rate")),
            profit_factor=_as_number(value.get("profit_factor")),
            benchmark_return=_as_number(value.get("benchmark_return")),
            excess_return=_as_number(value.get("excess_return")),
            trade_count=_as_int(value.get("trade_count")),
            config_fingerprint=_as_string(value.get("config_fingerprint")),
            source_fingerprint=_as_string(value.get("source_fingerprint")),
            updated_at=_as_string(value.get("updated_at")),
        )

    def to_dict(self) -> dict:
        value = asdict(self)
        for key in ("actual_start", "actual_end"):
            if value[key] is not None:
                value[key] = value[key].isoformat()
        return value


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _as_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _as_int(value) -> int | None:
    if type(value) is int:
        return value
    return None


def _as_string(value) -> str | None:
    return value if isinstance(value, str) else None


@dataclass
class StrategyLibraryTaskItem:
    strategy_id: str
    period: BacktestPeriod
    window: BacktestWindow
    status: str = "queued"
    attempts: int = 0
    progress: dict | None = None
    reason: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "period": self.period.value,
            "window": {
                "period": self.window.period.value,
                "requested_start": self.window.requested_start.isoformat(),
                "requested_end": self.window.requested_end.isoformat(),
                "actual_start": self.window.actual_start.isoformat()
                if self.window.actual_start else None,
                "actual_end": self.window.actual_end.isoformat() if self.window.actual_end else None,
                "availability": self.window.availability,
                "reason": self.window.reason,
            },
            "status": self.status,
            "attempts": self.attempts,
            "progress": self.progress,
            "reason": self.reason,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, value: dict) -> StrategyLibraryTaskItem:
        raw_window = value["window"]
        window = BacktestWindow(
            period=BacktestPeriod(raw_window["period"]),
            requested_start=date.fromisoformat(raw_window["requested_start"]),
            requested_end=date.fromisoformat(raw_window["requested_end"]),
            actual_start=_as_date(raw_window.get("actual_start")),
            actual_end=_as_date(raw_window.get("actual_end")),
            availability=str(raw_window.get("availability", "pending")),
            reason=_as_string(raw_window.get("reason")),
        )
        return cls(
            strategy_id=str(value["strategy_id"]),
            period=BacktestPeriod(value["period"]),
            window=window,
            status=str(value.get("status", "queued")),
            attempts=max(0, int(value.get("attempts", 0))),
            progress=value.get("progress") if isinstance(value.get("progress"), dict) else None,
            reason=_as_string(value.get("reason")),
            started_at=_as_string(value.get("started_at")),
            completed_at=_as_string(value.get("completed_at")),
        )


@dataclass
class StrategyLibraryTask:
    id: str
    user_id: str
    state: StrategyLibraryTaskStatus
    created_at: str
    updated_at: str
    items: list[StrategyLibraryTaskItem]
    strategy_configs: dict[str, dict] = field(default_factory=dict)
    current_strategy_id: str | None = None
    current_period: BacktestPeriod | None = None
    cancel_requested: bool = False
    error: str | None = None

    def item(
        self, strategy_id: str, period: BacktestPeriod
    ) -> StrategyLibraryTaskItem | None:
        return next(
            (
                item for item in self.items
                if item.strategy_id == strategy_id and item.period == BacktestPeriod(period)
            ),
            None,
        )

    def to_dict(self, *, include_user: bool = True) -> dict:
        value = {
            "id": self.id,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "items": [item.to_dict() for item in self.items],
            "strategy_configs": self.strategy_configs,
            "current_strategy_id": self.current_strategy_id,
            "current_period": self.current_period.value if self.current_period else None,
            "cancel_requested": self.cancel_requested,
            "error": self.error,
        }
        if include_user:
            value["user_id"] = self.user_id
        return value

    @classmethod
    def from_dict(cls, value: dict) -> StrategyLibraryTask:
        return cls(
            id=str(value["id"]),
            user_id=str(value.get("user_id", "standalone")),
            state=StrategyLibraryTaskStatus(value["state"]),
            created_at=str(value["created_at"]),
            updated_at=str(value.get("updated_at", value["created_at"])),
            items=[StrategyLibraryTaskItem.from_dict(item) for item in value.get("items", [])],
            strategy_configs=(
                value.get("strategy_configs")
                if isinstance(value.get("strategy_configs"), dict) else {}
            ),
            current_strategy_id=_as_string(value.get("current_strategy_id")),
            current_period=(
                BacktestPeriod(value["current_period"])
                if value.get("current_period") else None
            ),
            cancel_requested=bool(value.get("cancel_requested", False)),
            error=_as_string(value.get("error")),
        )
