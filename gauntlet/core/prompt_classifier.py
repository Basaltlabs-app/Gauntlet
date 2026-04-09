"""Prompt classifier -- infer a Gauntlet profile from a user prompt.

Uses keyword scoring to classify prompts into profiles. No LLM calls.
Fast, deterministic, local.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


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


# ---------------------------------------------------------------------------
# Subcategory keyword groups -- require 2+ matches to activate
# ---------------------------------------------------------------------------

_SUBCATEGORY_KEYWORDS: dict[str, list[str]] = {
    "database": [
        "supabase", "postgres", "postgresql", "mysql", "sqlite", "mongodb",
        "rls", "row-level security", "row level security",
        "schema", "migration", "sql", "prisma", "drizzle", "sequelize",
        "foreign key", "index", "table", "column", "join",
        "insert", "select", "update", "delete",
        "orm", "typeorm", "knex", "hasura",
    ],
    "auth_security": [
        "auth", "authentication", "authorization", "login", "signup", "sign up",
        "session", "jwt", "token", "oauth", "rbac", "role",
        "permission", "password", "mfa", "two-factor", "2fa",
        "csrf", "cors", "bcrypt", "hash", "clerk", "auth0", "nextauth",
    ],
    "apps_script": [
        "google apps script", "apps script", "gas project",
        "spreadsheet api", "spreadsheetapp", "documentapp",
        "onedit", "onopen", "onformsubmit",
        "urlfetchapp", "scriptapp", "triggersbuilder",
        "google sheets", "google docs", "google forms",
        "clasp", "appscript",
    ],
    "frontend": [
        "react", "vue", "svelte", "angular", "nextjs", "next.js", "nuxt",
        "component", "css", "tailwind", "styled-components",
        "ui", "layout", "responsive", "animation", "modal",
        "button", "form", "input", "dropdown", "navbar",
        "shadcn", "radix", "chakra", "material ui", "ant design",
    ],
    "backend_api": [
        "api", "endpoint", "rest", "restful", "graphql",
        "middleware", "route", "controller", "handler",
        "fastapi", "express", "flask", "django", "koa", "hono",
        "request", "response", "status code", "payload",
        "webhook", "microservice", "grpc",
    ],
    "devops": [
        "docker", "dockerfile", "container", "kubernetes", "k8s",
        "ci/cd", "cicd", "pipeline", "github actions", "gitlab ci",
        "deploy", "deployment", "terraform", "ansible", "nginx",
        "helm", "prometheus", "grafana", "aws", "gcp", "azure",
    ],
    "data_analysis": [
        "dataset", "csv", "excel", "spreadsheet",
        "pandas", "numpy", "dataframe", "series",
        "correlation", "regression", "statistics", "statistical",
        "pivot", "aggregate", "groupby", "group by",
        "chart", "plot", "visualization", "histogram",
        "mean", "median", "standard deviation", "outlier",
        "cleaning", "transform", "etl", "warehouse",
    ],
    "writing_content": [
        "blog", "article", "post", "essay", "story",
        "tone", "voice", "draft", "outline", "copy",
        "copywriting", "newsletter", "email campaign",
        "headline", "subtitle", "paragraph",
        "persuasive", "informative", "narrative",
        "content strategy", "seo writing", "marketing copy",
    ],
}

# Human-readable labels for subcategories
_SUBCATEGORY_LABELS: dict[str, str] = {
    "database": "database",
    "auth_security": "auth & security",
    "apps_script": "Google Apps Script",
    "frontend": "frontend",
    "backend_api": "backend API",
    "devops": "DevOps",
    "data_analysis": "data analysis",
    "writing_content": "writing & content",
}

# Minimum keyword hits to activate a subcategory
_MIN_SUBCATEGORY_HITS = 2


@dataclass
class PromptClassification:
    """Detailed classification of a user prompt for domain-aware evaluation."""

    category: str                          # "coder", "researcher", "assistant"
    subcategory: str | None = None         # e.g. "database", "frontend", etc.
    subcategory_label: str | None = None   # e.g. "database", "Google Apps Script"
    confidence: float = 0.0                # 0.0-1.0
    matched_signals: list[str] = field(default_factory=list)


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


def classify_prompt_detailed(prompt: str) -> PromptClassification:
    """Classify a prompt with fine-grained subcategory for domain-aware evaluation.

    Returns a PromptClassification with:
    - category: top-level profile ("coder", "researcher", "assistant")
    - subcategory: specific domain (e.g. "database", "frontend") or None
    - confidence: 0.0-1.0 based on match strength
    - matched_signals: which keywords triggered the classification
    """
    category = classify_prompt(prompt)

    if not prompt or not prompt.strip():
        return PromptClassification(category="assistant")

    text = prompt.lower()

    # Score each subcategory
    best_sub: str | None = None
    best_hits = 0
    best_signals: list[str] = []

    for sub_name, keywords in _SUBCATEGORY_KEYWORDS.items():
        hits = 0
        signals = []
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", text):
                hits += 1
                signals.append(kw)

        if hits >= _MIN_SUBCATEGORY_HITS and hits > best_hits:
            best_sub = sub_name
            best_hits = hits
            best_signals = signals

    if best_sub is None:
        return PromptClassification(
            category=category,
            confidence=0.0,
        )

    # Confidence: ratio of matched keywords to total available for that subcategory
    total_keywords = len(_SUBCATEGORY_KEYWORDS[best_sub])
    confidence = min(1.0, best_hits / max(total_keywords * 0.4, 1))

    return PromptClassification(
        category=category,
        subcategory=best_sub,
        subcategory_label=_SUBCATEGORY_LABELS.get(best_sub, best_sub),
        confidence=confidence,
        matched_signals=best_signals,
    )
