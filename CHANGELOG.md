# Changelog

## [2.1.2] - 2026-05-03

### Fixes — community submission pipeline

The dashboard has been silently dropping data. Three independent silent-failure paths converged into "I ran benchmarks and nothing showed up." All three are fixed in this release.

- **CLI submissions were missing `hardware_tier` and `attestation`.** `gauntlet benchmark` built the payload manually instead of going through `build_attestation()`, so every CLI row landed in Supabase with `hardware_tier=""`. Tier-filtered dashboard views (Consumer-Mid, Consumer-High, Cloud) were systematically empty for CLI runs. Both fields now flow through; outcomes are surfaced inline (`✓ submitted`, `⚠ network error`, `✗ rejected (400): <reason>`) instead of being swallowed by the daemon thread's bare `except: pass`.
- **MCP submissions used a hardcoded "serverless" placeholder fingerprint** even when the MCP server was running as a desktop subprocess (Gemini CLI, Claude Desktop, Cursor). Real RAM/CPU/GPU was being thrown away and replaced with `unknown`/`0`. `_save_mcp_results` now detects whether it's running on Vercel (`$VERCEL`) and only uses the placeholder there; desktop runs get the full `collect_fingerprint()`.
- **`submit_result` rejection logs were at DEBUG level** (invisible without `--verbose`). Bumped to WARNING and the response body is included so the user can actually see why the API rejected their submission.

### Features

- **`gauntlet --version` / `gauntlet -V`**: prints version and exits. Long overdue.
- **`gauntlet doctor`**: one-command diagnostic that prints env-var detection, `.env` file discovery, Supabase reachability, public-API reachability, current hardware fingerprint preview, last 5 local runs, and pending retry-queue status. Drains the queue while it's at it. Designed to answer "why didn't my last run show up?" in five seconds.
- **MCP server startup banner**: prints one line on launch — `Community push: ENABLED` or `DISABLED — SUPABASE_URL / SUPABASE_SERVICE_KEY not visible to this process` — so users discover misconfiguration upfront, not after a 20-minute benchmark. Goes to stderr so it never pollutes stdio MCP frames.
- **Persistent retry queue** (`~/.gauntlet/pending/`): when a community submit fails (network blip, Supabase outage, transient 5xx), the payload is queued to disk and replayed on the next CLI invocation. Permanent 4xx rejections are dropped after one log line — they'd never be accepted anyway. Capped at 200 files. Self-healing without user intervention.
- **MCP write path now goes through the same validator as `/api/submit`.** A new `gauntlet/mcp/submit_validator.py` enforces score-range, model-name length, category sanity, score-consistency, probe-count, attestation shape, probe-details size caps, and dedup. Closes the gap where anyone hitting the public `/mcp` could write arbitrary scores into the leaderboard.
- **dotenv-style env loader runs at package import** (`gauntlet/__init__.py:_bootstrap_env`). Searches `$GAUNTLET_ENV_FILE`, `.env.vercel.local`/`.env.local`/`.env` walking up to a repo root, then `~/.gauntlet/.env`. Allowlist of 10 keys; never overwrites parent-process env. Fixes "I exported `SUPABASE_URL` but Gemini CLI's gauntlet subprocess still can't see it" — MCP clients spawn children with stripped env on macOS, and gauntlet's loader compensates without requiring per-client config.

### Code health

- **HMAC submit key deduplicated** to `gauntlet.core.config.get_submit_key()`. Previously hardcoded as `"gauntlet-community-2026"` in both `api/index.py` and `gauntlet/core/submit.py` — easy to miss on rotation.
- **`str(e)` leakage plugged** in three API handlers (`submit_handler`, `predict_handler`, `recommend_handler`). Errors now log server-side and return generic messages — could previously leak the internal Supabase URL.
- **`_format_save_status` extracted** to `gauntlet/mcp/save_status.py` so it imports cleanly without FastMCP. Tests target the helper directly instead of dancing around `sys.modules`.

### Tests

- 42 new tests across `test_bootstrap_env.py` (env loader: priority order, allowlist, never-overwrite, walk-up, idempotence, `export`/quote stripping), `test_save_status.py` (status formatter shapes), and `test_submit_validator.py` (every validation rule).
- Total: 552 passed, 0 failures.

### Docs

- New README section: **Running gauntlet as a local MCP server**. Covers the `~/.gauntlet/.env` global file, per-client `env` blocks for Gemini CLI / Claude Desktop / Cursor, the macOS Dock-launch gotcha (`.zshrc` not sourced), and the `GAUNTLET_ENV_FILE` override for CI.
- Clarified MCP data-quality language: desktop MCP runs now produce real fingerprints, the "serverless" caveat only applies to the hosted endpoint.

### QOL release additions (round 2)

- **Auto-update notification** on `gauntlet benchmark`. `update_check.py` was already implemented but only wired into TUI/dashboard — now `benchmark` runs surface "Update available: vX.Y.Z → vX.Y.Z+1. Run: pipx upgrade gauntlet-cli" at the bottom of the run if a newer version exists on PyPI. Cached 24h, never blocks.
- **`MIN_CLI_VERSION` bumped 1.3.5 → 2.0.0.** Anything below 2.0.0 pre-dates fingerprint + attestation fields and was being silently accepted with `hardware_tier=""`. The API now rejects ancient submissions outright.
- **Hardware fingerprint reused across multi-model runs.** Was being rebuilt for every model in a benchmark suite — pointless `psutil` / `sysctl` / `nvidia-smi` calls. Now collected once per run with model-config varying per result.
- **CTRL-C-safe submission ordering.** Previously, killing the CLI mid-submit lost the result entirely. Now the payload is enqueued to `~/.gauntlet/pending/` *before* the network call; only successful 200 deletes it. Mid-flight CTRL-C means the file stays for the next drain.
- **`--no-submit` flag + `GAUNTLET_PRIVATE=1` env**: opt out of community submission for iteration runs. Same effect either way.
- **`gauntlet history`**: list past local benchmark runs as a Rich table, with `--limit N` and `--model <substr>` filtering. Reads from `~/.gauntlet/benchmarks/` only — no network, no leakage.
- **Client-side validation**: the CLI now runs `validate_submission()` against its payload before posting, so users see specific rejection reasons instantly instead of waiting for a generic 400 back from the API.
- **`/api/version` endpoint**: returns `{server, min_supported, recommended, latest, upgrade_command, upgrade_url, release_notes}`. Lets `gauntlet doctor` and update-check warn users authoritatively.
- **`GAUNTLET_API_URL` env override** for self-hosting / staging environments. Centralized via `gauntlet.core.config.get_community_api_base()`. Removes hardcoded `gauntlet.basaltlabs.app` from 5 files.
- **Read endpoint cache TTLs**: `Cache-Control: max-age=30, s-maxage=60` → `max-age=300, s-maxage=900, stale-while-revalidate=86400`. Leaderboard data churns hourly, not every 30 seconds. Saves Vercel function invocations and gives users instant page loads.
- **`/api/predict` + `/api/recommend` matrix cache**: shared 60s in-memory cache with stale-fallback. Both endpoints fetched 2000 history rows from Supabase on every request — typical dashboard / CLI usage hit Supabase 10× per minute. Now once per minute. Stale serve on Supabase outage instead of 503.
- **Dashboard polling pauses when tab is hidden.** `useFetch` was running `setInterval(fetchData, 60_000)` regardless of tab visibility. `visibilitychange` listener stops the timer when hidden, kicks an immediate refetch on focus. Cuts Supabase chatter to ~zero for background tabs.
- **Tests**: `validate_submission` parity for CLI, history-command smoke, `/api/version` shape, cache stale-fallback. 540 passing.

### Deferred to a focused future PR

- `gauntlet/dashboard/server.py` (>1200 lines) split into per-feature modules. Marked with a `TODO(refactor)` block at the top of the file naming the natural split points. Pure mechanical move — should land alone, not bundled with feature work.

---

## [2.1.1] - 2026-04-21

### Features
- **Hardware detection — `lspci` fallback for NVIDIA GPU names**: when `nvidia-smi` isn't on PATH (server builds, stripped-down containers, some distros), `_detect_gpu_info()` now parses `lspci` output to extract the GPU model name (e.g. "GeForce RTX 3090"). Previously these runs submitted with `gpu_name="unknown"`, polluting the community leaderboard. Includes 5 parse tests covering bracketed / non-bracketed output, multi-GPU selection, AMD-only lines, and empty input.

### API / Embeds
- **`/api/badge` rebrand**: dropped the A–F / shields.io colour ramp. Badges now use Gauntlet's actual certification system (Gold / Silver / Bronze / Tested / no data) with the ember palette. A 71-score model that previously rendered as hostile red "F (71.1)" now renders as warm copper "71 · Bronze" — something a model author actually wants in their HuggingFace / GitHub README.
- Added `viewBox` to the badge SVG so resizing via `<img width="...">` preserves aspect ratio and text crispness.
- Added `role="img"` + `<title>` for screen-reader accessibility.

---

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
