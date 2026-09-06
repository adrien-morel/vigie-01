from backend import graph as graph_module


def test_build_graph_compiles_without_error():
    assert graph_module.build_graph() is not None


def test_build_graph_includes_verify_node():
    graph = graph_module.build_graph()
    assert "verify" in graph.get_graph().nodes


def test_run_pipeline_passes_max_steps_per_run_as_recursion_limit(monkeypatch):
    captured = {}

    class _FakeGraph:
        def invoke(self, state, config=None):
            captured["config"] = config
            return {"raw_items": [], "analyzed_items": [], "truncated": False}

    monkeypatch.setattr(graph_module, "build_graph", lambda: _FakeGraph())
    monkeypatch.setattr(graph_module, "MAX_STEPS_PER_RUN", 7)

    graph_module.run_pipeline()

    assert captured["config"] == {"recursion_limit": 7}


def test_run_pipeline_resets_the_submission_tally(monkeypatch):
    """Like the per-node split, the outcome of submitted items measures *one* run: the API serves
    /run without restarting, so two runs in the same process would accumulate their breakdowns."""
    from backend.agents import analyst

    class _FakeGraph:
        def invoke(self, state, config=None):
            return {"raw_items": [], "analyzed_items": [], "truncated": False}

    monkeypatch.setattr(graph_module, "build_graph", lambda: _FakeGraph())
    analyst._submissions[("a_source", "kept")] += 1

    graph_module.run_pipeline()

    assert analyst.submissions_by_source() == {}
