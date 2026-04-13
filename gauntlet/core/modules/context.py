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

import random
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
# Long passage generator for extended context probes
# ---------------------------------------------------------------------------

_NOVATECH_PARAGRAPHS = [
    "NovaTech Solutions reported strong Q{q} results for fiscal year 20{y}. Revenue from the enterprise division reached ${rev}M, driven by expanded partnerships with Fortune 500 clients. The sales team, led by Regional Director {name}, closed {deals} new contracts during the quarter. Management attributed the growth to improved customer retention strategies and a more aggressive pricing model for multi-year agreements.",
    "The infrastructure migration project entered its {phase} phase in {month} 20{y}. Lead architect {name} presented the updated timeline to the steering committee, estimating completion by Q{q} of the following year. The total allocated budget stands at ${rev}M, with ${spent}M already committed to vendor contracts. Server uptime during the transition period remained above 99.{uptime}%, exceeding the SLA target.",
    "NovaTech's product development team shipped version {major}.{minor} of the DataSync platform in {month} 20{y}. The release included {features} new features and resolved {bugs} critical bugs identified during the beta program. Quality assurance manager {name} confirmed that all regression tests passed, and the deployment was executed with zero downtime across all production environments.",
    "The quarterly client onboarding report showed {clients} new enterprise accounts activated during Q{q} 20{y}. Customer success lead {name} noted that average onboarding time decreased from {old_days} days to {new_days} days following the introduction of automated provisioning workflows. Client satisfaction scores averaged {score}/10 across all new accounts, up from {old_score}/10 in the previous quarter.",
    "NovaTech's security team completed its annual penetration testing cycle in {month} 20{y}. Chief Information Security Officer {name} reported that {vulns} vulnerabilities were identified, of which {critical} were classified as critical. All critical findings were remediated within the {sla}-hour SLA window. The team also implemented a new threat detection system with an estimated ${rev}K annual operating cost.",
    "Market analysis conducted by NovaTech's strategy division in Q{q} 20{y} identified {segments} emerging market segments with combined addressable revenue of ${rev}B. Senior analyst {name} recommended prioritizing the healthcare vertical, which showed {growth}% year-over-year growth in technology spending. The competitive landscape report noted {competitors} direct competitors in the enterprise middleware space.",
    "The human resources department processed {hires} new hires during Q{q} 20{y}, bringing total headcount to {total}. VP of People Operations {name} announced the launch of a revised compensation framework, with median salary adjustments of {adjust}% across engineering roles. Employee engagement surveys returned a {engage}% satisfaction rating, a {delta}-point improvement over the prior period.",
    "NovaTech's finance team released the consolidated P&L statement for Q{q} 20{y}. Gross margin improved to {margin}%, up from {old_margin}% in the same quarter last year. Controller {name} attributed the improvement to renegotiated cloud hosting agreements and reduced third-party licensing fees. Operating expenses totaled ${opex}M, in line with the board-approved annual budget of ${budget}M.",
    "The research and development division allocated ${rd}M toward its next-generation analytics engine in Q{q} 20{y}. Principal engineer {name} demonstrated an early prototype capable of processing {tps}K transactions per second, a {improvement}x improvement over the current production system. Patent applications for {patents} novel algorithms were filed with the USPTO during the quarter.",
    "NovaTech's partner ecosystem expanded to {partners} certified integrators by the end of Q{q} 20{y}. Channel director {name} signed strategic alliances with {new_partners} new technology vendors, including agreements for co-marketing initiatives valued at ${co_market}M. Partner-sourced revenue accounted for {partner_rev}% of total bookings, up from {old_partner_rev}% in the previous fiscal year.",
    "The data governance committee met on {month} {day}, 20{y} to review compliance readiness for upcoming regulatory changes. Chief compliance officer {name} confirmed that {pct}% of customer data had been migrated to the new encrypted storage tier. Audit preparation for the SOC 2 Type II certification is {status}, with the external auditor scheduled for {audit_month} 20{y}.",
    "NovaTech's customer support metrics for Q{q} 20{y} showed a median first-response time of {response_min} minutes, well within the {sla_min}-minute SLA. Support director {name} reported that ticket volume increased {ticket_pct}% quarter-over-quarter, primarily due to the DataSync {major}.{minor} release. Escalation rates remained stable at {esc}%, and CSAT scores held at {csat}%.",
    "The corporate development team evaluated {acq} potential acquisition targets during Q{q} 20{y}. VP of Corporate Development {name} presented term sheets for {shortlist} companies to the executive committee, with combined enterprise values ranging from ${low_ev}M to ${high_ev}M. Due diligence on the leading candidate, a {specialty} startup, is expected to conclude by {month} 20{y}.",
    "NovaTech's global operations expanded into the {region} market with the opening of a new regional office in {city} during Q{q} 20{y}. Country manager {name} onboarded an initial team of {staff} employees and secured {local_clients} pilot engagements with local enterprises. The office lease was signed for a {lease_years}-year term at an annual cost of ${lease_cost}K.",
    "The internal tooling team delivered Project Beacon in {month} 20{y}, a unified developer portal consolidating CI/CD pipelines, monitoring dashboards, and documentation. Engineering manager {name} reported that developer onboarding time decreased by {onboard_pct}% and deployment frequency increased from {old_deploys} to {new_deploys} releases per sprint. The platform serves {devs} active developers across {teams} engineering teams.",
]

_NOVATECH_NAMES = [
    "Sarah Mitchell", "David Chen", "Maria Gonzalez", "James Okafor",
    "Priya Sharma", "Michael Torres", "Aiko Tanaka", "Robert Kim",
    "Elena Volkov", "Samuel Adeyemi", "Laura Petrov", "Thomas Nakamura",
    "Fatima Al-Hassan", "Richard Lindqvist", "Amara Okonkwo",
]

_MONTHS = ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]

_REGIONS = ["Southeast Asian", "Central European", "Latin American", "Nordic", "Middle Eastern"]
_CITIES = ["Singapore", "Prague", "Bogota", "Stockholm", "Dubai"]
_PHASES = ["second", "third", "final", "integration", "validation"]
_STATUSES = ["on track", "ahead of schedule", "progressing well", "nearing completion"]
_SPECIALTIES = ["machine learning", "cybersecurity", "data integration", "cloud native", "edge computing"]


def _generate_long_passage(
    target_words: int,
    needle: str,
    needle_position: str = "middle",
    distractors: list[str] | None = None,
    seed: int | None = None,
) -> str:
    """Generate a long NovaTech passage with an embedded needle and optional distractors.

    Args:
        target_words: Approximate word count target.
        needle: The string to embed as a needle.
        needle_position: "beginning" (first 10%), "middle" (40-60%), or "end" (last 10%).
        distractors: Optional list of distractor strings to place at other positions.
        seed: Optional seed for reproducibility.
    """
    rng = random.Random(seed) if seed is not None else random.Random()

    paragraphs: list[str] = []
    word_count = 0

    while word_count < target_words:
        template = rng.choice(_NOVATECH_PARAGRAPHS)
        name = rng.choice(_NOVATECH_NAMES)
        month = rng.choice(_MONTHS)
        region_idx = rng.randint(0, len(_REGIONS) - 1)

        filled = template.format(
            q=rng.randint(1, 4), y=rng.randint(24, 26),
            rev=rng.randint(12, 95), spent=rng.randint(5, 40),
            name=name, deals=rng.randint(8, 45),
            phase=rng.choice(_PHASES), month=month,
            uptime=rng.randint(90, 99),
            major=rng.randint(3, 8), minor=rng.randint(0, 9),
            features=rng.randint(6, 25), bugs=rng.randint(3, 18),
            clients=rng.randint(5, 30), old_days=rng.randint(14, 30),
            new_days=rng.randint(5, 12), score=rng.randint(7, 9),
            old_score=rng.randint(6, 8),
            vulns=rng.randint(12, 50), critical=rng.randint(2, 8),
            sla=rng.randint(24, 72),
            segments=rng.randint(3, 7), growth=rng.randint(12, 35),
            competitors=rng.randint(4, 12),
            hires=rng.randint(20, 80), total=rng.randint(800, 2500),
            adjust=rng.randint(3, 8), engage=rng.randint(72, 92),
            delta=rng.randint(2, 7),
            margin=rng.randint(55, 75), old_margin=rng.randint(50, 70),
            opex=rng.randint(15, 60), budget=rng.randint(50, 200),
            rd=rng.randint(5, 25), tps=rng.randint(50, 500),
            improvement=rng.randint(2, 10), patents=rng.randint(2, 8),
            partners=rng.randint(40, 150), new_partners=rng.randint(5, 20),
            co_market=rng.randint(2, 15),
            partner_rev=rng.randint(15, 35), old_partner_rev=rng.randint(10, 25),
            day=rng.randint(1, 28), pct=rng.randint(70, 98),
            status=rng.choice(_STATUSES), audit_month=rng.choice(_MONTHS),
            response_min=rng.randint(3, 15), sla_min=rng.randint(15, 30),
            ticket_pct=rng.randint(5, 25), esc=rng.randint(2, 8),
            csat=rng.randint(85, 97),
            acq=rng.randint(3, 12), shortlist=rng.randint(2, 4),
            low_ev=rng.randint(20, 80), high_ev=rng.randint(100, 400),
            specialty=rng.choice(_SPECIALTIES),
            region=_REGIONS[region_idx], city=_CITIES[region_idx],
            staff=rng.randint(8, 30), local_clients=rng.randint(3, 10),
            lease_years=rng.randint(3, 7), lease_cost=rng.randint(200, 800),
            onboard_pct=rng.randint(20, 50),
            old_deploys=rng.randint(2, 5), new_deploys=rng.randint(6, 12),
            devs=rng.randint(50, 200), teams=rng.randint(5, 20),
        )
        paragraphs.append(filled)
        word_count += len(filled.split())

    total_paras = len(paragraphs)

    # Determine needle insertion index based on position
    if needle_position == "beginning":
        needle_idx = max(0, int(total_paras * 0.05))
    elif needle_position == "end":
        needle_idx = max(0, int(total_paras * 0.90))
    else:  # middle
        needle_idx = max(0, int(total_paras * 0.50))

    # Build needle paragraph
    needle_para = (
        f"During the network security review conducted in Q{rng.randint(1,4)} 20{rng.randint(24,26)}, "
        f"the security audit section referenced authorization code {needle}. "
        f"This identifier was flagged by the compliance team for tracking across all subsequent audit reports."
    )
    paragraphs.insert(needle_idx, needle_para)

    # Insert distractors at other positions
    if distractors:
        for i, distractor in enumerate(distractors):
            # Spread distractors away from needle
            if needle_position == "middle":
                if i % 2 == 0:
                    d_idx = max(0, int(len(paragraphs) * 0.15))
                else:
                    d_idx = min(len(paragraphs), int(len(paragraphs) * 0.85))
            elif needle_position == "end":
                d_idx = max(0, int(len(paragraphs) * (0.2 + i * 0.2)))
            else:  # beginning
                d_idx = min(len(paragraphs), int(len(paragraphs) * (0.5 + i * 0.15)))

            distractor_para = (
                f"A secondary reference code {distractor} appeared in the preliminary review notes "
                f"from {rng.choice(_MONTHS)} but was subsequently marked as superseded and inactive."
            )
            paragraphs.insert(d_idx, distractor_para)

    return "\n\n".join(paragraphs)


# Pre-generate static long passages for non-parameterized probes
_PASSAGE_CTX11 = _generate_long_passage(
    target_words=1000, needle="AUTH-GAMMA-7721",
    needle_position="middle",
    distractors=["AUTH-DELTA-9933", "AUTH-BETA-5504"],
    seed=42,
)

_PASSAGE_CTX12 = _generate_long_passage(
    target_words=5000, needle="BUDGET-APEX-2847",
    needle_position="end",
    distractors=None,
    seed=43,
)

_PASSAGE_CTX13_PHASE1 = _generate_long_passage(
    target_words=500, needle="PHASE-1-BUDGET-2300000",
    needle_position="beginning",
    distractors=None,
    seed=44,
).replace(
    "PHASE-1-BUDGET-2300000",
    "$2.3M allocated for Phase 1 infrastructure modernization",
)

_PASSAGE_CTX13_PHASE2 = _generate_long_passage(
    target_words=500, needle="PHASE-2-BUDGET-1700000",
    needle_position="beginning",
    distractors=None,
    seed=45,
).replace(
    "PHASE-2-BUDGET-1700000",
    "$1.7M allocated for Phase 2 application development",
)

_PASSAGE_CTX14 = _generate_long_passage(
    target_words=1000, needle="REF-OMEGA-3319",
    needle_position="beginning",
    distractors=None,
    seed=46,
)

_PASSAGE_CTX15 = _generate_long_passage(
    target_words=10000, needle="CIPHER-NOVA-8856",
    needle_position="middle",
    distractors=["CIPHER-LUNA-4421", "CIPHER-VEGA-2290", "CIPHER-MARS-6617"],
    seed=47,
)


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

    # --- LONG CONTEXT PROBES ---
    Probe(
        id="ctx_11",
        name="Long context: 1K passage with distractors",
        description="Find a needle code in ~1000-word passage with distractor codes",
        severity=Severity.HIGH,
        tags=["needle_haystack", "long_context"],
        messages=[
            ("user", f"Read this document carefully:\n\n{_PASSAGE_CTX11}\n\nWhat is the primary authorization code referenced in the security audit section?"),
        ],
        expected="Should find: AUTH-GAMMA-7721",
        meta={"answer_pattern": r"AUTH[\s-]*GAMMA[\s-]*7721"},
    ),
    Probe(
        id="ctx_12",
        name="Long context: 5K passage, needle at end",
        description="Find a budget identifier near the end of a ~5000-word document",
        severity=Severity.HIGH,
        tags=["needle_haystack", "long_context"],
        messages=[
            ("user", f"Read this document carefully:\n\n{_PASSAGE_CTX12}\n\nWhat is the budget tracking identifier mentioned near the end of this document?"),
        ],
        expected="Should find: BUDGET-APEX-2847",
        meta={"answer_pattern": r"BUDGET[\s-]*APEX[\s-]*2847"},
    ),
    Probe(
        id="ctx_13",
        name="Long context: multi-document synthesis",
        description="Combine budget figures from two separate documents",
        severity=Severity.HIGH,
        tags=["multi_fact", "long_context"],
        messages=[
            ("user",
             f"Read the following two project documents:\n\n"
             f"--- DOCUMENT A: Phase 1 Report ---\n\n{_PASSAGE_CTX13_PHASE1}\n\n"
             f"--- DOCUMENT B: Phase 2 Report ---\n\n{_PASSAGE_CTX13_PHASE2}\n\n"
             f"What is the combined total budget across both Phase 1 and Phase 2?"),
        ],
        expected="Should find: $4.0M ($2.3M + $1.7M)",
        meta={"required_patterns": [r"\$?4[\s,.]?0|\bfour\s+million\b"]},
    ),
    Probe(
        id="ctx_14",
        name="Long context: 1K passage, needle at beginning",
        description="Find a reference code in the opening section of a ~1000-word document",
        severity=Severity.MEDIUM,
        tags=["needle_haystack", "long_context"],
        messages=[
            ("user", f"Read this document carefully:\n\n{_PASSAGE_CTX14}\n\nWhat reference code appears in the opening section?"),
        ],
        expected="Should find: REF-OMEGA-3319",
        meta={"answer_pattern": r"REF[\s-]*OMEGA[\s-]*3319"},
    ),
    Probe(
        id="ctx_15",
        name="Long context: 10K passage with deep needle",
        description="Find a cipher code in a ~10000-word document with 3 distractors",
        severity=Severity.HIGH,
        tags=["needle_haystack", "long_context"],
        messages=[
            ("user", f"Read this document carefully:\n\n{_PASSAGE_CTX15}\n\nIn the network security review section, what is the exact cipher reference code?"),
        ],
        expected="Should find: CIPHER-NOVA-8856",
        meta={"answer_pattern": r"CIPHER[\s-]*NOVA[\s-]*8856"},
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

        # Generate parameterized long-context probes with randomized needles
        rand_needle_11 = f"AUTH-{gen.canary_string().split('-')[1]}-{gen.random_int(1000, 9999)}"
        passage_11 = _generate_long_passage(
            target_words=1000, needle=rand_needle_11,
            needle_position="middle",
            distractors=["AUTH-DELTA-9933", "AUTH-BETA-5504"],
            seed=seed + 100,
        )
        probes.append(Probe(
            id="ctx_11p",
            name="Long context: 1K passage with distractors (parameterized)",
            description="Find a randomized needle in ~1000-word passage with distractors",
            severity=Severity.HIGH,
            tags=["needle_haystack", "long_context"],
            messages=[
                ("user", f"Read this document carefully:\n\n{passage_11}\n\nWhat is the primary authorization code referenced in the security audit section?"),
            ],
            expected=f"Should find: {rand_needle_11}",
            meta={"answer_pattern": rand_needle_11.replace("-", r"[\s-]*")},
        ))

        rand_needle_14 = f"REF-{gen.canary_string().split('-')[1]}-{gen.random_int(1000, 9999)}"
        passage_14 = _generate_long_passage(
            target_words=1000, needle=rand_needle_14,
            needle_position="beginning",
            distractors=None,
            seed=seed + 200,
        )
        probes.append(Probe(
            id="ctx_14p",
            name="Long context: 1K passage, needle at beginning (parameterized)",
            description="Find a randomized reference code in the opening section",
            severity=Severity.MEDIUM,
            tags=["needle_haystack", "long_context"],
            messages=[
                ("user", f"Read this document carefully:\n\n{passage_14}\n\nWhat reference code appears in the opening section?"),
            ],
            expected=f"Should find: {rand_needle_14}",
            meta={"answer_pattern": rand_needle_14.replace("-", r"[\s-]*")},
        ))

        # Keep static long-context probes that don't benefit from parameterization
        static_long_ids = {"ctx_12", "ctx_13", "ctx_15"}
        for p in _PROBES_FULL:
            if p.id in static_long_ids:
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
