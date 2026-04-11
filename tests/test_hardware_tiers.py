"""Tests for hardware tier classification."""
import pytest
from gauntlet.core.hardware_tiers import (
    Tier, HardwareTier, classify_from_dicts, REFERENCE_PROFILES,
    _classify_memory, _classify_compute,
)


class TestTierClassification:
    """Test deterministic tier assignment."""

    def test_cloud_provider_openai(self):
        tier = classify_from_dicts(
            {"gpu_class": "none", "vram_gb": 0, "ram_total_gb": 8, "device_class": "unknown", "gpu_name": ""},
            {"provider": "openai"},
        )
        assert tier.tier == Tier.CLOUD

    def test_cloud_provider_anthropic(self):
        tier = classify_from_dicts(
            {"gpu_class": "none", "vram_gb": 0, "ram_total_gb": 8, "device_class": "unknown", "gpu_name": ""},
            {"provider": "anthropic"},
        )
        assert tier.tier == Tier.CLOUD

    def test_cloud_device_class(self):
        tier = classify_from_dicts(
            {"gpu_class": "nvidia", "vram_gb": 80, "ram_total_gb": 256, "device_class": "cloud", "gpu_name": "A100"},
            {"provider": "ollama"},
        )
        assert tier.tier == Tier.CLOUD

    def test_consumer_high_nvidia(self):
        tier = classify_from_dicts(
            {"gpu_class": "nvidia", "vram_gb": 24, "ram_total_gb": 32, "device_class": "desktop", "gpu_name": "RTX 4090"},
            {"provider": "ollama"},
        )
        assert tier.tier == Tier.CONSUMER_HIGH

    def test_consumer_high_apple_silicon(self):
        tier = classify_from_dicts(
            {"gpu_class": "apple_silicon", "vram_gb": 0, "ram_total_gb": 64, "device_class": "desktop", "gpu_name": "Apple M3 Ultra"},
            {"provider": "ollama"},
        )
        assert tier.tier == Tier.CONSUMER_HIGH

    def test_consumer_mid_nvidia(self):
        tier = classify_from_dicts(
            {"gpu_class": "nvidia", "vram_gb": 12, "ram_total_gb": 32, "device_class": "desktop", "gpu_name": "RTX 3060"},
            {"provider": "ollama"},
        )
        assert tier.tier == Tier.CONSUMER_MID

    def test_consumer_mid_apple_silicon(self):
        tier = classify_from_dicts(
            {"gpu_class": "apple_silicon", "vram_gb": 0, "ram_total_gb": 32, "device_class": "laptop", "gpu_name": "Apple M2 Pro"},
            {"provider": "ollama"},
        )
        assert tier.tier == Tier.CONSUMER_MID

    def test_consumer_low_nvidia(self):
        tier = classify_from_dicts(
            {"gpu_class": "nvidia", "vram_gb": 6, "ram_total_gb": 16, "device_class": "desktop", "gpu_name": "GTX 1660"},
            {"provider": "ollama"},
        )
        assert tier.tier == Tier.CONSUMER_LOW

    def test_consumer_low_apple_silicon(self):
        tier = classify_from_dicts(
            {"gpu_class": "apple_silicon", "vram_gb": 0, "ram_total_gb": 16, "device_class": "laptop", "gpu_name": "Apple M1"},
            {"provider": "ollama"},
        )
        assert tier.tier == Tier.CONSUMER_LOW

    def test_edge_cpu_only(self):
        tier = classify_from_dicts(
            {"gpu_class": "none", "vram_gb": 0, "ram_total_gb": 8, "device_class": "laptop", "gpu_name": ""},
            {"provider": "ollama"},
        )
        assert tier.tier == Tier.EDGE

    def test_edge_low_ram_apple(self):
        tier = classify_from_dicts(
            {"gpu_class": "apple_silicon", "vram_gb": 0, "ram_total_gb": 8, "device_class": "laptop", "gpu_name": "Apple M1"},
            {"provider": "ollama"},
        )
        assert tier.tier == Tier.EDGE

    def test_tier_is_deterministic(self):
        """Same input always produces same tier."""
        hw = {"gpu_class": "nvidia", "vram_gb": 12, "ram_total_gb": 32, "device_class": "desktop", "gpu_name": "RTX 3060"}
        rt = {"provider": "ollama"}
        results = [classify_from_dicts(hw, rt) for _ in range(100)]
        assert all(r.tier == results[0].tier for r in results)

    def test_tier_ordering(self):
        """Tiers are ordered: EDGE < CONSUMER_LOW < CONSUMER_MID < CONSUMER_HIGH < CLOUD"""
        assert Tier.EDGE < Tier.CONSUMER_LOW < Tier.CONSUMER_MID < Tier.CONSUMER_HIGH < Tier.CLOUD


class TestMemoryClassification:
    def test_constrained(self):
        assert _classify_memory(4) == "constrained"

    def test_moderate(self):
        assert _classify_memory(16) == "moderate"

    def test_ample(self):
        assert _classify_memory(32) == "ample"

    def test_abundant(self):
        assert _classify_memory(128) == "abundant"


class TestComputeClassification:
    def test_cpu_only(self):
        assert _classify_compute("none", 0, "") == "cpu_only"

    def test_apple_silicon(self):
        assert _classify_compute("apple_silicon", 0, "M2") == "integrated_gpu"

    def test_nvidia_datacenter(self):
        assert _classify_compute("nvidia", 80, "A100") == "datacenter"

    def test_nvidia_discrete_high(self):
        assert _classify_compute("nvidia", 24, "RTX 4090") == "discrete_high"

    def test_nvidia_discrete_mid(self):
        assert _classify_compute("nvidia", 12, "RTX 3060") == "discrete_mid"

    def test_nvidia_discrete_low(self):
        assert _classify_compute("nvidia", 4, "GTX 1050") == "discrete_low"


class TestHardwareTierDataclass:
    def test_frozen(self):
        """HardwareTier is immutable."""
        tier = classify_from_dicts(
            {"gpu_class": "nvidia", "vram_gb": 24, "ram_total_gb": 32, "device_class": "desktop", "gpu_name": "RTX 4090"},
            {"provider": "ollama"},
        )
        with pytest.raises(AttributeError):
            tier.tier = Tier.EDGE  # type: ignore


class TestReferenceProfiles:
    def test_profiles_exist(self):
        assert len(REFERENCE_PROFILES) > 0

    def test_cloud_api_min_tier_is_edge(self):
        assert REFERENCE_PROFILES["cloud_api"]["min_tier"] == "EDGE"

    def test_70b_fp16_needs_cloud(self):
        assert REFERENCE_PROFILES["70b_fp16"]["min_tier"] == "CLOUD"

    def test_all_profiles_have_required_keys(self):
        for key, profile in REFERENCE_PROFILES.items():
            assert "min_tier" in profile, f"{key} missing min_tier"
            assert "recommended_tier" in profile, f"{key} missing recommended_tier"
