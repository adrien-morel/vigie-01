import os

# backend/config.py requires these at import time, with no defaults (fail-fast by design).
# Tests must not depend on a local .env, so set safe defaults before backend.* is imported.
os.environ.setdefault("MAX_STEPS_PER_RUN", "20")
os.environ.setdefault("MAX_LLM_CALLS_PER_DAY", "200")

import pytest  # noqa: E402  (must follow the env defaults above)


@pytest.fixture(autouse=True)
def persistence(tmp_path):
    """Isolates each test's persistent state in a temporary directory.

    Autouse and not optional: the LLM budget, the seen links and the analysed history are real files
    in the repository. A test that forgot to redirect them would corrupt the day's budget counter or
    the cross-check history — the kind of side effect you only notice once a digest is in production.
    """
    from backend import config
    from backend.agents.analyst import reset_submission_tally
    from backend.guardrails import reset_call_tally
    from backend.memory.persistence import LocalFilePersistence, set_persistence

    # Same reason as above, for the other state that survives a test: the per-node call split and the
    # outcome of submitted items live in module memory, so they leak from one test to the next unless
    # they are cleared.
    reset_call_tally()
    reset_submission_tally()

    # Full-text fetching makes real outbound HTTP requests: it is off by default in the suite, just as
    # the LLM and the RSS feeds are mocked. The tests that exercise it turn it back on and substitute
    # the transport (see tests/test_fetcher.py).
    config.FETCH_FULL_ARTICLE = False

    instance = LocalFilePersistence(
        budget_file=tmp_path / "budget.json",
        seen_file=tmp_path / "seen.json",
        analyzed_file=tmp_path / "history.json",
    )
    set_persistence(instance)
    yield instance
    set_persistence(None)
