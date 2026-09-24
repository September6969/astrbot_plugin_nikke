from __future__ import annotations

import inspect
import tempfile

from astrbot_plugin_nikke.core.storage import NikkeStore


def test_store_exposes_generic_run_queries_not_cdk_key_interpretation() -> None:
    assert hasattr(NikkeStore, "list_runs")
    assert not hasattr(NikkeStore, "get_legacy_cdk_runs")
    source = inspect.getsource(NikkeStore)
    assert "DISPATCH_INTENT" not in source
    assert "UNKNOWN_AFTER_ACTION" not in source
    assert '"cdk:"' not in source


def test_run_state_transitions_are_supplied_by_the_consumer() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = NikkeStore(directory)

        assert store.claim_run(
            "key-one", "user-one", "cdk", initial_status="consumer_intent"
        )
        assert store.get_run("key-one")["status"] == "consumer_intent"

        assert store.finish_run("key-one", "retryable") is None
        assert store.transition_run(
            "key-one",
            from_statuses={"retryable"},
            to_status="consumer_intent_v2",
            refresh_created_at=True,
        )
        assert store.get_run("key-one")["status"] == "consumer_intent_v2"

        assert store.transition_run(
            "key-one",
            from_statuses={"consumer_intent_v2"},
            to_status="consumer_unknown",
            stale_after=0,
            detail="uncertain",
        )
        assert store.get_run("key-one")["status"] == "consumer_unknown"
        assert store.list_runs(action="cdk")[0]["run_key"] == "key-one"
        assert store.list_runs(action="daily") == []


def test_binding_session_states_are_supplied_by_the_consumer() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = NikkeStore(directory)
        store.create_bind_session("token-one", "user-one", status="consumer_pending")
        assert store.get_bind_session("token-one")["status"] == "consumer_pending"

        store.fail_bind_session("token-one", "safe detail", status="consumer_failed")
        assert store.get_bind_session("token-one")["status"] == "consumer_failed"
