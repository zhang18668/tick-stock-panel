from datetime import date, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market_time import cn_now


class ReviewRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["observed", "backfill"]
    period: Literal["day", "week"] = "day"
    scope: Literal["market", "watchlist", "symbols"] = "market"
    symbols: list[str] = Field(default_factory=list, max_length=10000)
    start: date
    end: date
    resume_from: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")

    @model_validator(mode="after")
    def validate_window(self):
        now = cn_now()
        if self.start > self.end or self.end > now.date():
            raise ValueError("日期范围无效或包含未来日期")
        if self.end == now.date() and now.time() < time(15, 30):
            raise ValueError("当天扫描须在北京时间15:30后运行")
        # A resume is authorized against the persisted owned request and data
        # fingerprint in jobs.create; it retains that task's observation date.
        if self.source == "observed" and not self.resume_from and not (self.start == self.end == now.date()):
            raise ValueError("实盘观测仅记录今天；历史日期请使用历史补算")
        return self
