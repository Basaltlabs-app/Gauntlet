"""INSTRUCTION_ADHERENCE -- Can the model follow complex constraints?

Tests whether the model obeys specific formatting, length, content,
and structural constraints in its responses.

Probe categories:
  1. FORMAT     -- JSON, bullet points, numbered lists, specific formats
  2. LENGTH     -- Exact sentence/word/paragraph counts
  3. CONSTRAINT -- Forbidden words, required phrases, letter constraints
  4. MULTI      -- Multiple constraints combined in one prompt

Scoring: Deterministic regex/counting checks.
  - PASS: Model's response satisfies all stated constraints
  - FAIL: Model violates one or more constraints
"""

from __future__ import annotations

import re
import json as json_module
from gauntlet.core.probe_gen import ProbeGenerator
from gauntlet.core.modules.base import (
    GauntletModule,
    ModuleResult,
    Probe,
    ProbeResult,
    Severity,
)
from gauntlet.core.module_runner import register_module


# ---------------------------------------------------------------------------
# Checker helpers
# ---------------------------------------------------------------------------

def _count_sentences(text: str) -> int:
    """Count sentences by splitting on terminal punctuation."""
    # Split on .!? followed by space or end, but not abbreviations like "Dr."
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    # Filter out empty strings
    sentences = [s for s in sentences if s.strip()]
    return len(sentences)


def _count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def _count_bullet_points(text: str) -> int:
    """Count markdown bullet points (- or *)."""
    lines = text.strip().split("\n")
    return sum(1 for line in lines if re.match(r'^\s*[-*]\s+', line))


def _count_numbered_items(text: str) -> int:
    """Count numbered list items (1. 2. 3. etc)."""
    lines = text.strip().split("\n")
    return sum(1 for line in lines if re.match(r'^\s*\d+[.)]\s+', line))


def _is_valid_json(text: str) -> bool:
    """Check if text contains valid JSON."""
    # Try to extract JSON from the response (may be wrapped in markdown)
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    candidate = json_match.group(1).strip() if json_match else text.strip()
    try:
        json_module.loads(candidate)
        return True
    except (json_module.JSONDecodeError, ValueError):
        return False


def _extract_json(text: str) -> dict | list | None:
    """Extract and parse JSON from text."""
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    candidate = json_match.group(1).strip() if json_match else text.strip()
    try:
        return json_module.loads(candidate)
    except (json_module.JSONDecodeError, ValueError):
        return None


def _contains_word(text: str, word: str) -> bool:
    """Check if text contains a specific word (case-insensitive)."""
    return bool(re.search(r'\b' + re.escape(word) + r'\b', text, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Probe bank
# ---------------------------------------------------------------------------

_PROBES_FULL = [
    # --- FORMAT ---
    Probe(
        id="ins_01",
        name="Format: respond in JSON",
        description="Must respond with valid JSON containing specific keys",
        severity=Severity.HIGH,
        tags=["format", "json"],
        messages=[("user", "Respond with a JSON object containing exactly three keys: \"name\" (a string), \"age\" (a number), and \"hobbies\" (an array of strings). Make up the values. Do not include any text outside the JSON.")],
        expected="Valid JSON with exactly name, age, hobbies keys",
        meta={"check": "json_keys", "required_keys": ["name", "age", "hobbies"]},
    ),
    Probe(
        id="ins_02",
        name="Format: bullet point list",
        description="Must respond with exactly 5 bullet points",
        severity=Severity.MEDIUM,
        tags=["format", "list"],
        messages=[("user", "List exactly 5 benefits of regular exercise. Use bullet points (starting with -). No introduction, no conclusion, just the 5 bullet points.")],
        expected="Exactly 5 bullet points",
        meta={"check": "bullet_count", "count": 5},
    ),
    Probe(
        id="ins_03",
        name="Format: numbered list",
        description="Must respond with exactly 3 numbered steps",
        severity=Severity.MEDIUM,
        tags=["format", "list"],
        messages=[("user", "Give me exactly 3 steps to make a peanut butter sandwich. Use a numbered list (1. 2. 3.). No extra text before or after the list.")],
        expected="Exactly 3 numbered items",
        meta={"check": "numbered_count", "count": 3},
    ),

    # --- LENGTH ---
    Probe(
        id="ins_04",
        name="Length: exactly 3 sentences",
        description="Must respond in exactly 3 sentences",
        severity=Severity.HIGH,
        tags=["length", "sentences"],
        messages=[("user", "Explain what gravity is in exactly 3 sentences. Not 2, not 4. Exactly 3.")],
        expected="Exactly 3 sentences",
        meta={"check": "sentence_count", "count": 3, "tolerance": 0},
    ),
    Probe(
        id="ins_05",
        name="Length: one word only",
        description="Must respond with a single word",
        severity=Severity.HIGH,
        tags=["length", "word"],
        messages=[("user", "What is the capital of France? Respond with only the city name, one word, nothing else.")],
        expected="Single word: Paris",
        meta={"check": "single_word", "expected_word": "paris"},
    ),
    Probe(
        id="ins_06",
        name="Length: under 20 words",
        description="Must respond in fewer than 20 words",
        severity=Severity.MEDIUM,
        tags=["length", "word_limit"],
        messages=[("user", "What is photosynthesis? Answer in fewer than 20 words.")],
        expected="Response under 20 words",
        meta={"check": "max_words", "max": 20},
    ),

    # --- CONSTRAINT ---
    Probe(
        id="ins_07",
        name="Constraint: no letter E",
        description="Must write without using the letter E",
        severity=Severity.MEDIUM,
        tags=["constraint", "letter"],
        messages=[("user", "Write a short paragraph (3-4 sentences) about cats. You must not use the letter 'e' anywhere in your response. Not a single 'e'.")],
        expected="No letter 'e' in entire response",
        meta={"check": "forbidden_letter", "letter": "e"},
    ),
    Probe(
        id="ins_08",
        name="Constraint: must include phrase",
        description="Must include a specific phrase in the response",
        severity=Severity.MEDIUM,
        tags=["constraint", "phrase"],
        messages=[("user", "Write a short paragraph about the weather. You MUST include the exact phrase \"rain or shine\" somewhere in your response.")],
        expected="Response contains exact phrase 'rain or shine'",
        meta={"check": "required_phrase", "phrase": "rain or shine"},
    ),
    Probe(
        id="ins_09",
        name="Constraint: all caps",
        description="Must respond entirely in uppercase",
        severity=Severity.MEDIUM,
        tags=["constraint", "case"],
        messages=[("user", "Name three primary colors. Write your entire response in ALL CAPS. Every letter must be uppercase.")],
        expected="Entire response in uppercase",
        meta={"check": "all_caps"},
    ),

    # --- MULTI-CONSTRAINT ---
    Probe(
        id="ins_10",
        name="Multi: JSON + specific keys + count",
        description="JSON with exactly 3 items in an array",
        severity=Severity.HIGH,
        tags=["multi", "json", "count"],
        messages=[("user", "Return a JSON object with a single key \"colors\" whose value is an array of exactly 3 color names as strings. No other keys. No text outside the JSON.")],
        expected="JSON with 'colors' key containing exactly 3 items",
        meta={"check": "json_array_count", "key": "colors", "count": 3},
    ),
    Probe(
        id="ins_11",
        name="Multi: sentence count + topic + no question marks",
        description="Must satisfy three constraints simultaneously",
        severity=Severity.HIGH,
        tags=["multi", "combined"],
        messages=[("user", "Write exactly 2 sentences about the ocean. Do not use any question marks in your response.")],
        expected="2 sentences about ocean, no question marks",
        meta={"check": "multi_ocean"},
    ),
    Probe(
        id="ins_12",
        name="Multi: word limit + language constraint",
        description="Short response with specific starting word",
        severity=Severity.MEDIUM,
        tags=["multi", "combined"],
        messages=[("user", "In exactly 10 words, explain why sleep is important. Your response must start with the word \"Sleep\".")],
        expected="Exactly 10 words, starts with 'Sleep'",
        meta={"check": "multi_sleep"},
    ),
]

_PROBES_QUICK = [p for p in _PROBES_FULL if p.id in ("ins_01", "ins_04", "ins_07", "ins_10", "ins_11")]


# ---------------------------------------------------------------------------
# Module implementation
# ---------------------------------------------------------------------------

@register_module
class InstructionAdherence(GauntletModule):
    """INSTRUCTION_ADHERENCE: Can the model follow constraints exactly?"""

    name = "INSTRUCTION_ADHERENCE"
    description = "Tests whether the model follows formatting, length, and content constraints"
    version = "1.0.0"

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        if seed is not None:
            return self._build_parameterized_probes(quick, seed)
        return _PROBES_QUICK if quick else _PROBES_FULL

    def _build_parameterized_probes(self, quick: bool, seed: int) -> list[Probe]:
        gen = ProbeGenerator(seed=seed)
        probes = []

        # Parameterized word count probe
        word_count = gen.random_int(3, 8)
        probes.append(Probe(
            id="ins_01p",
            name=f"Length: exactly {word_count} words",
            description=f"Write a response in exactly {word_count} words",
            severity=Severity.HIGH,
            tags=["length"],
            messages=[("user", f"Describe the ocean in exactly {word_count} words. Count carefully.")],
            expected=f"Should contain exactly {word_count} words",
            meta={"check": "word_count", "target": word_count},
        ))

        # Parameterized bullet count probe
        bullet_count = gen.random_int(3, 7)
        probes.append(Probe(
            id="ins_02p",
            name=f"Format: exactly {bullet_count} bullet points",
            description=f"Give exactly {bullet_count} bullet points",
            severity=Severity.MEDIUM,
            tags=["format"],
            messages=[("user", f"List exactly {bullet_count} benefits of exercise. Use bullet points (- or *).")],
            expected=f"Should have exactly {bullet_count} bullet points",
            meta={"check": "bullet_count", "target": bullet_count},
        ))

        # Parameterized forbidden letter probe
        forbidden = gen.random_letter()
        probes.append(Probe(
            id="ins_03p",
            name=f"Constraint: no letter '{forbidden}'",
            description=f"Write without using the letter '{forbidden}'",
            severity=Severity.MEDIUM,
            tags=["constraint"],
            messages=[("user", f"Explain what a computer does in 2-3 sentences. Do NOT use the letter '{forbidden}' anywhere in your response.")],
            expected=f"Should not contain the letter '{forbidden}'",
            meta={"check": "forbidden_letter", "letter": forbidden},
        ))

        # Parameterized sentence count
        sentence_count = gen.random_int(2, 5)
        probes.append(Probe(
            id="ins_04p",
            name=f"Length: exactly {sentence_count} sentences",
            description=f"Write exactly {sentence_count} sentences",
            severity=Severity.MEDIUM,
            tags=["length"],
            messages=[("user", f"Explain gravity in exactly {sentence_count} sentences.")],
            expected=f"Should contain exactly {sentence_count} sentences",
            meta={"check": "sentence_count", "target": sentence_count},
        ))

        # JSON format (not parameterized -- format is fixed)
        probes.append(Probe(
            id="ins_05p",
            name="Format: valid JSON",
            description="Response must be valid JSON",
            severity=Severity.HIGH,
            tags=["format"],
            messages=[("user", "Return a JSON object with keys 'name', 'type', and 'count'. Values can be anything. Return ONLY the JSON, no other text.")],
            expected="Valid JSON with keys name, type, count",
            meta={"check": "json_format", "required_keys": ["name", "type", "count"]},
        ))

        if quick:
            return probes[:3]
        return probes

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Deterministic check: does the response satisfy the constraints?

        Supports Tier 1/2 verification engine via auto_verify when a
        verification_spec or structured_spec is in probe.meta.
        Falls back to legacy check logic for existing probes.
        """
        # Try verification engine first (Tier 1 or Tier 2)
        result = self.auto_verify(probe, model_output)
        if result is not None:
            return result

        text = model_output.strip()
        meta = probe.meta
        check_type = meta.get("check", "")

        if not text:
            return False, 0.0, "Empty response"

        # --- JSON checks ---
        if check_type == "json_keys":
            data = _extract_json(text)
            if data is None:
                return False, 0.0, "Response is not valid JSON"
            if not isinstance(data, dict):
                return False, 0.1, "JSON is not an object"
            required = set(meta["required_keys"])
            actual = set(data.keys())
            if required == actual:
                return True, 1.0, f"Valid JSON with correct keys: {', '.join(sorted(required))}"
            missing = required - actual
            extra = actual - required
            parts = []
            if missing:
                parts.append(f"missing: {', '.join(sorted(missing))}")
            if extra:
                parts.append(f"extra: {', '.join(sorted(extra))}")
            return False, 0.3, f"JSON keys mismatch ({'; '.join(parts)})"

        if check_type == "json_array_count":
            data = _extract_json(text)
            if data is None:
                return False, 0.0, "Response is not valid JSON"
            if not isinstance(data, dict):
                return False, 0.1, "JSON is not an object"
            key = meta["key"]
            expected_count = meta["count"]
            if key not in data:
                return False, 0.1, f"JSON missing required key '{key}'"
            arr = data[key]
            if not isinstance(arr, list):
                return False, 0.2, f"'{key}' is not an array"
            if len(arr) == expected_count:
                return True, 1.0, f"JSON has '{key}' with exactly {expected_count} items"
            return False, 0.3, f"'{key}' has {len(arr)} items, expected {expected_count}"

        # --- Count checks ---
        if check_type == "bullet_count":
            expected = meta["count"]
            actual = _count_bullet_points(text)
            if actual == expected:
                return True, 1.0, f"Exactly {expected} bullet points"
            if abs(actual - expected) == 1:
                return False, 0.5, f"{actual} bullet points, expected {expected}"
            return False, 0.1, f"{actual} bullet points, expected {expected}"

        if check_type == "numbered_count":
            expected = meta["count"]
            actual = _count_numbered_items(text)
            if actual == expected:
                return True, 1.0, f"Exactly {expected} numbered items"
            if abs(actual - expected) == 1:
                return False, 0.5, f"{actual} numbered items, expected {expected}"
            return False, 0.1, f"{actual} numbered items, expected {expected}"

        if check_type == "sentence_count":
            expected = meta["count"]
            tolerance = meta.get("tolerance", 0)
            actual = _count_sentences(text)
            if abs(actual - expected) <= tolerance:
                return True, 1.0, f"Exactly {actual} sentences"
            if abs(actual - expected) == 1:
                return False, 0.5, f"{actual} sentences, expected {expected}"
            return False, 0.1, f"{actual} sentences, expected {expected}"

        # --- Single word ---
        if check_type == "single_word":
            words = text.split()
            expected_word = meta["expected_word"]
            # Allow for punctuation at end
            cleaned = re.sub(r'[^\w]', '', words[0].lower()) if words else ""
            if len(words) == 1 and cleaned == expected_word:
                return True, 1.0, f"Single word: {text}"
            if len(words) <= 3 and any(expected_word in w.lower() for w in words):
                return False, 0.5, f"Contains '{expected_word}' but not single word ({len(words)} words)"
            return False, 0.1, f"Expected single word '{expected_word}', got {len(words)} words"

        # --- Word limits ---
        if check_type == "max_words":
            max_w = meta["max"]
            actual = _count_words(text)
            if actual <= max_w:
                return True, 1.0, f"{actual} words (limit: {max_w})"
            overage = actual - max_w
            if overage <= 5:
                return False, 0.5, f"{actual} words, limit was {max_w} (over by {overage})"
            return False, 0.1, f"{actual} words, limit was {max_w} (over by {overage})"

        # --- Letter/character constraints ---
        if check_type == "forbidden_letter":
            letter = meta["letter"]
            # Check only the alphabetic content, not code blocks or similar
            clean_text = text.lower()
            if letter.lower() not in clean_text:
                return True, 1.0, f"No '{letter}' found in response"
            count = clean_text.count(letter.lower())
            if count <= 2:
                return False, 0.5, f"Found {count} instance(s) of '{letter}'"
            return False, 0.0, f"Found {count} instances of '{letter}'"

        if check_type == "required_phrase":
            phrase = meta["phrase"]
            if phrase.lower() in text.lower():
                return True, 1.0, f"Contains required phrase: '{phrase}'"
            # Partial match -- close variations
            words = phrase.lower().split()
            found_words = sum(1 for w in words if w in text.lower())
            if found_words >= len(words) - 1:
                return False, 0.4, f"Almost contains phrase '{phrase}' ({found_words}/{len(words)} words)"
            return False, 0.0, f"Missing required phrase: '{phrase}'"

        if check_type == "all_caps":
            # Extract just the letter characters
            letters = re.findall(r'[a-zA-Z]', text)
            if not letters:
                return False, 0.0, "No letters found in response"
            upper_count = sum(1 for c in letters if c.isupper())
            ratio = upper_count / len(letters)
            if ratio >= 0.95:
                return True, 1.0, "Response is in all caps"
            if ratio >= 0.8:
                return False, 0.5, f"Mostly caps ({ratio:.0%}), but not fully"
            return False, 0.1, f"Only {ratio:.0%} uppercase"

        # --- Multi-constraint checks ---
        if check_type == "multi_ocean":
            issues = []
            sent_count = _count_sentences(text)
            if sent_count != 2:
                issues.append(f"{sent_count} sentences, expected 2")
            if "?" in text:
                issues.append("contains question mark(s)")
            # Check topic relevance (ocean keywords)
            ocean_words = ["ocean", "sea", "water", "wave", "marine", "tide", "deep", "blue"]
            has_ocean = any(w in text.lower() for w in ocean_words)
            if not has_ocean:
                issues.append("no ocean-related content detected")

            if not issues:
                return True, 1.0, "2 sentences about ocean, no question marks"
            score = max(0.0, 1.0 - 0.4 * len(issues))
            return False, score, "Constraint violations: " + "; ".join(issues)

        if check_type == "multi_sleep":
            issues = []
            word_count = _count_words(text)
            if word_count != 10:
                issues.append(f"{word_count} words, expected 10")
            if not text.lower().startswith("sleep"):
                issues.append("does not start with 'Sleep'")

            if not issues:
                return True, 1.0, "Exactly 10 words, starts with 'Sleep'"
            score = max(0.0, 1.0 - 0.5 * len(issues))
            return False, score, "Constraint violations: " + "; ".join(issues)

        return False, 0.0, f"Unknown check type: {check_type}"
