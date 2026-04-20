"""System fingerprint collector for community benchmarking.

Captures anonymous hardware, runtime, and model metadata so community
results can be filtered by setup: "Which model is best on Apple Silicon M2
with 16GB RAM, Q4 quantization?"

Privacy: No IP, username, MAC address, or hostname is collected.
Only hardware class identifiers (GPU model, CPU model, RAM tier) and
model configuration. "RTX 4090" identifies a GPU tier, not a person.
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import psutil


# ---------------------------------------------------------------------------
# RAM bucket tiers (auto-adapts as new hardware appears)
# ---------------------------------------------------------------------------

_RAM_BUCKETS = [
    (6, "4gb"),
    (12, "8gb"),
    (20, "16gb"),
    (28, "24gb"),
    (48, "32gb"),
    (80, "64gb"),
    (112, "96gb"),
    (160, "128gb"),
    (float("inf"), "128gb+"),
]

_VRAM_BUCKETS = [
    (6, "4gb"),
    (10, "8gb"),
    (14, "12gb"),
    (20, "16gb"),
    (28, "24gb"),
    (40, "32gb"),
    (52, "48gb"),
    (float("inf"), "48gb+"),
]


def _bucket(value_gb: float, buckets: list[tuple[float, str]]) -> str:
    """Find the bucket label for a given GB value."""
    for threshold, label in buckets:
        if value_gb < threshold:
            return label
    return buckets[-1][1]


@dataclass
class SystemFingerprint:
    """Anonymous system and model metadata for community aggregation."""

    # Hardware
    cpu_arch: str = "unknown"          # arm64, x86_64
    cpu_cores: int = 0                 # physical cores
    cpu_model: str = "unknown"         # "Apple M1", "AMD Ryzen 9 7950X"
    ram_total_gb: float = 0.0          # exact RAM
    ram_bucket: str = "unknown"        # "8gb", "16gb", "32gb", etc.
    gpu_class: str = "unknown"         # apple_silicon, nvidia, amd, none
    gpu_name: str = "unknown"          # "Apple M1", "RTX 4090", "RX 7900 XTX"
    vram_gb: float = 0.0              # dedicated VRAM (shared on Apple Silicon)
    vram_bucket: str = "unknown"       # "8gb", "16gb", "24gb", etc.
    device_class: str = "unknown"      # laptop, desktop, server, cloud

    # Runtime
    python_version: str = ""           # 3.14.2
    os_platform: str = ""              # darwin, linux, windows
    os_version: str = ""               # 15.4, 6.19

    # Model-specific
    model_family: str = "unknown"      # llama, qwen, gemma
    model_parameter_size: str = ""     # 7b, 35b
    quantization: str = "unknown"      # q4_0, q4_k_m, q8_0, fp16
    quant_method: str = "unknown"      # gguf, gptq, awq, exl2, bba (quantization algorithm)
    quant_source: str = "unknown"      # who made the quant: bartowski, thebloke, official, etc.
    model_format: str = "unknown"      # gguf, safetensors
    model_size_gb: float = 0.0         # file size on disk

    # Provider
    provider: str = "unknown"          # ollama, openai, anthropic
    provider_version: str = ""         # Ollama version if local

    # Tier classification (populated by hardware_tiers.classify)
    hardware_tier: str = ""            # CLOUD, CONSUMER_HIGH, CONSUMER_MID, CONSUMER_LOW, EDGE
    tier_label: str = ""               # Human-readable: "Cloud", "Consumer (High)", etc.

    def to_storage_dicts(self) -> tuple[dict, dict, dict]:
        """Split into (hardware, runtime, model_config) dicts for Supabase JSONB."""
        hardware = {
            "cpu_arch": self.cpu_arch,
            "cpu_cores": self.cpu_cores,
            "cpu_model": self.cpu_model,
            "ram_total_gb": round(self.ram_total_gb, 1),
            "ram_bucket": self.ram_bucket,
            "gpu_class": self.gpu_class,
            "gpu_name": self.gpu_name,
            "vram_gb": round(self.vram_gb, 1),
            "vram_bucket": self.vram_bucket,
            "device_class": self.device_class,
            "os_platform": self.os_platform,
            "hardware_tier": self.hardware_tier,
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
            "quant_method": self.quant_method,
            "quant_source": self.quant_source,
            "format": self.model_format,
            "size_gb": round(self.model_size_gb, 1),
        }
        return hardware, runtime, model_config

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Hardware detection
# ---------------------------------------------------------------------------

def _run_cmd(cmd: list[str], timeout: int = 3) -> str:
    """Run a command and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, PermissionError):
        pass
    return ""


def _detect_cpu_model() -> str:
    """Detect the CPU model name."""
    system = platform.system().lower()

    if system == "darwin":
        # macOS: sysctl gives the chip name
        brand = _run_cmd(["sysctl", "-n", "machdep.cpu.brand_string"])
        if brand:
            return brand
        # Apple Silicon doesn't always have brand_string, use chip name
        chip = _run_cmd(["sysctl", "-n", "hw.chip"])
        if chip:
            return chip

    elif system == "linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except (OSError, IOError):
            pass

    # Fallback
    proc = platform.processor()
    if proc and proc != "":
        return proc
    return platform.machine()


def _detect_gpu_info() -> tuple[str, str, float]:
    """Detect GPU class, name, and VRAM.

    Returns: (gpu_class, gpu_name, vram_gb)
    """
    system = platform.system().lower()

    # Apple Silicon: GPU is integrated, VRAM = shared system RAM
    if system == "darwin" and platform.machine() == "arm64":
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        # Get chip name for GPU name
        chip = _run_cmd(["sysctl", "-n", "machdep.cpu.brand_string"])
        if not chip:
            chip = _run_cmd(["sysctl", "-n", "hw.chip"])
        if not chip:
            chip = "Apple Silicon"
        return "apple_silicon", chip, round(ram_gb, 1)

    # NVIDIA: nvidia-smi for name and VRAM
    nvidia_name = _run_cmd(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader,nounits"]
    )
    if nvidia_name:
        vram_str = _run_cmd(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]
        )
        vram_gb = 0.0
        if vram_str:
            try:
                vram_gb = round(float(vram_str.split("\n")[0]) / 1024, 1)
            except (ValueError, IndexError):
                pass
        return "nvidia", nvidia_name.split("\n")[0], vram_gb

    # Check for NVIDIA driver without nvidia-smi
    if Path("/proc/driver/nvidia/version").exists():
        return "nvidia", "NVIDIA GPU (unknown model)", 0.0
    if os.environ.get("CUDA_VISIBLE_DEVICES") is not None:
        return "nvidia", "NVIDIA GPU (CUDA)", 0.0

    # AMD ROCm
    if Path("/opt/rocm").exists() or os.environ.get("ROCM_PATH"):
        amd_name = _run_cmd(["rocm-smi", "--showproductname"])
        vram_str = _run_cmd(["rocm-smi", "--showmeminfo", "vram"])
        vram_gb = 0.0
        if vram_str:
            # Parse VRAM from rocm-smi output
            for line in vram_str.split("\n"):
                if "total" in line.lower():
                    parts = line.split()
                    for p in parts:
                        try:
                            val = float(p)
                            if val > 1000:  # likely in MB
                                vram_gb = round(val / 1024, 1)
                            break
                        except ValueError:
                            continue
        gpu_name = "AMD GPU"
        if amd_name:
            for line in amd_name.split("\n"):
                if "GPU" in line or "Radeon" in line or "RX" in line:
                    gpu_name = line.strip()
                    break
        return "amd", gpu_name, vram_gb

    # Intel integrated (macOS x86_64)
    if system == "darwin" and platform.machine() == "x86_64":
        return "intel_integrated", "Intel Integrated", 0.0

    return "none", "No dedicated GPU", 0.0


def _detect_device_class() -> str:
    """Infer whether this is a laptop, desktop, server, or cloud instance."""
    # Check for battery (laptops have one)
    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            return "laptop"
    except (AttributeError, RuntimeError):
        pass

    # Cloud detection: common cloud markers
    system = platform.system().lower()
    if system == "linux":
        # Check for common cloud instance markers
        dmi_product = ""
        try:
            with open("/sys/class/dmi/id/product_name") as f:
                dmi_product = f.read().strip().lower()
        except (OSError, IOError):
            pass

        cloud_markers = ["virtual", "kvm", "xen", "hvm", "amazon", "google", "azure", "digitalocean"]
        if any(m in dmi_product for m in cloud_markers):
            return "cloud"

        # Check for container markers
        if Path("/.dockerenv").exists():
            return "cloud"

    # High core count + no battery = likely desktop or server
    cores = os.cpu_count() or 0
    ram_gb = psutil.virtual_memory().total / (1024 ** 3)

    if cores >= 32 or ram_gb >= 128:
        return "server"
    if cores >= 4:
        return "desktop"

    return "unknown"


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
    if provider == "ollama":
        return _get_ollama_metadata(model_name)
    elif provider == "llamacpp":
        return _get_llamacpp_metadata(model_name)
    elif provider == "lmstudio":
        return _get_lmstudio_metadata(model_name)
    return {}


def _get_lmstudio_metadata(model_name: str) -> dict:
    """Infer LM Studio model metadata from /v1/models and the model ID.

    LM Studio's OpenAI-compatible API doesn't expose quantization directly,
    but the model ID usually contains enough signal (e.g. "llama-3.2-8b-q4_k_m")
    to infer family, parameter size, and quantization.
    """
    import re

    meta: dict = {
        "family": "unknown",
        "parameter_size": "",
        "quantization": "unknown",
        "format": "gguf",
        "families": [],
    }

    try:
        import httpx
        from gauntlet.core.config import get_lmstudio_host

        host = get_lmstudio_host()

        # Prefer the current model_name; fall back to whichever is loaded.
        candidate_id = model_name
        try:
            resp = httpx.get(f"{host}/v1/models", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                ids = [m.get("id", "") for m in models if m.get("id")]
                if model_name not in ids and ids:
                    candidate_id = ids[0]
        except Exception:
            pass

        lower = candidate_id.lower()

        # Family inference
        for fam in ["llama", "qwen", "gemma", "phi", "mistral",
                    "deepseek", "yi", "falcon", "mamba", "starcoder",
                    "codellama", "mixtral"]:
            if fam in lower:
                meta["family"] = fam
                break

        # Quantization from ID suffix (e.g. "-q4_k_m", "-q8_0", "-f16")
        quant_match = re.search(
            r"[_.-](q\d[_a-z0-9]*|f16|f32|fp16|fp32|bf16)\b",
            lower,
        )
        if quant_match:
            meta["quantization"] = quant_match.group(1).upper()

        # Parameter size (e.g. "8b", "70b", "1.5b")
        param_match = re.search(r"(\d+(?:\.\d+)?)[_.-]?b\b", lower)
        if param_match:
            meta["parameter_size"] = f"{param_match.group(1)}B"

    except Exception:
        pass

    return meta


def _get_ollama_metadata(model_name: str) -> dict:
    """Get model metadata from Ollama /api/show."""
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


def _get_llamacpp_metadata(model_name: str) -> dict:
    """Get model metadata from llama.cpp server /props and /v1/models.

    llama-server exposes:
      GET /props -> { default_generation_settings: { n_ctx, model, ... }, ... }
      GET /v1/models -> { data: [{ id, ... }] }

    We extract what we can: context length, model file path (to infer
    quantization from the filename), and model ID.
    """
    import re

    try:
        import httpx
        from gauntlet.core.config import get_llamacpp_host

        host = get_llamacpp_host()
        meta: dict = {
            "family": "unknown",
            "parameter_size": "",
            "quantization": "unknown",
            "format": "gguf",
            "families": [],
        }

        # Query /props for generation settings and model path
        try:
            resp = httpx.get(f"{host}/props", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                gen = data.get("default_generation_settings", {})
                model_path = gen.get("model", "")

                # Extract info from GGUF filename
                # e.g. "qwen3-8b-q4_K_M.gguf" -> quant=Q4_K_M, params=8B
                if model_path:
                    filename = model_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

                    # Detect quantization from filename
                    quant_match = re.search(
                        r"[_.-](q\d[_a-zA-Z0-9]*|f16|f32|fp16|fp32|bf16)",
                        filename, re.IGNORECASE,
                    )
                    if quant_match:
                        meta["quantization"] = quant_match.group(1).upper()

                    # Detect parameter size from filename
                    param_match = re.search(
                        r"(\d+(?:\.\d+)?)[_.-]?[bB]",
                        filename,
                    )
                    if param_match:
                        meta["parameter_size"] = f"{param_match.group(1)}B"

                # Context length
                n_ctx = gen.get("n_ctx", 0)
                if n_ctx:
                    meta["context_length"] = n_ctx
        except Exception:
            pass

        # Query /v1/models for model ID
        try:
            resp = httpx.get(f"{host}/v1/models", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                if models:
                    model_id = models[0].get("id", "")
                    if model_id and meta["family"] == "unknown":
                        # Try to infer family from model ID
                        for fam in ["llama", "qwen", "gemma", "phi", "mistral",
                                    "deepseek", "yi", "falcon", "mamba", "starcoder"]:
                            if fam in model_id.lower():
                                meta["family"] = fam
                                break
        except Exception:
            pass

        return meta
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Main collector
# ---------------------------------------------------------------------------

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
    ram_gb = round(mem.total / (1024 ** 3), 1)
    gpu_class, gpu_name, vram_gb = _detect_gpu_info()

    fp = SystemFingerprint(
        # Hardware
        cpu_arch=platform.machine(),
        cpu_cores=os.cpu_count() or 0,
        cpu_model=_detect_cpu_model(),
        ram_total_gb=ram_gb,
        ram_bucket=_bucket(ram_gb, _RAM_BUCKETS),
        gpu_class=gpu_class,
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        vram_bucket=_bucket(vram_gb, _VRAM_BUCKETS) if vram_gb > 0 else "shared" if gpu_class == "apple_silicon" else "none",
        device_class=_detect_device_class(),

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

    # LM Studio / llama.cpp metadata (GGUF-based, inferred from model id)
    if provider in ("lmstudio", "llamacpp"):
        meta = _get_model_metadata(model_name, provider)
        if meta:
            fp.model_family = meta.get("family", "unknown")
            fp.model_parameter_size = meta.get("parameter_size", "")
            fp.quantization = meta.get("quantization", "unknown")
            fp.model_format = meta.get("format", "gguf")

            # Infer quant_method from format + quantization pattern.
            # GGUF quants have distinctive patterns (Q4_K_M, IQ4_XS, etc.)
            # GPTQ/AWQ/EXL2 typically use safetensors format.
            fmt = fp.model_format.lower()
            quant = fp.quantization.upper()
            if fmt == "gguf":
                # Distinguish IQ (importance-matrix quants) vs standard Q-types
                if quant.startswith("IQ"):
                    fp.quant_method = "gguf_iq"  # importance-matrix quantization
                else:
                    fp.quant_method = "gguf"
            elif fmt == "safetensors":
                # safetensors is used by GPTQ, AWQ, EXL2, and unquantized models
                if "gptq" in model_name.lower():
                    fp.quant_method = "gptq"
                elif "awq" in model_name.lower():
                    fp.quant_method = "awq"
                elif "exl2" in model_name.lower():
                    fp.quant_method = "exl2"
                else:
                    fp.quant_method = "safetensors"
            elif fmt == "api":
                fp.quant_method = "cloud"

            # Infer quant_source from the model name/tag (Ollama tags often
            # encode the source: "bartowski/llama3:Q4_K_M", "thebloke/...", etc.)
            model_lower = model_name.lower()
            for source in ("bartowski", "thebloke", "mradermacher", "turboderp",
                           "unsloth", "mlabonne", "cognitivecomputations", "nousresearch"):
                if source in model_lower:
                    fp.quant_source = source
                    break
            else:
                # Check Ollama families metadata for community quants
                families = meta.get("families", [])
                if families and len(families) > 1:
                    fp.quant_source = "community"
                else:
                    fp.quant_source = "official"

    # Cloud providers
    elif provider in ("openai", "anthropic", "google"):
        fp.model_family = model_name.split("-")[0] if "-" in model_name else model_name
        fp.quantization = "cloud"
        fp.quant_method = "cloud"
        fp.quant_source = "official"
        fp.model_format = "api"
        fp.device_class = "cloud"

    # Model size
    if model_size_bytes > 0:
        fp.model_size_gb = round(model_size_bytes / (1024 ** 3), 1)

    # Hardware tier classification
    try:
        from gauntlet.core.hardware_tiers import classify
        tier = classify(fp)
        fp.hardware_tier = tier.tier_name
        fp.tier_label = tier.tier_label
    except Exception:
        pass  # non-critical — leave defaults

    return fp
