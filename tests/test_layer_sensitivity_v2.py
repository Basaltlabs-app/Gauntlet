"""Tests for the V2 layer sensitivity probes (ls_syn_04+ through ls_pra_05)."""
from __future__ import annotations

import pytest
from gauntlet.core.modules.layer_sensitivity import LayerSensitivity


class TestNewSyntaxProbes:

    def setup_method(self):
        self.mod = LayerSensitivity()
        self.probes = self.mod.build_probes(seed=42)

    def _get(self, pid):
        return next(p for p in self.probes if p.id == pid)

    def test_pronoun_resolution_correct(self):
        p = self._get("ls_syn_04")
        passed, score, _ = self.mod.check(p, "trophy")
        assert passed and score == 1.0

    def test_pronoun_resolution_wrong(self):
        p = self._get("ls_syn_04")
        passed, _, _ = self.mod.check(p, "suitcase")
        assert not passed

    def test_word_order_correct(self):
        p = self._get("ls_syn_05")
        passed, score, _ = self.mod.check(p, "cat")
        assert passed and score == 1.0

    def test_word_order_wrong(self):
        p = self._get("ls_syn_05")
        passed, _, _ = self.mod.check(p, "mouse")
        assert not passed


class TestNewFactualProbes:

    def setup_method(self):
        self.mod = LayerSensitivity()
        self.probes = self.mod.build_probes(seed=42)

    def test_extra_factual_correct(self):
        p = next(x for x in self.probes if x.id == "ls_fac_04")
        patterns = p.meta["patterns"]
        passed, score, _ = self.mod.check(p, patterns[0])
        assert passed and score == 1.0

    def test_extra_factual_wrong(self):
        p = next(x for x in self.probes if x.id == "ls_fac_04")
        passed, _, _ = self.mod.check(p, "completely_wrong_xyz")
        assert not passed


class TestNewLogicProbes:

    def setup_method(self):
        self.mod = LayerSensitivity()
        self.probes = self.mod.build_probes(seed=42)

    def test_base_rate_correct(self):
        p = next(x for x in self.probes if x.id == "ls_log_05")
        passed, score, _ = self.mod.check(p, "GREEN")
        assert passed and score == 1.0

    def test_base_rate_wrong(self):
        p = next(x for x in self.probes if x.id == "ls_log_05")
        passed, _, _ = self.mod.check(p, "BLUE")
        assert not passed

    def test_double_negation_correct(self):
        p = next(x for x in self.probes if x.id == "ls_log_06")
        passed, score, _ = self.mod.check(p, "YES")
        assert passed and score == 1.0

    def test_double_negation_wrong(self):
        p = next(x for x in self.probes if x.id == "ls_log_06")
        passed, _, _ = self.mod.check(p, "NO")
        assert not passed


class TestNewSpatialProbes:

    def setup_method(self):
        self.mod = LayerSensitivity()
        self.probes = self.mod.build_probes(seed=42)

    def test_mental_rotation_correct(self):
        p = next(x for x in self.probes if x.id == "ls_spa_04")
        passed, score, _ = self.mod.check(p, "Z")
        assert passed and score == 1.0

    def test_mental_rotation_wrong(self):
        p = next(x for x in self.probes if x.id == "ls_spa_04")
        passed, _, _ = self.mod.check(p, "M")
        assert not passed

    def test_direction_after_turning_correct(self):
        p = next(x for x in self.probes if x.id == "ls_spa_05")
        passed, score, _ = self.mod.check(p, "south")
        assert passed and score == 1.0

    def test_direction_after_turning_wrong(self):
        p = next(x for x in self.probes if x.id == "ls_spa_05")
        passed, _, _ = self.mod.check(p, "north")
        assert not passed


class TestNewPragmaticProbes:

    def setup_method(self):
        self.mod = LayerSensitivity()
        self.probes = self.mod.build_probes(seed=42)

    def test_understatement_correct(self):
        p = next(x for x in self.probes if x.id == "ls_pra_04")
        passed, score, _ = self.mod.check(p, "NO")
        assert passed and score == 1.0

    def test_understatement_wrong(self):
        p = next(x for x in self.probes if x.id == "ls_pra_04")
        passed, _, _ = self.mod.check(p, "YES")
        assert not passed

    def test_indirect_refusal_correct(self):
        p = next(x for x in self.probes if x.id == "ls_pra_05")
        passed, score, _ = self.mod.check(p, "REFUSAL")
        assert passed and score == 1.0

    def test_indirect_refusal_wrong(self):
        p = next(x for x in self.probes if x.id == "ls_pra_05")
        passed, _, _ = self.mod.check(p, "GENUINE")
        assert not passed


class TestNewProbeCount:

    def test_full_count_at_least_25(self):
        probes = LayerSensitivity().build_probes(seed=42)
        assert len(probes) >= 25

    def test_quick_still_5(self):
        probes = LayerSensitivity().build_probes(quick=True, seed=42)
        assert len(probes) == 5

    def test_all_new_ids_exist(self):
        probes = LayerSensitivity().build_probes(seed=42)
        ids = {p.id for p in probes}
        new_ids = {"ls_syn_04", "ls_syn_05", "ls_fac_04", "ls_log_05",
                   "ls_log_06", "ls_spa_04", "ls_spa_05", "ls_pra_04", "ls_pra_05"}
        missing = new_ids - ids
        assert not missing, f"Missing probe IDs: {missing}"
