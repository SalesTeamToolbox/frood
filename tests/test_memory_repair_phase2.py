"""Phase 2 tests: LLM judge + semantic/supersede checks.

Uses a stub router for llm_judge so no live API is exercised.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from memory.repair.checks import (
    conflict_supersede_check,
    semantic_duplicate_check,
)
from memory.repair.llm_judge import _parse_judgment, judge
from memory.repair.models import LLMJudgment


@dataclass
class _StubPair:
    a: Path
    b: Path
    a_text: str
    b_text: str
    similarity: float


def _write(path: Path, body: str, mtime: float) -> None:
    path.write_text(body, encoding="utf-8")
    import os

    os.utime(path, (mtime, mtime))


class _FakeRouter:
    """Minimal ConsolidationRouter stand-in for llm_judge tests."""

    def __init__(self, response: str, has_providers: bool = True):
        self._response = response
        self.has_providers = has_providers
        self.calls: list[tuple[str, list[dict]]] = []

    async def complete(self, model: str, messages: list[dict]) -> tuple[str, str]:
        self.calls.append((model, messages))
        return self._response, "fake_provider"


class TestParseJudgment:
    def test_valid_supersede_json(self):
        raw = (
            'Some prose before.\n{"verdict": "supersede", "rationale": "newer wins", '
            '"confidence": 0.92, "keeper_target": "new.md"}'
        )
        j = _parse_judgment(raw, "openrouter")
        assert j.verdict == "supersede"
        assert j.confidence == 0.92
        assert j.keeper_target == "new.md"
        assert j.provider == "openrouter"

    def test_missing_json_returns_none_verdict(self):
        j = _parse_judgment("I refuse to output JSON", "fake")
        assert j.verdict == "none"

    def test_malformed_json_returns_none_verdict(self):
        j = _parse_judgment('{"verdict": "supersede", "rationale": missing-quotes}', "fake")
        assert j.verdict == "none"

    def test_invalid_verdict_falls_to_none(self):
        j = _parse_judgment('{"verdict": "nuke", "rationale": "x", "confidence": 0.5}', "fake")
        # Pydantic Literal rejects "nuke", falls back to parse-failed state
        assert j.verdict == "none"


class TestJudge:
    @pytest.mark.asyncio
    async def test_no_providers_returns_none(self):
        router = _FakeRouter('{"verdict": "supersede"}', has_providers=False)
        j = await judge("supersede", "a.md", "aa", "b.md", "bb", router=router)
        assert j.verdict == "none"
        assert router.calls == []

    @pytest.mark.asyncio
    async def test_supersede_roundtrip(self):
        router = _FakeRouter(
            '{"verdict": "supersede", "rationale": "B newer and contradicts A", '
            '"confidence": 0.88, "keeper_target": "new.md"}'
        )
        j = await judge("supersede", "new.md", "newer text", "old.md", "older text", router=router)
        assert j.verdict == "supersede"
        assert j.keeper_target == "new.md"
        assert j.provider == "fake_provider"

    @pytest.mark.asyncio
    async def test_router_failure_degrades_to_none(self):
        class BoomRouter:
            has_providers = True

            async def complete(self, model, messages):
                raise RuntimeError("providers down")

        j = await judge("merge", "a.md", "aa", "b.md", "bb", router=BoomRouter())
        assert j.verdict == "none"


class TestSemanticDuplicateCheck:
    def test_emits_delete_above_auto_threshold(self, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        _write(a, "body A", mtime=1000.0)
        _write(b, "body B", mtime=2000.0)
        pairs = [_StubPair(a=a, b=b, a_text="A", b_text="B", similarity=0.97)]
        ops = semantic_duplicate_check("claude_code", pairs, auto_threshold=0.95)
        assert len(ops) == 1
        assert ops[0].kind == "delete_file"
        assert ops[0].target == b  # newer mtime wins deletion
        assert ops[0].extra["keeper"] == str(a)
        assert ops[0].decided_by == "deterministic"

    def test_skips_below_auto_threshold(self, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        _write(a, "body A", mtime=1000.0)
        _write(b, "body B", mtime=2000.0)
        pairs = [_StubPair(a=a, b=b, a_text="A", b_text="B", similarity=0.90)]
        assert semantic_duplicate_check("claude_code", pairs, auto_threshold=0.95) == []


class TestConflictSupersedeCheck:
    @pytest.mark.asyncio
    async def test_llm_supersede_emits_flagged_op(self, tmp_path, monkeypatch):
        a = tmp_path / "older.md"
        b = tmp_path / "newer.md"
        _write(a, "older body", mtime=1000.0)
        _write(b, "newer body", mtime=2000.0)
        pairs = [_StubPair(a=a, b=b, a_text="older", b_text="newer", similarity=0.88)]

        async def fake_judge(kind, a_target, a_text, b_target, b_text, router=None):
            return LLMJudgment(
                verdict="supersede",
                rationale="newer contradicts older",
                confidence=0.9,
                keeper_target=a_target,
                provider="stub",
            )

        monkeypatch.setattr("memory.repair.checks.judge", fake_judge, raising=False)
        # Patch the lazy import inside conflict_supersede_check
        import memory.repair.llm_judge as llmj

        monkeypatch.setattr(llmj, "judge", fake_judge)

        ops = await conflict_supersede_check(
            "claude_code", pairs, auto_threshold=0.95, flag_threshold=0.85
        )
        assert len(ops) == 1
        op = ops[0]
        assert op.kind == "mark_superseded"
        assert op.decided_by == "llm"
        assert op.target == a  # the older file
        assert op.extra["keeper"] == str(b)
        assert op.extra["llm_provider"] == "stub"

    @pytest.mark.asyncio
    async def test_llm_none_verdict_emits_nothing(self, tmp_path, monkeypatch):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        _write(a, "a", mtime=1000.0)
        _write(b, "b", mtime=2000.0)
        pairs = [_StubPair(a=a, b=b, a_text="a", b_text="b", similarity=0.88)]

        async def fake_judge(kind, a_target, a_text, b_target, b_text, router=None):
            return LLMJudgment(verdict="none", rationale="no conflict", provider="stub")

        import memory.repair.llm_judge as llmj

        monkeypatch.setattr(llmj, "judge", fake_judge)

        ops = await conflict_supersede_check(
            "claude_code", pairs, auto_threshold=0.95, flag_threshold=0.85
        )
        assert ops == []

    @pytest.mark.asyncio
    async def test_pair_outside_threshold_range_is_skipped(self, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        _write(a, "a", mtime=1000.0)
        _write(b, "b", mtime=2000.0)
        # similarity 0.97 belongs to semantic_duplicate_check, not supersede
        pairs = [_StubPair(a=a, b=b, a_text="a", b_text="b", similarity=0.97)]
        ops = await conflict_supersede_check(
            "claude_code", pairs, auto_threshold=0.95, flag_threshold=0.85
        )
        assert ops == []
