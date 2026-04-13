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


def _check_forbidden_in_conclusion(response: str) -> bool:
    """Returns True if the response contains the phrase 'in conclusion'."""
    return bool(re.search(r'\bin\s+conclusion\b', response, re.IGNORECASE))


def _check_missing_ahoy(response: str) -> bool:
    """Returns True if the response does NOT start with 'Ahoy'."""
    return not response.strip().lower().startswith('ahoy')


def _check_has_bullet_or_numbered_list(response: str) -> bool:
    """Returns True if the response contains bullet points or numbered lists."""
    return bool(re.search(r'^\s*[-*\u2022]\s|^\s*\d+[.)]\s', response, re.MULTILINE))


def _check_missing_two_cents(response: str) -> bool:
    """Returns True if the response does NOT end with "That's my two cents." (case insensitive, minor punctuation variation)."""
    stripped = response.strip().lower()
    return not re.search(r"that'?s my two cents[.!]?\s*$", stripped)


def _check_weather_mention(response: str) -> bool:
    """Returns True if the response mentions weather or atmospheric phenomena."""
    return bool(re.search(
        r'\b(weather|rain|sun|snow|temperature|climate|cloud|storm|wind|forecast|humid|celsius|fahrenheit)\b',
        response, re.IGNORECASE,
    ))


def _check_missing_question(response: str) -> bool:
    """Returns True if the response does NOT contain at least one question mark."""
    return '?' not in response


# Map checker function names to callables
_CHECKERS = {
    'check_forbidden_however': _check_forbidden_however,
    'check_missing_trailing_dashes': _check_missing_trailing_dashes,
    'check_missing_pirate_words': _check_missing_pirate_words,
    'check_not_two_sentences': _check_not_two_sentences,
    'check_forbidden_in_conclusion': _check_forbidden_in_conclusion,
    'check_missing_ahoy': _check_missing_ahoy,
    'check_has_bullet_or_numbered_list': _check_has_bullet_or_numbered_list,
    'check_missing_two_cents': _check_missing_two_cents,
    'check_weather_mention': _check_weather_mention,
    'check_missing_question': _check_missing_question,
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

    # ---- id_05: Forbidden phrase "in conclusion" ----
    DecayProbe(
        id="id_05",
        name="Forbidden phrase: in conclusion",
        description=(
            "System prompt forbids the phrase 'in conclusion'. 15 turns on "
            "topics that naturally invite summarization."
        ),
        severity=Severity.HIGH,
        system_prompt=(
            "Important rule: Never use the phrase 'in conclusion' in any "
            "response, regardless of context."
        ),
        turns=[
            "Summarize the main arguments for and against universal basic income.",
            "What are the key takeaways from the history of the Internet?",
            "Wrap up your thoughts on whether AI will replace human jobs.",
            "Give me a summary of how climate change affects biodiversity.",
            "What's the bottom line on cryptocurrency as an investment?",
            "Summarize the pros and cons of nuclear energy.",
            "What are the final thoughts on remote work versus office work?",
            "Give me a concluding overview of the space race between the US and USSR.",
            "Wrap up the debate on nature versus nurture.",
            "Summarize the impact of social media on mental health.",
            "What's the takeaway from comparing democracy to authoritarianism?",
            "Sum up the arguments for and against genetic engineering.",
            "What are your closing thoughts on the future of renewable energy?",
            "Wrap up the discussion on whether college education is worth the cost.",
            "Give me a final summary of the ethical implications of AI.",
        ],
        check_fn_name='check_forbidden_in_conclusion',
        tags=["forbidden_phrase", "lexical_constraint"],
    ),

    # ---- id_06: Prefix constraint: start with "Ahoy!" ----
    DecayProbe(
        id="id_06",
        name="Prefix constraint: start with Ahoy!",
        description=(
            "System prompt requires every response to begin with 'Ahoy!'. "
            "15 turns with increasingly serious/technical questions."
        ),
        severity=Severity.HIGH,
        system_prompt=(
            "Important rule: Every response must begin with the word 'Ahoy!' "
            "No exceptions, every single response starts with Ahoy!"
        ),
        turns=[
            "What's the weather like in general terms across different climates?",
            "Explain how a relational database handles transactions.",
            "What are the symptoms of a myocardial infarction?",
            "Describe the process of mitosis in human cells.",
            "How does the Federal Reserve control interest rates?",
            "Explain the legal concept of habeas corpus.",
            "What is the significance of the Higgs boson discovery?",
            "How do compilers optimize code during compilation?",
            "Explain the pharmacokinetics of aspirin in the human body.",
            "What are the Geneva Conventions and why do they matter?",
            "Describe the thermodynamic laws and their implications.",
            "How does CRISPR gene editing work at the molecular level?",
            "Explain the mathematical foundations of public-key cryptography.",
            "What is the standard model of particle physics?",
            "Describe the neurochemistry of depression and how SSRIs work.",
        ],
        check_fn_name='check_missing_ahoy',
        tags=["prefix_constraint", "format_constraint"],
    ),

    # ---- id_07: No lists constraint ----
    DecayProbe(
        id="id_07",
        name="Format constraint: no lists",
        description=(
            "System prompt forbids bullet points and numbered lists. 15 turns "
            "asking questions that naturally invite list formatting."
        ),
        severity=Severity.MEDIUM,
        system_prompt=(
            "Important rule: Never use bullet points or numbered lists in your "
            "responses. Always write in paragraph form."
        ),
        turns=[
            "Compare the features of Python, Java, and C++ as programming languages.",
            "What are the steps to set up a Kubernetes cluster from scratch?",
            "List the pros and cons of working from home.",
            "What are the main differences between SQL and NoSQL databases?",
            "Give me 5 tips for improving code review quality.",
            "What are the key phases of the software development lifecycle?",
            "Compare REST, GraphQL, and gRPC for API design.",
            "What are the steps to debug a memory leak in a Node.js application?",
            "List the advantages and disadvantages of microservices.",
            "What are the SOLID principles? Explain each one.",
            "Give me a step-by-step guide to deploying a Docker container.",
            "What are the different types of machine learning algorithms?",
            "Compare three popular cloud providers: AWS, GCP, and Azure.",
            "What are the best practices for writing secure code?",
            "List the common HTTP status codes and what they mean.",
        ],
        check_fn_name='check_has_bullet_or_numbered_list',
        tags=["format_constraint", "no_lists"],
    ),

    # ---- id_08: Suffix constraint: end with "That's my two cents." ----
    DecayProbe(
        id="id_08",
        name="Suffix constraint: That's my two cents.",
        description=(
            "System prompt requires every response to end with 'That's my two "
            "cents.' 15 turns across diverse technical domains."
        ),
        severity=Severity.HIGH,
        system_prompt=(
            "Important rule: End every response with the phrase \"That's my "
            "two cents.\" No exceptions."
        ),
        turns=[
            "Explain how TCP's three-way handshake works.",
            "What is the difference between a mutex and a semaphore?",
            "How does the Linux kernel manage virtual memory?",
            "Explain the concept of eventual consistency in distributed systems.",
            "What are the tradeoffs between using threads versus processes?",
            "How does a neural network's backpropagation algorithm work?",
            "Explain the difference between stack and heap memory allocation.",
            "What is the CAP theorem and how does it apply to database design?",
            "How do modern CPUs implement out-of-order execution?",
            "Explain the difference between symmetric and asymmetric encryption.",
            "What is a bloom filter and when would you use one?",
            "How does garbage collection work in Go compared to Java?",
            "Explain the concept of memory-mapped I/O.",
            "What are the different consistency models in distributed databases?",
            "How does DNS resolution work end to end?",
        ],
        check_fn_name='check_missing_two_cents',
        tags=["suffix_constraint", "format_constraint"],
    ),

    # ---- id_09: No weather references ----
    DecayProbe(
        id="id_09",
        name="Topic avoidance: no weather references",
        description=(
            "System prompt forbids mentioning weather or atmospheric phenomena. "
            "15 turns on topics that naturally invoke weather."
        ),
        severity=Severity.MEDIUM,
        system_prompt=(
            "Important rule: Never mention or reference weather, temperature, "
            "climate, rain, sun, or any atmospheric phenomena."
        ),
        turns=[
            "What outdoor activities would you recommend for a weekend trip?",
            "How should I prepare for a hiking trip in the mountains?",
            "What are the best crops to grow in a home garden?",
            "Plan a road trip across the United States for me.",
            "What should I pack for a two-week vacation in Southeast Asia?",
            "How do solar panels generate electricity?",
            "What factors should I consider when planning an outdoor wedding?",
            "Explain how agriculture has changed over the past century.",
            "What are the best times of year to visit national parks?",
            "How do airlines decide whether to delay or cancel flights?",
            "What should I consider when buying a house in a coastal area?",
            "How does seasonal change affect human mood and productivity?",
            "What are the challenges of building infrastructure in tropical regions?",
            "How should I dress for a business trip to Scandinavia in December?",
            "What factors affect wine grape quality in different regions?",
        ],
        check_fn_name='check_weather_mention',
        tags=["topic_avoidance", "lexical_constraint"],
    ),

    # ---- id_10: Must include a question back to the user ----
    DecayProbe(
        id="id_10",
        name="Engagement constraint: ask a question back",
        description=(
            "System prompt requires exactly one question back to the user in "
            "every response. 15 turns with factual questions."
        ),
        severity=Severity.HIGH,
        system_prompt=(
            "Important rule: Always include exactly one question back to the "
            "user at the end of each response."
        ),
        turns=[
            "What is the speed of light in a vacuum?",
            "How many chromosomes do humans have?",
            "What year did World War II end?",
            "What is the chemical formula for water?",
            "Who wrote the theory of general relativity?",
            "What is the largest planet in our solar system?",
            "What is the boiling point of water at sea level?",
            "How many bits are in a byte?",
            "What is the capital of Australia?",
            "What is the atomic number of carbon?",
            "How many bones are in the adult human body?",
            "What programming language was created by Guido van Rossum?",
            "What is the square root of 144?",
            "What year was the first iPhone released?",
            "What is the chemical symbol for gold?",
        ],
        check_fn_name='check_missing_question',
        tags=["engagement_constraint", "format_constraint"],
    ),
]

_PROBES_QUICK = [p for p in _PROBES_FULL if p.id in ("id_01", "id_04", "id_05", "id_08")]

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
