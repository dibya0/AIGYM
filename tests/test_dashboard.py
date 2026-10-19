"""Dashboard build test (brief Phase 06): built from real (baseline) result files, no network."""

import json
import re

import pytest

pytest.importorskip("jinja2")
pytest.importorskip("verifiers")

from paygym.dashboard.build import build  # noqa: E402
from paygym.eval.runner import main as eval_main  # noqa: E402


def test_dashboard_builds_from_result_files(tmp_path):
    results, public = tmp_path / "results", tmp_path / "public"
    for name in ("naive_no_ceiling", "always_abstain", "format_only"):
        eval_main(["--model", f"baseline/{name}", "--n-seeds", "12", "--rollouts", "2", "--out", str(results), "--run-name", "r"])
    index = build(results, public)
    html = index.read_text()
    raw = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)
    data = json.loads(raw)
    assert len(data["main_runs"]) == 3 and all(r["is_baseline"] for r in data["main_runs"])
    assert data["heatmap"]["tasks"] and len(data["heatmap"]["z"]) == 3
    for run in data["main_runs"]:
        transcript = json.loads((public / run["transcript_file"]).read_text())
        assert transcript["rollouts"] and transcript["expected"]
    for section in ('id="verdict"', 'id="leaderboard"', 'id="heatmap"', 'id="cost"', 'id="transcripts"', 'id="rl"', 'id="trackc"'):
        assert section in html
    assert "</script" not in raw  # embedded data cannot close its script tag
    assert set(data["distribution"]) == {r["model"] for r in data["main_runs"]}  # P02: score distribution shown
    assert (public / "quickstart.py").exists()  # P08: one-command quickstart, no clone


def test_transcript_view_handles_real_tool_call_shapes():
    """Real verifiers transcripts store each tool call as a JSON string; the first build on real results
    crashed on it (synthetic test transcripts used dicts)."""
    from paygym.dashboard.build import _last_assistant

    completion = [{"role": "assistant", "content": "", "tool_calls": ['{"id": "c1", "name": "lookup_rules", "arguments": "{}"}',
                                                                      {"function": {"name": "calc", "arguments": "{}"}}]},
                  {"role": "tool", "content": "rates"}, {"role": "assistant", "content": "final"}]
    steps = _last_assistant(completion)["steps"]
    assert [s.get("name") for s in steps if s["type"] == "tool_call"] == ["lookup_rules", "calc"]
    assert steps[-1] == {"type": "assistant", "text": "final"}
    assert _last_assistant("plain text")["steps"][0]["text"] == "plain text"
