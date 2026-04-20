from bughound_agent import BugHoundAgent
from llm_client import MockClient


class SameCodeFixLLMClient:
    """
    Offline stub: valid analyzer JSON, but fix step echoes the original snippet.
    Mirrors the MockClient pattern (no network) to exercise the no-op fix guardrail.
    """

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if "Return ONLY valid JSON" in system_prompt:
            return '[{"type":"Maintainability","severity":"Low","msg":"cosmetic note"}]'
        if "Return ONLY the full rewritten Python code" in system_prompt:
            marker = "CODE:\n"
            if marker in user_prompt:
                return user_prompt.split(marker, 1)[1]
        return ""


def test_workflow_runs_in_offline_mode_and_returns_shape():
    agent = BugHoundAgent(client=None)  # heuristic-only
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    assert isinstance(result, dict)
    assert "issues" in result
    assert "fixed_code" in result
    assert "risk" in result
    assert "logs" in result

    assert isinstance(result["issues"], list)
    assert isinstance(result["fixed_code"], str)
    assert isinstance(result["risk"], dict)
    assert isinstance(result["logs"], list)
    assert len(result["logs"]) > 0


def test_offline_mode_detects_print_issue():
    agent = BugHoundAgent(client=None)
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    assert any(issue.get("type") == "Code Quality" for issue in result["issues"])


def test_offline_mode_proposes_logging_fix_for_print():
    agent = BugHoundAgent(client=None)
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    fixed = result["fixed_code"]
    assert "logging" in fixed
    assert "logging.info(" in fixed


def test_no_op_llm_fix_does_not_autofix():
    agent = BugHoundAgent(client=SameCodeFixLLMClient())
    code = "def add(a, b):\n    return a + b\n"
    result = agent.run(code)

    assert result["fixed_code"].strip() == code.strip()
    assert result["risk"]["should_autofix"] is False
    assert any("No code change despite" in r for r in result["risk"]["reasons"])


def test_mock_client_forces_llm_fallback_to_heuristics_for_analysis():
    # MockClient returns non-JSON for analyzer prompts, so agent should fall back.
    agent = BugHoundAgent(client=MockClient())
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    assert any(issue.get("type") == "Code Quality" for issue in result["issues"])
    # Ensure we logged the fallback path
    assert any("Falling back to heuristics" in entry.get("message", "") for entry in result["logs"])
