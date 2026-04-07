"""Prompt classifier -- infer a Gauntlet profile from a user prompt.

Uses keyword scoring to classify prompts into profiles. No LLM calls.
Fast, deterministic, local.
"""

from __future__ import annotations
import re


_CODING_KEYWORDS = [
    "write", "implement", "function", "class", "api", "debug",
    "code", "script", "algorithm", "refactor", "bug", "test",
    "compile", "deploy", "variable", "method", "module", "import",
    "syntax", "exception", "loop", "array", "string", "integer",
    "boolean", "return", "parameter", "argument", "library",
    "framework", "endpoint", "database", "query", "schema",
    "python", "javascript", "typescript", "rust", "go", "java",
    "html", "css", "react", "flask", "django", "fastapi",
    "git", "commit", "merge", "branch", "docker", "kubernetes",
    "async", "await", "promise", "callback", "closure",
]

_RESEARCH_KEYWORDS = [
    "explain", "analyze", "compare", "summarize", "what is",
    "how does", "define", "describe", "research", "study",
    "evidence", "data", "theory", "hypothesis", "findings",
    "literature", "review", "methodology", "conclusion",
    "historical", "scientific", "philosophical", "economic",
    "political", "cultural", "social", "psychological",
    "statistics", "correlation", "causation", "experiment",
    "observation", "phenomenon", "principle", "concept",
]


def classify_prompt(prompt: str) -> str:
    """Classify a user prompt into a Gauntlet profile.

    Returns: "coder", "researcher", or "assistant".
    """
    if not prompt or not prompt.strip():
        return "assistant"

    text = prompt.lower()

    coder_hits = 0
    for kw in _CODING_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", text):
            coder_hits += 1

    researcher_hits = 0
    for kw in _RESEARCH_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", text):
            researcher_hits += 1

    if coder_hits == 0 and researcher_hits == 0:
        return "assistant"

    if coder_hits > researcher_hits:
        return "coder"
    return "researcher"
