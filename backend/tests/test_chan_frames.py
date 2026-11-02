import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.chan_analysis import analyze, iter_chan_frames
from tests.test_chan_analysis import bars


def test_daily_frames_equal_independent_prefixes_without_future_data():
    data = bars(150)
    dates = {"2025-03-11", "2025-04-10", "2025-05-30"}
    frames = dict(iter_chan_frames(data, "day", observed_dates=dates))
    for day in dates:
        prefix = [r for r in data if r["date"] <= day]
        assert frames[day] == analyze(prefix, "day")
    assert len(frames["2025-03-11"]["rows"]) == 70
    assert all(s["end"]["date"] <= "2025-03-11" for s in frames["2025-03-11"]["structures"])


def test_weekly_frames_match_prefixes_including_partial_weeks():
    data = bars(150)
    dates = {"2025-03-10", "2025-03-11", "2025-03-16", "2025-04-10"}
    frames = dict(iter_chan_frames(data, "week", observed_dates=dates))
    for day in dates:
        assert frames[day] == analyze([r for r in data if r["date"] <= day], "week")


def test_no_invented_dates_and_cancel_stops_iteration():
    data = bars(30)
    event = threading.Event()
    iterator = iter_chan_frames(data, "day", observed_dates={r["date"] for r in data}, cancel_event=event)
    assert next(iterator)[0] == "2025-01-01"
    event.set()
    assert list(iterator) == []
    assert list(iter_chan_frames([], "day", observed_dates={"2025-01-01"})) == []
    assert list(iter_chan_frames(data, "day", observed_dates={"2026-01-01"})) == []


def test_current_incomplete_day_is_not_an_observed_frame():
    now = datetime(2025, 1, 30, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = dict(iter_chan_frames(bars(30), "day", observed_dates={"2025-01-29", "2025-01-30"}, now=now))
    assert list(result) == ["2025-01-29"]
