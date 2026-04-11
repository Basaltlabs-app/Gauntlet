import React, { useState, useMemo, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Gauge, Play, Loader2, CheckCircle2, XCircle, Clock, Square, RotateCcw,
  ClipboardCheck, Code, CheckCircle, Target, Repeat, Shield, Timer, Search,
  ListOrdered, AlertTriangle, ChevronRight, Zap, Brain, Eye, History, Calendar
} from 'lucide-react'
import { getModelColor, staggerContainer, staggerItem } from '../lib/animations'

const CATEGORY_META = {
  // Module names (uppercase — from module_runner pipeline)
  AMBIGUITY_HONESTY:        { icon: Eye,            label: 'Honesty',       color: '#a87c94' },
  SYCOPHANCY_TRAP:          { icon: Shield,         label: 'Pressure',      color: '#c27065' },
  SYCOPHANCY_GRADIENT:      { icon: Shield,         label: 'Gradient',      color: '#c27065' },
  INSTRUCTION_ADHERENCE:    { icon: ClipboardCheck, label: 'Instructions',  color: '#5da4a8' },
  INSTRUCTION_DECAY:        { icon: ClipboardCheck, label: 'Decay',         color: '#5da4a8' },
  CONSISTENCY_DRIFT:        { icon: Repeat,         label: 'Consistency',   color: '#7d93ab' },
  LOGICAL_CONSISTENCY:      { icon: Target,         label: 'Logic',         color: '#7d93ab' },
  SAFETY_BOUNDARY:          { icon: Shield,         label: 'Safety',        color: '#6ea882' },
  HALLUCINATION_PROBE:      { icon: Brain,          label: 'Hallucination', color: '#c87850' },
  CONTEXT_FIDELITY:         { icon: Search,         label: 'Context',       color: '#9b8e78' },
  REFUSAL_CALIBRATION:      { icon: Shield,         label: 'Refusal',       color: '#6ea882' },
  CONTAMINATION_CHECK:      { icon: AlertTriangle,  label: 'Contamination', color: '#c4a05a' },
  TEMPORAL_COHERENCE:       { icon: Clock,          label: 'Temporal',      color: '#b08d6e' },
  CONFIDENCE_CALIBRATION:   { icon: Target,         label: 'Confidence',    color: '#c87850' },
  ANCHORING_BIAS:           { icon: Brain,          label: 'Anchoring',     color: '#c4a05a' },
  PROMPT_INJECTION:         { icon: AlertTriangle,  label: 'Injection',     color: '#6ea882' },
  FRAMING_EFFECT:           { icon: Repeat,         label: 'Framing',       color: '#c4a05a' },
  // Legacy lowercase categories (from old benchmarks.py pipeline)
  instruction_following:    { icon: ClipboardCheck, label: 'Instructions',  color: '#5da4a8' },
  code_generation:          { icon: Code,           label: 'Coding',        color: '#a87c94' },
  factual_accuracy:         { icon: CheckCircle,    label: 'Accuracy',      color: '#6ea882' },
  reasoning:                { icon: Target,         label: 'Reasoning',     color: '#c4a05a' },
  consistency:              { icon: Repeat,         label: 'Consistency',   color: '#7d93ab' },
  pressure_resistance:      { icon: Shield,         label: 'Pressure',      color: '#c27065' },
  speed:                    { icon: Timer,          label: 'Speed',         color: '#b08d6e' },
  context_recall:           { icon: Search,         label: 'Recall',        color: '#9b8e78' },
}

function scoreColor(score) {
  if (score >= 70) return 'text-[var(--cs-sage)]'
  if (score >= 50) return 'text-[var(--cs-gold)]'
  return 'text-[var(--cs-terracotta)]'
}

function barBg(score) {
  if (score >= 70) return 'bg-[#6ea882]'
  if (score >= 50) return 'bg-[#c4a05a]'
  return 'bg-[#c27065]'
}

function categoryBadgeStyle(cat) {
  const meta = CATEGORY_META[cat]
  if (!meta) return { background: 'rgba(255,255,255,0.04)', color: 'var(--text-dim)' }
  return { background: `${meta.color}15`, color: meta.color }
}

// ── Test status icon with animation ──────────────────────────────

function TestStatusIcon({ status, passed }) {
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

// ── Single test row in the progress trail ──────────────────────────

function TestRow({ test, index }) {
  const meta = CATEGORY_META[test.category] || { label: test.category, color: '#9a9590', icon: Gauge }
  const Icon = meta.icon
  const isActive = test.status === 'running'
  const isDone = test.status === 'done'

  return (
    <motion.div
      initial={{ opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.03, duration: 0.25 }}
      className={`
        flex items-center gap-3 px-4 py-2.5 rounded-lg transition-all duration-300
        ${isActive ? 'bg-[var(--cs-gold)]/[0.06] border border-[var(--cs-gold)]/15' : ''}
        ${isDone && test.passed ? 'bg-[var(--cs-sage)]/[0.03]' : ''}
        ${isDone && !test.passed ? 'bg-[var(--cs-terracotta)]/[0.03]' : ''}
        ${!isActive && !isDone ? 'opacity-40' : ''}
      `}
    >
      {/* Status icon */}
      <TestStatusIcon status={test.status} passed={test.passed} />

      {/* Test name */}
      <span className={`text-sm font-mono flex-grow ${isActive ? 'text-[var(--cs-gold)] font-medium' : isDone ? 'text-[var(--cs-text)]' : 'text-[var(--text-muted)]'}`}>
        {test.name.replace(/_/g, ' ')}
      </span>

      {/* Category badge */}
      <span
        className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase shrink-0"
        style={categoryBadgeStyle(test.category)}
      >
        {meta.label}
      </span>

      {/* Duration */}
      {isDone && test.duration_s != null && (
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="text-[10px] font-mono text-[var(--text-muted)] w-12 text-right shrink-0"
        >
          {test.duration_s.toFixed(1)}s
        </motion.span>
      )}

      {/* Score */}
      {isDone && test.score_pct != null && (
        <motion.span
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          className={`text-xs font-bold font-mono w-10 text-right shrink-0 ${test.passed ? 'text-[var(--cs-sage)]' : 'text-[var(--cs-terracotta)]'}`}
        >
          {test.score_pct}%
        </motion.span>
      )}
    </motion.div>
  )
}

// ── Progress bar ──────────────────────────────────────────────────

function ProgressBar({ completed, total, passed, failed }) {
  const pct = total > 0 ? (completed / total) * 100 : 0

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-[10px] font-mono text-[var(--text-muted)]">
        <span>{completed}/{total} tests</span>
        <div className="flex items-center gap-3">
          {passed > 0 && (
            <span className="flex items-center gap-1 text-[var(--cs-sage)]">
              <CheckCircle2 size={10} /> {passed}
            </span>
          )}
          {failed > 0 && (
            <span className="flex items-center gap-1 text-[var(--cs-terracotta)]">
              <XCircle size={10} /> {failed}
            </span>
          )}
        </div>
      </div>
      <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
        <motion.div
          className="h-full rounded-full"
          style={{
            background: failed > 0
              ? 'linear-gradient(90deg, var(--cs-sage), var(--cs-gold))'
              : 'linear-gradient(90deg, var(--cs-bronze), var(--cs-sage))',
          }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
        />
      </div>
    </div>
  )
}


// ── Main component ────────────────────────────────────────────────

export default function BenchmarkPanel({ selectedModels, sendMessage, benchmarkState, resetBenchmark }) {
  const [quick, setQuick] = useState(false)
  const [history, setHistory] = useState([])
  const [loadedResults, setLoadedResults] = useState(null)  // Results loaded from history
  const [showHistory, setShowHistory] = useState(false)

  const isRunning = benchmarkState?.status === 'running'
  const isStopping = benchmarkState?.status === 'stopping'
  const isComplete = benchmarkState?.status === 'complete'
  const isStopped = benchmarkState?.status === 'stopped'
  const hasStreamedResults = isComplete || isStopped

  // Load benchmark history + latest results on mount
  useEffect(() => {
    fetchHistory()
    // Auto-load latest benchmark if no results are showing
    if (!benchmarkState?.results && !loadedResults) {
      fetch('/api/benchmark/latest')
        .then(r => r.json())
        .then(data => {
          if (data.results) setLoadedResults(data.results)
        })
        .catch(() => {})
    }
  }, [])

  // Auto-refresh history when a run completes
  useEffect(() => {
    if (hasStreamedResults) fetchHistory()
  }, [hasStreamedResults])

  async function fetchHistory() {
    try {
      const res = await fetch('/api/benchmark/history?limit=20')
      const data = await res.json()
      setHistory(data.runs || [])
    } catch (e) {
      console.error('Failed to load benchmark history:', e)
    }
  }

  async function loadRun(runId) {
    try {
      const res = await fetch(`/api/benchmark/history/${runId}`)
      const data = await res.json()
      if (data.results) {
        setLoadedResults(data.results)
        resetBenchmark()  // Clear any streaming state
        setShowHistory(false)
      }
    } catch (e) {
      console.error('Failed to load run:', e)
    }
  }

  // Compute progress stats
  const progressStats = useMemo(() => {
    if (!benchmarkState?.tests) return { completed: 0, total: 0, passed: 0, failed: 0 }
    let completed = 0, passed = 0, failed = 0, total = 0
    Object.values(benchmarkState.tests).forEach(modelTests => {
      modelTests.forEach(t => {
        total++
        if (t.status === 'done') {
          completed++
          if (t.passed) passed++
          else failed++
        }
      })
    })
    return { completed, total, passed, failed }
  }, [benchmarkState?.tests])

  function startBenchmark() {
    if (!selectedModels.length) return
    setLoadedResults(null)  // Clear loaded history
    resetBenchmark()
    sendMessage({
      action: 'start_benchmark',
      models: selectedModels,
      quick,
    })
  }

  function stopBenchmark() {
    sendMessage({ action: 'stop_benchmark' })
  }

  function runAgain() {
    setLoadedResults(null)
    resetBenchmark()
  }

  // Results: prefer streamed, fall back to loaded from history
  const results = benchmarkState?.results || loadedResults || null
  const hasResults = hasStreamedResults || loadedResults !== null
  const bestIdx = results ? results.reduce((best, r, i) =>
    r.overall_score > (results[best]?.overall_score ?? -1) ? i : best, 0) : -1

  return (
    <div className="space-y-8">
      {/* Page header */}
      <section className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl md:text-5xl font-display font-bold tracking-tighter gradient-text-hero mb-2">Benchmark</h1>
          <p className="text-xs uppercase tracking-[0.15em] text-[var(--text-muted)] font-display font-bold">
            {quick ? '8' : '17'} automated tests · programmatic verification · no LLM judge
          </p>
        </div>
        <div className="flex gap-3 items-center">
          {/* Status indicator */}
          <span className="px-3 py-1 bg-white/[0.03] border border-white/8 rounded-full text-xs font-medium text-[var(--text-dim)] flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${
              isRunning ? 'bg-[var(--cs-gold)] animate-pulse'
              : isStopping ? 'bg-[var(--cs-terracotta)] animate-pulse'
              : hasResults ? 'bg-[var(--cs-sage)]'
              : 'bg-[var(--text-muted)]'
            }`} />
            {isRunning ? 'Running...' : isStopping ? 'Stopping...' : hasResults ? (isStopped ? 'Stopped' : 'Complete') : 'Ready'}
          </span>
        </div>
      </section>

      {/* Controls */}
      <div className="flex items-center gap-4 flex-wrap">
        <button
          onClick={() => setQuick(!quick)}
          disabled={isRunning}
          className={`flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg border transition-all ${
            quick
              ? 'border-[var(--cs-gold)]/30 bg-[var(--cs-gold)]/5 text-[var(--cs-gold)]'
              : 'border-white/8 text-[var(--text-dim)]'
          } ${isRunning ? 'opacity-30 cursor-not-allowed' : ''}`}
        >
          <Clock size={12} />
          {quick ? 'Quick (8 tests)' : 'Full (17 tests)'}
        </button>

        <span className="text-[10px] text-[var(--text-muted)]">
          {selectedModels.length} model{selectedModels.length !== 1 ? 's' : ''} selected
        </span>

        <div className="ml-auto flex items-center gap-3">
          {/* Run Again button (after results) */}
          {hasResults && (
            <motion.button
              onClick={runAgain}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-white/8 text-[var(--text-dim)] hover:text-[var(--cs-text)] hover:border-white/15 transition-all"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              <RotateCcw size={14} />
              New Run
            </motion.button>
          )}

          {/* Stop button */}
          {(isRunning || isStopping) && (
            <motion.button
              onClick={stopBenchmark}
              disabled={isStopping}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-bold bg-[var(--cs-terracotta)]/15 border border-[var(--cs-terracotta)]/30 text-[var(--cs-terracotta)] hover:bg-[var(--cs-terracotta)]/25 transition-all disabled:opacity-50"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              <Square size={12} fill="currentColor" />
              {isStopping ? 'Stopping...' : 'Stop'}
            </motion.button>
          )}

          {/* Run button */}
          {!isRunning && !isStopping && !hasResults && (
            <motion.button
              onClick={startBenchmark}
              disabled={!selectedModels.length}
              className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-bold btn-primary disabled:opacity-30 disabled:cursor-not-allowed transition-all"
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              <Play size={14} />
              Run Benchmark
            </motion.button>
          )}
        </div>
      </div>

      {/* ── History Panel ── */}
      {history.length > 0 && !isRunning && (
        <div className="space-y-3">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="flex items-center gap-2 text-xs text-[var(--text-dim)] hover:text-[var(--cs-text)] transition-colors"
          >
            <History size={12} />
            <span>{showHistory ? 'Hide' : 'Show'} History ({history.length} runs)</span>
            <ChevronRight size={10} className={`transition-transform ${showHistory ? 'rotate-90' : ''}`} />
          </button>

          <AnimatePresence>
            {showHistory && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden"
              >
                <div className="glass rounded-xl overflow-hidden">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="bg-white/[0.02] text-[var(--text-muted)] text-[10px] uppercase tracking-widest">
                        <th className="px-4 py-2.5 border-b border-white/5">Date</th>
                        <th className="px-4 py-2.5 border-b border-white/5">Models</th>
                        <th className="px-4 py-2.5 border-b border-white/5">Type</th>
                        <th className="px-4 py-2.5 border-b border-white/5 text-right">Scores</th>
                        <th className="px-4 py-2.5 border-b border-white/5 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="text-sm">
                      {history.map((run) => {
                        const date = new Date(run.timestamp)
                        const dateStr = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
                        const timeStr = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

                        return (
                          <tr key={run.run_id} className="hover:bg-white/[0.02] transition-colors">
                            <td className="px-4 py-2.5 border-b border-white/[0.03]">
                              <div className="flex items-center gap-2">
                                <Calendar size={10} className="text-[var(--text-muted)]" />
                                <span className="font-mono text-[var(--cs-text)]">{dateStr}</span>
                                <span className="text-[var(--text-muted)] text-[10px]">{timeStr}</span>
                              </div>
                            </td>
                            <td className="px-4 py-2.5 border-b border-white/[0.03]">
                              <div className="flex gap-1.5 flex-wrap">
                                {run.models.map((m, i) => (
                                  <span key={m} className="text-xs font-mono px-1.5 py-0.5 rounded bg-white/[0.03]" style={{ color: getModelColor(i) }}>
                                    {m}
                                  </span>
                                ))}
                              </div>
                            </td>
                            <td className="px-4 py-2.5 border-b border-white/[0.03]">
                              <span className={`text-[10px] font-bold uppercase ${run.stopped ? 'text-[var(--cs-gold)]' : run.quick ? 'text-[var(--cs-steel)]' : 'text-[var(--text-dim)]'}`}>
                                {run.stopped ? 'Partial' : run.quick ? 'Quick' : 'Full'}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 border-b border-white/[0.03] text-right">
                              <div className="flex items-center justify-end gap-2">
                                {Object.entries(run.scores || {}).map(([model, score], i) => (
                                  <span key={model} className={`text-xs font-mono font-bold ${scoreColor(score)}`}>
                                    {score}%
                                  </span>
                                ))}
                              </div>
                            </td>
                            <td className="px-4 py-2.5 border-b border-white/[0.03] text-right">
                              <button
                                onClick={() => loadRun(run.run_id)}
                                className="text-[10px] px-2.5 py-1 rounded border border-white/8 text-[var(--text-dim)] hover:text-[var(--cs-text)] hover:border-white/15 transition-all"
                              >
                                Load
                              </button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* ── Live Progress Trail ── */}
      {benchmarkState && !hasResults && (
        <div className="space-y-6">
          {Object.entries(benchmarkState.tests || {}).map(([model, tests], modelIdx) => {
            const modelCompleted = tests.filter(t => t.status === 'done').length
            const modelPassed = tests.filter(t => t.status === 'done' && t.passed).length
            const modelFailed = tests.filter(t => t.status === 'done' && !t.passed).length
            const isCurrent = model === benchmarkState.currentModel

            return (
              <motion.div
                key={model}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: modelIdx * 0.1 }}
                className="glass rounded-xl overflow-hidden"
              >
                {/* Model header */}
                <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {isCurrent && (
                      <motion.div
                        className="w-2 h-2 rounded-full bg-[var(--cs-gold)]"
                        animate={{ opacity: [1, 0.3, 1] }}
                        transition={{ repeat: Infinity, duration: 1.5 }}
                      />
                    )}
                    <h3 className="text-lg font-display font-bold tracking-tight text-[var(--cs-text)]">
                      {model}
                    </h3>
                    <span className="text-[10px] text-[var(--text-muted)] font-mono">
                      {modelIdx + 1}/{benchmarkState.totalModels}
                    </span>
                  </div>
                  <div className="flex items-center gap-4">
                    {modelPassed > 0 && (
                      <span className="flex items-center gap-1 text-[10px] font-mono text-[var(--cs-sage)]">
                        <CheckCircle2 size={10} /> {modelPassed}
                      </span>
                    )}
                    {modelFailed > 0 && (
                      <span className="flex items-center gap-1 text-[10px] font-mono text-[var(--cs-terracotta)]">
                        <XCircle size={10} /> {modelFailed}
                      </span>
                    )}
                    <span className="text-[10px] font-mono text-[var(--text-muted)]">
                      {modelCompleted}/{tests.length}
                    </span>
                  </div>
                </div>

                {/* Progress bar */}
                <div className="px-5 pt-3">
                  <ProgressBar
                    completed={modelCompleted}
                    total={tests.length}
                    passed={modelPassed}
                    failed={modelFailed}
                  />
                </div>

                {/* Test trail */}
                <div className="p-3 space-y-0.5">
                  <AnimatePresence>
                    {tests.map((test, ti) => (
                      <TestRow key={`${model}-${ti}`} test={test} index={ti} />
                    ))}
                  </AnimatePresence>
                </div>
              </motion.div>
            )
          })}

          {/* Overall progress */}
          {benchmarkState.totalModels > 1 && (
            <div className="glass rounded-xl p-5">
              <div className="flex items-center gap-3 mb-3">
                <Gauge size={14} className="text-[var(--cs-bronze)]" />
                <span className="text-xs font-display font-bold text-[var(--cs-text)] uppercase tracking-wider">Overall Progress</span>
              </div>
              <ProgressBar {...progressStats} />
            </div>
          )}
        </div>
      )}

      {/* ── Results (after completion or stop) ── */}
      {hasResults && results && (
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="space-y-8"
        >
          {/* Stopped banner */}
          {isStopped && (
            <motion.div
              variants={staggerItem}
              className="glass rounded-xl p-5 border border-[var(--cs-gold)]/20 bg-[var(--cs-gold)]/[0.03]"
            >
              <div className="flex items-center gap-3">
                <AlertTriangle size={16} className="text-[var(--cs-gold)]" />
                <p className="text-sm text-[var(--cs-gold)]">
                  Benchmark stopped early. Showing partial results.
                </p>
              </div>
            </motion.div>
          )}

          {/* Overall result cards */}
          <motion.section variants={staggerItem} className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {results.map((r, i) => {
              const color = getModelColor(i)
              const isBest = i === bestIdx && results.length > 1

              return (
                <div
                  key={r.model}
                  className={`glass rounded-xl p-7 relative overflow-hidden ${isBest ? 'highlight-winner' : ''}`}
                >
                  {isBest && (
                    <div className="absolute top-0 right-0 p-3">
                      <span className="px-2.5 py-0.5 bg-[var(--cs-sage)]/15 text-[var(--cs-sage)] border border-[var(--cs-sage)]/20 rounded text-[10px] font-bold tracking-wider uppercase">
                        BEST
                      </span>
                    </div>
                  )}
                  <div className="flex justify-between items-end mb-5">
                    <div>
                      <h3 className="text-xl font-display font-bold tracking-tight text-[var(--cs-text)]">{r.model}</h3>
                      <p className="text-[var(--text-dim)] text-sm">
                        {r.total_passed}/{r.total_tests} tests passed
                      </p>
                    </div>
                    <div className="text-right">
                      <div className={`text-3xl font-black font-mono ${scoreColor(r.overall_score)}`}>
                        {r.overall_score}%
                      </div>
                    </div>
                  </div>
                  <div className="h-2.5 bg-white/5 rounded-full overflow-hidden">
                    <motion.div
                      className="h-full rounded-full"
                      style={{
                        background: r.overall_score >= 50
                          ? `linear-gradient(90deg, ${color}60, var(--cs-sage))`
                          : `linear-gradient(90deg, ${color}60, var(--cs-terracotta))`,
                      }}
                      initial={{ width: 0 }}
                      animate={{ width: `${r.overall_score}%` }}
                      transition={{ duration: 0.8, delay: i * 0.15 }}
                    />
                  </div>
                </div>
              )
            })}
          </motion.section>

          {/* Category breakdown */}
          <motion.section variants={staggerItem} className="space-y-5">
            <div className="flex items-center gap-4">
              <h2 className="text-sm font-display font-bold text-[var(--cs-text)] uppercase tracking-wider">Category Breakdown</h2>
              <div className="h-[1px] bg-white/5 flex-grow" />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {Object.entries(results[0]?.category_scores || {}).map(([cat, score]) => {
                const meta = CATEGORY_META[cat] || { icon: Gauge, label: cat, color: '#9a9590' }
                const Icon = meta.icon
                return (
                  <div key={cat} className="glass rounded-lg p-4">
                    <div className="flex items-center gap-2.5 mb-3">
                      <div className="p-1.5 rounded-md" style={{ background: `${meta.color}12`, color: meta.color }}>
                        <Icon size={14} />
                      </div>
                      <span className="text-sm font-display font-semibold text-[var(--cs-text)]">{meta.label}</span>
                    </div>
                    <div className="space-y-2.5">
                      {results.map((r, i) => {
                        const catScore = r.category_scores?.[cat] || 0
                        return (
                          <div key={r.model} className="space-y-1">
                            <div className="flex justify-between text-[10px] font-medium text-[var(--text-muted)]">
                              <span>{r.model.split(':')[0]}</span>
                              <span>{catScore.toFixed(0)}%</span>
                            </div>
                            <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                              <motion.div
                                className={`h-full rounded-full ${barBg(catScore)}`}
                                initial={{ width: 0 }}
                                animate={{ width: `${catScore}%` }}
                                transition={{ duration: 0.6, delay: i * 0.1 }}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          </motion.section>

          {/* Test suite table */}
          <motion.section variants={staggerItem} className="space-y-5">
            <div className="flex items-center gap-4">
              <h2 className="text-sm font-display font-bold text-[var(--cs-text)] uppercase tracking-wider">Test Suite</h2>
              <div className="h-[1px] bg-white/5 flex-grow" />
            </div>
            <div className="overflow-hidden rounded-xl glass">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-white/[0.02] text-[var(--text-muted)] text-[10px] uppercase tracking-widest">
                    <th className="px-5 py-3 border-b border-white/5">Test</th>
                    <th className="px-5 py-3 border-b border-white/5">Category</th>
                    {results.map((r, i) => (
                      <th key={r.model} className="px-5 py-3 border-b border-white/5 text-right" style={{ color: getModelColor(i) }}>
                        {r.model}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="text-sm">
                  {(results[0]?.results || []).map((test, ti) => {
                    const catStyle = categoryBadgeStyle(test.category)
                    return (
                      <tr key={test.name} className="hover:bg-white/[0.02] transition-colors">
                        <td className="px-5 py-3.5 border-b border-white/[0.03] font-medium text-[var(--cs-text)]">
                          {test.name}
                        </td>
                        <td className="px-5 py-3.5 border-b border-white/[0.03]">
                          <span
                            className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase"
                            style={catStyle}
                          >
                            {(CATEGORY_META[test.category]?.label || test.category)}
                          </span>
                        </td>
                        {results.map((r, i) => {
                          const t = r.results?.[ti]
                          if (!t) return <td key={i} className="px-5 py-3.5 border-b border-white/[0.03]" />
                          return (
                            <td key={r.model} className="px-5 py-3.5 border-b border-white/[0.03] text-right">
                              <div className={`flex items-center justify-end gap-2 ${scoreColor(t.score_pct)}`}>
                                {t.passed ? (
                                  <CheckCircle2 size={14} />
                                ) : t.score_pct >= 50 ? (
                                  <AlertTriangle size={14} className="text-[var(--cs-gold)]" />
                                ) : (
                                  <XCircle size={14} />
                                )}
                                <span className="font-mono">{t.score_pct}%</span>
                              </div>
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </motion.section>

          {/* Winner summary */}
          {results.length > 1 && bestIdx >= 0 && (
            <motion.section variants={staggerItem}>
              <div className="glass-medium highlight-winner rounded-xl p-7 flex flex-col md:flex-row items-center gap-6">
                <div className="flex-shrink-0 w-16 h-16 bg-[var(--cs-sage)]/10 rounded-xl flex items-center justify-center border border-[var(--cs-sage)]/20">
                  <ListOrdered size={28} className="text-[var(--cs-sage)]" />
                </div>
                <div className="text-center md:text-left space-y-1 flex-grow">
                  <h2 className="text-xl font-display font-bold tracking-tight text-[var(--cs-text)]">
                    {results[bestIdx].model} leads the benchmark
                  </h2>
                  <p className="text-[var(--text-dim)] text-sm max-w-2xl">
                    Scored {results[bestIdx].overall_score}% overall,
                    passing {results[bestIdx].total_passed} of {results[bestIdx].total_tests} tests.
                  </p>
                </div>
              </div>
            </motion.section>
          )}
        </motion.div>
      )}
    </div>
  )
}
