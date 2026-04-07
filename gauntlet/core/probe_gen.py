"""ProbeGenerator -- seeded random value generation for parameterized probes."""

from __future__ import annotations

import random
import string


_WORD_BANKS: dict[str, list[str]] = {
    "adjectives": [
        "quantum", "recursive", "stochastic", "fractal", "emergent",
        "entropic", "harmonic", "kinetic", "spectral", "volatile",
        "ambient", "radiant", "cryptic", "orbital", "prismatic",
    ],
    "nouns": [
        "lattice", "vortex", "nexus", "prism", "helix",
        "cipher", "beacon", "fulcrum", "crucible", "conduit",
        "paradigm", "catalyst", "threshold", "gradient", "synthesis",
    ],
    "topics": [
        "Macro-Biological Systems", "Nano-Scale Resonance",
        "Temporal Drift Patterns", "Cognitive Load Dynamics",
        "Neural Pathway Optimization", "Subatomic Field Theory",
        "Distributed Memory Networks", "Chromatic Wave Analysis",
        "Synthetic Ecosystem Modeling", "Phase Transition Mechanics",
    ],
    "journals": [
        "Journal of Applied Neurocognitive Research",
        "International Review of Synthetic Biology",
        "Quarterly Journal of Computational Metaphysics",
        "Annals of Theoretical Data Science",
        "Proceedings of the Global Institute for Abstract Mathematics",
    ],
    "first_names": [
        "Helena", "Marcus", "Yuki", "Priya", "Dmitri",
        "Amara", "Liam", "Fatima", "Chen", "Rashid",
        "Elena", "Jorge", "Anika", "Tomoko", "Kavi",
    ],
    "last_names": [
        "Marchetti", "Okonkwo", "Tanaka", "Volkov", "Ramirez",
        "Ashworth", "Petrov", "Nakamura", "Oduya", "Lindqvist",
        "Chowdhury", "Moreau", "Ivanovic", "Kowalski", "Bergstrom",
    ],
    "forbidden_letters": list("etaoinsrhld"),
}


class ProbeGenerator:
    """Seeded random value generator for parameterized probes."""

    def __init__(self, seed: int | None = None):
        if seed is None:
            seed = random.randint(0, 2**31 - 1)
        self.seed = seed
        self._rng = random.Random(seed)

    def random_int(self, lo: int, hi: int) -> int:
        return self._rng.randint(lo, hi)

    def random_word(self, bank_name: str) -> str:
        bank = _WORD_BANKS[bank_name]
        return self._rng.choice(bank)

    def random_letter(self) -> str:
        return self._rng.choice(string.ascii_lowercase)

    def random_name(self) -> str:
        first = self.random_word("first_names")
        last = self.random_word("last_names")
        return f"{first} {last}"

    def random_phrase(self) -> str:
        adj = self.random_word("adjectives")
        topic = self.random_word("topics")
        return f"{adj.title()} {topic}"

    def canary_string(self) -> str:
        letters = "".join(self._rng.choices(string.ascii_uppercase, k=5))
        digits = "".join(self._rng.choices(string.digits, k=5))
        return f"CANARY-{letters}-{digits}"
