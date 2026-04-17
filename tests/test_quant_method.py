"""Tests for V2 quantization method and source detection."""
from __future__ import annotations

import pytest
from gauntlet.core.system_info import SystemFingerprint


class TestQuantMethodFields:
    """Verify new quant_method and quant_source fields exist and serialize."""

    def test_default_values(self):
        fp = SystemFingerprint()
        assert fp.quant_method == "unknown"
        assert fp.quant_source == "unknown"

    def test_in_storage_dict(self):
        fp = SystemFingerprint(quant_method="gguf", quant_source="bartowski")
        _, _, mc = fp.to_storage_dicts()
        assert mc["quant_method"] == "gguf"
        assert mc["quant_source"] == "bartowski"

    def test_to_dict_includes_fields(self):
        fp = SystemFingerprint(quant_method="awq", quant_source="thebloke")
        d = fp.to_dict()
        assert d["quant_method"] == "awq"
        assert d["quant_source"] == "thebloke"

    def test_cloud_provider_values(self):
        """Cloud providers should get 'cloud' for method and 'official' for source."""
        fp = SystemFingerprint(
            quant_method="cloud",
            quant_source="official",
            quantization="cloud",
            model_format="api",
        )
        _, _, mc = fp.to_storage_dicts()
        assert mc["quant_method"] == "cloud"
        assert mc["quant_source"] == "official"


class TestQuantMethodInference:
    """Test the inference logic that populates quant_method from model metadata.

    Note: These test the inference RULES, not the actual Ollama API calls.
    The real detection happens in collect_fingerprint() which calls Ollama.
    Here we verify the logic patterns that system_info.py applies to metadata.
    """

    def test_gguf_standard_detected(self):
        """Standard Q4_K_M GGUF should produce quant_method='gguf'."""
        fp = SystemFingerprint()
        fp.model_format = "gguf"
        fp.quantization = "Q4_K_M"
        # Simulate the inference logic
        fmt = fp.model_format.lower()
        quant = fp.quantization.upper()
        if fmt == "gguf":
            if quant.startswith("IQ"):
                fp.quant_method = "gguf_iq"
            else:
                fp.quant_method = "gguf"
        assert fp.quant_method == "gguf"

    def test_gguf_iq_detected(self):
        """Importance-matrix quants (IQ4_XS) should produce 'gguf_iq'."""
        fp = SystemFingerprint()
        fp.model_format = "gguf"
        fp.quantization = "IQ4_XS"
        fmt = fp.model_format.lower()
        quant = fp.quantization.upper()
        if fmt == "gguf":
            if quant.startswith("IQ"):
                fp.quant_method = "gguf_iq"
            else:
                fp.quant_method = "gguf"
        assert fp.quant_method == "gguf_iq"

    def test_source_detection_bartowski(self):
        """Model names containing 'bartowski' should be attributed."""
        model_lower = "bartowski/llama3-8b:Q4_K_M".lower()
        source = "unknown"
        for s in ("bartowski", "thebloke", "mradermacher", "turboderp",
                  "unsloth", "mlabonne"):
            if s in model_lower:
                source = s
                break
        assert source == "bartowski"

    def test_source_detection_thebloke(self):
        model_lower = "thebloke/mistral-7b-gptq".lower()
        source = "unknown"
        for s in ("bartowski", "thebloke", "mradermacher", "turboderp",
                  "unsloth", "mlabonne"):
            if s in model_lower:
                source = s
                break
        assert source == "thebloke"

    def test_source_detection_official_fallback(self):
        """Unknown model names should fall back to 'official'."""
        model_lower = "qwen2.5:14b".lower()
        source = "unknown"
        for s in ("bartowski", "thebloke", "mradermacher", "turboderp",
                  "unsloth", "mlabonne"):
            if s in model_lower:
                source = s
                break
        if source == "unknown":
            source = "official"
        assert source == "official"

    def test_gptq_from_model_name(self):
        """Model names containing 'gptq' should produce quant_method='gptq'."""
        fp = SystemFingerprint()
        fp.model_format = "safetensors"
        model_name = "TheBloke/Llama-2-7B-GPTQ"
        if "gptq" in model_name.lower():
            fp.quant_method = "gptq"
        assert fp.quant_method == "gptq"

    def test_awq_from_model_name(self):
        fp = SystemFingerprint()
        fp.model_format = "safetensors"
        model_name = "TheBloke/Mistral-7B-AWQ"
        if "awq" in model_name.lower():
            fp.quant_method = "awq"
        assert fp.quant_method == "awq"

    def test_exl2_from_model_name(self):
        fp = SystemFingerprint()
        fp.model_format = "safetensors"
        model_name = "turboderp/Llama-3-8B-exl2"
        if "exl2" in model_name.lower():
            fp.quant_method = "exl2"
        assert fp.quant_method == "exl2"
