"""Tests for ProbeGenerator -- seeded randomization for probes."""
from gauntlet.core.probe_gen import ProbeGenerator


class TestProbeGeneratorDeterminism:
    def test_same_seed_same_int(self):
        g1 = ProbeGenerator(seed=42)
        g2 = ProbeGenerator(seed=42)
        assert g1.random_int(1, 100) == g2.random_int(1, 100)

    def test_same_seed_same_sequence(self):
        g1 = ProbeGenerator(seed=99)
        g2 = ProbeGenerator(seed=99)
        seq1 = [g1.random_int(1, 10) for _ in range(5)]
        seq2 = [g2.random_int(1, 10) for _ in range(5)]
        assert seq1 == seq2

    def test_different_seed_different_values(self):
        g1 = ProbeGenerator(seed=1)
        g2 = ProbeGenerator(seed=2)
        vals1 = [g1.random_int(1, 1000) for _ in range(10)]
        vals2 = [g2.random_int(1, 1000) for _ in range(10)]
        assert vals1 != vals2


class TestProbeGeneratorMethods:
    def test_random_int_in_range(self):
        g = ProbeGenerator(seed=1)
        for _ in range(50):
            v = g.random_int(3, 8)
            assert 3 <= v <= 8

    def test_random_word_returns_string(self):
        g = ProbeGenerator(seed=1)
        word = g.random_word("adjectives")
        assert isinstance(word, str) and len(word) > 0

    def test_random_word_unknown_bank_raises(self):
        g = ProbeGenerator(seed=1)
        try:
            g.random_word("nonexistent_bank")
            assert False, "Should have raised KeyError"
        except KeyError:
            pass

    def test_random_name_returns_full_name(self):
        g = ProbeGenerator(seed=1)
        name = g.random_name()
        assert " " in name
        assert len(name.split()) == 2

    def test_random_phrase_returns_string(self):
        g = ProbeGenerator(seed=1)
        phrase = g.random_phrase()
        assert isinstance(phrase, str) and len(phrase) > 5

    def test_canary_string_is_unique(self):
        g = ProbeGenerator(seed=1)
        c1 = g.canary_string()
        c2 = g.canary_string()
        assert c1 != c2
        assert len(c1) > 8

    def test_random_letter_returns_single_char(self):
        g = ProbeGenerator(seed=1)
        letter = g.random_letter()
        assert len(letter) == 1 and letter.isalpha()


class TestProbeGeneratorSeedRecording:
    def test_explicit_seed_recorded(self):
        g = ProbeGenerator(seed=42)
        assert g.seed == 42

    def test_auto_seed_recorded(self):
        g = ProbeGenerator()
        assert isinstance(g.seed, int)
