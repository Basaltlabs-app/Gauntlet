"""System fingerprint collector for community benchmarking.

Captures anonymous hardware, runtime, and model metadata so community
results can be filtered by setup: "Which model is best on Apple Silicon
with Q4 quantization and 16GB RAM?"

Privacy: No IP, username, MAC address, or hostname is collected.
Only hardware class, core counts, RAM, and model configuration.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import psutil


@dataclass
class SystemFingerprint:
    """Anonymous system and model metadata for community aggregation."""

    # Hardware
    cpu_arch: str = "unknown"          # arm64, x86_64
    cpu_cores: int = 0                 # physical cores
    ram_total_gb: float = 0.0          # total system RAM
    gpu_class: str = "unknown"         # apple_silicon, nvidia, amd, none

    # Runtime
    python_version: str = ""           # 3.14.2
    os_platform: str = ""              # darwin, linux, windows
    os_version: str = ""               # 15.4, 6.19

    # Model-specific
    model_family: str = "unknown"      # llama, qwen, gemma
    model_parameter_size: str = ""     # 7b, 35b
    quantization: str = "unknown"      # q4_0, q8_0, fp16
    model_format: str = "unknown"      # gguf, safetensors
    model_size_gb: float = 0.0         # file size on disk

    # Provider
    provider: str = "unknown"          # ollama, openai, anthropic
    provider_version: str = ""         # Ollama version if local

    def to_storage_dicts(self) -> tuple[dict, dict, dict]:
        """Split into (hardware, runtime, model_config) dicts for Supabase JSONB columns."""
        hardware = {
            "cpu_arch": self.cpu_arch,
            "cpu_cores": self.cpu_cores,
            "ram_total_gb": round(self.ram_total_gb, 1),
            "gpu_class": self.gpu_class,
            "os_platform": self.os_platform,
        }
        runtime = {
            "provider": self.provider,
            "provider_version": self.provider_version,
            "python_version": self.python_version,
            "os_version": self.os_version,
        }
        model_config = {
            "family": self.model_family,
            "parameter_size": self.model_parameter_size,
            "quantization": self.quantization,
            "format": self.model_format,
            "size_gb": round(self.model_size_gb, 1),
        }
        return hardware, runtime, model_config

    def to_dict(self) -> dict:
        return asdict(self)


def _detect_gpu_class() -> str:
    """Detect the GPU class without installing GPU-specific libraries."""
    system = platform.system().lower()

    # Apple Silicon (macOS with arm64)
    if system == "darwin" and platform.machine() == "arm64":
        return "apple_silicon"

    # NVIDIA (check for driver presence)
    if Path("/proc/driver/nvidia/version").exists():
        return "nvidia"
    if os.environ.get("CUDA_VISIBLE_DEVICES") is not None:
        return "nvidia"
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            return "nvidia"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # AMD ROCm
    if Path("/opt/rocm").exists():
        return "amd"
    if os.environ.get("ROCM_PATH"):
        return "amd"

    # Intel (macOS with x86_64 often has integrated Intel GPU)
    if system == "darwin" and platform.machine() == "x86_64":
        return "intel_integrated"

    return "none"


def _get_ollama_version() -> str:
    """Get Ollama server version if running."""
    try:
        import httpx
        resp = httpx.get("http://127.0.0.1:11434/api/version", timeout=2)
        if resp.status_code == 200:
            return resp.json().get("version", "")
    except Exception:
        pass
    return ""


def _get_model_metadata(model_name: str, provider: str) -> dict:
    """Get model metadata from the provider (quantization, family, size)."""
    if provider != "ollama":
        return {}

    try:
        import httpx
        resp = httpx.post(
            "http://127.0.0.1:11434/api/show",
            json={"name": model_name},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            details = data.get("details", {})
            model_info = data.get("model_info", {})

            # Extract size from modelfile or model_info
            size_bytes = 0
            for key, val in model_info.items():
                if "size" in key.lower() and isinstance(val, (int, float)):
                    size_bytes = max(size_bytes, int(val))

            return {
                "family": details.get("family", "unknown"),
                "parameter_size": details.get("parameter_size", ""),
                "quantization": details.get("quantization_level", "unknown"),
                "format": details.get("format", "unknown"),
                "families": details.get("families", []),
            }
    except Exception:
        pass
    return {}


def collect_fingerprint(
    model_name: str,
    provider: str,
    model_size_bytes: int = 0,
) -> SystemFingerprint:
    """Collect an anonymous system fingerprint for community benchmarking.

    Args:
        model_name: Name of the model being tested
        provider: Provider type (ollama, openai, etc.)
        model_size_bytes: Model file size in bytes (from discover, if available)

    Returns:
        SystemFingerprint with hardware, runtime, and model metadata
    """
    mem = psutil.virtual_memory()

    fp = SystemFingerprint(
        # Hardware
        cpu_arch=platform.machine(),
        cpu_cores=os.cpu_count() or 0,
        ram_total_gb=round(mem.total / (1024 ** 3), 1),
        gpu_class=_detect_gpu_class(),

        # Runtime
        python_version=platform.python_version(),
        os_platform=platform.system().lower(),
        os_version=platform.release(),

        # Provider
        provider=provider,
    )

    # Ollama-specific metadata
    if provider == "ollama":
        fp.provider_version = _get_ollama_version()
        meta = _get_model_metadata(model_name, provider)
        if meta:
            fp.model_family = meta.get("family", "unknown")
            fp.model_parameter_size = meta.get("parameter_size", "")
            fp.quantization = meta.get("quantization", "unknown")
            fp.model_format = meta.get("format", "unknown")

    # Cloud providers
    elif provider in ("openai", "anthropic", "google"):
        fp.model_family = model_name.split("-")[0] if "-" in model_name else model_name
        fp.quantization = "cloud"
        fp.model_format = "api"

    # Model size
    if model_size_bytes > 0:
        fp.model_size_gb = round(model_size_bytes / (1024 ** 3), 1)

    return fp
