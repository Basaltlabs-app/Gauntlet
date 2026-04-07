import React, { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { BookOpen, ChevronDown, ChevronRight, Terminal, Layers, Timer, Gauge, Target } from 'lucide-react'

const GETTING_STARTED = [
  {
    title: 'Install a model',
    icon: Layers,
    content: `Gauntlet tests LLMs that run on your machine via Ollama. If you haven't already:

1. Install Ollama: https://ollama.com/download
2. Pull a model: ollama pull qwen3.5:4b
3. Pull a second to compare: ollama pull gemma3

Models are downloaded once and run locally. Your prompts never leave your machine.`
  },
  {
    title: 'Run your first comparison',
    icon: Timer,
    content: `From the Compare tab, select 2 models, type a prompt, and hit "Run Comparison".

Gauntlet sends the same prompt to both models simultaneously (or one at a time in sequential mode), measures speed, and shows you the results side by side.

The winner is determined by a transparent composite score: Speed (30%) + Quality (50%) + Responsiveness (20%).`
  },
  {
    title: 'Run the benchmark suite',
    icon: Gauge,
    content: `The Benchmark tab runs 20 automated tests across 8 categories:

- Instruction Following: does it do exactly what you asked?
- Code Generation: can it fix bugs and build data structures?
- Factual Accuracy: does it hallucinate or give real facts?
- Reasoning: multi-step logic and math
- Consistency: same question asked 3 ways = same answer?
- Pressure Resistance: does it cave when you push back?
- Speed: tokens per second on your hardware
- Context Recall: find hidden info in longer text

Every test has a programmatic pass/fail check. No LLM judges another LLM.`
  },
  {
    title: 'Understanding scores',
    icon: Target,
    content: `Scores are out of 100. Here's what they mean:

90-100: Excellent. The model aced this category.
70-89:  Good. Minor issues but generally reliable.
50-69:  Mixed. Some tests passed, some failed.
Below 50: Weak. The model struggles here.

The Overall score is the average across all categories. Different models have different strengths. A model that scores 40% overall might still be the best at coding.`
  },
]

const FAQ = [
  {
    q: 'Why is my model so slow?',
    a: `Ollama loads the full model weights into RAM to run inference. A 4.9GB model needs roughly 4.9GB of free memory. If the model exceeds your available RAM, your OS starts swapping to disk, which tanks performance.

On an 8GB Mac, aim for models under 4GB (like qwen3.5:4b at 3.4GB). Also close heavy apps (browsers, media servers) before running benchmarks to free up memory.`
  },
  {
    q: 'What does "Sequential mode" do?',
    a: `Sequential mode runs one model at a time instead of in parallel. This uses less memory because only one model is loaded at once. Essential for machines with 8GB RAM. Slightly slower overall but each model gets your full resources.`
  },
  {
    q: 'Can I test cloud models (GPT-4, Claude, Gemini)?',
    a: `Yes! Set the API key as an environment variable, then use the provider prefix:

export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_API_KEY=AI...

Then in the terminal: gauntlet run openai:gpt-4o anthropic:claude-sonnet-4-20250514 "your prompt"

Cloud models aren't shown in the dashboard model picker yet but work via CLI.`
  },
  {
    q: 'What does the SWE test do?',
    a: `SWE (Software Engineering) tests give models real buggy code and ask them to fix it. The fix is then run through a pytest test suite to verify it actually works. This is similar to how SWE-bench evaluates models, but runs entirely on your machine.

Use: gauntlet swe (from terminal)`
  },
  {
    q: 'How is the winner decided?',
    a: `For "Run Comparison": a weighted formula -- Speed (30%) + Quality (50%) + Responsiveness (20%). Quality comes from an optional LLM judge. You see every component score.

For "Benchmark": the overall percentage of tests passed. Each test is pass/fail with programmatic verification (no LLM judging).

The leaderboard tracks trust rankings over many comparisons using a weighted rating system.`
  },
  {
    q: 'Is my data sent anywhere?',
    a: `No. Everything runs locally. Your prompts, model outputs, and benchmark results never leave your machine. Gauntlet connects only to your local Ollama instance (or cloud APIs if you explicitly set API keys).`
  },
  {
    q: 'How do I add more models?',
    a: `Pull them with Ollama:

ollama pull llama3.2
ollama pull phi4
ollama pull mistral

Then refresh the model list in the dashboard. Gauntlet works with any model Ollama supports.`
  },
]

function Accordion({ title, children, defaultOpen = false, icon: Icon }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-white/5 last:border-0">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 py-3 text-left hover:bg-white/[0.02] transition-colors"
      >
        {Icon && <Icon size={14} className="text-[var(--primary)] shrink-0" />}
        <span className="text-sm font-medium text-[var(--text)] flex-1">{title}</span>
        {open ? <ChevronDown size={14} className="text-[var(--text-muted)]" /> : <ChevronRight size={14} className="text-[var(--text-muted)]" />}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="pb-4 pl-7 text-xs text-[var(--text-dim)] leading-relaxed whitespace-pre-line">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default function HelpPanel() {
  return (
    <div className="space-y-6">
      {/* Getting Started */}
      <div className="glass rounded-xl p-6">
        <div className="flex items-center gap-2 mb-4">
          <BookOpen size={14} className="text-[var(--primary)]" />
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
            Getting Started
          </h2>
        </div>
        <div>
          {GETTING_STARTED.map((item, i) => (
            <Accordion key={i} title={item.title} icon={item.icon} defaultOpen={i === 0}>
              {item.content}
            </Accordion>
          ))}
        </div>
      </div>

      {/* FAQ */}
      <div className="glass rounded-xl p-6">
        <div className="flex items-center gap-2 mb-4">
          <BookOpen size={14} className="text-[var(--secondary)]" />
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
            FAQ
          </h2>
        </div>
        <div>
          {FAQ.map((item, i) => (
            <Accordion key={i} title={item.q}>
              {item.a}
            </Accordion>
          ))}
        </div>
      </div>

      {/* Terminal commands reference */}
      <div className="glass rounded-xl p-6">
        <div className="flex items-center gap-2 mb-4">
          <Terminal size={14} className="text-[var(--cs-sage)]" />
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
            Terminal Commands
          </h2>
        </div>
        <div className="space-y-2">
          {[
            ['gauntlet dashboard', 'Open this dashboard'],
            ['gauntlet run "prompt"', 'Quick comparison with auto-detected models'],
            ['gauntlet benchmark', 'Run the full 20-test suite'],
            ['gauntlet benchmark --quick', 'Run 8 key tests (faster)'],
            ['gauntlet swe', 'SWE-bench style code testing'],
            ['gauntlet discover', 'List all installed models'],
            ['gauntlet leaderboard', 'View persistent trust rankings'],
          ].map(([cmd, desc]) => (
            <div key={cmd} className="flex items-center gap-3">
              <code className="text-[11px] font-mono text-[var(--primary)] bg-white/[0.03] rounded px-2 py-1 border border-white/5 shrink-0">
                {cmd}
              </code>
              <span className="text-[10px] text-[var(--text-dim)]">{desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
