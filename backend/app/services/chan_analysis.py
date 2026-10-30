"""Stateless chart adapter for the pinned chan.py engine; no duplicated Chan rules."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.vendor.chanpy.ChanConfig import CChanConfig
from app.vendor.chanpy.Common.CEnum import DATA_FIELD, FX_TYPE, KL_TYPE
from app.vendor.chanpy.Common.CTime import CTime
from app.vendor.chanpy.KLine.KLine_List import CKLine_List
from app.vendor.chanpy.KLine.KLine_Unit import CKLine_Unit
from app.vendor.chanpy.Math.MACD import CMACD

REVISION = "f8ca3b5e44d7166e2abd756a8e7fa816c79faebe"
ENGINE_CONFIG = {
    "trigger_step": True,
    "bi_strict": True,
    "seg_algo": "chan",
    "zs_algo": "normal",
    "zs_combine": True,
    "divergence_rate": 0.9,
    "macd_algo": "peak",
    "bs_type": "1,1p,2,2s,3a,3b",
    "print_warning": False,
    "print_err_time": False,
}


class ChanBar(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="ignore")
    date: date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def check_prices(self):
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("K线高低价必须包含开收盘价")
        return self


def _weekly(rows: list[dict]) -> list[dict]:
    result: list[dict] = []
    last_week = None
    for row in rows:
        day = date.fromisoformat(row["date"])
        week = day - timedelta(days=day.weekday())
        if week != last_week:
            result.append(dict(row))
            last_week = week
        else:
            current = result[-1]
            current.update(date=row["date"], high=max(current["high"], row["high"]),
                           low=min(current["low"], row["low"]), close=row["close"],
                           volume=current["volume"] + row["volume"])
    return result


def _point(klu, price: float) -> dict:
    return {"date": klu.time.toDateStr("-"), "price": price, "index": klu.idx}


def _snapshot(engine: CKLine_List, seen: dict, observed_at: str) -> list[dict]:
    structures: list[dict] = []

    def append(kind, start, end, sure, label, basis, **extra):
        # Geometry is part of the key: extensions/merged centers must not inherit
        # an earlier version's confirmation date.
        key = (kind, label, start["date"], start["price"], end["date"], end["price"], extra.get("low"), extra.get("high"))
        if sure:
            seen.setdefault(key, observed_at)
        structures.append({"id": ":".join(map(str, key)), "kind": kind, "start": start, "end": end,
                           "confirmedAt": seen[key] if sure else None, "observedAt": observed_at,
                           "label": label, "basis": basis, **extra})

    for klc in engine:
        if klc.fx == FX_TYPE.UNKNOWN:
            continue
        top = klc.fx == FX_TYPE.TOP
        p = _point(klc.get_peak_klu(is_high=top), klc.high if top else klc.low)
        append("fractal", p, p, True, "顶" if top else "底", "chan.py 合并K线分型，右侧K线形成后确认")
    for kind, lines in [("stroke", engine.bi_list), ("segment", engine.seg_list)]:
        for line in lines:
            append(kind, _point(line.get_begin_klu(), line.get_begin_val()), _point(line.get_end_klu(), line.get_end_val()),
                   line.is_sure, ("上行" if line.is_up() else "下行") + ("笔" if kind == "stroke" else "线段"),
                   f"chan.py {'严格笔' if kind == 'stroke' else 'chan 特征序列线段'}；确认状态沿用引擎 is_sure")
    for i, zs in enumerate(engine.zs_list):
        append("center", _point(zs.begin, zs.low), _point(zs.end, zs.high), zs.is_sure,
               f"ZS{i + 1}", "chan.py 笔中枢；normal 算法、允许重叠中枢合并；上下沿直接读取引擎",
               low=zs.low, high=zs.high)
    # Public CBS_Point has no own is_sure flag. A sure underlying stroke alone
    # does not establish an immutable signal: expose all as current-frame shapes.
    for bsp in engine.bs_point_lst.bsp_iter():
        features = {k: v for k, v in bsp.features.items() if isinstance(v, (int, float)) and math.isfinite(v)}
        for bs_type in bsp.type:
            label = ("B" if bsp.is_buy else "S") + bs_type.value
            append("signal", _point(bsp.bi.get_begin_klu(), bsp.bi.get_begin_val()), _point(bsp.klu, bsp.bi.get_end_val()),
                   False, label, "chan.py 当前帧形态学买卖点，公开对象无独立确认标记；新增K线后可能变化或消失",
                   features=features)
    return structures


def analyze(rows: list[dict], period: Literal["day", "week"], *, now: datetime | None = None) -> dict:
    normalized = [ChanBar.model_validate(row).model_dump(mode="json") for row in rows]
    if len(normalized) > 2000:
        raise ValueError("最多分析2000根日K线")
    if any(a["date"] >= b["date"] for a, b in pairwise(normalized)):
        raise ValueError("K线日期必须严格递增且不能重复")
    chart_rows = _weekly(normalized) if period == "week" else normalized
    metric = CMACD()
    for row in chart_rows:
        m = metric.add(row["close"])
        row.update(macd_dif=m.DIF, macd_dea=m.DEA, macd_hist=m.macd)
    engine = CKLine_List(KL_TYPE.K_WEEK if period == "week" else KL_TYPE.K_DAY, CChanConfig(dict(ENGINE_CONFIG)))
    now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    warnings = ["买卖点为当前帧形态信号，可能变化；不等同于已确认交易指令"]
    # The last weekly aggregate may contain a partial week (holiday calendars
    # aren't inferred here). It remains on the chart but cannot confirm rules.
    evidence = chart_rows
    if period == "week" and chart_rows:
        evidence = chart_rows[:-1]
        warnings.append("最后一周保守视为未完成，仅展示K线，不作为结构确认依据")
    elif chart_rows and chart_rows[-1]["date"] == str(now.date()) and (now.hour, now.minute) < (15, 30):
        evidence = chart_rows[:-1]
        warnings.append("当日K线尚未定版，仅展示，不作为结构确认依据")
    seen: dict = {}
    structures: list[dict] = []
    previous = None
    # Under the conservative weekly policy a completed week's OHLC only enters
    # evidence when the first bar of the next week exists. Record that actual
    # availability date, not the earlier weekly candle label, for confirmation.
    next_daily_date = {a["date"]: b["date"] for a, b in pairwise(normalized)}
    observed_at = None
    for i, row in enumerate(evidence):
        day = date.fromisoformat(row["date"])
        unit = CKLine_Unit({**row, DATA_FIELD.FIELD_TIME: CTime(day.year, day.month, day.day, 0, 0, auto=False)})
        unit.set_idx(i)
        unit.kl_type = engine.kl_type
        unit.set_pre_klu(previous)
        previous = unit
        engine.add_single_klu(unit)
        observed_at = next_daily_date[row["date"]] if period == "week" else row["date"]
        structures = _snapshot(engine, seen, observed_at)
    return {"rows": chart_rows, "structures": structures, "warnings": warnings,
            "asOf": observed_at,
            "ruleVersion": "chan.py · strict / chan / normal",
            "engine": {"name": "chan.py", "revision": REVISION, "config": ENGINE_CONFIG}}
