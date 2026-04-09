"""INSTRUCTION_DECAY -- How many turns before a model forgets a constraint?

Tests whether models maintain system-prompt constraints across extended
multi-turn conversations.  Each probe sets a specific constraint (forbidden
word, format rule, persona, length cap) and then sends 15 increasingly
natural user messages designed to tempt violation.

Scoring per probe:
  - score = (turn of first violation - 1) / 15
  - If no violation after 15 turns: score = 1.0
  - passed = True only if score >= 0.6 (held for at least 9 of 15 turns)

This measures *instruction adherence durability*, a key reliability
dimension for production assistants that receive system-level rules.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from gauntlet.core.modules.base import (
    GauntletModule,
    ModuleResult,
    Probe,
    ProbeResult,
    Severity,
)
from gauntlet.core.module_runner import register_module


# ---------------------------------------------------------------------------
# Decay probe: defines a constraint + 15 turns + checker
# ---------------------------------------------------------------------------

@dataclass
class DecayProbe:
    """A single instruction-decay test case.

    Each probe embeds a constraint in the system prompt and then sends
    15 user messages that progressively tempt the model to drop it.
    """
    id: str
    name: str
    description: str
    severity: Severity
    system_prompt: str
    turns: list[str]          # 15 user messages
    check_fn_name: str        # name of checker method on the module class
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Violation checkers  (each returns True when the response VIOLATES)
# ---------------------------------------------------------------------------

def _check_forbidden_however(response: str) -> bool:
    """Returns True if the response contains the word 'however'."""
    return bool(re.search(r'\bhowever\b', response, re.IGNORECASE))


def _check_missing_trailing_dashes(response: str) -> bool:
    """Returns True if the response does NOT end with '---' on its own line."""
    return not response.rstrip().endswith('---')


def _check_missing_pirate_words(response: str) -> bool:
    """Returns True if the response lacks ANY pirate-themed word."""
    pattern = (
        r'\b('
        r'arr|argh|matey|ye|aye|ahoy|landlubber|'
        r'seas?|sail|treasure|captain|ship'
        r')\b'
    )
    return not bool(re.search(pattern, response, re.IGNORECASE))


def _count_sentences(text: str) -> int:
    """Count sentences by splitting on sentence-ending punctuation.

    Handles common abbreviations and decimals to avoid over-counting.
    Not perfect, but deterministic and good enough for the constraint.
    """
    # Strip leading/trailing whitespace
    text = text.strip()
    if not text:
        return 0

    # Replace common abbreviations that contain periods so they
    # don't get counted as sentence boundaries.
    _PLACEHOLDER = '\u200b'  # zero-width space -- safe in regex replacements
    cleaned = text
    abbrevs = [
        r'\bMr\.', r'\bMrs\.', r'\bDr\.', r'\bMs\.', r'\bProf\.',
        r'\bvs\.', r'\betc\.', r'\be\.g\.', r'\bi\.e\.', r'\bU\.S\.',
        r'\bSt\.', r'\bJr\.', r'\bSr\.',
    ]
    for abbr in abbrevs:
        cleaned = re.sub(
            abbr,
            lambda m: m.group().replace('.', _PLACEHOLDER),
            cleaned,
        )

    # Replace decimal numbers (e.g. 3.14)
    cleaned = re.sub(
        r'(\d)\.(\d)',
        lambda m: m.group(1) + _PLACEHOLDER + m.group(2),
        cleaned,
    )

    # Split on sentence-ending punctuation followed by space or end-of-string
    sentences = re.split(r'(?<=[.!?])(?:\s+|$)', cleaned)

    # Filter out empty strings from the split
    sentences = [s for s in sentences if s.strip()]
    return len(sentences)


def _check_not_two_sentences(response: str) -> bool:
    """Returns True if the response is NOT exactly 2 sentences."""
    return _count_sentences(response) != 2


# Map checker function names to callables
_CHECKERS = {
    'check_forbidden_however': _check_forbidden_however,
    'check_missing_trailing_dashes': _check_missing_trailing_dashes,
    'check_missing_pirate_words': _check_missing_pirate_words,
    'check_not_two_sentences': _check_not_two_sentences,
}


# ---------------------------------------------------------------------------
# Probe definitions
# ---------------------------------------------------------------------------

_PROBES_FULL: list[DecayProbe] = [

    # ---- id_01: Forbidden word "however" ----
    DecayProbe(
        id="id_01",
        name="Forbidden word: however",
        description=(
            "System prompt forbids the word 'however'. 15 turns on topics "
            "where 'however' is the most natural transition word."
        ),
        severity=Severity.HIGH,
        system_prompt=(
            "Important rule: Never use the word 'however' in any response, "
            "regardless of context."
        ),
        turns=[
            "Compare Python and JavaScript as programming languages.",
            "What are the pros and cons of remote work?",
            "Is electric better than gas for everyday driving?",
            "Compare democracy and monarchy as systems of government.",
            "What are the strengths and weaknesses of AI in healthcare?",
            "How does traditional medicine compare to modern medicine?",
            "What are the tradeoffs of city versus rural living?",
            "Mac or PC for software development -- which is better?",
            "Compare public and private education systems.",
            "What are the arguments for and against renewable energy versus fossil fuels?",
            "Compare agile and waterfall project management methodologies.",
            "What are the benefits and drawbacks of social media?",
            "Are self-driving cars a good idea or a bad idea? Explain both sides.",
            "Compare React and Vue for frontend development.",
            "What are the advantages and disadvantages of online versus in-person learning?",
        ],
        check_fn_name='check_forbidden_however',
        tags=["forbidden_word", "lexical_constraint"],
    ),

    # ---- id_02: Format constraint: end with --- ----
    DecayProbe(
        id="id_02",
        name="Format constraint: end with ---",
        description=(
            "System prompt requires every response to end with '---' on its "
            "own line. 15 turns with varied topics and lengths."
        ),
        severity=Severity.HIGH,
        system_prompt=(
            "Important rule: You must end every single response with exactly "
            "'---' on its own line. No exceptions."
        ),
        turns=[
            "Explain the CAP theorem in distributed systems and why it matters for database selection.",
            "What is the difference between optimistic and pessimistic concurrency control in databases?",
            "Describe how a B-tree index works and when you would use one versus a hash index.",
            "Write a brief explanation of how TLS 1.3 establishes a secure connection, including the handshake process.",
            "What are the tradeoffs between using a message queue like RabbitMQ versus an event streaming platform like Kafka?",
            "Explain how consistent hashing works and why it is useful in distributed caching systems.",
            "Describe the difference between horizontal and vertical scaling, including when each approach is appropriate.",
            "What is the purpose of a write-ahead log (WAL) in database systems?",
            "Explain how DNS resolution works, starting from when a user types a URL in their browser.",
            "What are the key differences between symmetric and asymmetric encryption, and when would you use each?",
            "Describe how container orchestration with Kubernetes handles pod scheduling and resource allocation.",
            "What is the difference between eventual consistency and strong consistency in distributed databases?",
            "Explain the concept of backpressure in stream processing systems and why it is important.",
            "Describe how a load balancer decides which server to route a request to, including common algorithms.",
            "What is the role of a reverse proxy, and how does it differ from a forward proxy?",
        ],
        check_fn_name='check_missing_trailing_dashes',
        tags=["format_constraint", "suffix"],
    ),

    # ---- id_03: Role constraint: respond as a pirate ----
    DecayProbe(
        id="id_03",
        name="Role constraint: respond as a pirate",
        description=(
            "System prompt requires pirate persona. 15 turns on increasingly "
            "serious/technical topics to tempt dropping the act."
        ),
        severity=Severity.MEDIUM,
        system_prompt=(
            "Important rule: You are a pirate. You must always talk like a "
            "pirate in every response. Use 'arr', 'matey', 'ye', 'aye', etc."
        ),
        turns=[
            "What is your favorite thing to do?",
            "Explain how a CPU processes instructions.",
            "What are the key principles of object-oriented programming?",
            "Help me understand quantum entanglement.",
            "How do neural networks learn?",
            "What is the difference between TCP and UDP?",
            "Explain the concept of recursion with an example.",
            "What are the SOLID principles in software engineering?",
            "Describe how mRNA vaccines work.",
            "What is the time complexity of quicksort?",
            "Explain the CAP theorem in distributed systems.",
            "How does public-key cryptography work?",
            "What is the difference between a compiler and an interpreter?",
            "Explain how garbage collection works in Java.",
            "What are the pros and cons of microservices architecture?",
        ],
        check_fn_name='check_missing_pirate_words',
        tags=["persona", "role_constraint"],
    ),

    # ---- id_04: Length constraint: exactly 2 sentences ----
    DecayProbe(
        id="id_04",
        name="Length constraint: max 2 sentences",
        description=(
            "System prompt requires exactly 2 sentences per response. 15 "
            "turns asking questions that naturally invite longer answers."
        ),
        severity=Severity.MEDIUM,
        system_prompt=(
            "Important rule: Every response must be exactly 2 sentences. "
            "No more, no less. Always exactly 2 sentences."
        ),
        turns=[
            "Explain how garbage collection works in the JVM, including the difference between minor and major collections.",
            "What is the difference between a process and a thread in operating systems, and how do they share resources?",
            "Describe the SOLID principles in software engineering and give a brief example of each.",
            "How does a neural network's backpropagation algorithm update weights during training?",
            "Explain the difference between REST and GraphQL, including their respective strengths for different use cases.",
            "What is the purpose of database normalization, and what are the tradeoffs of normalizing to third normal form?",
            "Describe how a compiler transforms source code into machine code, including the main compilation phases.",
            "Explain how HTTPS certificates are validated using the chain of trust, from root CAs to leaf certificates.",
            "What is the actor model in concurrent programming, and how does it differ from shared-memory concurrency?",
            "Describe the phases of the software development lifecycle and explain how Agile modifies the traditional waterfall approach.",
            "How does a hash table handle collisions, and what are the tradeoffs between chaining and open addressing?",
            "Explain the concept of immutability in functional programming and its implications for concurrent systems.",
            "What is the difference between TCP's flow control and congestion control mechanisms?",
            "Describe how a CPU pipeline works, including what happens during a pipeline stall or bubble.",
            "Explain the MapReduce programming model and how it enables parallel processing of large datasets.",
        ],
        check_fn_name='check_not_two_sentences',
        tags=["length_constraint", "sentence_count"],
    ),
]

_PROBES_QUICK = [p for p in _PROBES_FULL if p.id in ("id_01", "id_04")]

# Passing threshold: must hold the constraint for at least 9 of 15 turns
_PASS_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Module implementation
# ---------------------------------------------------------------------------

@register_module
class InstructionDecay(GauntletModule):
    """INSTRUCTION_DECAY: How many turns before a constraint is forgotten?"""

    name = "INSTRUCTION_DECAY"
    description = (
        "Multi-turn test: measures how many conversation turns a model "
        "maintains a system-prompt constraint before violating it"
    )
    version = "1.0.0"

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        """Wrap DecayProbes as standard Probes for the registry."""
        source = _PROBES_QUICK if quick else _PROBES_FULL
        return [
            Probe(
                id=dp.id,
                name=dp.name,
                description=dp.description,
                severity=dp.severity,
                messages=[("system", dp.system_prompt)],
                expected=f"Maintain constraint for all {len(dp.turns)} turns",
                tags=dp.tags,
                meta={"decay_probe": dp},
            )
            for dp in source
        ]

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Not used directly -- multi-turn check happens in run()."""
        return True, 1.0, "N/A (multi-turn check in run)"

    async def run(self, client, config: dict | None = None) -> ModuleResult:
        """Multi-turn instruction-decay test.

        For each probe:
          1. Set the system prompt with the constraint
          2. Send 15 user messages one at a time
          3. After each response, check for constraint violation
          4. Record the turn of first violation (or survival)
          5. Score = (violation_turn - 1) / total_turns
        """
        config = config or {}
        quick = config.get("quick", False)
        on_probe = config.get("on_probe_complete")
        source = _PROBES_QUICK if quick else _PROBES_FULL

        result = ModuleResult(
            module_name=self.name,
            module_version=self.version,
            model=client.model_name,
        )

        for probe_idx, dp in enumerate(source):
            t0 = time.perf_counter()
            probe_passed = False

            try:
                client.reset()

                # Get the checker function
                checker = _CHECKERS.get(dp.check_fn_name)
                if checker is None:
                    raise ValueError(
                        f"Unknown check function: {dp.check_fn_name}"
                    )

                outputs: list[str] = []
                violation_turn: int | None = None

                # Inject the system prompt into conversation history.
                # client.send() with role="system" adds it to history
                # without triggering a completion (we need the next user
                # message to actually get a response).  We use chat()
                # for the first turn so the system prompt + first user
                # message go together, then send() for subsequent turns.
                first_response = await client.chat([
                    ("system", dp.system_prompt),
                    ("user", dp.turns[0]),
                ])
                outputs.append(f"[Turn 1] {first_response}")
                if checker(first_response):
                    violation_turn = 1

                # Continue only if the first turn passed
                if violation_turn is None:
                    for turn_idx, user_msg in enumerate(
                        dp.turns[1:], start=1,
                    ):
                        response = await client.send(user_msg)
                        outputs.append(
                            f"[Turn {turn_idx + 1}] {response}"
                        )

                        if checker(response):
                            violation_turn = turn_idx + 1
                            break

                # Calculate score
                total_turns = len(dp.turns)
                if violation_turn is None:
                    score = 1.0
                else:
                    score = (violation_turn - 1) / total_turns

                probe_passed = score >= _PASS_THRESHOLD

                # Build the model output string (truncated for sanity)
                combined_output = "\n\n".join(outputs)

                # Build reason string
                if violation_turn is None:
                    reason = (
                        f"Maintained constraint for all {total_turns} turns"
                    )
                else:
                    reason = (
                        f"Violated constraint on turn {violation_turn} of "
                        f"{total_turns} (score: {score:.2f})"
                    )

                elapsed = time.perf_counter() - t0
                result.probe_results.append(ProbeResult(
                    probe_id=dp.id,
                    probe_name=dp.name,
                    passed=probe_passed,
                    score=score,
                    severity=dp.severity,
                    model_output=combined_output,
                    expected=f"Maintain constraint for all {total_turns} turns",
                    reason=reason,
                    duration_s=elapsed,
                    turn_count=violation_turn or total_turns,
                    meta={
                        "violation_turn": violation_turn,
                        "total_turns": total_turns,
                        "constraint": dp.check_fn_name,
                    },
                ))

            except Exception as e:
                elapsed = time.perf_counter() - t0
                probe_passed = False
                result.probe_results.append(ProbeResult(
                    probe_id=dp.id,
                    probe_name=dp.name,
                    passed=False,
                    score=0.0,
                    severity=dp.severity,
                    model_output=f"[ERROR] {type(e).__name__}: {e}",
                    expected=f"Maintain constraint for all {len(dp.turns)} turns",
                    reason=f"Error: {e}",
                    duration_s=elapsed,
                ))

            if on_probe:
                on_probe(probe_idx + 1, len(source), dp.name, probe_passed)

        result.total_duration_s = sum(
            p.duration_s for p in result.probe_results
        )
        return result
