# Changelog

## [2.1.0] - 2026-04-20

### Features
- **LM Studio provider** (closes #2): first-class support for [LM Studio](https://lmstudio.ai)'s OpenAI-compatible local server. Run benchmarks with `gauntlet run --model lmstudio/<name>`; `gauntlet discover` lists currently-loaded models. Host configurable via `LMSTUDIO_HOST` env var, `gauntlet config --lmstudio-host`, or the default `http://localhost:1234`. Metadata (family, parameter size, quantization) inferred from the model ID.
- **Cloud ChatClient wiring**: `gauntlet run --model openai/<id>`, `anthropic/<id>`, and `google/<id>` now work directly (previously `NotImplementedError`). Enables leaderboard baselines for GPT-4o, Claude, and Gemini — typical full-sweep cost is under $5, and Gemini has a free tier.
- **MCP server improvements**:
  - Self-driving tool instructions so MCP clients (Claude Code, Gemini CLI, Cursor) can run the full suite without custom user prompts — includes explicit "do NOT shell out" directives.
  - Auto-detects the client app via `Context.session.client_params.clientInfo`, with a clear separation between client app and model identifier.
  - New `gauntlet_status(session_id)` tool replays the current probe on demand for resumability.

### Fixes
- **Temporal Reasoning probe**: prompt previously said "Reply with ONLY the name" despite the correct answer being neither Alice nor Bob. Some models (notably Gemini 2.5 Pro) looped for minutes trying to resolve the bind before their own CLI aborted. Prompt now lists `'Alice' | 'Bob' | 'Neither'` explicitly. Verify function unchanged (still accepts equal/both/tie/neither).
- **Leaderboard provider mis-attribution**: `collect_fingerprint(r.model, "ollama")` hardcoded the provider when submitting results, so non-Ollama runs appeared on the leaderboard as Ollama. Now derived via `detect_provider()`. Affected `gauntlet quick` and the TUI path.

### Safety
- **Agent-invocation guard on `gauntlet run`**: when stdin/stdout aren't TTYs (the tell for MCP-client subprocess spawns), refuse to benchmark local models (Ollama / LM Studio / llama.cpp) unless `GAUNTLET_ALLOW_LOCAL=1` is set. Prevents MCP agents from accidentally loading large local models and overloading the user's machine. Cloud providers and interactive humans are unaffected.

### Polish
- Error messages, `_auto_select_models()`, and the interactive setup now include LM Studio alongside Ollama — no more "Is Ollama running?" when LM Studio is loaded.
- Host resolution honors the config file for Ollama and LM Studio (env > file > default); persistent `gauntlet config --ollama-host` and `--lmstudio-host` flags now actually take effect.
- README: new LM Studio and Cloud Baselines sections, updated provider filter tables.

### Tests
- 12 new LM Studio tests: host resolution precedence (env > config > default), spec parsing, factory wiring, metadata inference across 5 model-id patterns.

---

## [2.0.3] - 2026-04-17

### Fixes
- **Confidence calibration crash**: `ModuleScore.__init__()` was missing `high_failures` and `summary` arguments, blocking all full benchmark runs from completing. Fixed.
- **Server error scoring**: Ollama 500 errors (OOM, context overflow) were scored as behavioral failures (0.0). Now marked as "Skipped (server error)" and excluded from module scores entirely. If 5/8 probes crash and 3/8 run, the score reflects only the 3 that ran.

### Improvements
- **Layer sensitivity expanded**: 16 to 25 probes. Added pronoun resolution, word order sensitivity, base-rate fallacy, double negation, mental rotation, direction tracking, understatement, and indirect refusal.
- **Dashboard empty tab UX**: Speed, Quality, and Graph tabs now show helpful messages explaining they need the Compare feature (`gauntlet compare model1 model2`).
- **Sycophancy Gradient display**: Category card now explains that the percentage reflects average pressure levels survived, not binary pass rate.
- **Category explanations**: Perplexity Baseline and Layer Sensitivity cards show contextual subtitles explaining what they measure.
- **Degradation API**: `/api/degradation` response now includes `perplexity_mean` and `perplexity_n` per quantization level when V2 data is available. Dashboard chart can overlay perplexity on degradation curves.

### Tests
- 22 new tests for V2 layer sensitivity probes (correct/wrong answer for each new probe)
- Total: 529 tests, 0 failures

---

## [2.0.2] - 2026-04-17

### Fixes
- Server error probes (HTTP 500/502/503) excluded from scoring

## [2.0.1] - 2026-04-17

### Fixes
- Confidence calibration crash blocking all full benchmark runs

## [2.0.0] - 2026-04-15

### What's different in V2

V2 adds the empirical tools to answer the question "does perplexity predict behavioral degradation under quantization?" Every V2 run now includes a perplexity baseline alongside the behavioral probes, so the community can build the correlation dataset that settles this debate with data instead of speculation.

V2 also adds layer-sensitivity probes that map specific cognitive functions (syntax, factual recall, logic, spatial reasoning, pragmatic inference) to different transformer layer groups. This enables the community to answer: "does Q4_K_M preserve logic but degrade spatial reasoning?" and "does GPTQ produce different error profiles than GGUF at the same bit width?"

### New modules

- **PERPLEXITY_BASELINE**: Measures raw token prediction quality on a fixed evaluation corpus using logprobs from Ollama/llama.cpp. NOT factored into TrustScore or GauntletScore. Reported as a standalone metric in community submissions for correlation analysis. Gracefully skips for cloud providers without logprob access.
- **LAYER_SENSITIVITY** (16 probes, 5 categories): Probes cognitive functions localized in different transformer layer groups:
  - Shallow syntax (3 probes): subject-verb agreement, format preservation, grammatical error detection
  - Factual recall (3 probes): chemical symbols, physical constants, biology facts
  - Multi-step logic (4 probes): chained arithmetic, transitivity, modus tollens, syllogism with distractor
  - Spatial reasoning (3 probes): relative position ordering, mirror reflection, clock position
  - Pragmatic inference (3 probes): sarcasm detection, Gricean implicature, social norm inference
  - Per-category score breakdown identifies which cognitive function degrades first under quantization

### Enhanced metadata

- **`quant_method`** field: Captures quantization algorithm (gguf, gguf_iq, gptq, awq, exl2, safetensors, cloud). Enables filtering by quant method on the community leaderboard.
- **`quant_source`** field: Captures who made the quantization (bartowski, thebloke, mradermacher, turboderp, unsloth, official, community). Not all Q4 quants are the same.
- Both fields auto-populated from model name patterns and format metadata.

### Scoring

- PERPLEXITY_BASELINE excluded from GauntletScore and TrustScore aggregation
- LAYER_SENSITIVITY added to all three profiles (assistant: 0.6, coder: 0.8, researcher: 0.9)
- Community submission payload includes `"perplexity": <float or null>` as a top-level metric

### Documentation

- New README section: "Doesn't perplexity already measure this?" directly addressing the most common criticism with specific behavioral examples
- Updated probe count badge: 231 probes across 19 modules
- Layer sensitivity and perplexity baseline added to behavioral taxonomy

### Tests

- New test suite: `test_perplexity_baseline.py` (perplexity math, module structure, scoring exclusion)
- New test suite: `test_layer_sensitivity.py` (probe generation, check logic for all 5 categories, scoring breakdown)
- New test suite: `test_quant_method.py` (field existence, inference logic for GGUF/IQ/GPTQ/AWQ/EXL2, source detection)
- All 449 existing tests continue to pass

---

## [1.5.1] - 2026-04-13

Previous release. See git history for details.
