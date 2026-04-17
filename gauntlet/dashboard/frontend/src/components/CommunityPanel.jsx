import React, { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Globe, Cpu, HardDrive, Monitor, TrendingDown, Brain, Activity,
  Loader2, AlertTriangle, Search, ChevronDown, BarChart3, Layers,
  Shield, ShieldAlert, Hash, Zap, Target, FlaskConical, GitBranch
} from 'lucide-react'
import {
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, LineChart, Line, CartesianGrid, Legend,
  ScatterChart, Scatter, ZAxis, RadarChart, Radar, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis, ReferenceLine
} from 'recharts'
import { staggerContainer, staggerItem, spring } from '../lib/animations'

const COMMUNITY_API = 'https://gauntlet.basaltlabs.app'

const TIER_OPTIONS = [
  { id: 'EDGE', label: 'Edge' },
  { id: 'CONSUMER_LOW', label: 'Consumer Low' },
  { id: 'CONSUMER_MID', label: 'Consumer Mid' },
  { id: 'CONSUMER_HIGH', label: 'Consumer High' },
  { id: 'CLOUD', label: 'Cloud' },
]

const CHART_COLORS = [
  '#7d93ab', '#b08d6e', '#6ea882', '#c4a05a',
  '#a87c94', '#c27065', '#5da4a8', '#9b8e78',
]

const QUANT_COLORS = {
  fp16: '#6ea882', Q8_0: '#7d93ab', Q6_K: '#5da4a8',
  Q5_K_M: '#b08d6e', Q4_K_M: '#c4a05a', Q4_K_S: '#c87850',
  Q3_K_M: '#c27065', Q2_K: '#a87c94',
}

const RECHARTS_TOOLTIP_STYLE = {
  contentStyle: {
    background: 'rgba(19, 20, 27, 0.92)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '8px',
    fontSize: '12px',
    color: '#e8e4dd',
    boxShadow: '0 4px 16px rgba(0,0,0,0.35)',
  },
  itemStyle: { color: '#9a9590' },
  labelStyle: { color: '#e8e4dd', fontWeight: 600 },
}

// Layer sensitivity categories for the radar chart
const LAYER_CATEGORIES = [
  { key: 'shallow_syntax', label: 'Syntax', fullLabel: 'Shallow Syntax (early layers)' },
  { key: 'factual_recall', label: 'Recall', fullLabel: 'Factual Recall (mid attention)' },
  { key: 'multi_step_logic', label: 'Logic', fullLabel: 'Multi-step Logic (late FFN)' },
  { key: 'spatial_reasoning', label: 'Spatial', fullLabel: 'Spatial Reasoning (mid-late attn)' },
  { key: 'pragmatic_inference', label: 'Pragmatic', fullLabel: 'Pragmatic Inference (late layers)' },
]


// ── Shared states ──────────────────────────────────────────────────

function LoadingState({ message }) {
  return (
    <div className="glass rounded-xl p-12 text-center flex flex-col items-center justify-center min-h-[200px]">
      <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: 'linear' }}>
        <Loader2 size={24} className="text-[var(--cs-bronze)]" />
      </motion.div>
      <p className="text-sm text-[var(--text-dim)] mt-3">{message || 'Loading...'}</p>
    </div>
  )
}

function ErrorState({ message }) {
  return (
    <div className="glass rounded-xl p-12 text-center flex flex-col items-center justify-center min-h-[200px]">
      <AlertTriangle size={24} className="text-[var(--cs-terracotta)] mb-3" />
      <p className="text-sm text-[var(--text-dim)]">{message || 'Failed to load data'}</p>
    </div>
  )
}

function EmptyState({ icon: Icon, message, submessage }) {
  return (
    <div className="glass rounded-xl p-12 text-center flex flex-col items-center justify-center min-h-[200px]">
      <Icon size={28} className="text-[var(--text-muted)] mb-3" />
      <p className="text-sm text-[var(--text-dim)]">{message}</p>
      {submessage && <p className="text-[10px] text-[var(--text-muted)] mt-1.5 max-w-sm">{submessage}</p>}
    </div>
  )
}

function SectionHeader({ icon: Icon, color, title, subtitle }) {
  return (
    <div className="flex items-center gap-3">
      <div className="p-2 rounded-lg" style={{ background: `${color}15` }}>
        <Icon size={16} style={{ color }} />
      </div>
      <div>
        <h2 className="text-sm font-display font-bold text-[var(--cs-text)] uppercase tracking-wider">{title}</h2>
        {subtitle && <p className="text-[10px] text-[var(--text-muted)]">{subtitle}</p>}
      </div>
    </div>
  )
}


// ── Data hook ──────────────────────────────────────────────────────

function useFetch(url, deps = []) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchData = useCallback(async () => {
    if (!url) { setLoading(false); return }
    setLoading(true)
    setError(null)
    try {
      let res
      try {
        const localUrl = url.replace(COMMUNITY_API, '')
        res = await fetch(localUrl)
        if (!res.ok) throw new Error('local failed')
      } catch {
        res = await fetch(url)
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [url])

  useEffect(() => { fetchData() }, [fetchData, ...deps])
  useEffect(() => {
    const interval = setInterval(fetchData, 60_000)
    return () => clearInterval(interval)
  }, [fetchData])

  return { data, loading, error, refetch: fetchData }
}


// ── Section 1: The Evidence (V2 hero) ──────────────────────────────

function PerplexityEvidence() {
  const { data, loading, error } = useFetch(`${COMMUNITY_API}/api/leaderboard/history`)

  // Extract perplexity + behavioral score pairs from history data
  const scatterData = React.useMemo(() => {
    if (!data?.tests) return []
    return data.tests
      .filter(t => t.perplexity != null && t.overall_score != null)
      .map(t => ({
        perplexity: parseFloat(t.perplexity),
        behavioral: parseFloat(t.overall_score),
        model: t.model_name || 'unknown',
        quant: t.model_config?.quantization || 'unknown',
      }))
  }, [data])

  return (
    <motion.section variants={staggerItem} className="space-y-5">
      <SectionHeader
        icon={Activity}
        color="var(--cs-sage)"
        title="The Evidence"
        subtitle="Does perplexity predict behavioral degradation?"
      />

      <div className="glass rounded-xl p-6">
        {loading ? <LoadingState message="Loading correlation data..." /> :
         error || scatterData.length === 0 ? (
          <EmptyState
            icon={Activity}
            message="Waiting for V2 community submissions"
            submessage="V2 includes perplexity baselines alongside behavioral scores. As community members run V2, this chart will populate with the correlation data that settles the perplexity vs. behavior debate."
          />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={320}>
              <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" />
                <XAxis dataKey="perplexity" name="Perplexity" tick={{ fontSize: 10, fill: '#9a9590' }} label={{ value: 'Perplexity (lower = better prediction)', position: 'bottom', fontSize: 10, fill: '#9a9590' }} />
                <YAxis dataKey="behavioral" name="Behavioral Score" tick={{ fontSize: 10, fill: '#9a9590' }} label={{ value: 'Behavioral Score', angle: -90, position: 'insideLeft', fontSize: 10, fill: '#9a9590' }} />
                <ZAxis range={[40, 200]} />
                <Tooltip {...RECHARTS_TOOLTIP_STYLE} formatter={(v, n) => [typeof v === 'number' ? v.toFixed(1) : v, n]} />
                <Scatter data={scatterData} fill="#c4a05a" stroke="#0c0d12" strokeWidth={1}>
                  {scatterData.map((entry, i) => (
                    <Cell key={i} fill={QUANT_COLORS[entry.quant] || '#c4a05a'} />
                  ))}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
            <p className="text-[10px] text-[var(--text-muted)] text-center mt-2">
              Each dot is one community run. X = perplexity (prediction quality), Y = behavioral score (reliability under pressure).
              If these diverge, behavioral probes capture something perplexity misses.
            </p>
          </>
        )}
      </div>
    </motion.section>
  )
}


// ── Section 2: Rankings ────────────────────────────────────────────

function Rankings() {
  const [tier, setTier] = useState('CONSUMER_MID')
  const { data, loading, error } = useFetch(
    `${COMMUNITY_API}/api/leaderboard/tier?tier=${tier}`, [tier]
  )
  const models = data?.models || []

  return (
    <motion.section variants={staggerItem} className="space-y-5">
      <SectionHeader icon={Target} color="var(--cs-gold)" title="Rankings" subtitle="Stratified by hardware capability" />

      <div className="flex gap-2 flex-wrap">
        {TIER_OPTIONS.map(t => (
          <button key={t.id} onClick={() => setTier(t.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
              tier === t.id
                ? 'border-[var(--cs-gold)]/30 bg-[var(--cs-gold)]/8 text-[var(--cs-gold)]'
                : 'border-white/8 text-[var(--text-dim)] hover:border-white/15 hover:text-[var(--cs-text)]'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {loading ? <LoadingState message={`Loading ${tier.replace(/_/g, ' ').toLowerCase()} rankings...`} /> :
       error ? <ErrorState message="Could not load tier data" /> :
       !models.length ? <EmptyState icon={Monitor} message={`No models ranked for ${tier.replace(/_/g, ' ')} tier yet`} /> : (
        <div className="glass rounded-xl overflow-hidden" style={{ boxShadow: 'var(--shadow-lg)' }}>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-white/8 bg-white/[0.02]">
                  {['Rank', 'Model', 'Score', 'CI Range', 'n', 'Grade', ''].map(h => (
                    <th key={h} className={`px-5 py-3 text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest ${h === 'Score' || h === 'CI Range' ? 'text-right' : h === 'n' || h === 'Grade' ? 'text-center' : ''}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {models.map((m, i) => {
                  const score = m.mean || m.avg_score || 0
                  const unreliable = (m.sample_size || m.n || 0) < 5
                  return (
                    <motion.tr key={m.model_name} initial={{ opacity: 0 }} animate={{ opacity: unreliable ? 0.45 : 1 }} transition={{ delay: i * 0.02 }} className="hover:bg-white/[0.02] transition-colors">
                      <td className="px-5 py-3 font-mono text-[var(--text-dim)]">{i + 1}</td>
                      <td className="px-5 py-3 font-display font-bold text-[var(--cs-text)] tracking-tight">{m.model_name}</td>
                      <td className={`px-5 py-3 text-right font-mono font-bold ${score >= 70 ? 'text-[var(--cs-sage)]' : score >= 50 ? 'text-[var(--cs-gold)]' : 'text-[var(--cs-terracotta)]'}`}>{score.toFixed(1)}</td>
                      <td className="px-5 py-3 text-right font-mono text-[10px] text-[var(--text-muted)]">{m.ci_lower != null ? `${m.ci_lower.toFixed(1)} - ${m.ci_upper.toFixed(1)}` : '--'}</td>
                      <td className="px-5 py-3 text-center font-mono text-[var(--text-dim)]">{m.sample_size || m.n || '--'}</td>
                      <td className="px-5 py-3 text-center">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          m.grade === 'A' ? 'bg-[var(--cs-sage)]/15 text-[var(--cs-sage)]' :
                          m.grade === 'B' ? 'bg-[var(--cs-gold)]/15 text-[var(--cs-gold)]' :
                          'bg-[var(--cs-terracotta)]/15 text-[var(--cs-terracotta)]'
                        }`}>{m.grade || '?'}</span>
                      </td>
                      <td className="px-5 py-3 text-center">
                        {unreliable ? <ShieldAlert size={14} className="text-[var(--cs-gold)] mx-auto" title="n < 5" /> : <Shield size={14} className="text-[var(--cs-sage)] mx-auto" />}
                      </td>
                    </motion.tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="px-5 py-3 border-t border-white/5 bg-white/[0.01] text-[10px] text-[var(--text-muted)] font-mono">
            {models.length} models on {tier.replace(/_/g, ' ').toLowerCase()} tier
          </div>
        </div>
      )}
    </motion.section>
  )
}


// ── Section 3: Quantization Impact (grouped) ───────────────────────

function QuantizationImpact() {
  const [family, setFamily] = useState('llama')
  const [size, setSize] = useState('7b')
  const [subView, setSubView] = useState('degradation') // degradation | method | layers
  const { data, loading, error } = useFetch(
    family && size ? `${COMMUNITY_API}/api/degradation?model_family=${family}&parameter_size=${size}` : null,
    [family, size]
  )

  const FAMILIES = ['llama', 'qwen', 'gemma', 'mistral', 'phi', 'deepseek']
  const SIZES = ['1b', '3b', '4b', '7b', '8b', '14b', '27b', '35b', '70b']
  const QUANT_ORDER = ['fp16', 'Q8_0', 'Q6_K', 'Q5_K_M', 'Q5_K_S', 'Q4_K_M', 'Q4_K_S', 'Q4_0', 'Q3_K_M', 'Q3_K_S', 'Q2_K', 'IQ2_M']

  const levels = data?.levels || {}
  const chartData = QUANT_ORDER
    .filter(q => levels[q])
    .map(q => ({
      name: q,
      score: parseFloat(levels[q].mean?.toFixed(1)),
      ci_lower: parseFloat(levels[q].ci_lower?.toFixed(1)),
      ci_upper: parseFloat(levels[q].ci_upper?.toFixed(1)),
      n: levels[q].sample_size,
      perplexity: levels[q].perplexity_mean || null,
    }))

  const degradation = data?.degradation || []

  const SUB_VIEWS = [
    { id: 'degradation', label: 'Score vs Quant', icon: TrendingDown },
    { id: 'method', label: 'Quant Methods', icon: GitBranch },
    { id: 'layers', label: 'Layer Sensitivity', icon: Layers },
  ]

  return (
    <motion.section variants={staggerItem} className="space-y-5">
      <SectionHeader icon={FlaskConical} color="var(--cs-terracotta)" title="Quantization Impact" subtitle="How quantization degrades model behavior" />

      {/* Family + size selectors */}
      <div className="flex gap-4 flex-wrap items-end">
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Model Family</label>
          <div className="flex gap-1.5 flex-wrap">
            {FAMILIES.map(f => (
              <button key={f} onClick={() => setFamily(f)}
                className={`px-2.5 py-1 rounded text-xs font-mono border transition-all ${
                  family === f ? 'border-[var(--cs-terracotta)]/30 bg-[var(--cs-terracotta)]/8 text-[var(--cs-terracotta)]' : 'border-white/8 text-[var(--text-dim)] hover:border-white/15'
                }`}>{f}</button>
            ))}
          </div>
        </div>
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Size</label>
          <div className="flex gap-1.5 flex-wrap">
            {SIZES.map(s => (
              <button key={s} onClick={() => setSize(s)}
                className={`px-2.5 py-1 rounded text-xs font-mono border transition-all ${
                  size === s ? 'border-[var(--cs-terracotta)]/30 bg-[var(--cs-terracotta)]/8 text-[var(--cs-terracotta)]' : 'border-white/8 text-[var(--text-dim)] hover:border-white/15'
                }`}>{s}</button>
            ))}
          </div>
        </div>
      </div>

      {/* Sub-view tabs */}
      <div className="flex gap-1 p-1 rounded-lg bg-white/[0.03] border border-white/5 w-fit">
        {SUB_VIEWS.map(sv => (
          <button key={sv.id} onClick={() => setSubView(sv.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              subView === sv.id ? 'bg-white/[0.08] text-[var(--cs-text)]' : 'text-[var(--text-dim)] hover:text-[var(--cs-text)]'
            }`}>
            <sv.icon size={12} />
            {sv.label}
          </button>
        ))}
      </div>

      {/* Degradation curve view */}
      {subView === 'degradation' && (
        loading ? <LoadingState message="Loading degradation data..." /> :
        error || chartData.length === 0 ? <EmptyState icon={TrendingDown} message={`No data for ${family} ${size}`} /> : (
          <div className="glass rounded-xl p-5 space-y-4">
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#9a9590' }} angle={-30} textAnchor="end" height={50} />
                <YAxis tick={{ fontSize: 10, fill: '#9a9590' }} domain={['auto', 'auto']} />
                <Tooltip {...RECHARTS_TOOLTIP_STYLE} />
                <Line type="monotone" dataKey="score" stroke="#c27065" strokeWidth={2.5} name="Behavioral Score" dot={{ r: 4, fill: '#c27065', stroke: '#0c0d12', strokeWidth: 2 }} activeDot={{ r: 6 }} />
                {chartData.some(d => d.perplexity != null) && (
                  <Line type="monotone" dataKey="perplexity" stroke="#7d93ab" strokeWidth={2} strokeDasharray="6 3" name="Perplexity" dot={{ r: 3, fill: '#7d93ab', stroke: '#0c0d12', strokeWidth: 1 }} />
                )}
                {chartData[0]?.ci_lower != null && (
                  <>
                    <Line type="monotone" dataKey="ci_upper" stroke="rgba(194,112,101,0.2)" strokeDasharray="4 4" dot={false} legendType="none" />
                    <Line type="monotone" dataKey="ci_lower" stroke="rgba(194,112,101,0.2)" strokeDasharray="4 4" dot={false} legendType="none" />
                  </>
                )}
                <Legend wrapperStyle={{ fontSize: 10, paddingTop: 8 }} />
              </LineChart>
            </ResponsiveContainer>

            {degradation.length > 0 && (
              <div className="space-y-1.5">
                <h4 className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">Score Drops</h4>
                <div className="flex gap-2 flex-wrap">
                  {degradation.map((d, i) => (
                    <span key={i} className="px-2.5 py-1 rounded-md bg-white/[0.03] border border-white/5 text-[10px] font-mono text-[var(--text-dim)]">
                      {d.from} {'>'} {d.to}:
                      <span className={`ml-1 font-bold ${d.drop > 5 ? 'text-[var(--cs-terracotta)]' : 'text-[var(--cs-gold)]'}`}>
                        -{d.drop?.toFixed(1)}%
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )
      )}

      {/* Quant method comparison view */}
      {subView === 'method' && (
        <div className="glass rounded-xl p-6">
          <EmptyState
            icon={GitBranch}
            message="Quant method comparison coming with V2 data"
            submessage="V2 captures the quantization method (GGUF, GPTQ, AWQ, EXL2) and source (bartowski, thebloke, etc.) for every submission. When enough data accumulates, this view will show side-by-side behavioral scores for different methods at the same bit width."
          />
        </div>
      )}

      {/* Layer sensitivity view */}
      {subView === 'layers' && (
        <div className="glass rounded-xl p-6">
          <EmptyState
            icon={Layers}
            message="Layer sensitivity data coming with V2"
            submessage="V2 tests 5 cognitive functions (syntax, factual recall, logic, spatial reasoning, pragmatic inference) mapped to different transformer layer groups. This radar chart will show which capabilities degrade first under each quantization level."
          />
        </div>
      )}
    </motion.section>
  )
}


// ── Section 4: Hardware Landscape (condensed) ──────────────────────

function HardwareLandscape() {
  const { data, loading, error } = useFetch(`${COMMUNITY_API}/api/survey`)

  if (loading) return <LoadingState message="Loading hardware survey..." />
  if (error) return <ErrorState message="Could not load survey data" />
  if (!data || !data.total_submissions) return <EmptyState icon={Cpu} message="No survey data yet" />

  const tierData = Object.entries(data.tier_distribution || {}).map(([name, count]) => ({
    name: name.replace('CONSUMER_', 'C. ').replace('_', ' '), value: count,
  }))
  const gpuData = Object.entries(data.gpu_distribution || {}).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([name, count]) => ({ name: name.replace('_', ' '), value: count }))
  const quantData = Object.entries(data.quantization_distribution || {}).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([name, count]) => ({ name, value: count }))

  return (
    <motion.section variants={staggerItem} className="space-y-5">
      <SectionHeader icon={Cpu} color="var(--cs-mauve)" title="Hardware Landscape" subtitle={`${data.total_submissions} submissions across ${Object.keys(data.tier_distribution || {}).length} tiers`} />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Tier distribution */}
        <div className="glass rounded-xl p-4">
          <h4 className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-3 text-center">Hardware Tiers</h4>
          {tierData.length > 0 ? (
            <ResponsiveContainer width="100%" height={140}>
              <PieChart>
                <Pie data={tierData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={55} innerRadius={30} paddingAngle={2} strokeWidth={0}>
                  {tierData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Pie>
                <Tooltip {...RECHARTS_TOOLTIP_STYLE} />
              </PieChart>
            </ResponsiveContainer>
          ) : <p className="text-xs text-[var(--text-muted)] text-center py-8">No tier data</p>}
          <div className="flex flex-wrap gap-1.5 mt-1 justify-center">
            {tierData.map((d, i) => (
              <span key={d.name} className="flex items-center gap-1 text-[9px] text-[var(--text-dim)]">
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: CHART_COLORS[i % CHART_COLORS.length] }} />{d.name}
              </span>
            ))}
          </div>
        </div>

        {/* GPU distribution */}
        <div className="glass rounded-xl p-4">
          <h4 className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-3 text-center">Top GPUs</h4>
          {gpuData.length > 0 ? (
            <ResponsiveContainer width="100%" height={140}>
              <BarChart data={gpuData} layout="vertical" margin={{ left: 60, right: 10 }}>
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 9, fill: '#9a9590' }} width={55} />
                <Bar dataKey="value" fill="#b08d6e" radius={[0, 3, 3, 0]} barSize={10} />
              </BarChart>
            </ResponsiveContainer>
          ) : <p className="text-xs text-[var(--text-muted)] text-center py-8">No GPU data</p>}
        </div>

        {/* Quantization distribution */}
        <div className="glass rounded-xl p-4">
          <h4 className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-3 text-center">Quantization Levels</h4>
          {quantData.length > 0 ? (
            <ResponsiveContainer width="100%" height={140}>
              <BarChart data={quantData} margin={{ left: 10, right: 10, bottom: 5 }}>
                <XAxis dataKey="name" tick={{ fontSize: 8, fill: '#9a9590' }} angle={-30} textAnchor="end" height={35} />
                <YAxis hide />
                <Tooltip {...RECHARTS_TOOLTIP_STYLE} />
                <Bar dataKey="value" radius={[3, 3, 0, 0]} barSize={14}>
                  {quantData.map((d, i) => <Cell key={i} fill={QUANT_COLORS[d.name] || CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <p className="text-xs text-[var(--text-muted)] text-center py-8">No quant data</p>}
        </div>
      </div>
    </motion.section>
  )
}


// ── Section 5: Model Prediction ────────────────────────────────────

function ModelPrediction() {
  const [model, setModel] = useState('')
  const [tier, setTier] = useState('CONSUMER_MID')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function predict() {
    if (!model.trim()) return
    setLoading(true); setError(null); setData(null)
    try {
      let res
      try {
        res = await fetch(`/api/predict?model=${encodeURIComponent(model)}&tier=${tier}`)
        if (!res.ok) throw new Error('local failed')
      } catch { res = await fetch(`${COMMUNITY_API}/api/predict?model=${encodeURIComponent(model)}&tier=${tier}`) }
      if (!res.ok) { const body = await res.json().catch(() => ({})); throw new Error(body.error || `HTTP ${res.status}`) }
      setData(await res.json())
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const confidencePct = data?.confidence != null ? Math.round(data.confidence * 100) : null

  return (
    <motion.section variants={staggerItem} className="space-y-5">
      <SectionHeader icon={Brain} color="var(--cs-mauve)" title="Predict" subtitle="Collaborative filtering for untested configurations" />

      <div className="flex gap-3 items-end flex-wrap">
        <div className="flex-grow max-w-sm">
          <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Model Name</label>
          <input type="text" value={model} onChange={e => setModel(e.target.value)} onKeyDown={e => e.key === 'Enter' && predict()}
            placeholder="e.g. qwen2.5:14b"
            className="w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/8 text-sm font-mono text-[var(--cs-text)] placeholder:text-[var(--text-muted)] focus:border-[var(--cs-mauve)]/40 focus:outline-none transition-colors" />
        </div>
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Tier</label>
          <select value={tier} onChange={e => setTier(e.target.value)}
            className="px-3 py-2 rounded-lg bg-white/[0.03] border border-white/8 text-sm font-mono text-[var(--cs-text)] focus:border-[var(--cs-mauve)]/40 focus:outline-none appearance-none cursor-pointer">
            {TIER_OPTIONS.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </div>
        <button onClick={predict} disabled={!model.trim() || loading}
          className="flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-bold btn-primary disabled:opacity-30 disabled:cursor-not-allowed">
          {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />} Predict
        </button>
      </div>

      {error && (
        <div className="glass rounded-xl p-5 border border-[var(--cs-terracotta)]/20 bg-[var(--cs-terracotta)]/[0.03]">
          <p className="text-sm text-[var(--cs-terracotta)]">{error}</p>
        </div>
      )}

      {data && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={spring}
          className="glass rounded-xl p-6 space-y-5">
          <div className="flex items-end gap-8">
            <div>
              <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest mb-1">Predicted Score</div>
              <div className={`text-4xl font-mono font-black ${
                data.predicted_score >= 70 ? 'text-[var(--cs-sage)]' : data.predicted_score >= 50 ? 'text-[var(--cs-gold)]' : 'text-[var(--cs-terracotta)]'
              }`}>{data.predicted_score?.toFixed(1)}</div>
            </div>
            {confidencePct != null && (
              <div className="flex-grow max-w-xs">
                <div className="flex justify-between text-[10px] text-[var(--text-muted)] mb-1">
                  <span>Confidence</span><span className="font-mono">{confidencePct}%</span>
                </div>
                <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                  <motion.div className="h-full rounded-full"
                    style={{ background: confidencePct >= 70 ? 'linear-gradient(90deg, var(--cs-bronze), var(--cs-sage))' : confidencePct >= 40 ? 'linear-gradient(90deg, var(--cs-bronze), var(--cs-gold))' : 'linear-gradient(90deg, var(--cs-bronze), var(--cs-terracotta))' }}
                    initial={{ width: 0 }} animate={{ width: `${confidencePct}%` }} transition={{ duration: 0.6 }} />
                </div>
              </div>
            )}
            {data.basis && (
              <span className={`px-2.5 py-1 rounded text-[10px] font-bold uppercase ${
                data.basis === 'direct' ? 'bg-[var(--cs-sage)]/15 text-[var(--cs-sage)]' :
                data.basis === 'interpolated' ? 'bg-[var(--cs-gold)]/15 text-[var(--cs-gold)]' :
                'bg-[var(--cs-terracotta)]/15 text-[var(--cs-terracotta)]'
              }`}>{data.basis}</span>
            )}
          </div>
          {data.similar_models?.length > 0 && (
            <div>
              <h4 className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-2">Similar Models</h4>
              <div className="flex gap-2 flex-wrap">
                {data.similar_models.map((sm, i) => (
                  <span key={i} className="px-2.5 py-1 rounded-md bg-white/[0.03] border border-white/5 text-xs font-mono text-[var(--text-dim)]">
                    {typeof sm === 'string' ? sm : sm.model || sm.name || JSON.stringify(sm)}
                  </span>
                ))}
              </div>
            </div>
          )}
          {data.notes && <p className="text-[10px] text-[var(--text-muted)] italic">{data.notes}</p>}
        </motion.div>
      )}
    </motion.section>
  )
}


// ── Main CommunityPanel ────────────────────────────────────────────

export default function CommunityPanel() {
  return (
    <motion.div variants={staggerContainer} initial="hidden" animate="show" className="space-y-12">
      {/* Hero header */}
      <motion.header variants={staggerItem}>
        <h1 className="text-4xl md:text-5xl font-display font-bold tracking-tighter gradient-text-hero mb-2">
          Community Intelligence
        </h1>
        <p className="text-[var(--text-muted)] text-sm max-w-2xl">
          Real-world behavioral data from real hardware. Every test contributes to a shared dataset
          that answers: how does quantization affect what models actually do, not just what they know?
        </p>
      </motion.header>

      <PerplexityEvidence />
      <Rankings />
      <QuantizationImpact />
      <HardwareLandscape />
      <ModelPrediction />
    </motion.div>
  )
}
