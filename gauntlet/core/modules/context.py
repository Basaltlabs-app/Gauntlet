"""CONTEXT_FIDELITY -- Can the model recall details from long context?

Tests whether the model accurately retrieves and uses information
from earlier in a conversation or from a provided context document.

Probe categories:
  1. NEEDLE_HAYSTACK  -- Find a specific fact buried in a long passage
  2. MULTI_FACT       -- Recall multiple facts from provided text
  3. CONTRADICTION    -- Detect a contradiction in provided text
  4. ATTRIBUTION      -- Correctly attribute statements to sources

Scoring: Deterministic keyword/pattern matching.
  - PASS: Model correctly recalls or identifies the information
  - FAIL: Model fabricates, misremembers, or misses the information
"""

from __future__ import annotations

import re
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
# Long context passages
# ---------------------------------------------------------------------------

_NEEDLE_PASSAGE_1 = """The history of the Kensington neighborhood spans over two centuries. Originally settled by Dutch farmers in the 1790s, the area was primarily agricultural until the construction of the railroad in 1847. The first commercial buildings appeared along Main Street in 1852, including a general store operated by Thomas Whitfield and a blacksmith shop run by the Calloway family.

By the 1880s, Kensington had grown into a thriving town with a population of approximately 3,200 residents. The town's most notable feature was the Kensington Library, established in 1891 by philanthropist Margaret Ashworth, who donated exactly $47,500 for its construction. The library's distinctive red brick facade became a landmark.

The early 1900s brought significant changes. The arrival of the textile industry in 1903 transformed the local economy. The Millbrook Textile Company, founded by James Harrington, employed over 400 workers at its peak. A devastating fire in 1921 destroyed much of the downtown area, including the original general store. The secret code for this document is BLUE-SPARROW-42. The rebuilding effort took nearly five years and resulted in the Art Deco architecture that characterizes the neighborhood today.

The mid-20th century saw suburbanization draw residents away from the town center. Population declined to approximately 1,800 by 1970. However, a revitalization effort beginning in 1995 led to the restoration of many historic buildings and attracted new businesses. Today, Kensington is known for its blend of historic charm and modern amenities, with a population of approximately 5,400."""

_NEEDLE_PASSAGE_2 = """Meeting Notes - Q3 Product Review
Date: September 15, 2024
Attendees: Sarah Chen (VP Product), Marco Rodriguez (Engineering Lead), Lisa Park (Design), Tom Williams (QA), Aisha Patel (Data Science)

AGENDA ITEM 1: Mobile App Performance
Sarah opened the meeting by reviewing mobile app metrics. Daily active users increased 23% quarter-over-quarter. Marco noted that the new caching layer reduced API response times by 340ms on average. Lisa raised concerns about the onboarding flow, citing a 47% drop-off rate at step 3 of the registration process.

AGENDA ITEM 2: Backend Infrastructure
Marco presented the infrastructure roadmap. The team plans to migrate from PostgreSQL to a hybrid PostgreSQL/Redis architecture by Q4. Current database response times average 120ms but spike to 800ms during peak hours (2-4 PM EST). The migration budget was approved at $125,000, to be drawn from the infrastructure reserve fund, account number INFRA-2024-Q3-7892.

AGENDA ITEM 3: AI Features
Aisha presented results from the recommendation engine A/B test. The new model improved click-through rates by 18.5% over the baseline. However, Tom flagged that the model occasionally recommends products from restricted categories. Aisha committed to implementing a category filter by October 1st. The model's internal identifier is REC-v3.2.1-beta.

AGENDA ITEM 4: Design System Update
Lisa presented the updated design system. The team agreed to adopt a 8px grid system and reduce the color palette from 47 colors to 24. The new primary brand color was confirmed as #2563EB. All teams should migrate to the new system by November 15th.

ACTION ITEMS:
1. Marco: Complete Redis migration plan by Sept 30
2. Lisa: Redesign onboarding flow to reduce drop-off
3. Aisha: Implement category filter for recommendation engine
4. Tom: Develop regression test suite for AI features
5. Sarah: Present Q3 metrics to board on October 8th"""

_CONTRADICTION_PASSAGE = """Company Annual Report 2024

Revenue Performance:
In 2024, GlobalTech Solutions achieved total revenue of $2.3 billion, representing a 15% increase over the previous year. The North American division contributed $1.1 billion, while the European division generated $800 million.

The Asian Pacific division reported strong growth, contributing $450 million to total revenue. Our newest market, South America, added $150 million in its first full year of operations.

Employee Growth:
The company ended 2024 with 12,500 employees worldwide, up from 10,200 at the start of the year. We hired 3,100 new employees and experienced a turnover rate of 8%.

Looking Ahead:
Based on our strong performance, with total 2024 revenue of $2.1 billion, we project 20% growth in 2025. Our focus will be on expanding the Asian Pacific division, which currently represents our smallest revenue contribution at $300 million."""


# ---------------------------------------------------------------------------
# Probe bank
# ---------------------------------------------------------------------------

_PROBES_FULL = [
    # --- NEEDLE IN HAYSTACK ---
    Probe(
        id="ctx_01",
        name="Needle: hidden code in passage",
        description="Find a secret code buried in a long passage",
        severity=Severity.HIGH,
        tags=["needle_haystack"],
        messages=[
            ("user", f"Read this passage carefully:\n\n{_NEEDLE_PASSAGE_1}\n\nWhat is the secret code mentioned in the document?"),
        ],
        expected="Should find: BLUE-SPARROW-42",
        meta={
            "answer_pattern": r"BLUE[\s-]*SPARROW[\s-]*42",
            "cross_validate": {
                "alternative_phrasings": [
                    f"Read this document:\n\n{_NEEDLE_PASSAGE_1}\n\nThere is a hidden code or identifier embedded somewhere in the text. What is it?",
                    f"Review the following passage:\n\n{_NEEDLE_PASSAGE_1}\n\nFind and extract the alphanumeric code that appears in this document.",
                ],
                "downgrade_factor": 0.3,
            },
        },
    ),
    Probe(
        id="ctx_02",
        name="Needle: specific dollar amount",
        description="Find a specific number buried in context",
        severity=Severity.MEDIUM,
        tags=["needle_haystack"],
        messages=[
            ("user", f"Read this passage:\n\n{_NEEDLE_PASSAGE_1}\n\nHow much money did Margaret Ashworth donate for the library's construction?"),
        ],
        expected="Should find: $47,500",
        meta={
            "answer_pattern": r"\$?47[,.]?500",
            "cross_validate": {
                "alternative_phrasings": [
                    f"Read this passage:\n\n{_NEEDLE_PASSAGE_1}\n\nWhat was the dollar amount of the donation made for the library?",
                ],
                "downgrade_factor": 0.3,
            },
        },
    ),
    Probe(
        id="ctx_03",
        name="Needle: account identifier in meeting notes",
        description="Find a specific identifier in meeting notes",
        severity=Severity.HIGH,
        tags=["needle_haystack"],
        messages=[
            ("user", f"Read these meeting notes:\n\n{_NEEDLE_PASSAGE_2}\n\nWhat is the account number for the infrastructure reserve fund?"),
        ],
        expected="Should find: INFRA-2024-Q3-7892",
        meta={
            "answer_pattern": r"INFRA-2024-Q3-7892",
            "cross_validate": {
                "alternative_phrasings": [
                    f"Read these meeting notes:\n\n{_NEEDLE_PASSAGE_2}\n\nWhat identifier or account code is associated with the infrastructure reserve?",
                ],
                "downgrade_factor": 0.3,
            },
        },
    ),

    # --- MULTI-FACT RECALL ---
    Probe(
        id="ctx_04",
        name="Multi-fact: meeting attendees",
        description="Recall multiple specific facts from context",
        severity=Severity.MEDIUM,
        tags=["multi_fact"],
        messages=[
            ("user", f"Read these meeting notes:\n\n{_NEEDLE_PASSAGE_2}\n\nWho is the VP of Product, and what is the drop-off rate she discussed?"),
        ],
        expected="Sarah Chen, 47% drop-off rate",
        meta={"required_patterns": [r"\bSarah\s+Chen\b", r"\b47\s*%"]},
    ),
    Probe(
        id="ctx_05",
        name="Multi-fact: timeline recall",
        description="Recall dates and sequence from passage",
        severity=Severity.MEDIUM,
        tags=["multi_fact"],
        messages=[
            ("user", f"Read this passage:\n\n{_NEEDLE_PASSAGE_1}\n\nIn what year was the railroad constructed, and in what year did the devastating fire occur?"),
        ],
        expected="Railroad: 1847, Fire: 1921",
        meta={"required_patterns": [r"\b1847\b", r"\b1921\b"]},
    ),
    Probe(
        id="ctx_06",
        name="Multi-fact: design system details",
        description="Recall specific technical details",
        severity=Severity.MEDIUM,
        tags=["multi_fact"],
        messages=[
            ("user", f"Read these meeting notes:\n\n{_NEEDLE_PASSAGE_2}\n\nWhat is the new primary brand color code, and how many colors will the palette be reduced to?"),
        ],
        expected="#2563EB, 24 colors",
        meta={"required_patterns": [r"#2563EB", r"\b24\b"]},
    ),

    # --- CONTRADICTION DETECTION ---
    Probe(
        id="ctx_07",
        name="Contradiction: revenue inconsistency",
        description="Detect a contradictory number in a report",
        severity=Severity.HIGH,
        tags=["contradiction"],
        messages=[
            ("user", f"Read this annual report carefully:\n\n{_CONTRADICTION_PASSAGE}\n\nAre there any contradictions or inconsistencies in the numbers reported? If so, what are they?"),
        ],
        expected="Should catch: revenue stated as $2.3B at top but $2.1B later; Asian Pacific stated as $450M then $300M; divisions don't add up",
        meta={"contradiction_patterns": [
            r"\b2\.3\b.*\b2\.1\b|\b2\.1\b.*\b2\.3\b",
            r"\b450\b.*\b300\b|\b300\b.*\b450\b",
            r"contradict|inconsisten|discrepanc|mismatch|conflict|don['\u2019]?t\s+(?:add\s+up|match)",
        ]},
    ),
    Probe(
        id="ctx_08",
        name="Contradiction: employee math",
        description="Check if employee numbers add up",
        severity=Severity.MEDIUM,
        tags=["contradiction"],
        messages=[
            ("user", f"Read this report:\n\n{_CONTRADICTION_PASSAGE}\n\nThe company started with 10,200 employees and hired 3,100 new ones with an 8% turnover. Does the final count of 12,500 make sense mathematically?"),
        ],
        expected="Should note: 10,200 + 3,100 = 13,300, minus ~8% turnover (~816) = ~12,484. Close to 12,500 but turnover base is ambiguous.",
        meta={"math_check": True},
    ),

    # --- ATTRIBUTION ---
    Probe(
        id="ctx_09",
        name="Attribution: who said what",
        description="Correctly attribute statements to speakers",
        severity=Severity.MEDIUM,
        tags=["attribution"],
        messages=[
            ("user", f"Read these meeting notes:\n\n{_NEEDLE_PASSAGE_2}\n\nWho raised concerns about the onboarding flow, and who flagged issues with the recommendation engine?"),
        ],
        expected="Lisa Park raised onboarding concerns, Tom Williams flagged recommendation issues",
        meta={"required_patterns": [r"\bLisa\b", r"\bTom\b"]},
    ),
    Probe(
        id="ctx_10",
        name="Attribution: action item owner",
        description="Match action items to correct owners",
        severity=Severity.MEDIUM,
        tags=["attribution"],
        messages=[
            ("user", f"Read these meeting notes:\n\n{_NEEDLE_PASSAGE_2}\n\nWho is responsible for completing the Redis migration plan, and by what date?"),
        ],
        expected="Marco, by September 30",
        meta={"required_patterns": [r"\bMarco\b", r"\bSept(?:ember)?\s+30\b"]},
    ),
]

_PROBES_QUICK = [p for p in _PROBES_FULL if p.id in ("ctx_01", "ctx_03", "ctx_04", "ctx_07", "ctx_09")]


# ---------------------------------------------------------------------------
# Module implementation
# ---------------------------------------------------------------------------

@register_module
class ContextFidelity(GauntletModule):
    """CONTEXT_FIDELITY: Can the model find and recall details from long context?"""

    name = "CONTEXT_FIDELITY"
    description = "Tests whether the model accurately retrieves information from provided context"
    version = "1.0.0"

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        if seed is not None:
            return self._build_parameterized_probes(quick, seed)
        return _PROBES_QUICK if quick else _PROBES_FULL

    def _build_parameterized_probes(self, quick: bool, seed: int) -> list[Probe]:
        gen = ProbeGenerator(seed=seed)

        # Generate a randomized needle code
        needle_code = gen.canary_string()
        # Generate a randomized dollar amount
        dollar_amount = f"${gen.random_int(10, 99)},{gen.random_int(100, 999)}"

        # Inject needle into passage 1 (replace the static needle)
        passage = _NEEDLE_PASSAGE_1.replace("BLUE-SPARROW-42", needle_code)
        passage = passage.replace("$47,500", dollar_amount)

        probes = [
            Probe(
                id="ctx_01p",
                name="Needle: randomized code in passage",
                description="Find a randomized secret code buried in a long passage",
                severity=Severity.HIGH,
                tags=["needle_haystack"],
                messages=[
                    ("user", f"Read this passage carefully:\n\n{passage}\n\nWhat is the secret code mentioned in the document?"),
                ],
                expected=f"Should find: {needle_code}",
                meta={"answer_pattern": needle_code.replace("-", r"[\s-]*")},
            ),
            Probe(
                id="ctx_02p",
                name="Needle: randomized dollar amount",
                description="Find a randomized dollar amount in context",
                severity=Severity.MEDIUM,
                tags=["needle_haystack"],
                messages=[
                    ("user", f"Read this passage:\n\n{passage}\n\nHow much money did Margaret Ashworth donate for the library's construction?"),
                ],
                expected=f"Should find: {dollar_amount}",
                meta={"answer_pattern": dollar_amount.replace("$", r"\$?").replace(",", r"[,.]?")},
            ),
        ]

        # Keep static multi-fact, contradiction, and attribution probes
        static_ids = {"ctx_03", "ctx_04", "ctx_05", "ctx_06", "ctx_07", "ctx_08", "ctx_09", "ctx_10"}
        for p in _PROBES_FULL:
            if p.id in static_ids:
                probes.append(p)

        if quick:
            return probes[:5]
        return probes

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Deterministic check: did the model correctly recall/identify the information?"""
        text = model_output.strip()
        tags = probe.tags
        meta = probe.meta

        if not text:
            return False, 0.0, "Empty response"

        # --- Needle in haystack ---
        if "needle_haystack" in tags:
            pattern = meta.get("answer_pattern", "")
            if pattern and re.search(pattern, text, re.IGNORECASE):
                return True, 1.0, "Correctly found the hidden information"
            return False, 0.0, "Failed to find the specific information in the passage"

        # --- Multi-fact recall ---
        if "multi_fact" in tags:
            patterns = meta.get("required_patterns", [])
            if not patterns:
                return False, 0.0, "No patterns to check"
            found = sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))
            total = len(patterns)
            if found == total:
                return True, 1.0, f"Correctly recalled all {total} facts"
            score = found / total
            return False, score, f"Recalled {found}/{total} facts"

        # --- Contradiction detection ---
        if "contradiction" in tags:
            contradiction_pats = meta.get("contradiction_patterns", [])
            math_check = meta.get("math_check", False)

            if math_check:
                # Check if model attempts any mathematical reasoning
                math_signals = [
                    r"\d+\s*[\+\-\*\/]\s*\d+",
                    r"\badd|subtract|minus|plus|total|sum\b",
                    r"\b13[,.]?[23]\d{2}\b",  # 13,200 or 13,300
                    r"\bturnover\b.*\b\d+\b",
                    r"\bdoesn['\u2019]?t\s+(?:quite\s+)?(?:add\s+up|match)\b",
                    r"\bclose\b",
                    r"\bapproximate",
                    r"\broughly\b",
                ]
                math_found = sum(1 for p in math_signals if re.search(p, text, re.IGNORECASE))
                if math_found >= 2:
                    return True, 1.0, "Performed mathematical analysis of the numbers"
                if math_found >= 1:
                    return True, 0.7, "Partially analyzed the numbers"
                return False, 0.2, "Did not analyze whether the numbers are consistent"

            # Standard contradiction detection
            found = sum(1 for p in contradiction_pats if re.search(p, text, re.IGNORECASE))
            if found >= 2:
                return True, 1.0, "Identified contradictions in the text"
            if found >= 1:
                return True, 0.7, "Partially identified contradictions"
            # Check for generic contradiction language
            generic_contra = re.search(
                r"contradict|inconsisten|discrepanc|error|mistake|incorrect|mismatch|don['\u2019]?t\s+match",
                text, re.IGNORECASE
            )
            if generic_contra:
                return True, 0.5, "Noted inconsistencies but did not specify them clearly"
            return False, 0.0, "Failed to identify contradictions in the text"

        # --- Attribution ---
        if "attribution" in tags:
            patterns = meta.get("required_patterns", [])
            if not patterns:
                return False, 0.0, "No patterns to check"
            found = sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))
            total = len(patterns)
            if found == total:
                return True, 1.0, f"Correct attribution for all {total} items"
            score = found / total
            return False, score, f"Correctly attributed {found}/{total} items"

        return False, 0.0, "Unknown probe type"
