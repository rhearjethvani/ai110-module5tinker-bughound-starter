# BugHound Mini Model Card (Reflection)

This document reflects the current BugHound starter behavior, including offline (heuristic) operation, optional Gemini integration, and the guardrails added during the module (analyzer fallbacks, over-edit scoring, and no-op fix blocking).

---

## 1) What is this system?

**Name:** BugHound  

**Purpose:** Take a short Python snippet, scan it for issues, propose a single revised version of the code, score how risky that change is, and recommend whether a human should review it before anything is auto-applied.

**Intended users:** Students and instructors exploring agentic workflows: planning, tool use (LLM vs heuristics), acting on code, lightweight “testing” via risk rules, and reflecting on when automation is appropriate.

---

## 2) How does it work?

BugHound’s `BugHoundAgent.run` method implements a compact loop:

1. **Plan** — Logs intent to run a scan-and-fix workflow (no separate planner model).
2. **Analyze** — `analyze` either runs **heuristics** (keyword and regex checks for `print(`, bare `except:`, and `TODO`) or calls **Gemini** when a client is configured. If the API errors, returns empty text, or yields JSON the agent cannot trust (unparseable array, empty model text, or issues with no usable `msg` fields), the agent **falls back to heuristics** and logs why.
3. **Act** — `propose_fix` either applies **heuristic rewrites** (logging import, swap `print` for `logging.info`, widen bare `except`) or asks **Gemini** for a full rewritten file. Empty or unusable LLM output falls back to the heuristic fixer.
4. **Test** — `assess_risk` scores the diff using explicit rules (severity of reported issues, structural signals like removed `return`, large line growth, and whether the text actually changed).
5. **Reflect** — Logs whether `should_autofix` is true under policy (and the UI surfaces the trace).

**Heuristics vs Gemini:** With no client or heuristic-only mode in the Streamlit sidebar, all analysis and fixing uses offline rules. With `GeminiClient` and a valid `GEMINI_API_KEY`, the same methods call the model first; failures and malformed outputs route back to heuristics so the app stays usable within tight API quotas.

---

## 3) Inputs and outputs

**Inputs:**

- **`sample_code/cleanish.py`** — Small, mostly reasonable helper using `logging`.
- **`sample_code/mixed_issues.py`** — Combines `TODO`, `print`, and bare `except` in one function.
- **`sample_code/print_spam.py`** — Simple `print`-heavy snippet.
- **`sample_code/flaky_try_except.py`** — Demonstrates bare `except` swallowing errors.

Shapes ranged from a few lines (single function) to short multi-branch scripts with try/except.

**Outputs:**

- **Issues** — Objects with `type`, `severity`, and `msg`. Heuristics emit predictable categories (for example Code Quality for prints, Reliability for bare except, Maintainability for TODO). Gemini mode can surface broader findings when JSON is accepted.
- **Fixes** — Heuristic mode rewrites prints and bare except blocks in a template-like way; Gemini mode can rewrite the whole snippet (often more holistic, sometimes noisier).
- **Risk report** — Numeric `score`, categorical `level` (`low` / `medium` / `high`), human-readable `reasons`, and `should_autofix`. Large line-count growth and no-op fixes (code unchanged while issues remain) push toward human review.

---

## 4) Reliability and safety rules

At least two rules from `assess_risk` (see `reliability/risk_assessor.py`):

### Rule A: Issue severity deductions

- **What it checks:** Each reported issue’s `severity` string (`high`, `medium`, `low`) and subtracts a fixed chunk from the starting score of 100.
- **Why it matters:** Ties the auto-fix decision to how alarming the *declared* problems are. High-severity items should rarely sail through silently.
- **False positive:** If the analyzer invents or exaggerates severities, the score punishes a benign edit.
- **False negative:** If severities are always labeled “Low” for serious bugs, the score stays optimistic even when the code is dangerous.

### Rule B: Large line-count increase (over-edit signal)

- **What it checks:** When the fixed file has more than **12 additional lines** than the original (after stripping), the scorer applies an extra penalty and records a “possible over-edit” style reason.
- **Why it matters:** Agents that balloon files may be refactoring recklessly or pasting boilerplate; that deserves scrutiny before merge.
- **False positive:** Legitimate fixes that must add many lines (for example adding a docstring block and structured logging) get penalized even if correct.
- **False negative:** A rewrite that deletes logic while keeping line count similar is not caught by this rule alone.

### Rule C: No-op fix with open issues (guardrail)

- **What it checks:** If the original and fixed code are identical after stripping **but** the issue list is non-empty, `should_autofix` is forced to **False** and a reason explains that human review is required.
- **Why it matters:** Prevents “confident” automation when the model claimed problems yet produced no change (or the pipeline echoed the input).
- **False positive:** Rare edge case where issues are informational and intentionally leaving code unchanged is correct—still safer to have a human confirm.
- **False negative:** If the model makes a tiny cosmetic change that is effectively a no-op but not byte-identical, this exact rule does not fire.

---

## 5) Observed failure modes

1. **Missed issues (heuristic blind spots)** — Heuristics only flag `print(`, bare `except:`, and `TODO`. Code with resource leaks, incorrect logic, or missing validation (for example `sample_code/cleanish.py`) often receives **no issues** even though a human reviewer might want improvements. Gemini may catch more—when its JSON is accepted—but is not guaranteed.

2. **Risky or heavy-handed fixes** — The heuristic fixer blanket-replaces `print(` with `logging.info(` and injects `import logging` when it sees Code Quality issues, which can be wrong for CLI tools or scripts meant to print to stdout. Bare-except “fixes” insert a generic `except Exception as e:` placeholder that still may hide bugs if not completed thoughtfully.

---

## 6) Heuristic vs Gemini comparison

| Dimension | Heuristic mode | Gemini mode (when JSON/code responses are accepted) |
|-----------|----------------|--------------------------------------------------------|
| Detection | Narrow, deterministic signals | Can surface broader style, logic, or API misuse (depends on prompt and model) |
| Consistency | Same input → same issues | May vary run to run |
| Fixes | Small, pattern-based edits | May rewrite entire functions; can be more context-aware or over-edit |
| Risk scorer | Same `assess_risk` pipeline | Same pipeline, but issue lists (and severities) may differ, changing scores |
| Quota | Unlimited offline | Each “Run BugHound” uses API budget |

Heuristics reliably catch the three taught smells. Gemini can broaden coverage but introduces parse/structure failures that the agent must handle (empty responses, markdown fences, malformed JSON), which is why stricter acceptance and fallbacks matter.

---

## 7) Human-in-the-loop decision

**Scenario:** The analyzer reports high-severity reliability issues and the proposed fix touches exception handling or return paths, but the diff is hard to reason about quickly.

**Trigger:** Combine existing signals: **high severity issues**, **large line growth**, **bare-except modification notes**, or **no-op fix with open issues** (already blocks auto-fix). A practical addition would be a UI banner when `level != "low"` or when `should_autofix` is false: “BugHound will not auto-apply this change; review the diff before merging.”

**Where to implement:** Keep scoring rules in `risk_assessor.py` (single source of truth), optionally mirror a short summary string in `bughound_app.py` for visibility.

**User-facing message:** “Human review recommended: risk level {level}. Reasons: {bulleted reasons}.”

---

## 8) Improvement idea

**Load external prompt files instead of duplicating strings in code.** The repository already contains `prompts/analyzer_*.txt` and `prompts/fixer_*.txt`, but `bughound_agent.py` currently hardcodes similar instructions. Reading prompts from disk would let teams iterate on wording without touching Python, reduce drift between “documented” and “executed” prompts, and make A/B testing of constraints (JSON-only, minimal diff) safer and more measurable.
