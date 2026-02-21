"""
Content analyzer tool — readability, tone, and structure analysis.

Pure Python implementation using standard library. Provides agents with
quantitative metrics to evaluate and improve written content.
"""

import math
import re
import logging
from collections import Counter

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.content_analyzer")

# Tone indicators — word lists for simple tone classification
_FORMAL_INDICATORS = {
    "therefore", "consequently", "furthermore", "moreover", "hereby",
    "pursuant", "accordingly", "notwithstanding", "whereas", "henceforth",
    "thus", "indeed", "nevertheless", "regarding", "pertaining",
}
_INFORMAL_INDICATORS = {
    "awesome", "cool", "gonna", "wanna", "gotta", "hey", "yeah", "nope",
    "btw", "lol", "ok", "okay", "stuff", "things", "kinda", "sorta",
    "basically", "literally", "super", "totally",
}
_PERSUASIVE_INDICATORS = {
    "free", "guaranteed", "proven", "exclusive", "limited", "now",
    "instant", "discover", "unlock", "transform", "imagine", "you",
    "your", "save", "boost", "increase", "secret", "powerful", "easy",
    "best", "new", "revolutionary",
}


class ContentAnalyzerTool(Tool):
    """Analyze text content for readability, tone, structure, and keywords."""

    @property
    def name(self) -> str:
        return "content_analyzer"

    @property
    def description(self) -> str:
        return (
            "Analyze text for readability (Flesch-Kincaid), tone (formal/informal/persuasive), "
            "structure (headings, paragraphs), keywords (frequency), compare two versions, "
            "and SEO analysis. "
            "Actions: readability, tone, structure, keywords, compare, seo."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["readability", "tone", "structure", "keywords", "compare", "seo"],
                    "description": "Analysis action",
                },
                "text": {
                    "type": "string",
                    "description": "Text to analyze",
                    "default": "",
                },
                "text_b": {
                    "type": "string",
                    "description": "Second text for compare action",
                    "default": "",
                },
                "top_n": {
                    "type": "integer",
                    "description": "Number of top keywords to return (default 15)",
                    "default": 15,
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "",
        text: str = "",
        text_b: str = "",
        top_n: int = 15,
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="action is required", success=False)
        if not text:
            return ToolResult(error="text is required", success=False)

        if action == "readability":
            return self._readability(text)
        elif action == "tone":
            return self._tone(text)
        elif action == "structure":
            return self._structure(text)
        elif action == "keywords":
            return self._keywords(text, top_n)
        elif action == "compare":
            if not text_b:
                return ToolResult(error="text_b is required for compare", success=False)
            return self._compare(text, text_b)
        elif action == "seo":
            return self._seo(text)
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    @staticmethod
    def _count_syllables(word: str) -> int:
        """Estimate syllable count for English words."""
        word = word.lower().strip()
        if not word:
            return 0
        if len(word) <= 3:
            return 1

        # Remove silent e
        if word.endswith("e"):
            word = word[:-1]

        # Count vowel groups
        count = len(re.findall(r"[aeiouy]+", word))
        return max(count, 1)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Split text into words."""
        return re.findall(r"[a-zA-Z']+", text)

    @staticmethod
    def _sentences(text: str) -> list[str]:
        """Split text into sentences."""
        sents = re.split(r"[.!?]+", text)
        return [s.strip() for s in sents if s.strip()]

    def _readability(self, text: str) -> ToolResult:
        words = self._tokenize(text)
        sentences = self._sentences(text)

        if not words or not sentences:
            return ToolResult(output="Text too short for readability analysis.")

        word_count = len(words)
        sentence_count = len(sentences)
        syllable_count = sum(self._count_syllables(w) for w in words)

        avg_sentence_len = word_count / sentence_count
        avg_syllables = syllable_count / word_count

        # Flesch Reading Ease
        fre = 206.835 - (1.015 * avg_sentence_len) - (84.6 * avg_syllables)
        fre = round(max(0, min(100, fre)), 1)

        # Flesch-Kincaid Grade Level
        fkgl = (0.39 * avg_sentence_len) + (11.8 * avg_syllables) - 15.59
        fkgl = round(max(0, fkgl), 1)

        # Reading level label
        if fre >= 80:
            level = "Easy (6th grade)"
        elif fre >= 60:
            level = "Standard (8th-9th grade)"
        elif fre >= 40:
            level = "Moderate (10th-12th grade)"
        elif fre >= 20:
            level = "Difficult (college level)"
        else:
            level = "Very Difficult (graduate level)"

        # Estimated reading time (avg 238 wpm)
        reading_mins = math.ceil(word_count / 238)

        output = (
            f"# Readability Analysis\n\n"
            f"| Metric | Value |\n"
            f"|--------|-------|\n"
            f"| Words | {word_count} |\n"
            f"| Sentences | {sentence_count} |\n"
            f"| Avg sentence length | {avg_sentence_len:.1f} words |\n"
            f"| Avg syllables/word | {avg_syllables:.2f} |\n"
            f"| Flesch Reading Ease | {fre} / 100 |\n"
            f"| Flesch-Kincaid Grade | {fkgl} |\n"
            f"| Reading Level | {level} |\n"
            f"| Est. Reading Time | {reading_mins} min |\n"
        )
        return ToolResult(output=output)

    def _tone(self, text: str) -> ToolResult:
        words = set(w.lower() for w in self._tokenize(text))
        total = max(len(words), 1)

        formal_count = len(words & _FORMAL_INDICATORS)
        informal_count = len(words & _INFORMAL_INDICATORS)
        persuasive_count = len(words & _PERSUASIVE_INDICATORS)

        formal_pct = round(formal_count / total * 100, 1)
        informal_pct = round(informal_count / total * 100, 1)
        persuasive_pct = round(persuasive_count / total * 100, 1)

        # Determine dominant tone
        scores = {"Formal": formal_count, "Informal": informal_count, "Persuasive": persuasive_count}
        dominant = max(scores, key=scores.get) if any(scores.values()) else "Neutral"

        formal_words = sorted(words & _FORMAL_INDICATORS)
        informal_words = sorted(words & _INFORMAL_INDICATORS)
        persuasive_words = sorted(words & _PERSUASIVE_INDICATORS)

        output = (
            f"# Tone Analysis\n\n"
            f"**Dominant Tone:** {dominant}\n\n"
            f"| Tone | Indicator Count | % of unique words |\n"
            f"|------|----------------|-------------------|\n"
            f"| Formal | {formal_count} | {formal_pct}% |\n"
            f"| Informal | {informal_count} | {informal_pct}% |\n"
            f"| Persuasive | {persuasive_count} | {persuasive_pct}% |\n\n"
        )
        if formal_words:
            output += f"**Formal indicators:** {', '.join(formal_words)}\n"
        if informal_words:
            output += f"**Informal indicators:** {', '.join(informal_words)}\n"
        if persuasive_words:
            output += f"**Persuasive indicators:** {', '.join(persuasive_words)}\n"

        return ToolResult(output=output)

    def _structure(self, text: str) -> ToolResult:
        lines = text.split("\n")
        headings = [l for l in lines if l.strip().startswith("#")]
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        blank_lines = sum(1 for l in lines if not l.strip())

        # Paragraph length distribution
        para_lengths = [len(self._tokenize(p)) for p in paragraphs]
        avg_para = sum(para_lengths) / max(len(para_lengths), 1)

        # List items
        list_items = len(re.findall(r"^[\s]*[-*•]\s", text, re.MULTILINE))
        numbered_items = len(re.findall(r"^[\s]*\d+[.)]\s", text, re.MULTILINE))

        # Links and emphasis
        links = len(re.findall(r"\[.+?\]\(.+?\)", text))
        bold = len(re.findall(r"\*\*.+?\*\*", text))
        italic = len(re.findall(r"(?<!\*)\*(?!\*).+?(?<!\*)\*(?!\*)", text))

        output = (
            f"# Structure Analysis\n\n"
            f"| Element | Count |\n"
            f"|---------|-------|\n"
            f"| Total lines | {len(lines)} |\n"
            f"| Headings | {len(headings)} |\n"
            f"| Paragraphs | {len(paragraphs)} |\n"
            f"| Avg paragraph length | {avg_para:.0f} words |\n"
            f"| Bullet list items | {list_items} |\n"
            f"| Numbered items | {numbered_items} |\n"
            f"| Links | {links} |\n"
            f"| Bold emphasis | {bold} |\n"
            f"| Italic emphasis | {italic} |\n\n"
        )

        if headings:
            output += "## Heading Hierarchy\n\n"
            for h in headings:
                level = len(h) - len(h.lstrip("#"))
                indent = "  " * (level - 1)
                output += f"{indent}- {h.strip()}\n"

        return ToolResult(output=output)

    def _keywords(self, text: str, top_n: int) -> ToolResult:
        # Common English stop words
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "is", "are", "was", "were",
            "be", "been", "being", "have", "has", "had", "do", "does", "did",
            "will", "would", "could", "should", "may", "might", "shall",
            "can", "it", "its", "this", "that", "these", "those", "i", "we",
            "you", "he", "she", "they", "me", "him", "her", "us", "them",
            "my", "your", "his", "our", "their", "not", "no", "so", "if",
            "as", "up", "out", "about", "into", "than", "then", "each",
            "all", "any", "both", "more", "most", "other", "some", "such",
        }

        words = [w.lower() for w in self._tokenize(text) if len(w) > 2]
        filtered = [w for w in words if w not in stop_words]
        freq = Counter(filtered)
        total = max(len(filtered), 1)

        top = freq.most_common(top_n)

        output = f"# Keyword Analysis (top {top_n})\n\n"
        output += "| Rank | Keyword | Count | Frequency |\n"
        output += "|------|---------|-------|----------|\n"
        for i, (word, count) in enumerate(top, 1):
            pct = round(count / total * 100, 1)
            output += f"| {i} | {word} | {count} | {pct}% |\n"

        output += f"\n**Total unique words:** {len(freq)}\n"
        output += f"**Total words (after filtering):** {total}\n"

        return ToolResult(output=output)

    def _compare(self, text_a: str, text_b: str) -> ToolResult:
        words_a = self._tokenize(text_a)
        words_b = self._tokenize(text_b)
        sents_a = self._sentences(text_a)
        sents_b = self._sentences(text_b)
        sylls_a = sum(self._count_syllables(w) for w in words_a)
        sylls_b = sum(self._count_syllables(w) for w in words_b)

        # Flesch Reading Ease for both
        def fre(words, sents, sylls):
            if not words or not sents:
                return 0
            asl = len(words) / len(sents)
            asw = sylls / len(words)
            return round(max(0, min(100, 206.835 - 1.015 * asl - 84.6 * asw)), 1)

        fre_a = fre(words_a, sents_a, sylls_a)
        fre_b = fre(words_b, sents_b, sylls_b)

        # Unique words comparison
        set_a = set(w.lower() for w in words_a)
        set_b = set(w.lower() for w in words_b)
        shared = set_a & set_b
        only_a = set_a - set_b
        only_b = set_b - set_a

        output = (
            f"# Content Comparison\n\n"
            f"| Metric | Version A | Version B | Delta |\n"
            f"|--------|-----------|-----------|-------|\n"
            f"| Words | {len(words_a)} | {len(words_b)} | {len(words_b) - len(words_a):+d} |\n"
            f"| Sentences | {len(sents_a)} | {len(sents_b)} | {len(sents_b) - len(sents_a):+d} |\n"
            f"| Flesch Reading Ease | {fre_a} | {fre_b} | {fre_b - fre_a:+.1f} |\n"
            f"| Unique words | {len(set_a)} | {len(set_b)} | {len(set_b) - len(set_a):+d} |\n\n"
            f"**Shared vocabulary:** {len(shared)} words\n"
            f"**Only in A:** {len(only_a)} words\n"
            f"**Only in B:** {len(only_b)} words\n"
        )

        return ToolResult(output=output)

    def _seo(self, text: str) -> ToolResult:
        """SEO analysis: keyword density, heading structure, meta description check."""
        words = self._tokenize(text)
        lines = text.split("\n")
        headings = [l.strip() for l in lines if l.strip().startswith("#")]

        word_count = len(words)
        if word_count == 0:
            return ToolResult(output="Text too short for SEO analysis.")

        # Keyword density (top terms)
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "is", "are", "was", "were",
            "be", "been", "being", "have", "has", "had", "do", "does", "did",
            "will", "would", "could", "should", "may", "might", "shall",
            "can", "it", "its", "this", "that", "these", "those", "i", "we",
            "you", "he", "she", "they", "not", "no", "so", "if", "as",
        }
        filtered = [w.lower() for w in words if w.lower() not in stop_words and len(w) > 2]
        freq = Counter(filtered)
        top_keywords = freq.most_common(10)

        # Heading structure analysis
        h1_count = sum(1 for h in headings if h.startswith("# ") and not h.startswith("## "))
        h2_count = sum(1 for h in headings if h.startswith("## ") and not h.startswith("### "))
        h3_count = sum(1 for h in headings if h.startswith("### "))

        # Check first paragraph as potential meta description
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
        meta_candidate = paragraphs[0] if paragraphs else ""
        meta_length = len(meta_candidate)
        meta_ok = 120 <= meta_length <= 160

        # Internal links
        links = re.findall(r"\[.+?\]\(.+?\)", text)
        internal_links = [l for l in links if not re.search(r"\(https?://", l)]
        external_links = [l for l in links if re.search(r"\(https?://", l)]

        # Image alt text check
        images = re.findall(r"!\[([^\]]*)\]\(", text)
        images_without_alt = sum(1 for alt in images if not alt.strip())

        # Content length assessment
        if word_count < 300:
            length_verdict = "Too short (aim for 800+ words)"
        elif word_count < 800:
            length_verdict = "Short (consider expanding to 1000+ words)"
        elif word_count < 1500:
            length_verdict = "Good length"
        elif word_count < 3000:
            length_verdict = "Strong length for SEO"
        else:
            length_verdict = "Comprehensive (good for pillar content)"

        output = (
            f"# SEO Analysis\n\n"
            f"## Content Metrics\n\n"
            f"| Metric | Value | Assessment |\n"
            f"|--------|-------|------------|\n"
            f"| Word count | {word_count} | {length_verdict} |\n"
            f"| H1 headings | {h1_count} | {'Good (1)' if h1_count == 1 else 'Should be exactly 1'} |\n"
            f"| H2 headings | {h2_count} | {'Good' if h2_count >= 2 else 'Add more H2 sections'} |\n"
            f"| H3 headings | {h3_count} | {'Good' if h3_count > 0 else 'Consider adding H3 subsections'} |\n"
            f"| Internal links | {len(internal_links)} | {'Good' if internal_links else 'Add internal links'} |\n"
            f"| External links | {len(external_links)} | {'Good' if external_links else 'Consider adding references'} |\n"
            f"| Images | {len(images)} | {'Good' if images else 'Add images'} |\n"
            f"| Images missing alt text | {images_without_alt} | {'Good' if images_without_alt == 0 else 'Add alt text'} |\n\n"
        )

        # Meta description
        output += f"## Meta Description\n\n"
        if meta_candidate:
            output += f"**Candidate (first paragraph):** {meta_candidate[:200]}\n"
            output += f"**Length:** {meta_length} chars "
            if meta_ok:
                output += "(ideal: 120-160)\n"
            elif meta_length < 120:
                output += f"(too short, add {120 - meta_length} chars)\n"
            else:
                output += f"(too long, trim {meta_length - 160} chars)\n"
        else:
            output += "No meta description candidate found. Add a descriptive first paragraph.\n"

        # Top keywords
        output += f"\n## Keyword Density (top 10)\n\n"
        output += "| Keyword | Count | Density |\n"
        output += "|---------|-------|---------|\n"
        for kw, count in top_keywords:
            density = round(count / len(filtered) * 100, 1) if filtered else 0
            ideal = "good" if 1.0 <= density <= 3.0 else ("low" if density < 1.0 else "high")
            output += f"| {kw} | {count} | {density}% ({ideal}) |\n"

        # SEO checklist
        issues = []
        if h1_count != 1:
            issues.append("Use exactly one H1 heading")
        if h2_count < 2:
            issues.append("Add at least 2 H2 subheadings for scannability")
        if word_count < 800:
            issues.append("Expand content to at least 800 words")
        if not internal_links:
            issues.append("Add internal links to related content")
        if images_without_alt > 0:
            issues.append(f"Add alt text to {images_without_alt} image(s)")
        if not meta_ok and meta_candidate:
            issues.append("Adjust first paragraph length to 120-160 chars for meta description")

        if issues:
            output += "\n## SEO Improvements\n\n"
            for issue in issues:
                output += f"- {issue}\n"
        else:
            output += "\n**SEO looks good!** All basic checks passed.\n"

        return ToolResult(output=output)
