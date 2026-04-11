import React, { useState, useEffect, useRef, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Play, Gauge, Loader2, RefreshCw, Layers, Timer } from 'lucide-react'
import { getModelColor } from '../lib/animations'

/**
 * Compact inline model chip -- sits flush next to siblings
 */
function ModelChip({ model, index, isSelected, onToggle, color }) {
  return (
    <button
      onClick={() => onToggle(model.spec)}
      className={`flex items-center gap-2 rounded-md px-3 py-2 transition-all duration-150 text-left ${
        isSelected
          ? 'bg-white/[0.06] border border-white/10'
          : 'bg-white/[0.02] border border-white/5 hover:bg-white/[0.04] hover:border-white/8'
      }`}
      style={isSelected ? { borderColor: `${color}30` } : {}}
    >
      {/* Selection dot */}
      <div
        className="w-1.5 h-1.5 rounded-full shrink-0 transition-colors"
        style={{ background: isSelected ? color : 'var(--cs-text-muted)' }}
      />

      {/* Name */}
      <span
        className="text-[13px] font-semibold tracking-tight whitespace-nowrap"
        style={{ color: isSelected ? color : 'var(--cs-text)' }}
      >
        {model.name}
      </span>

      {/* Size badge */}
      {model.parameter_size && (
        <span
          className="text-[10px] font-medium px-1.5 py-0.5 rounded tracking-wider shrink-0"
          style={isSelected ? {
            background: `${color}10`,
            color: color,
          } : {
            background: 'rgba(255,255,255,0.04)',
            color: 'var(--cs-text-dim)',
          }}
        >
          {model.parameter_size}
        </span>
      )}

      {model.size_gb && (
        <span className="text-[10px] font-mono text-[var(--text-muted)] shrink-0">
          {model.size_gb}GB
        </span>
      )}

      {model.multimodal && (
        <span className="text-[9px] font-semibold text-[var(--cs-mauve)] tracking-wider uppercase shrink-0">
          Vision
        </span>
      )}

      {model.memory_warning && !model.fits_in_memory && (
        <span className="text-[9px] text-[var(--cs-gold)] shrink-0">Low RAM</span>
      )}
    </button>
  )
}

export default function ControlPanel({ onRunStarted, onModelsSelected, sendMessage, benchmarkState, resetBenchmark }) {
  const [models, setModels] = useState([])
  const [selected, setSelected] = useState([])
  const [systemInfo, setSystemInfo] = useState(null)
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [sequential, setSequential] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => { fetchModels() }, [])

  async function fetchModels() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/models')
      const data = await res.json()
      setModels(data.models || [])
      setSystemInfo(data.system || null)
      const safe = (data.models || []).filter(m => m.fits_in_memory)
      const pool = safe.length >= 2 ? safe : (data.models || [])
      let autoSelected = []
      if (pool.length >= 2) autoSelected = [pool[0].spec, pool[1].spec]
      else if (pool.length === 1) autoSelected = [pool[0].spec]
      setSelected(autoSelected)
      if (onModelsSelected) onModelsSelected(autoSelected)
    } catch (e) {
      setError('Could not fetch models. Is Ollama running?')
    }
    setLoading(false)
  }

  function toggleModel(spec) {
    setSelected(prev => {
      const next = prev.includes(spec) ? prev.filter(s => s !== spec) : [...prev, spec]
      if (onModelsSelected) onModelsSelected(next)
      return next
    })
  }

  async function handleRun() {
    if (!selected.length || !prompt.trim()) return
    setRunning(true)
    try {
      const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ models: selected, prompt: prompt.trim(), sequential }),
      })
      const data = await res.json()
      if (data.status === 'started' && onRunStarted) onRunStarted()
    } catch (e) {
      setError('Failed to start comparison')
    }
    setRunning(false)
  }

  function handleBenchmarkStart(quick) {
    if (!selected.length || !sendMessage) return
    sendMessage({
      action: 'start_benchmark',
      models: selected,
      quick: !!quick,
    })
  }

  async function handleBenchmark() {
    if (!selected.length) return
    setRunning(true)
    try {
      const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          models: selected,
          prompt: 'Write a Python function that reverses a linked list. Show your reasoning step by step.',
          sequential,
        }),
      })
      const data = await res.json()
      if (data.status === 'started' && onRunStarted) onRunStarted()
    } catch (e) {
      setError('Failed to start benchmark')
    }
    setRunning(false)
  }

  const ramPct = systemInfo
    ? ((systemInfo.total_ram_gb - systemInfo.available_ram_gb) / systemInfo.total_ram_gb * 100)
    : 0

  return (
    <div className="space-y-5">

      {/* ---- HEADER ---- */}
      <header className="space-y-2">
        <h1 className="text-2xl md:text-3xl font-display font-bold tracking-tighter gradient-text-hero">
          Test Models
        </h1>
        <p className="text-sm text-[var(--text-dim)] max-w-lg">
          Select models, choose a test mode. Every result contributes to the community dataset.
        </p>

        {/* System info */}
        {systemInfo && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.15 }}
            className="flex items-center gap-5"
          >
            <div className="flex items-center gap-3">
              <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--text-muted)]">
                System RAM
              </span>
              <div className="w-28 h-1.5 bg-white/5 rounded-full overflow-hidden">
                <motion.div
                  className="h-full rounded-full bg-[var(--cs-sage)]"
                  initial={{ width: 0 }}
                  animate={{ width: `${ramPct}%` }}
                  transition={{ duration: 0.8, delay: 0.2 }}
                />
              </div>
              <span className="text-xs font-mono text-[var(--cs-sage)]">
                {systemInfo.available_ram_gb}GB free
              </span>
              <span className="text-[10px] font-mono text-[var(--text-muted)]">
                / {systemInfo.total_ram_gb}GB
              </span>
            </div>
          </motion.div>
        )}
      </header>

      {/* ---- MODEL SELECTION ---- */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2.5">
            <Layers size={14} className="text-[var(--primary)]" />
            <h2 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-muted)]">
              Available Models
            </h2>
          </div>
          <button
            onClick={fetchModels}
            className="text-[10px] text-[var(--text-muted)] hover:text-[var(--text-dim)] flex items-center gap-1.5 transition-colors font-semibold uppercase tracking-wider"
          >
            <RefreshCw size={10} />
            Refresh
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 gap-3">
            <div className="w-5 h-5 border-2 border-[var(--primary)] border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-[var(--text-dim)]">Discovering models...</span>
          </div>
        ) : error ? (
          <div className="glass rounded-xl p-8 text-center">
            <p className="text-sm text-[var(--cs-terracotta)] mb-3">{error}</p>
            <button onClick={fetchModels} className="text-xs text-[var(--primary)] hover:underline">
              Try again
            </button>
          </div>
        ) : models.length === 0 ? (
          <div className="glass rounded-xl p-12 text-center">
            <Layers size={32} className="mx-auto text-[var(--text-muted)] mb-4 opacity-40" />
            <p className="text-sm text-[var(--text-dim)] mb-2">No models found</p>
            <p className="text-[11px] text-[var(--text-muted)] mb-4">
              Install Ollama and pull models to get started:
            </p>
            <code className="inline-block text-[11px] font-mono text-[var(--primary)] bg-black/40 rounded-lg px-4 py-2 border border-white/5">
              ollama pull gemma4:e2b && ollama pull qwen3.5:4b
            </code>
          </div>
        ) : (
          <motion.div
            initial="hidden"
            animate="show"
            variants={{
              hidden: { opacity: 0 },
              show: { opacity: 1, transition: { staggerChildren: 0.03 } },
            }}
            className="flex flex-wrap gap-1.5"
          >
            {models.map((m, i) => {
              const isSelected = selected.includes(m.spec)
              const color = getModelColor(i)
              return (
                <motion.div
                  key={m.spec}
                  variants={{
                    hidden: { opacity: 0, y: 8 },
                    show: { opacity: 1, y: 0 },
                  }}
                >
                  <ModelChip
                    model={m}
                    index={i}
                    isSelected={isSelected}
                    onToggle={toggleModel}
                    color={color}
                  />
                </motion.div>
              )
            })}
          </motion.div>
        )}
      </section>

      {/* ---- PROMPT INPUT ---- */}
      <section className="glass-medium rounded-xl p-6 space-y-4">
        <div className="flex items-center justify-between relative z-10">
          <label className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-muted)]">
            Prompt
          </label>
          <div className="flex items-center gap-2.5">
            <span className="text-[11px] text-[var(--text-muted)]">Sequential</span>
            <button
              onClick={() => setSequential(!sequential)}
              className="w-10 h-5 rounded-full relative transition-all duration-200"
              style={{
                background: sequential
                  ? 'var(--cs-bronze)'
                  : 'rgba(255,255,255,0.06)',
                border: sequential ? 'none' : '1px solid rgba(255,255,255,0.1)',
              }}
            >
              <motion.div
                className="absolute top-0.5 w-3.5 h-3.5 bg-white rounded-full"
                style={{ boxShadow: '0 1px 3px rgba(0,0,0,0.3)' }}
                animate={{ left: sequential ? 22 : 3 }}
                transition={{ type: 'spring', stiffness: 400, damping: 25 }}
              />
            </button>
          </div>
        </div>

        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="What do you want to test? Write a prompt to evaluate your models..."
          className="relative z-10 w-full h-36 bg-black/20 border border-white/6 rounded-lg p-4 text-[var(--cs-text)] font-mono text-sm leading-relaxed focus:ring-1 focus:ring-[var(--primary)]/30 focus:border-[var(--primary)]/20 outline-none resize-none transition-all placeholder:text-[var(--text-muted)]"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleRun()
          }}
        />

        {/* Action buttons — 4 test modes */}
        <div className="relative z-10 space-y-3 pt-1">
          <div className="flex flex-wrap items-center gap-3">
            {/* Compare: user prompt */}
            <motion.button
              onClick={handleRun}
              disabled={running || !selected.length || !prompt.trim()}
              className="flex items-center gap-2.5 px-6 py-2.5 rounded-lg font-semibold text-sm btn-primary disabled:opacity-30 disabled:cursor-not-allowed disabled:shadow-none disabled:transform-none"
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              {running ? (
                <>
                  <Loader2 size={15} className="animate-spin" />
                  Starting...
                </>
              ) : (
                <>
                  <Play size={15} />
                  Compare
                </>
              )}
            </motion.button>

            {/* Divider */}
            <span className="text-[var(--text-muted)] text-xs">or</span>

            {/* Benchmark modes */}
            <motion.button
              onClick={() => handleBenchmarkStart(true)}
              disabled={running || !selected.length}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg font-semibold text-sm btn-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-all"
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              <Gauge size={14} />
              Quick Benchmark
            </motion.button>

            <motion.button
              onClick={() => handleBenchmarkStart(false)}
              disabled={running || !selected.length}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg font-semibold text-sm border border-white/8 hover:border-white/15 text-[var(--cs-text)] disabled:opacity-30 disabled:cursor-not-allowed transition-all"
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              <Gauge size={14} />
              Full Benchmark
            </motion.button>
          </div>

          {/* Info row */}
          <div className="flex items-center gap-4 text-[var(--text-muted)]">
            <div className="flex items-center gap-1.5">
              <Timer size={12} />
              <span className="text-xs font-semibold">
                {selected.length} model{selected.length !== 1 ? 's' : ''}
              </span>
            </div>
            <span className="text-[10px] text-[var(--text-muted)]">
              Compare: custom prompt &bull; Quick: ~5 min &bull; Full: ~30 min
            </span>
            <span className="text-[10px] font-mono opacity-50 ml-auto">
              {navigator.platform?.includes('Mac') ? 'Cmd' : 'Ctrl'}+Enter
            </span>
          </div>

          <p className="text-[10px] text-[var(--text-muted)] italic">
            All test results contribute to the community dataset with your hardware metadata.
          </p>
        </div>
      </section>
    </div>
  )
}
