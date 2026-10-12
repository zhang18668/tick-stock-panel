"""`QuoteService.boot_check()` 的**启动决策 + 可观测性**回归测试。

背景(本机实测事故 2026-09-16): 面板 08:58 起, 直到用户 09:35:33 手动开启才有行情
⇒ 开盘后 6 分钟实时评估全空。根因 = 旧版 `stop()` 把 `realtime_quotes_enabled` 写成 False
(lifespan shutdown 也调 `stop`) ⇒ 次日 `boot_check()` 读到 False 就**静默不启动**,
且**一行日志都不打** ⇒ 排查只能靠排除法。

⚠️ 与本文件的分工:
  * `tests/test_realtime_preference_persistence.py` 管**根因**(`stop()` 不持久化 / `disable()` 才持久化)
    —— 上游已有该文件, 本文件**不重复**它的断言。
  * 本文件管 `boot_check()` **拿这个偏好做了什么决策**、**有没有留下痕迹**
    —— 上游此前对 `boot_check()` 本身**没有任何测试**
      (`test_data_integrity.py` 里那个同名 `boot_check` 是数据修复用的, ⛔ 不是本函数)。

当**档位允许**但**偏好为关**时, 服务必须保持关闭并留下一行日志, 以区分用户主动关闭与服务启动失败。

⚠️ 标点惯例: 本仓 `tests/` 共 288 个文件, 其中 271 个不含 RUF00x(全角标点)告警 ⇒ 本文件随多数派
  在**文档串/注释**里用 ASCII 标点(`(` `)` `,` `:` `;`), 以保持 `ruff check tests` 零新增。
"""
from __future__ import annotations

import logging

from app.services import preferences
from app.services.quote_service import QuoteService


def _make(monkeypatch, *, tier_allowed: bool, pref_enabled: bool):
    """构造一个不真启动线程的 QuoteService, 并返回 (qs, started 记录器)。"""
    monkeypatch.setattr(QuoteService, "is_realtime_allowed", classmethod(lambda cls: tier_allowed))
    monkeypatch.setattr(preferences, "get_realtime_quotes_enabled", lambda: pref_enabled)
    qs = QuoteService()
    started: list = []
    monkeypatch.setattr(qs, "start", lambda *a, **k: started.append(1))
    return qs, started


def test_starts_when_preference_enabled(monkeypatch):
    """⭐ 反向对照: 偏好为开且档位允许 ⇒ **必须**启动(防止把守卫写成「永远不启动」)。"""
    qs, started = _make(monkeypatch, tier_allowed=True, pref_enabled=True)
    qs.boot_check()
    assert started == [1], "偏好为开且档位允许时必须启动"


def test_does_not_start_when_preference_disabled(monkeypatch):
    """用户主动关闭并持久化的偏好必须在下次启动时继续生效。"""
    qs, started = _make(monkeypatch, tier_allowed=True, pref_enabled=False)
    qs.boot_check()
    assert started == [], "偏好为关时不应启动"


def test_logs_and_does_not_start_when_tier_disallows(monkeypatch, caplog):
    """档位 none ⇒ 不启动 **且必须留日志**(09-16 事故的教训: 静默不可排查)。"""
    qs, started = _make(monkeypatch, tier_allowed=False, pref_enabled=True)
    with caplog.at_level(logging.INFO, logger="app.services.quote_service"):
        qs.boot_check()
    assert started == [], "档位 none 时不应启动"
    msgs = [r.getMessage() for r in caplog.records]
    assert any("未启动" in m for m in msgs), f"档位不允许时必须留下可解析的日志行, 实际={msgs}"


def test_demotes_preference_when_tier_disallows(monkeypatch):
    """档位 none 且偏好为开 ⇒ 必须把偏好**同步写 False**(否则 UI 会误显示「已开启」)。"""
    saved: list[dict] = []
    monkeypatch.setattr(preferences, "save", lambda updates: saved.append(updates))
    qs, started = _make(monkeypatch, tier_allowed=False, pref_enabled=True)
    qs.boot_check()
    assert started == [], "档位 none 时不应启动"
    assert saved == [{"realtime_quotes_enabled": False}], f"应把偏好降级写回, 实际={saved}"


def test_preference_disabled_leaves_a_log(monkeypatch, caplog):
    """偏好为关且档位允许时不启动, 并留下可诊断日志。"""

    qs, started = _make(monkeypatch, tier_allowed=True, pref_enabled=False)
    with caplog.at_level(logging.INFO, logger="app.services.quote_service"):
        qs.boot_check()
    assert started == []
    msgs = [r.getMessage() for r in caplog.records]
    assert any("未启动" in m for m in msgs), f"偏好为关时也应留日志, 实际={msgs}"
