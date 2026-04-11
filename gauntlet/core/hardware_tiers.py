"""Hardware tier classification for Gauntlet benchmarks.

Maps hardware fingerprints to standardized tiers for community
intelligence: comparing scores across similar hardware configurations.

Tiers:
  CLOUD          - API providers (OpenAI, Anthropic, Google) or cloud VMs
  CONSUMER_HIGH  - High-end consumer (RTX 4090, M3 Ultra, 64GB+ RAM)
  CONSUMER_MID   - Mid-range consumer (RTX 3070, M2 Pro, 32GB RAM)
  CONSUMER_LOW   - Entry-level consumer (GTX 1660, M1, 16GB RAM)
  EDGE           - Constrained devices (CPU-only, <16GB RAM)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gauntlet.core.system_info import SystemFingerprint

logger = logging.getLogger("gauntlet.hardware_tiers")


class Tier(IntEnum):
    """Hardware tiers, ordered by compute capability."""
    EDGE = 0
    CONSUMER_LOW = 1
    CONSUMER_MID = 2
    CONSUMER_HIGH = 3
    CLOUD = 4


@dataclass(frozen=True)
class HardwareTier:
    """Classification result for a hardware configuration."""
    tier: Tier
    tier_name: str           # "CLOUD", "CONSUMER_HIGH", etc.
    tier_label: str          # "Cloud", "Consumer (High)", etc.
    tier_rank: int           # 0-4 for ordering
    compute_class: str       # "cpu_only", "integrated_gpu", "discrete_low", "discrete_mid", "discrete_high", "datacenter"
    memory_class: str        # "constrained", "moderate", "ample", "abundant"
    inference_profile: str   # "q2_q4_only", "q4_q8", "q8_fp16", "fp16_native", "any"


# Human-readable labels
_TIER_LABELS = {
    Tier.EDGE: "Edge Device",
    Tier.CONSUMER_LOW: "Consumer (Low)",
    Tier.CONSUMER_MID: "Consumer (Mid)",
    Tier.CONSUMER_HIGH: "Consumer (High)",
    Tier.CLOUD: "Cloud",
}

# Inference profiles per tier
_TIER_PROFILES = {
    Tier.EDGE: "q2_q4_only",
    Tier.CONSUMER_LOW: "q4_q8",
    Tier.CONSUMER_MID: "q8_fp16",
    Tier.CONSUMER_HIGH: "fp16_native",
    Tier.CLOUD: "any",
}


def _classify_memory(ram_gb: float) -> str:
    if ram_gb < 8:
        return "constrained"
    elif ram_gb < 24:
        return "moderate"
    elif ram_gb < 64:
        return "ample"
    return "abundant"


def _classify_compute(gpu_class: str, vram_gb: float, gpu_name: str) -> str:
    if gpu_class == "none" or (gpu_class == "intel_integrated"):
        return "cpu_only"
    if gpu_class == "apple_silicon":
        return "integrated_gpu"  # unified memory
    if gpu_class == "nvidia":
        if vram_gb >= 40:
            return "datacenter"
        if vram_gb >= 16:
            return "discrete_high"
        if vram_gb >= 8:
            return "discrete_mid"
        return "discrete_low"
    if gpu_class == "amd":
        if vram_gb >= 16:
            return "discrete_high"
        if vram_gb >= 8:
            return "discrete_mid"
        return "discrete_low"
    return "cpu_only"


def classify(fingerprint: SystemFingerprint) -> HardwareTier:
    """Classify a hardware fingerprint into a tier.

    Deterministic: same fingerprint always produces same tier.
    """
    hw = fingerprint  # alias for readability

    # Rule 1: Cloud providers are always CLOUD tier
    if hw.provider in ("openai", "anthropic", "google"):
        tier = Tier.CLOUD
    elif hw.device_class == "cloud":
        tier = Tier.CLOUD
    # Rule 2: High-end consumer
    elif (hw.gpu_class == "nvidia" and hw.vram_gb >= 24) or \
         (hw.gpu_class == "apple_silicon" and hw.ram_total_gb >= 64) or \
         (hw.gpu_class == "amd" and hw.vram_gb >= 24):
        tier = Tier.CONSUMER_HIGH
    # Rule 3: Mid-range consumer
    elif (hw.gpu_class == "nvidia" and hw.vram_gb >= 12) or \
         (hw.gpu_class == "apple_silicon" and hw.ram_total_gb >= 32) or \
         (hw.gpu_class == "amd" and hw.vram_gb >= 12):
        tier = Tier.CONSUMER_MID
    # Rule 4: Entry-level consumer (has some GPU or decent RAM)
    elif (hw.gpu_class in ("nvidia", "amd") and hw.vram_gb >= 6) or \
         (hw.gpu_class == "apple_silicon" and hw.ram_total_gb >= 16):
        tier = Tier.CONSUMER_LOW
    # Rule 5: Everything else is edge
    else:
        tier = Tier.EDGE

    compute = _classify_compute(hw.gpu_class, hw.vram_gb, hw.gpu_name)
    memory = _classify_memory(hw.ram_total_gb)

    return HardwareTier(
        tier=tier,
        tier_name=tier.name,
        tier_label=_TIER_LABELS[tier],
        tier_rank=tier.value,
        compute_class=compute,
        memory_class=memory,
        inference_profile=_TIER_PROFILES[tier],
    )


def classify_from_dicts(
    hardware: dict,
    runtime: Optional[dict] = None,
    model_config: Optional[dict] = None,
) -> HardwareTier:
    """Classify from stored JSONB dicts (for existing submissions)."""
    gpu_class = hardware.get("gpu_class", "none")
    vram_gb = float(hardware.get("vram_gb", 0))
    ram_gb = float(hardware.get("ram_total_gb", 0))
    device_class = hardware.get("device_class", "unknown")
    gpu_name = hardware.get("gpu_name", "")
    provider = runtime.get("provider", "ollama") if runtime else "ollama"

    # Build a minimal proxy for the classification rules
    # (avoids importing SystemFingerprint which may have complex init)

    class _Proxy:
        pass

    proxy = _Proxy()
    proxy.provider = provider
    proxy.device_class = device_class
    proxy.gpu_class = gpu_class
    proxy.vram_gb = vram_gb
    proxy.ram_total_gb = ram_gb
    proxy.gpu_name = gpu_name

    return classify(proxy)  # type: ignore


# Reference profiles: recommended hardware tiers per model size
REFERENCE_PROFILES: dict[str, dict[str, str]] = {
    "3b_q4": {"min_tier": "EDGE", "recommended_tier": "CONSUMER_LOW"},
    "7b_q4": {"min_tier": "CONSUMER_LOW", "recommended_tier": "CONSUMER_MID"},
    "7b_q8": {"min_tier": "CONSUMER_MID", "recommended_tier": "CONSUMER_MID"},
    "7b_fp16": {"min_tier": "CONSUMER_MID", "recommended_tier": "CONSUMER_HIGH"},
    "14b_q4": {"min_tier": "CONSUMER_MID", "recommended_tier": "CONSUMER_HIGH"},
    "14b_q8": {"min_tier": "CONSUMER_HIGH", "recommended_tier": "CONSUMER_HIGH"},
    "14b_fp16": {"min_tier": "CONSUMER_HIGH", "recommended_tier": "CLOUD"},
    "35b_q4": {"min_tier": "CONSUMER_HIGH", "recommended_tier": "CLOUD"},
    "70b_q4": {"min_tier": "CONSUMER_HIGH", "recommended_tier": "CLOUD"},
    "70b_fp16": {"min_tier": "CLOUD", "recommended_tier": "CLOUD"},
    "cloud_api": {"min_tier": "EDGE", "recommended_tier": "EDGE"},
}
