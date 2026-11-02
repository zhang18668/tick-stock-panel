from copy import deepcopy

import pytest

from app.chan_review.store import ChanReviewArchive


def frame(day="2025-01-10", labels=("B1", "B1p", "B2", "B2s", "B3a", "B3b")):
    point = {"date": "2025-01-03", "price": 10, "index": 0}
    return {
        "rows": [{"date": "2025-01-03", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100}],
        "structures": [{"id": label, "kind": "signal", "label": label, "start": point, "end": point,
                        "confirmedAt": None, "observedAt": day, "basis": "fixture"} for label in labels],
        "observed_as_of": day, "asOf": day, "period": "day", "warnings": [], "ruleVersion": "test",
        "engine": {"name": "chan.py", "revision": "revision-a", "config": {"bi_strict": True}},
    }


def save(store, day, labels=("B1",), run="run-a", owner="alice", source="backfill"):
    value = frame(day, labels)
    inp = store.save_input(owner, value["rows"])
    result = store.save_observation(owner, run, "600000.SH", "浦发银行", source, value, inp, day == "2025-01-10")
    store.publish_run(owner, run, {"complete": True})
    return result


def test_classes_pagination_original_subtypes_and_repeated_runs(tmp_path):
    store = ChanReviewArchive(tmp_path)
    save(store, "2025-01-10", ("B1", "B1p", "B2", "B2s", "B3a", "B3b"))
    save(store, "2025-01-10", ("B1", "B1p", "B2", "B2s", "B3a", "B3b"), run="run-b")
    result = store.list_signals("alice", {"source": "backfill", "category": "1"}, 1, 1)
    assert result["total"] == 2
    assert result["counts"] == {"1": 2, "2": 2, "3": 2}
    assert result["items"][0]["point_type"] in {"1", "1p"}
    assert result["items"][0]["left_censored"] is True
    assert len(store.list_signals("alice", {"source": "backfill"}, 1, 100)["items"]) == 6


def test_disappeared_signal_remains_and_reappearance_has_a_new_episode(tmp_path):
    store = ChanReviewArchive(tmp_path)
    save(store, "2025-01-10")
    save(store, "2025-01-13", run="run-b")
    # Failed scan writes no successful observation: it must not close an episode.
    store.publish_run("alice", "failed-run", {"complete": False, "failed": 1})
    result = store.list_signals("alice", {}, 1, 30)["items"]
    assert len(result) == 1 and result[0]["last_seen"] == "2025-01-13"
    save(store, "2025-01-14", (), run="run-c")
    assert store.list_signals("alice", {}, 1, 30)["items"][0]["status"] == "not_seen"
    save(store, "2025-01-15", run="run-d")
    result = store.list_signals("alice", {}, 1, 30)
    assert result["total"] == 2
    assert result["items"][0]["first_seen"] == "2025-01-15"


def test_original_snapshot_does_not_depend_on_later_market_or_rule_changes(tmp_path):
    store = ChanReviewArchive(tmp_path)
    save(store, "2025-01-10")
    item = store.list_signals("alice", {}, 1, 30)["items"][0]
    original = store.get_snapshot("alice", item["snapshot_id"])
    updated = deepcopy(frame())
    updated["engine"]["revision"] = "revision-b"
    updated["rows"][0]["close"] = 10.5
    store.save_observation("alice", "other", "600000.SH", "浦发银行", "backfill", updated, store.save_input("alice", updated["rows"]), False)
    store.publish_run("alice", "other", {"complete": True})
    assert store.get_snapshot("alice", item["snapshot_id"]) == original
    assert original["rows"][0]["close"] == 10
    assert store.get_signal("alice", item["id"])["point_type"] == "1"
    assert store.list_signals("bob", {}, 1, 30)["total"] == 0
    with pytest.raises(KeyError):
        store.get_snapshot("bob", item["snapshot_id"])


def test_inputs_are_deduplicated_and_paths_are_constrained(tmp_path):
    store = ChanReviewArchive(tmp_path)
    value = frame()["rows"]
    assert store.save_input("alice", value) == store.save_input("alice", value)
    with pytest.raises(ValueError):
        store.get_snapshot("alice", "../outside")
    with pytest.raises(ValueError):
        store.save_observation("alice", "../escape", "600000.SH", "name", "backfill", frame(), "bad", False)


def test_unpublished_work_is_invisible_and_sources_do_not_merge(tmp_path):
    store = ChanReviewArchive(tmp_path)
    value = frame()
    store.save_observation("alice", "pending", "600000.SH", "name", "backfill", value, store.save_input("alice", value["rows"]), False)
    assert store.list_signals("alice", {}, 1, 30)["total"] == 0
    save(store, "2025-01-10", source="observed", run="observed")
    save(store, "2025-01-10", source="backfill", run="backfill")
    assert store.list_signals("alice", {"source": "observed"}, 1, 30)["total"] == 1
    assert store.list_signals("alice", {"source": "backfill"}, 1, 30)["total"] == 1


def test_revised_observations_keep_the_original_and_offer_archived_versions(tmp_path):
    store = ChanReviewArchive(tmp_path)
    save(store, "2025-01-10")
    first = store.list_signals("alice", {}, 1, 30)["items"][0]
    value = frame()
    value["rows"][0]["close"] = 10.5
    inp = store.save_input("alice", value["rows"])
    store.save_observation("alice", "revision", "600000.SH", "浦发银行", "backfill", value, inp, True)
    store.publish_run("alice", "revision", {"partial": True})
    detail = store.get_signal("alice", first["id"])
    assert detail["snapshot_id"] == first["snapshot_id"]
    assert len(detail["observations"]) == 2
    assert {store.get_snapshot("alice", v["snapshot_id"])["rows"][0]["close"] for v in detail["observations"]} == {10, 10.5}


def test_real_engine_first_second_third_buys_round_trip(tmp_path):
    import random
    from datetime import date, timedelta

    from app.services.chan_analysis import analyze

    rng, value, rows = random.Random(2), 100, []
    for i in range(500):
        value = max(10, value + rng.uniform(-4, 4) + .03)
        rows.append(dict(date=str(date(2020, 1, 1) + timedelta(days=i)), open=value, high=value + 1,
                         low=value - 1, close=value + .3, volume=1000))
    computed = analyze(rows, "day")
    assert {"B1", "B2", "B3a"} <= {s["label"] for s in computed["structures"] if s["kind"] == "signal"}
    store = ChanReviewArchive(tmp_path)
    store.save_observation("alice", "engine", "600000.SH", "fixture", "backfill", computed,
                           store.save_input("alice", rows), False)
    store.publish_run("alice", "engine", {"partial": False})
    result = store.list_signals("alice", {}, 1, 100)
    assert all(result["counts"][c] > 0 for c in ("1", "2", "3"))
    for item in result["items"]:
        snapshot = store.get_snapshot("alice", item["snapshot_id"])
        assert snapshot["structures"] == computed["structures"]


def test_same_day_corrected_absence_keeps_original_as_not_seen(tmp_path):
    store = ChanReviewArchive(tmp_path)
    save(store, "2025-01-10")
    first = store.list_signals("alice", {}, 1, 30)["items"][0]
    save(store, "2025-01-10", (), run="corrected")
    result = store.get_signal("alice", first["id"])
    assert result["status"] == "not_seen"


def test_queries_use_materialized_index_not_replay_all_observations(tmp_path, monkeypatch):
    store = ChanReviewArchive(tmp_path)
    save(store, "2025-01-10")
    item = store.list_signals("alice", {}, 1, 30)["items"][0]
    def no_replay(*args):
        raise AssertionError("HTTP reads must not replay all raw observations")
    monkeypatch.setattr(store, "_episodes", no_replay)
    assert store.list_signals("alice", {"start": "2025-01-10", "category": "1"}, 1, 1)["total"] == 1
    assert store.get_signal("alice", item["id"])["point_type"] == "1"
    assert store.get_snapshot("alice", item["snapshot_id"])["rows"]
