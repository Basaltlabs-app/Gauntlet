"""HEALTH_CHECK -- 15-probe real-world capability assessment across 6 domains.

Tests practical AI competence: writing, code, reasoning, summarization,
data analysis, and creative tasks. Designed as a fast "health check"
that covers breadth rather than depth.

This module is NOT registered via @register_module. It is separate from
the behavioral suite and invoked independently by the health runner.

Probe categories (6 domains, 15 probes):
  1. WRITING         (3 probes) -- Professional communication
  2. CODE            (3 probes) -- Programming tasks
  3. REASONING       (2 probes) -- Math and logic
  4. SUMMARIZATION   (2 probes) -- Information extraction
  5. DATA_ANALYSIS   (2 probes) -- Quantitative analysis
  6. CREATIVE        (2 probes) -- Creative generation
  7. REGRESSION_ANCHOR (1 probe) -- Fixed probe for drift detection

Scoring:
  - Deterministic: regex pattern matching for verifiable answers
  - Code deterministic: extract code blocks, check structure/patterns
  - LLM-judged: judge_rubric in meta for external LLM evaluation
  - Hybrid: deterministic base + LLM refinement
"""

from __future__ import annotations

import re
from gauntlet.core.modules.base import (
    GauntletModule,
    ModuleResult,
    ModuleScore,
    Probe,
    ProbeResult,
    Severity,
    semantic_similarity,
)


# ---------------------------------------------------------------------------
# Checker helpers
# ---------------------------------------------------------------------------

def _extract_code_block(text: str) -> str:
    """Extract the first fenced code block from text, or return full text."""
    match = re.search(r"```(?:\w+)?\s*\n?([\s\S]*?)```", text)
    return match.group(1).strip() if match else text.strip()


def _count_pattern_matches(text: str, patterns: list[str], flags: int = re.IGNORECASE) -> int:
    """Count how many patterns match in the text."""
    return sum(1 for p in patterns if re.search(p, text, flags))


def _count_items(text: str) -> int:
    """Count numbered or bulleted list items in text."""
    lines = text.strip().split("\n")
    count = 0
    for line in lines:
        stripped = line.strip()
        if re.match(r"^\d+[.)]\s+", stripped):
            count += 1
        elif re.match(r"^[-*]\s+", stripped):
            count += 1
    return count


def _extract_percentage(text: str) -> float | None:
    """Extract a percentage-like number from text. Returns the float value or None."""
    # Look for patterns like "22.8%", "22%", "~23%", "approximately 22.8 percent"
    patterns = [
        r"(\d+\.?\d*)\s*%",
        r"(\d+\.?\d*)\s*percent",
    ]
    for p in patterns:
        match = re.search(p, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


# ---------------------------------------------------------------------------
# Probe definitions
# ---------------------------------------------------------------------------

_PROBES = [
    # =====================================================================
    # WRITING (3 probes) -- LLM-judged via meta["judge_rubric"]
    # =====================================================================
    Probe(
        id="hc_01",
        name="Writing: decline meeting email",
        description="Write a professional email declining a meeting invitation with rescheduling suggestion",
        severity=Severity.MEDIUM,
        tags=["writing", "email", "professional"],
        messages=[
            ("user", "Write a professional email declining a meeting invitation. Be polite but firm, and suggest rescheduling next week."),
        ],
        expected="Professional email with decline, reason, and rescheduling suggestion",
        meta={
            "category": "writing",
            "checker_type": "llm_only",
            "judge_rubric": {
                "criteria": [
                    {"name": "tone", "desc": "Professional and polite", "weight": 1.0},
                    {"name": "completeness", "desc": "Includes clear decline, reason, and rescheduling suggestion", "weight": 1.5},
                    {"name": "format", "desc": "Proper email structure with greeting and sign-off", "weight": 0.8},
                ],
            },
        },
    ),
    Probe(
        id="hc_02",
        name="Writing: concise rewrite",
        description="Rewrite a verbose paragraph to be more concise without losing meaning",
        severity=Severity.MEDIUM,
        tags=["writing", "editing", "conciseness"],
        messages=[
            ("user",
             "Rewrite this paragraph to be more concise without losing meaning:\n\n"
             "'The implementation of remote work policies across various organizations has, "
             "in many instances, led to a significant and noteworthy increase in overall "
             "employee satisfaction levels, primarily due to the elimination of the daily "
             "commute, which many workers found to be an extremely time-consuming and "
             "stressful part of their everyday routine, along with providing them greater "
             "flexibility in managing their work-life balance.'"),
        ],
        expected="Significantly shorter rewrite retaining all key ideas",
        meta={
            "category": "writing",
            "checker_type": "llm_only",
            "judge_rubric": {
                "criteria": [
                    {"name": "conciseness", "desc": "Significantly shorter than original (target: under 60 words)", "weight": 1.5},
                    {"name": "meaning_preservation", "desc": "All key ideas retained: remote work, satisfaction, no commute, flexibility", "weight": 1.5},
                    {"name": "readability", "desc": "Clear, natural prose", "weight": 1.0},
                ],
            },
        },
    ),
    Probe(
        id="hc_03",
        name="Writing: bug report",
        description="Write a structured bug report from a scenario description",
        severity=Severity.MEDIUM,
        tags=["writing", "technical", "bug_report"],
        messages=[
            ("user",
             "Write a bug report for this issue: The login page shows a blank screen on "
             "Safari after updating to iOS 18. Chrome works fine. The console shows "
             "'TypeError: Cannot read properties of undefined (reading .at)'"),
        ],
        expected="Structured bug report with steps to reproduce, expected vs actual, environment",
        meta={
            "category": "writing",
            "checker_type": "llm_only",
            "judge_rubric": {
                "criteria": [
                    {"name": "structure", "desc": "Has steps to reproduce, expected vs actual behavior, environment details", "weight": 1.5},
                    {"name": "technical_detail", "desc": "References the error, browser, OS version specifics", "weight": 1.0},
                    {"name": "actionability", "desc": "Developer could start debugging from this report", "weight": 1.0},
                ],
            },
        },
    ),

    # =====================================================================
    # CODE (3 probes) -- deterministic + LLM
    # =====================================================================
    Probe(
        id="hc_04",
        name="Code: second_largest function",
        description="Write a Python function to find the second largest unique value in a list",
        severity=Severity.HIGH,
        tags=["code", "python", "function"],
        messages=[
            ("user",
             "Write a Python function called `second_largest` that takes a list of numbers "
             "and returns the second largest unique value. Return None if there is no second "
             "largest. Include type hints."),
        ],
        expected="Correct second_largest function handling edge cases",
        meta={
            "category": "code",
            "checker_type": "code_deterministic",
            "deterministic_checks": {
                "required_patterns": [
                    r"def\s+second_largest",
                ],
                "test_cases": [
                    {"input": "[1, 2, 3]", "expected": "2"},
                    {"input": "[1, 1, 2]", "expected": "1"},
                    {"input": "[5]", "expected": "None"},
                    {"input": "[]", "expected": "None"},
                ],
            },
            "judge_rubric": {
                "criteria": [
                    {"name": "correctness", "desc": "Handles all edge cases", "weight": 2.0},
                    {"name": "code_quality", "desc": "Clean, readable, Pythonic code with type hints", "weight": 1.0},
                    {"name": "edge_cases", "desc": "Explicitly handles empty list, single element, duplicates", "weight": 1.0},
                ],
            },
        },
    ),
    Probe(
        id="hc_05",
        name="Code: fix binary search bug",
        description="Identify and fix a bug in a binary search implementation",
        severity=Severity.HIGH,
        tags=["code", "python", "debugging"],
        messages=[
            ("user",
             "This Python function has a bug. Find and fix it:\n\n"
             "```python\n"
             "def binary_search(arr, target):\n"
             "    low, high = 0, len(arr)\n"
             "    while low < high:\n"
             "        mid = (low + high) // 2\n"
             "        if arr[mid] == target:\n"
             "            return mid\n"
             "        elif arr[mid] < target:\n"
             "            low = mid\n"
             "        else:\n"
             "            high = mid\n"
             "    return -1\n"
             "```"),
        ],
        expected="Identifies low = mid should be low = mid + 1, and/or high = len(arr) - 1",
        meta={
            "category": "code",
            "checker_type": "code_deterministic",
            "deterministic_checks": {
                "fix_patterns": [
                    r"low\s*=\s*mid\s*\+\s*1",
                    r"high\s*=\s*len\(arr\)\s*-\s*1|high\s*=\s*mid\s*-\s*1",
                ],
            },
            "judge_rubric": {
                "criteria": [
                    {"name": "bug_identification", "desc": "Correctly identifies the infinite loop / off-by-one bug", "weight": 2.0},
                    {"name": "fix_quality", "desc": "Fix is correct and complete", "weight": 1.5},
                    {"name": "explanation", "desc": "Clear explanation of why the bug occurs", "weight": 1.0},
                ],
            },
        },
    ),
    Probe(
        id="hc_06",
        name="Code: explain and optimize SQL",
        description="Explain a SQL query and suggest an optimization",
        severity=Severity.MEDIUM,
        tags=["code", "sql", "optimization"],
        messages=[
            ("user",
             "Explain what this SQL query does and suggest one optimization:\n\n"
             "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id "
             "WHERE o.created_at > '2024-01-01' ORDER BY o.total DESC"),
        ],
        expected="Correct explanation of JOIN/filter/sort and a valid optimization suggestion",
        meta={
            "category": "code",
            "checker_type": "llm_only",
            "judge_rubric": {
                "criteria": [
                    {"name": "accuracy", "desc": "Correctly describes the JOIN, filter, and sort operations", "weight": 1.5},
                    {"name": "optimization", "desc": "Suggests a valid optimization (index, column selection, pagination)", "weight": 1.5},
                    {"name": "clarity", "desc": "Explanation is clear and well-structured", "weight": 0.8},
                ],
            },
        },
    ),

    # =====================================================================
    # REASONING (2 probes) -- deterministic
    # =====================================================================
    Probe(
        id="hc_07",
        name="Reasoning: compound discount",
        description="Calculate total discount from sequential percentage discounts",
        severity=Severity.HIGH,
        tags=["reasoning", "math", "discount"],
        messages=[
            ("user",
             "A store offers 20% off, then an additional 15% off the already reduced price. "
             "What is the total discount percentage? Show your work step by step."),
        ],
        expected="32% total discount (1 - 0.8 * 0.85 = 0.32)",
        meta={
            "category": "reasoning",
            "checker_type": "deterministic",
            "deterministic_checks": {
                "accept_patterns": [r"\b32\b", r"32%", r"0\.32"],
                "reject_patterns": [r"\b35\b", r"35%"],
                "step_patterns": [r"0\.8|80%", r"0\.85|85%", r"0\.68|68%"],
            },
        },
    ),
    Probe(
        id="hc_08",
        name="Reasoning: scheduling overlap",
        description="Find common availability across three people's schedules",
        severity=Severity.HIGH,
        tags=["reasoning", "logic", "scheduling"],
        messages=[
            ("user",
             "Three colleagues need to schedule a 1-hour meeting. Alex is free 9-12 and 2-4. "
             "Blake is free 10-1 and 3-5. Casey is free 8-11 and 1-3. What time slot works "
             "for all three? Show your reasoning."),
        ],
        expected="10-11 (or 10am-11am) is the only common slot",
        meta={
            "category": "reasoning",
            "checker_type": "deterministic",
            "deterministic_checks": {
                "accept_patterns": [
                    r"\b10\b.*\b11\b",
                    r"10\s*[-\u2013\u2014:to]+\s*11",
                    r"10\s*(am|AM)?\s*[-\u2013\u2014to]+\s*11",
                ],
                "reasoning_patterns": [r"overlap|intersect|common|available|free"],
            },
        },
    ),

    # =====================================================================
    # SUMMARIZATION (2 probes) -- LLM-judged + deterministic
    # =====================================================================
    Probe(
        id="hc_09",
        name="Summarization: Kubernetes for executives",
        description="Summarize a technical document in 3 bullet points for non-technical audience",
        severity=Severity.MEDIUM,
        tags=["summarization", "technical", "audience"],
        messages=[
            ("user",
             "Summarize this technical document in 3 bullet points for a non-technical executive:\n\n"
             "Kubernetes orchestrates containerized applications across clusters of machines. "
             "It automates deployment, scaling, and operations. Key concepts include pods "
             "(smallest deployable units), services (stable networking endpoints), and "
             "deployments (desired state management). Rolling updates allow zero-downtime "
             "releases by gradually replacing pod instances. Horizontal Pod Autoscaling "
             "adjusts replica counts based on CPU or custom metrics. Persistent Volumes "
             "abstract storage from compute, enabling stateful workloads. Network policies "
             "control traffic flow between pods. Helm charts package applications for "
             "repeatable installations. The control plane (API server, scheduler, etcd) "
             "manages cluster state, while kubelets on worker nodes execute pod specifications."),
        ],
        expected="3 concise, jargon-free bullet points capturing orchestration, automation, scaling",
        meta={
            "category": "summarization",
            "checker_type": "llm_only",
            "judge_rubric": {
                "criteria": [
                    {"name": "accuracy", "desc": "Captures the key points: orchestration, automation, scaling", "weight": 1.5},
                    {"name": "audience", "desc": "Avoids jargon or explains it simply; an executive would understand", "weight": 1.5},
                    {"name": "format", "desc": "Exactly 3 bullet points", "weight": 1.0},
                    {"name": "conciseness", "desc": "Each bullet is 1-2 sentences, not a paragraph", "weight": 0.8},
                ],
            },
        },
    ),
    Probe(
        id="hc_10",
        name="Summarization: meeting action items",
        description="Extract action items with owners from a meeting transcript",
        severity=Severity.HIGH,
        tags=["summarization", "extraction", "action_items"],
        messages=[
            ("user",
             "Read this meeting transcript and list the action items with owners:\n\n"
             "Sarah: 'We need to finalize the Q3 budget by Friday. Tom, can you get the "
             "engineering estimates together?'\n"
             "Tom: 'Sure, I'll have those by Wednesday. But we still need the marketing numbers.'\n"
             "Sarah: 'Right. Lisa, can you pull the marketing spend report by Thursday?'\n"
             "Lisa: 'Yes, I'll send it to both of you. Also, we need someone to update the "
             "board deck.'\n"
             "Sarah: 'I'll handle the board deck myself. Let's reconvene Friday afternoon.'\n"
             "Tom: 'Sounds good. I'll also schedule a sync with the data team about the "
             "pipeline migration.'"),
        ],
        expected="4 action items: Tom/engineering estimates, Lisa/marketing report, Sarah/board deck, Tom/data team sync",
        meta={
            "category": "summarization",
            "checker_type": "deterministic_plus_llm",
            "deterministic_checks": {
                "action_item_patterns": [
                    r"\bTom\b.*\bengineering|estimates\b",
                    r"\bLisa\b.*\bmarketing\b",
                    r"\bSarah\b.*\bboard\s+deck\b",
                    r"\bTom\b.*\bdata\s+team|pipeline\b",
                ],
            },
            "judge_rubric": {
                "criteria": [
                    {"name": "completeness", "desc": "All 4 action items captured", "weight": 2.0},
                    {"name": "attribution", "desc": "Each item has correct owner", "weight": 1.5},
                    {"name": "deadlines", "desc": "Deadlines mentioned where given (Wednesday, Thursday, Friday)", "weight": 1.0},
                    {"name": "format", "desc": "Clear, structured list format", "weight": 0.8},
                ],
            },
        },
    ),

    # =====================================================================
    # DATA ANALYSIS (2 probes) -- deterministic + LLM
    # =====================================================================
    Probe(
        id="hc_11",
        name="Data: revenue analysis",
        description="Identify highest revenue month and calculate percentage above average",
        severity=Severity.HIGH,
        tags=["data_analysis", "math", "csv"],
        messages=[
            ("user",
             "Given this data, which month had the highest revenue and by what percentage "
             "does it exceed the monthly average?\n\n"
             "Month,Revenue\n"
             "Jan,45000\n"
             "Feb,52000\n"
             "Mar,38000\n"
             "Apr,61000\n"
             "May,47000\n"
             "Jun,55000"),
        ],
        expected="April, approximately 22-23% above average (avg=49666.67, Apr=61000)",
        meta={
            "category": "data_analysis",
            "checker_type": "deterministic_plus_llm",
            "deterministic_checks": {
                "month_patterns": [r"\bApr(?:il)?\b"],
                "percentage_range": {"min": 22.0, "max": 24.0},
            },
            "judge_rubric": {
                "criteria": [
                    {"name": "correct_month", "desc": "Identifies April as highest revenue month", "weight": 1.5},
                    {"name": "correct_percentage", "desc": "Calculates approximately 22-23% above average", "weight": 1.5},
                    {"name": "methodology", "desc": "Shows or explains the calculation steps", "weight": 1.0},
                ],
            },
        },
    ),
    Probe(
        id="hc_12",
        name="Data: SQL query for churned users",
        description="Write a SQL query to find users who signed up in 2024 but are inactive",
        severity=Severity.MEDIUM,
        tags=["data_analysis", "sql", "query"],
        messages=[
            ("user",
             "I have a dataset with columns: user_id, signup_date, last_login, total_purchases. "
             "Write a SQL query to find users who signed up in 2024 but haven't logged in "
             "for 30+ days."),
        ],
        expected="SQL query with SELECT, date filtering for 2024 signup and 30-day inactivity",
        meta={
            "category": "data_analysis",
            "checker_type": "code_deterministic",
            "deterministic_checks": {
                "required_patterns": [
                    r"\bSELECT\b",
                    r"\bsignup_date\b.*\b2024\b",
                    r"\blast_login\b.*\b30\b|INTERVAL|DATEDIFF|DATE_SUB|CURRENT_DATE",
                ],
            },
            "judge_rubric": {
                "criteria": [
                    {"name": "correctness", "desc": "Query logic correctly filters signup year and inactivity period", "weight": 2.0},
                    {"name": "syntax", "desc": "Valid SQL syntax", "weight": 1.0},
                    {"name": "completeness", "desc": "Includes appropriate columns in SELECT", "weight": 0.8},
                ],
            },
        },
    ),

    # =====================================================================
    # CREATIVE (2 probes) -- LLM-judged + deterministic
    # =====================================================================
    Probe(
        id="hc_13",
        name="Creative: product description",
        description="Write a compelling product description for a smart water bottle",
        severity=Severity.MEDIUM,
        tags=["creative", "marketing", "copywriting"],
        messages=[
            ("user",
             "Write a product description for a smart water bottle that tracks hydration and "
             "syncs with fitness apps. Target audience: fitness enthusiasts. Maximum 100 words."),
        ],
        expected="Compelling, concise product description under 100 words targeting fitness enthusiasts",
        meta={
            "category": "creative",
            "checker_type": "llm_only",
            "judge_rubric": {
                "criteria": [
                    {"name": "engagement", "desc": "Compelling, persuasive copy", "weight": 1.0},
                    {"name": "audience_fit", "desc": "Appeals specifically to fitness enthusiasts", "weight": 1.0},
                    {"name": "word_count", "desc": "Under 100 words", "weight": 0.8},
                    {"name": "product_features", "desc": "Mentions tracking and app sync features", "weight": 1.0},
                ],
            },
        },
    ),
    Probe(
        id="hc_14",
        name="Creative: app name brainstorm",
        description="Generate 5 creative app names with taglines for a dog-friendly dining app",
        severity=Severity.MEDIUM,
        tags=["creative", "naming", "brainstorm"],
        messages=[
            ("user",
             "Generate 5 creative names for a mobile app that helps people find dog-friendly "
             "restaurants and cafes. Include a one-line tagline for each."),
        ],
        expected="5 creative app names with taglines, related to dogs and dining",
        meta={
            "category": "creative",
            "checker_type": "deterministic_plus_llm",
            "deterministic_checks": {
                "min_items": 5,
            },
            "judge_rubric": {
                "criteria": [
                    {"name": "creativity", "desc": "Names are memorable and original", "weight": 1.5},
                    {"name": "relevance", "desc": "Names clearly relate to dogs + dining", "weight": 1.0},
                    {"name": "count", "desc": "Exactly 5 names with taglines", "weight": 1.0},
                    {"name": "tagline_quality", "desc": "Taglines are catchy and descriptive", "weight": 0.8},
                ],
            },
        },
    ),

    # =====================================================================
    # REGRESSION ANCHOR (1 probe) -- deterministic, NEVER changes
    # =====================================================================
    Probe(
        id="hc_15",
        name="Regression: auth vs authz",
        description="Explain the difference between authentication and authorization with examples",
        severity=Severity.MEDIUM,
        tags=["regression_anchor", "security", "concepts"],
        messages=[
            ("user",
             "Explain the difference between authentication and authorization in web security. "
             "Be concise and give one real-world example of each."),
        ],
        expected="Clear distinction between authentication (who you are) and authorization (what you can do) with examples",
        meta={
            "category": "regression_anchor",
            "checker_type": "deterministic",
            "deterministic_checks": {
                "required_patterns": [
                    r"\bauthenticat\w*\b",
                    r"\bauthoriz\w*\b",
                    r"\bidentity|who\s+you\s+are|verify|credential|login|password\b",
                    r"\bpermission|access|allow|role|what\s+you\s+can\b",
                ],
            },
            "use_semantic_similarity": True,
        },
    ),
]


# ---------------------------------------------------------------------------
# Module implementation
# ---------------------------------------------------------------------------

class HealthCheck(GauntletModule):
    """HEALTH_CHECK: 15-probe real-world capability assessment.

    Tests 6 domains: writing, code, reasoning, summarization,
    data analysis, and creative tasks. Includes one regression anchor
    probe whose score is used for cross-run drift detection.

    NOT registered via @register_module -- invoked separately by
    the health runner.
    """

    name = "HEALTH_CHECK"
    description = "Real-world capability assessment across 6 domains"
    version = "1.0.0"

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        """Return all 15 health check probes.

        The `quick` flag is ignored -- the health check IS the quick test.
        All 15 probes always run.
        """
        return list(_PROBES)

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Dispatch to the correct checker based on meta['checker_type'].

        Returns:
            (passed, score, reason) where:
              - passed: bool
              - score: 0.0 - 1.0
              - reason: human-readable explanation
        """
        text = model_output.strip()
        meta = probe.meta
        checker_type = meta.get("checker_type", "llm_only")

        if not text:
            return False, 0.0, "Empty response"

        if checker_type == "deterministic":
            return self._check_deterministic(probe, text)
        elif checker_type == "code_deterministic":
            return self._check_code_deterministic(probe, text)
        elif checker_type == "llm_only":
            return self._check_llm_only(probe, text)
        elif checker_type == "deterministic_plus_llm":
            return self._check_deterministic_plus_llm(probe, text)
        else:
            return False, 0.0, f"Unknown checker_type: {checker_type}"

    def _check_deterministic(self, probe: Probe, text: str) -> tuple[bool, float, str]:
        """Pure deterministic check using regex patterns."""
        checks = probe.meta.get("deterministic_checks", {})

        # --- Accept patterns: at least one must match ---
        accept_patterns = checks.get("accept_patterns", [])
        if accept_patterns:
            accept_hits = _count_pattern_matches(text, accept_patterns)
            if accept_hits == 0:
                return False, 0.1, "No correct answer pattern found in response"

        # --- Reject patterns: none should match ---
        reject_patterns = checks.get("reject_patterns", [])
        if reject_patterns:
            reject_hits = _count_pattern_matches(text, reject_patterns)
            if reject_hits > 0:
                return False, 0.1, "Response contains a known incorrect answer"

        # --- Required patterns: all must match ---
        required_patterns = checks.get("required_patterns", [])
        if required_patterns:
            required_hits = _count_pattern_matches(text, required_patterns)
            if required_hits < len(required_patterns):
                missing = len(required_patterns) - required_hits
                partial_score = required_hits / len(required_patterns)
                return False, partial_score * 0.7, f"Missing {missing}/{len(required_patterns)} required elements"

        # --- Step patterns (reasoning): bonus, not required ---
        step_patterns = checks.get("step_patterns", [])
        step_bonus = 0.0
        if step_patterns:
            step_hits = _count_pattern_matches(text, step_patterns)
            step_bonus = 0.1 * (step_hits / len(step_patterns))

        # --- Reasoning patterns: check presence ---
        reasoning_patterns = checks.get("reasoning_patterns", [])
        if reasoning_patterns:
            reasoning_hits = _count_pattern_matches(text, reasoning_patterns)
            if reasoning_hits == 0:
                # Answer correct but no reasoning shown
                return True, 0.7, "Correct answer but reasoning not shown"

        # --- Semantic similarity for regression anchor ---
        if probe.meta.get("use_semantic_similarity"):
            sim = semantic_similarity(text, probe.expected)
            probe.meta["semantic_similarity_score"] = sim

        base_score = min(1.0, 0.9 + step_bonus)
        return True, base_score, "Deterministic check passed"

    def _check_code_deterministic(self, probe: Probe, text: str) -> tuple[bool, float, str]:
        """Check code-related probes: extract code, verify patterns."""
        checks = probe.meta.get("deterministic_checks", {})
        code = _extract_code_block(text)
        score = 0.0
        reasons = []

        # --- Required patterns (function definition, keywords) ---
        required_patterns = checks.get("required_patterns", [])
        if required_patterns:
            hits = _count_pattern_matches(code, required_patterns)
            if hits == 0:
                # Also check full text in case code is inline
                hits = _count_pattern_matches(text, required_patterns)
            if hits < len(required_patterns):
                missing = len(required_patterns) - hits
                reasons.append(f"Missing {missing}/{len(required_patterns)} required code patterns")
            else:
                score += 0.4
                reasons.append("Required code patterns found")

        # --- Fix patterns (for bug-fix probes) ---
        fix_patterns = checks.get("fix_patterns", [])
        if fix_patterns:
            fix_hits = _count_pattern_matches(text, fix_patterns)
            if fix_hits > 0:
                score += 0.5
                reasons.append(f"Fix detected ({fix_hits}/{len(fix_patterns)} patterns)")
            else:
                reasons.append("No fix pattern detected in response")

        # --- Test cases (for function probes) ---
        test_cases = checks.get("test_cases", [])
        if test_cases:
            # We cannot execute code, but we check for structural patterns
            # that indicate correct handling of edge cases
            case_score = 0.0
            for tc in test_cases:
                expected_val = tc["expected"]
                if expected_val == "None":
                    if re.search(r"\bNone\b|return\s+None", text, re.IGNORECASE):
                        case_score += 1
                else:
                    # Check if the expected value appears in reasoning/code
                    if re.search(rf"\b{re.escape(expected_val)}\b", text):
                        case_score += 1
            if test_cases:
                case_ratio = case_score / len(test_cases)
                score += 0.3 * case_ratio
                reasons.append(f"Test case coverage: {case_score}/{len(test_cases)}")

        # If no specific checks were defined, give base credit for having code
        if not required_patterns and not fix_patterns and not test_cases:
            if code and len(code) > 20:
                score = 0.5
                reasons.append("Code block present but no deterministic checks defined")

        final_score = min(1.0, score)
        passed = final_score >= 0.5
        reason = "; ".join(reasons) if reasons else "Code check completed"
        return passed, final_score, reason

    def _check_llm_only(self, probe: Probe, text: str) -> tuple[bool, float, str]:
        """Placeholder for LLM-judged probes.

        Returns a neutral score. Actual scoring is done by the health runner
        which invokes an LLM judge using meta['judge_rubric'].
        """
        # Basic sanity: response should be non-trivial
        if len(text) < 20:
            return False, 0.1, "Response too short for meaningful evaluation"

        return True, 0.5, "Requires LLM judge"

    def _check_deterministic_plus_llm(self, probe: Probe, text: str) -> tuple[bool, float, str]:
        """Run deterministic checks, return that score. LLM judge adds to it later."""
        checks = probe.meta.get("deterministic_checks", {})
        score = 0.0
        reasons = []

        # --- Action item patterns (hc_10) ---
        action_item_patterns = checks.get("action_item_patterns", [])
        if action_item_patterns:
            hits = _count_pattern_matches(text, action_item_patterns)
            ratio = hits / len(action_item_patterns)
            score = ratio * 0.8
            reasons.append(f"Action items found: {hits}/{len(action_item_patterns)}")

        # --- Month patterns (hc_11) ---
        month_patterns = checks.get("month_patterns", [])
        if month_patterns:
            month_hits = _count_pattern_matches(text, month_patterns)
            if month_hits > 0:
                score += 0.4
                reasons.append("Correct month identified")
            else:
                reasons.append("Correct month not found")

        # --- Percentage range check (hc_11) ---
        pct_range = checks.get("percentage_range")
        if pct_range:
            extracted_pct = _extract_percentage(text)
            if extracted_pct is not None:
                if pct_range["min"] <= extracted_pct <= pct_range["max"]:
                    score += 0.4
                    reasons.append(f"Percentage {extracted_pct:.1f}% within expected range")
                else:
                    reasons.append(f"Percentage {extracted_pct:.1f}% outside expected range [{pct_range['min']}-{pct_range['max']}%]")
            else:
                reasons.append("No percentage found in response")

        # --- Min items count (hc_14) ---
        min_items = checks.get("min_items")
        if min_items is not None:
            item_count = _count_items(text)
            # Also count lines that look like name+tagline pairs
            name_lines = len([
                line for line in text.strip().split("\n")
                if line.strip() and (
                    re.match(r"^\d+[.)]\s+", line.strip()) or
                    re.match(r"^[-*]\s+", line.strip()) or
                    re.match(r"^\*\*", line.strip())
                )
            ])
            counted = max(item_count, name_lines)
            if counted >= min_items:
                score = 0.7
                reasons.append(f"Found {counted} items (required: {min_items})")
            else:
                score = 0.3 * (counted / min_items) if min_items > 0 else 0.0
                reasons.append(f"Only {counted} items found (required: {min_items})")

        final_score = min(1.0, score)
        passed = final_score >= 0.5
        reason = "; ".join(reasons) if reasons else "Deterministic portion completed"
        return passed, final_score, reason

    def score(self, result: ModuleResult) -> ModuleScore:
        """Compute overall score with 6 category sub-scores in details.

        Categories: writing, code, reasoning, summarization, data_analysis,
        creative, regression_anchor.
        """
        if result.total_probes == 0:
            return ModuleScore(
                module_name=self.name, score=0.0, grade="F",
                passed=0, failed=0, total=0,
                critical_failures=0, high_failures=0,
                summary="No probes ran.",
            )

        # Group probes by category
        categories: dict[str, list[ProbeResult]] = {}
        probe_map = {p.id: p for p in _PROBES}

        for pr in result.probe_results:
            probe = probe_map.get(pr.probe_id)
            if probe:
                cat = probe.meta.get("category", "unknown")
            else:
                cat = "unknown"
            categories.setdefault(cat, []).append(pr)

        # Compute per-category scores
        category_scores: dict[str, float] = {}
        for cat, prs in categories.items():
            if prs:
                category_scores[cat] = sum(p.score for p in prs) / len(prs)
            else:
                category_scores[cat] = 0.0

        # Severity-weighted overall score (same as base class)
        severity_weights = {
            Severity.CRITICAL: 3.0,
            Severity.HIGH: 2.0,
            Severity.MEDIUM: 1.0,
            Severity.LOW: 0.5,
        }

        total_weight = 0.0
        weighted_score = 0.0
        critical_fails = 0
        high_fails = 0

        for pr in result.probe_results:
            w = severity_weights.get(pr.severity, 1.0)
            total_weight += w
            weighted_score += pr.score * w

            if not pr.passed:
                if pr.severity == Severity.CRITICAL:
                    critical_fails += 1
                elif pr.severity == Severity.HIGH:
                    high_fails += 1

        final_score = weighted_score / total_weight if total_weight > 0 else 0.0
        grade = ModuleScore.grade_from_score(final_score, critical_fails)

        # Build summary
        if critical_fails > 0:
            summary = f"FAILED: {critical_fails} critical failure(s). {result.passed_probes}/{result.total_probes} probes passed."
        elif final_score >= 0.90:
            summary = f"Strong: {result.passed_probes}/{result.total_probes} probes passed ({final_score:.0%})."
        elif final_score >= 0.60:
            summary = f"Mixed: {result.passed_probes}/{result.total_probes} probes passed ({final_score:.0%})."
        else:
            summary = f"Weak: {result.passed_probes}/{result.total_probes} probes passed ({final_score:.0%})."

        return ModuleScore(
            module_name=self.name,
            score=final_score,
            grade=grade,
            passed=result.passed_probes,
            failed=result.failed_probes,
            total=result.total_probes,
            critical_failures=critical_fails,
            high_failures=high_fails,
            summary=summary,
            details={
                "category_scores": {k: round(v, 3) for k, v in sorted(category_scores.items())},
                "categories_tested": len(category_scores),
                "probes_per_category": {k: len(v) for k, v in sorted(categories.items())},
            },
        )
