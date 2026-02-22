"""Tests for agents/model_researcher.py — benchmark research."""

from agents.model_researcher import ModelResearcher


class TestModelResearcher:
    """Tests for ModelResearcher benchmark data handling."""

    def test_init_empty(self, tmp_path):
        researcher = ModelResearcher(research_path=tmp_path / "research.json")
        assert researcher.get_scores() == {}
        assert researcher.needs_research() is True

    def test_cache_roundtrip(self, tmp_path):
        """Scores should persist across save/load cycles."""
        research_path = tmp_path / "research.json"

        r1 = ModelResearcher(research_path=research_path)
        r1._scores = {
            "test/model": {"coding": 0.9, "reasoning": 0.8, "writing": 0.7, "general": 0.85}
        }
        r1._last_research = 1000.0
        r1._save_cache()

        r2 = ModelResearcher(research_path=research_path)
        assert len(r2.get_scores()) == 1
        assert r2.get_score("test/model", "coding") == 0.9

    def test_get_score_exact_match(self, tmp_path):
        researcher = ModelResearcher(research_path=tmp_path / "r.json")
        researcher._scores = {
            "meta-llama/llama-4-maverick": {
                "coding": 0.8,
                "reasoning": 0.7,
            }
        }
        assert researcher.get_score("meta-llama/llama-4-maverick", "coding") == 0.8

    def test_get_score_partial_match(self, tmp_path):
        researcher = ModelResearcher(research_path=tmp_path / "r.json")
        researcher._scores = {
            "meta-llama/llama-4-maverick": {
                "coding": 0.8,
            }
        }
        # Partial match
        assert researcher.get_score("llama-4-maverick", "coding") == 0.8

    def test_get_score_missing(self, tmp_path):
        researcher = ModelResearcher(research_path=tmp_path / "r.json")
        assert researcher.get_score("nonexistent", "coding") == 0.5  # Neutral default

    def test_get_score_missing_capability(self, tmp_path):
        researcher = ModelResearcher(research_path=tmp_path / "r.json")
        researcher._scores = {"test/model": {"coding": 0.9}}
        assert researcher.get_score("test/model", "writing") == 0.5  # Default

    def test_needs_research_after_interval(self, tmp_path):
        researcher = ModelResearcher(
            research_path=tmp_path / "r.json",
            interval_hours=0.001,
        )
        researcher._scores = {"m": {"coding": 0.5}}
        researcher._last_research = 0.0
        assert researcher.needs_research() is True

    def test_parse_scores_valid_json(self):
        response = '{"model/a": {"coding": 0.9, "reasoning": 0.8}}'
        scores = ModelResearcher._parse_scores(response)
        assert "model/a" in scores
        assert scores["model/a"]["coding"] == 0.9

    def test_parse_scores_json_block(self):
        response = 'Here are the scores:\n```json\n{"model/a": {"coding": 0.9}}\n```\nDone.'
        scores = ModelResearcher._parse_scores(response)
        assert "model/a" in scores

    def test_parse_scores_clamps_values(self):
        response = '{"model/a": {"coding": 1.5, "reasoning": -0.3}}'
        scores = ModelResearcher._parse_scores(response)
        assert scores["model/a"]["coding"] == 1.0
        assert scores["model/a"]["reasoning"] == 0.0

    def test_parse_scores_invalid_json(self):
        scores = ModelResearcher._parse_scores("not json at all")
        assert scores == {}

    def test_parse_scores_filters_invalid_caps(self):
        response = '{"model/a": {"coding": 0.9, "invalid_cap": 0.5}}'
        scores = ModelResearcher._parse_scores(response)
        assert "coding" in scores["model/a"]
        assert "invalid_cap" not in scores["model/a"]
