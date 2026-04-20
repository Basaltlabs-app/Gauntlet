"""Tests for gauntlet.core.system_info helpers."""
from __future__ import annotations

from gauntlet.core.system_info import _nvidia_name_from_lspci


class TestNvidiaNameFromLspci:
    """Parse tests for the lspci NVIDIA GPU name fallback.

    These tests feed canned lspci output into the helper via its
    `raw_output` parameter so they work on any platform (no real lspci
    binary required).
    """

    def test_bracketed_model_is_preferred(self):
        raw = (
            "00:00.0 Host bridge: Intel Corporation Some Host\n"
            "01:00.0 VGA compatible controller: NVIDIA Corporation GA102 "
            "[GeForce RTX 3090] (rev a1)\n"
        )
        assert _nvidia_name_from_lspci(raw) == "GeForce RTX 3090"

    def test_no_brackets_falls_back_to_codename(self):
        raw = (
            "01:00.0 VGA compatible controller: NVIDIA Corporation GA102 (rev a1)\n"
        )
        assert _nvidia_name_from_lspci(raw) == "GA102"

    def test_empty_string_returns_none(self):
        assert _nvidia_name_from_lspci("") is None

    def test_no_nvidia_lines_returns_none(self):
        raw = (
            "00:00.0 Host bridge: Intel Corporation Something\n"
            "01:00.0 VGA compatible controller: Advanced Micro Devices, Inc. "
            "[AMD/ATI] Navi 31 [Radeon RX 7900 XTX] (rev c8)\n"
            "02:00.0 Audio device: Intel Corporation Sunrise Point-LP HD Audio\n"
        )
        assert _nvidia_name_from_lspci(raw) is None

    def test_first_nvidia_match_wins_with_multiple_gpus(self):
        raw = (
            "01:00.0 VGA compatible controller: NVIDIA Corporation GA102 "
            "[GeForce RTX 3090] (rev a1)\n"
            "02:00.0 VGA compatible controller: NVIDIA Corporation AD102 "
            "[GeForce RTX 4090] (rev a1)\n"
        )
        assert _nvidia_name_from_lspci(raw) == "GeForce RTX 3090"
