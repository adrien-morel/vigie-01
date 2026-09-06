import json

import pytest

import backend.guardrails as guardrails


def test_calls_under_limit_are_allowed_and_counted(monkeypatch):
    monkeypatch.setattr(guardrails, "MAX_LLM_CALLS_PER_DAY", 2)

    guardrails.check_and_increment_llm_call()
    guardrails.check_and_increment_llm_call()

    assert guardrails.remaining_calls_today() == 0


def test_call_beyond_limit_raises_budget_exceeded(monkeypatch):
    monkeypatch.setattr(guardrails, "MAX_LLM_CALLS_PER_DAY", 1)

    guardrails.check_and_increment_llm_call()
    with pytest.raises(guardrails.BudgetExceeded):
        guardrails.check_and_increment_llm_call()


def test_counter_resets_on_new_day(persistence, monkeypatch):
    persistence._budget_file.write_text(json.dumps({"date": "2000-01-01", "calls": 1}), encoding="utf-8")
    monkeypatch.setattr(guardrails, "MAX_LLM_CALLS_PER_DAY", 1)

    assert guardrails.remaining_calls_today() == 1
    guardrails.check_and_increment_llm_call()  # stale date must be treated as a fresh day, not raise


def test_budget_survives_a_new_persistence_instance_on_the_same_storage(persistence, monkeypatch):
    """The counter lives in the storage, not in process memory: a restart must not reset the cap.
    That is what Cloud Run's ephemeral disk used to break."""
    from backend.memory.persistence import LocalFilePersistence, set_persistence

    monkeypatch.setattr(guardrails, "MAX_LLM_CALLS_PER_DAY", 1)
    guardrails.check_and_increment_llm_call()

    set_persistence(
        LocalFilePersistence(
            budget_file=persistence._budget_file,
            seen_file=persistence._seen_file,
            analyzed_file=persistence._analyzed_file,
        )
    )

    with pytest.raises(guardrails.BudgetExceeded):
        guardrails.check_and_increment_llm_call()


def test_calls_are_attributed_to_the_node_that_spent_them(monkeypatch):
    """The prerequisite for any arbitration of the budget split (docs/scoping.md §11): knowing which
    node consumed what. A global counter alone says a run was truncated, not by whom."""
    monkeypatch.setattr(guardrails, "MAX_LLM_CALLS_PER_DAY", 5)

    guardrails.check_and_increment_llm_call("analyze")
    guardrails.check_and_increment_llm_call("analyze")
    guardrails.check_and_increment_llm_call("verify")
    guardrails.check_and_increment_llm_call("thread")

    assert guardrails.calls_by_node() == {"analyze": 2, "verify": 1, "thread": 1}


def test_a_refused_call_is_not_charged_to_its_node(monkeypatch):
    """The refused reservation precedes the model call: it cost nothing. Charging it would make the
    node carry spending it never obtained, and would inflate its share in the arbitration."""
    monkeypatch.setattr(guardrails, "MAX_LLM_CALLS_PER_DAY", 1)

    guardrails.check_and_increment_llm_call("verify")
    with pytest.raises(guardrails.BudgetExceeded):
        guardrails.check_and_increment_llm_call("thread")

    assert guardrails.calls_by_node() == {"verify": 1}


def test_tally_is_per_run_while_the_daily_ceiling_is_not(monkeypatch):
    """reset_call_tally() bounds a per-run measurement; it must emphatically not reopen the day's
    cap, which is persistent — otherwise a second run would circumvent it by resetting itself."""
    monkeypatch.setattr(guardrails, "MAX_LLM_CALLS_PER_DAY", 1)

    guardrails.check_and_increment_llm_call("analyze")
    guardrails.reset_call_tally()

    assert guardrails.calls_by_node() == {}
    with pytest.raises(guardrails.BudgetExceeded):
        guardrails.check_and_increment_llm_call("analyze")
