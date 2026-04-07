# Contributing to Gauntlet

Thanks for your interest in making Gauntlet better.

## Quick Start

```bash
git clone https://github.com/Basaltlabs-app/Gauntlet.git
cd Gauntlet
pip install -e .
gauntlet --help
```

For the dashboard:
```bash
cd gauntlet/dashboard/frontend
npm install
npm run dev     # dev server with hot reload
```

## What We Need

### New Probes

The most impactful contribution. Add probes to existing modules in `gauntlet/core/modules/`:

1. Create a `Probe(id=..., name=..., ...)` with a clear behavioral test
2. The prompt should test one specific behavior (honesty, resistance, adherence, etc.)
3. Scoring is **deterministic** -- regex, keyword matching, pattern detection. No LLM judges.
4. Add it to the module's `_PROBES_FULL` list and optionally `_PROBES_QUICK`

### New Modules

Propose and implement new behavioral dimensions. Each module extends `GauntletModule`:

1. Create a file in `gauntlet/core/modules/` (e.g. `my_module.py`)
2. Implement `build_probes()` and `check()` methods
3. Use the `@register_module` decorator
4. All scoring must be programmatic -- no LLM-as-judge

### New Providers

Add LLM providers in `gauntlet/core/providers/`:

1. Implement the `LLMProvider` base class (stream_generate, list_models, check_connection)
2. Add it to `factory.py`
3. Add the provider prefix to `config.py`

### Pattern Improvements

Better regex/keyword patterns for scoring. If a model response should pass but doesn't
(or vice versa), submit a PR improving the detection patterns.

## Guidelines

- **Tests must be deterministic.** No randomness in expected outputs.
- **No LLM-as-judge.** Every test must have a programmatic verification.
- **Timeouts everywhere.** Default per-probe: 600s. Thinking models need 300-900s.
- **Works on 8GB RAM.** Sequential mode must be supported.

## Commit Messages

Use conventional format: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`

## Questions?

Open an issue or start a discussion on GitHub.
