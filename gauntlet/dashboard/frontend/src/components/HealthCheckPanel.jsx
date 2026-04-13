import React, { useState, useEffect, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Activity, Play, Loader2, CheckCircle2, XCircle, Clock, Square,
  RotateCcw, Pen, Code2, Brain, FileText, BarChart3, Sparkles,
  Shield, TrendingUp, TrendingDown, Minus, Timer, Zap
} from 'lucide-react'
import { getModelColor, staggerContainer, staggerItem, spring } from '../lib/animations'

// ── Category metadata ─────────────────────────────────────────────

const HC_CATEGORIES = {
  writing:            { icon: Pen,       label: 'Writing',   color: '#a87c94' },
  code:               { icon: Code2,     label: 'Code',      color: '#5da4a8' },
  reasoning:          { icon: Brain,     label: 'Reasoning', color: '#c4a05a' },
  summarization:      { icon: FileText,  label: 'Summary',   color: '#7d93ab' },
  data_analysis:      { icon: BarChart3, label: 'Data',      color: '#b08d6e' },
  creative:           { icon: Sparkles,  label: 'Creative',  color: '#c27065' },
  regression_anchor:  { icon: Shield,    label: 'Anchor',    color: '#6ea882' },
}

// ── Utilities ─────────────────────────────────────────────────────

function scoreColor(score) {
  if (score >= 70) return 'var(--cs-sage)'
  if (score >= 50) return 'var(--cs-gold)'
  return 'var(--cs-terracotta)'
}

function scoreTextClass(score) {
  if (score >= 70) return 'text-[var(--cs-sage)]'
  if (score >= 50) return 'text-[var(--cs-gold)]'
  return 'text-[var(--cs-terracotta)]'
}

function barBg(score) {
  if (score >= 70) return '#6ea882'
  if (score >= 50) return '#c4a05a'
  return '#c27065'
}

function letterGrade(score) {
  if (score >= 93) return 'A'
  if (score >= 85) return 'A-'
  if (score >= 80) return 'B+'
  if (score >= 73) return 'B'
  if (score >= 65) return 'B-'
  if (score >= 58) return 'C+'
  if (score >= 50) return 'C'
  if (score >= 40) return 'D'
  return 'F'
}

// ── Elapsed timer ─────────────────────────────────────────────────

function ElapsedTimer() {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setElapsed(e => e + 1), 1000)
    return () => clearInterval(t)
  }, [])
  const mins = Math.floor(elapsed / 60)
  const secs = elapsed % 60
  return (
    <span className="text-xs font-mono text-[var(--cs-gold)] tabular-nums">
      {mins}:{secs.toString().padStart(2, '0')}
    </span>
  )
}

// ── Model chip (single-select) ────────────────────────────────────

function ModelChip({ model, index, isSelected, onSelect, color }) {
  return (
    <button
      onClick={() => onSelect(model.spec)}
      className={`flex items-center gap-2 rounded-md px-3 py-2 transition-all duration-150 text-left ${
        isSelected
          ? 'bg-white/[0.06] border border-white/10'
          : 'bg-white/[0.02] border border-white/5 hover:bg-white/[0.04] hover:border-white/8'
      }`}
      style={isSelected ? { borderColor: `${color}30` } : {}}
    >
      <div
        className="w-1.5 h-1.5 rounded-full shrink-0 transition-colors"
        style={{ background: isSelected ? color : 'var(--cs-text-muted)' }}
      />
      <span
        className="text-[13px] font-semibold tracking-tight whitespace-nowrap"
        style={{ color: isSelected ? color : 'var(--cs-text)' }}
      >
        {model.name}
      </span>
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
    </button>
  )
}

// ── Probe status icon ─────────────────────────────────────────────

function ProbeStatusIcon({ status, passed }) {
  if (status === 'running') {
    return (
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ repeat: Infinity, duration: 1, ease: 'linear' }}
        className="w-4 h-4 flex items-center justify-center"
      >
        <Loader2 size={14} className="text-[var(--cs-gold)]" />
      </motion.div>
    )
  }
  if (status === 'done') {
    return passed ? (
      <motion.div
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 500, damping: 15 }}
      >
        <CheckCircle2 size={14} className="text-[var(--cs-sage)]" />
      </motion.div>
    ) : (
      <motion.div
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 500, damping: 15 }}
      >
        <XCircle size={14} className="text-[var(--cs-terracotta)]" />
      </motion.div>
    )
  }
  // pending
  return <div className="w-3.5 h-3.5 rounded-full border border-white/10" />
}

// ── Model Selection View ──────────────────────────────────────────

function ModelSelectionView({ sendMessage }) {
  const [models, setModels] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchModels()
  }, [])

  async function fetchModels() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/models')
      const data = await res.json()
      const modelList = data.models || []
      setModels(modelList)
      // Auto-select first model that fits in memory
      const safe = modelList.filter(m => m.fits_in_memory)
      if (safe.length > 0) setSelected(safe[0].spec)
      else if (modelList.length > 0) setSelected(modelList[0].spec)
    } catch (e) {
      setError('Could not fetch models. Is Ollama running?')
    }
    setLoading(false)
  }

  function handleStart() {
    if (!selected || !sendMessage) return
    sendMessage({
      action: 'start_health_check',
      model: selected,
    })
  }

  if (loading) {
    return (
      <div className="glass rounded-xl p-12 text-center flex flex-col items-center justify-center min-h-[300px]">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ repeat: Infinity, duration: 1, ease: 'linear' }}
        >
          <Loader2 size={24} className="text-[var(--cs-bronze)]" />
        </motion.div>
        <p className="text-sm text-[var(--text-muted)] mt-4">Loading models...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="glass rounded-xl p-12 text-center">
        <XCircle size={24} className="text-[var(--cs-terracotta)] mx-auto mb-3" />
        <p className="text-sm text-[var(--cs-terracotta)]">{error}</p>
        <button
          onClick={fetchModels}
          className="mt-4 px-4 py-2 text-xs font-medium rounded-lg bg-white/5 text-[var(--text-dim)] hover:bg-white/8 transition"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className="space-y-8"
    >
      {/* Header */}
      <div className="text-center space-y-3">
        <div className="flex items-center justify-center gap-3">
          <Zap size={20} className="text-[var(--cs-gold)]" />
          <h2 className="text-xl font-display font-bold text-[var(--cs-text)]">
            Quick Test
          </h2>
        </div>
        <p className="text-sm text-[var(--text-muted)] max-w-lg mx-auto">
          Can this model handle real tasks on your hardware? Writing, code, reasoning, summarization, data analysis, and creative work — tested in ~5 minutes. Results feed the community leaderboard.
        </p>
      </div>

      {/* Model selection */}
      <div className="glass rounded-xl p-6 space-y-4">
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-semibold">
            Select Model
          </span>
          <span className="text-[10px] text-[var(--text-muted)]">
            ({models.length} available)
          </span>
        </div>

        <div className="flex flex-wrap gap-2">
          {models.map((model, i) => (
            <ModelChip
              key={model.spec}
              model={model}
              index={i}
              isSelected={selected === model.spec}
              onSelect={setSelected}
              color={getModelColor(i)}
            />
          ))}
        </div>

        {models.length === 0 && (
          <p className="text-sm text-[var(--text-muted)] text-center py-4">
            No models found. Make sure Ollama is running with at least one model pulled.
          </p>
        )}
      </div>

      {/* Start button */}
      <div className="flex justify-center">
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={handleStart}
          disabled={!selected}
          className={`flex items-center gap-2.5 px-8 py-3 rounded-xl font-semibold text-sm transition-all duration-200 ${
            selected
              ? 'bg-[var(--cs-sage)]/20 border border-[var(--cs-sage)]/30 text-[var(--cs-sage)] hover:bg-[var(--cs-sage)]/25'
              : 'bg-white/5 border border-white/8 text-[var(--text-muted)] cursor-not-allowed'
          }`}
        >
          <Play size={16} />
          Run Quick Test
        </motion.button>
      </div>
    </motion.div>
  )
}

// ── Running View ──────────────────────────────────────────────────

function RunningView({ healthState, sendMessage }) {
  const completedCount = healthState.probes.length
  const totalCount = healthState.totalProbes || 0
  const pct = totalCount > 0 ? (completedCount / totalCount) * 100 : 0
  const passedCount = healthState.probes.filter(p => p.passed).length
  const failedCount = healthState.probes.filter(p => !p.passed).length
  const isStopping = healthState.status === 'stopping'

  // Group probes by category
  const grouped = useMemo(() => {
    const groups = {}
    for (const probe of healthState.probes) {
      const cat = probe.category || 'unknown'
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(probe)
    }
    return groups
  }, [healthState.probes])

  function handleStop() {
    if (sendMessage) {
      sendMessage({ action: 'stop_health_check' })
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className="space-y-6"
    >
      {/* Header */}
      <div className="glass rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ repeat: Infinity, duration: 2, ease: 'linear' }}
            >
              <Activity size={18} className="text-[var(--cs-sage)]" />
            </motion.div>
            <div>
              <h3 className="text-sm font-display font-bold text-[var(--cs-text)]">
                Running Quick Test
              </h3>
              <p className="text-[11px] text-[var(--text-muted)] font-mono mt-0.5">
                {healthState.model}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <Timer size={12} className="text-[var(--text-muted)]" />
              <ElapsedTimer />
            </div>

            <button
              onClick={handleStop}
              disabled={isStopping}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-[var(--cs-terracotta)]/10 text-[var(--cs-terracotta)] border border-[var(--cs-terracotta)]/20 hover:bg-[var(--cs-terracotta)]/15 transition disabled:opacity-50"
            >
              <Square size={12} />
              {isStopping ? 'Stopping...' : 'Stop'}
            </button>
          </div>
        </div>

        {/* Progress bar */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-[10px] font-mono text-[var(--text-muted)]">
            <span>{completedCount}/{totalCount} probes</span>
            <div className="flex items-center gap-3">
              {passedCount > 0 && (
                <span className="flex items-center gap-1 text-[var(--cs-sage)]">
                  <CheckCircle2 size={10} /> {passedCount}
                </span>
              )}
              {failedCount > 0 && (
                <span className="flex items-center gap-1 text-[var(--cs-terracotta)]">
                  <XCircle size={10} /> {failedCount}
                </span>
              )}
            </div>
          </div>
          <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
            <motion.div
              className="h-full rounded-full"
              style={{
                background: failedCount > 0
                  ? 'linear-gradient(90deg, var(--cs-sage), var(--cs-gold))'
                  : 'var(--cs-sage)',
              }}
              initial={{ width: 0 }}
              animate={{ width: `${pct}%` }}
              transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            />
          </div>
        </div>
      </div>

      {/* Probe results by category */}
      <div className="space-y-3">
        {Object.entries(grouped).map(([cat, probes]) => {
          const meta = HC_CATEGORIES[cat] || { icon: Activity, label: cat, color: '#9a9590' }
          const Icon = meta.icon
          return (
            <motion.div
              key={cat}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="glass rounded-xl p-4"
            >
              <div className="flex items-center gap-2 mb-3">
                <Icon size={14} style={{ color: meta.color }} />
                <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: meta.color }}>
                  {meta.label}
                </span>
              </div>
              <div className="space-y-1.5">
                {probes.map((probe, idx) => (
                  <div key={idx} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-white/[0.02]">
                    <ProbeStatusIcon status={probe.status} passed={probe.passed} />
                    <span className="text-sm font-mono text-[var(--cs-text)] flex-grow">
                      {(probe.name || '').replace(/_/g, ' ')}
                    </span>
                    {probe.duration_s != null && (
                      <span className="text-[10px] font-mono text-[var(--text-muted)] w-12 text-right shrink-0">
                        {probe.duration_s.toFixed(1)}s
                      </span>
                    )}
                    {probe.score != null && (
                      <span className={`text-xs font-bold font-mono w-10 text-right shrink-0 ${scoreTextClass(probe.score)}`}>
                        {Math.round(probe.score)}%
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </motion.div>
          )
        })}

        {/* Pending placeholder */}
        {completedCount < totalCount && (
          <div className="glass rounded-xl p-6 flex items-center justify-center gap-3 opacity-40">
            <Loader2 size={14} className="animate-spin text-[var(--text-muted)]" />
            <span className="text-xs text-[var(--text-muted)] font-mono">
              {totalCount - completedCount} probes remaining...
            </span>
          </div>
        )}
      </div>
    </motion.div>
  )
}

// ── Category Score Card ───────────────────────────────────────────

function CategoryCard({ category, score, delay }) {
  const meta = HC_CATEGORIES[category] || { icon: Activity, label: category, color: '#9a9590' }
  const Icon = meta.icon
  const pct = Math.round(score)

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className="glass rounded-xl p-4 space-y-3"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center"
            style={{ background: `${meta.color}15` }}
          >
            <Icon size={14} style={{ color: meta.color }} />
          </div>
          <span className="text-sm font-semibold text-[var(--cs-text)]">{meta.label}</span>
        </div>
        <span className={`text-lg font-display font-bold tabular-nums ${scoreTextClass(pct)}`}>
          {pct}%
        </span>
      </div>

      {/* Score bar */}
      <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
        <motion.div
          className="h-full rounded-full"
          style={{ background: barBg(pct) }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ delay: delay + 0.2, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>
    </motion.div>
  )
}

// ── Results View ──────────────────────────────────────────────────

function ResultsView({ healthState, resetHealth, sendMessage }) {
  const result = healthState.result
  const [history, setHistory] = useState(null)
  const [loadingHistory, setLoadingHistory] = useState(false)

  const overallScore = result?.overall_score ?? 0
  const grade = letterGrade(overallScore)
  const categoryScores = result?.category_scores || {}
  const regression = result?.regression || null
  const speedMetrics = result?.speed || {}
  const judgeType = result?.judge_type || 'self'

  // Fetch history on mount
  useEffect(() => {
    if (healthState.model) {
      fetchHistory()
    }
  }, [healthState.model])

  async function fetchHistory() {
    setLoadingHistory(true)
    try {
      const res = await fetch(`/api/health-check/history/${encodeURIComponent(healthState.model)}`)
      if (res.ok) {
        const data = await res.json()
        setHistory(data.history || [])
      }
    } catch (e) {
      // History fetch is non-critical
    }
    setLoadingHistory(false)
  }

  function handleRunAgain() {
    resetHealth()
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      className="space-y-6"
    >
      {/* ── Main score card ── */}
      <div className="glass rounded-xl p-8">
        <div className="flex flex-col items-center text-center space-y-4">
          {/* Model name */}
          <span className="text-xs font-mono text-[var(--text-muted)] uppercase tracking-wider">
            {healthState.model}
          </span>

          {/* Big score */}
          <div className="flex items-baseline gap-3">
            <motion.span
              initial={{ opacity: 0, scale: 0.5 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ type: 'spring', stiffness: 200, damping: 12, delay: 0.1 }}
              className="text-6xl font-display font-bold tabular-nums"
              style={{ color: scoreColor(overallScore) }}
            >
              {Math.round(overallScore)}
            </motion.span>
            <motion.span
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.3, duration: 0.3 }}
              className="text-2xl font-display font-bold"
              style={{ color: scoreColor(overallScore) }}
            >
              {grade}
            </motion.span>
          </div>

          {/* Speed and judge badges */}
          <div className="flex items-center gap-3 flex-wrap justify-center">
            {speedMetrics.tokens_per_sec != null && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.4 }}
                className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-white/5 text-[11px] font-mono text-[var(--text-dim)]"
              >
                <Zap size={11} className="text-[var(--cs-gold)]" />
                {speedMetrics.tokens_per_sec.toFixed(1)} tok/s
              </motion.span>
            )}
            {speedMetrics.ttft_ms != null && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.45 }}
                className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-white/5 text-[11px] font-mono text-[var(--text-dim)]"
              >
                <Timer size={11} className="text-[var(--cs-bronze)]" />
                {Math.round(speedMetrics.ttft_ms)}ms TTFT
              </motion.span>
            )}
            <motion.span
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.5 }}
              className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-white/5 text-[11px] font-mono text-[var(--text-dim)]"
            >
              <Brain size={11} className="text-[var(--cs-mauve)]" />
              {judgeType === 'self' ? 'Self-judge' : `External: ${judgeType}`}
            </motion.span>
          </div>
        </div>
      </div>

      {/* ── Category cards grid ── */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {Object.entries(categoryScores).map(([cat, score], i) => (
          <CategoryCard
            key={cat}
            category={cat}
            score={score}
            delay={0.1 + i * 0.08}
          />
        ))}
      </div>

      {/* ── Regression panel ── */}
      {regression && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6, duration: 0.4 }}
        >
          {regression.is_regression ? (
            <div className="rounded-xl p-5 border border-[var(--cs-terracotta)]/20 bg-[var(--cs-terracotta)]/[0.06]">
              <div className="flex items-center gap-2.5 mb-2">
                <TrendingDown size={16} className="text-[var(--cs-terracotta)]" />
                <span className="text-sm font-semibold text-[var(--cs-terracotta)]">
                  Regression Detected
                </span>
              </div>
              <p className="text-sm text-[var(--text-dim)]">
                <span className="font-mono font-bold text-[var(--cs-terracotta)]">
                  {regression.delta > 0 ? '+' : ''}{regression.delta?.toFixed(1)}%
                </span>
                {' '}since {regression.baseline_date || 'previous run'}
              </p>
              {regression.anchor_drift != null && Math.abs(regression.anchor_drift) > 2 && (
                <p className="text-xs text-[var(--text-muted)] mt-2 font-mono">
                  Anchor drift: {regression.anchor_drift > 0 ? '+' : ''}{regression.anchor_drift.toFixed(1)}%
                </p>
              )}
            </div>
          ) : regression.is_improvement ? (
            <div className="rounded-xl p-5 border border-[var(--cs-sage)]/20 bg-[var(--cs-sage)]/[0.06]">
              <div className="flex items-center gap-2.5 mb-2">
                <TrendingUp size={16} className="text-[var(--cs-sage)]" />
                <span className="text-sm font-semibold text-[var(--cs-sage)]">
                  Improved
                </span>
              </div>
              <p className="text-sm text-[var(--text-dim)]">
                <span className="font-mono font-bold text-[var(--cs-sage)]">
                  +{regression.delta?.toFixed(1)}%
                </span>
                {' '}since {regression.baseline_date || 'previous run'}
              </p>
            </div>
          ) : (
            <div className="rounded-xl p-5 border border-white/5 bg-white/[0.02]">
              <div className="flex items-center gap-2.5">
                <Minus size={16} className="text-[var(--text-muted)]" />
                <span className="text-sm text-[var(--text-muted)]">
                  Stable — consistent with previous run
                </span>
              </div>
            </div>
          )}
        </motion.div>
      )}

      {/* ── History section ── */}
      {history && history.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.7, duration: 0.4 }}
          className="glass rounded-xl p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <Clock size={14} className="text-[var(--text-muted)]" />
            <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-semibold">
              Recent History
            </span>
          </div>
          <div className="space-y-1.5">
            {history.slice(0, 5).map((entry, i) => (
              <div key={i} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-white/[0.02]">
                <span className="text-[11px] font-mono text-[var(--text-muted)] w-24 shrink-0">
                  {entry.date ? new Date(entry.date).toLocaleDateString() : '—'}
                </span>
                <div className="flex-grow h-1 bg-white/5 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${entry.score || 0}%`,
                      background: barBg(entry.score || 0),
                    }}
                  />
                </div>
                <span className={`text-xs font-bold font-mono w-10 text-right ${scoreTextClass(entry.score || 0)}`}>
                  {Math.round(entry.score || 0)}%
                </span>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      {loadingHistory && (
        <div className="text-center py-2">
          <Loader2 size={14} className="animate-spin text-[var(--text-muted)] inline" />
        </div>
      )}

      {/* ── Run Again button ── */}
      <div className="flex justify-center pt-2">
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={handleRunAgain}
          className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-medium bg-white/5 border border-white/8 text-[var(--text-dim)] hover:bg-white/8 transition"
        >
          <RotateCcw size={14} />
          Run Again
        </motion.button>
      </div>
    </motion.div>
  )
}

// ── Error View ────────────────────────────────────────────────────

function ErrorView({ healthState, resetHealth }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className="glass rounded-xl p-12 text-center space-y-4"
    >
      <XCircle size={32} className="text-[var(--cs-terracotta)] mx-auto" />
      <div>
        <h3 className="text-sm font-display font-bold text-[var(--cs-text)] mb-1">
          Quick Test Failed
        </h3>
        <p className="text-sm text-[var(--cs-terracotta)]">
          {healthState.error || 'An unexpected error occurred'}
        </p>
      </div>
      {healthState.model && (
        <p className="text-xs font-mono text-[var(--text-muted)]">
          Model: {healthState.model}
        </p>
      )}
      <button
        onClick={resetHealth}
        className="inline-flex items-center gap-2 px-5 py-2 rounded-lg text-xs font-medium bg-white/5 text-[var(--text-dim)] hover:bg-white/8 transition mt-2"
      >
        <RotateCcw size={12} />
        Try Again
      </button>
    </motion.div>
  )
}

// ── Main HealthCheckPanel ─────────────────────────────────────────

export default function HealthCheckPanel({ sendMessage, healthState, resetHealth }) {
  // No health state — show model selection
  if (!healthState) {
    return <ModelSelectionView sendMessage={sendMessage} />
  }

  // Error
  if (healthState.status === 'error') {
    return <ErrorView healthState={healthState} resetHealth={resetHealth} />
  }

  // Running or stopping
  if (healthState.status === 'running' || healthState.status === 'stopping') {
    return <RunningView healthState={healthState} sendMessage={sendMessage} />
  }

  // Complete
  if (healthState.status === 'complete') {
    return <ResultsView healthState={healthState} resetHealth={resetHealth} sendMessage={sendMessage} />
  }

  // Fallback
  return <ModelSelectionView sendMessage={sendMessage} />
}
