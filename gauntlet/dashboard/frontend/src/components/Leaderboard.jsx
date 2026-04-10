import React from 'react'
import { motion, AnimatePresence, LayoutGroup } from 'framer-motion'
import { ListOrdered, Crown } from 'lucide-react'
import { getModelColor } from '../lib/animations'

function Sparkline({ data, color, width = 96, height = 32 }) {
  if (!data || data.length < 2) return null
  const min = Math.min(...data), max = Math.max(...data), range = max - min || 1
  const pts = data.map((v, i) =>
    `${(i / (data.length - 1)) * width},${height - ((v - min) / range) * height}`
  ).join(' L')
  return (
    <svg width={width} height={height} className="opacity-60">
      <path d={`M${pts}`} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

export default function Leaderboard({ data, result }) {
  const models = data?.models || []

  if (!models.length) return (
    <div className="space-y-8">
      <header>
        <h1 className="text-4xl md:text-5xl font-display font-bold tracking-tighter gradient-text-hero mb-2">
          Local Rankings
        </h1>
        <p className="text-[var(--text-muted)] uppercase tracking-[0.15em] text-sm font-display font-bold">Elo ratings from head-to-head comparisons on this machine (K=32, base 1500)</p>
      </header>
      <div className="glass rounded-xl p-16 text-center flex flex-col items-center justify-center min-h-[400px]">
        <ListOrdered size={36} className="text-[var(--text-muted)] mb-4" />
        <p className="text-sm text-[var(--text-dim)]">No leaderboard data yet</p>
        <p className="text-[10px] text-[var(--text-muted)] mt-1">Run comparisons or benchmarks to build rankings</p>
      </div>
    </div>
  )

  const totalRuns = models.reduce((sum, m) => sum + m.total_comparisons, 0)
  const topModel = models[0]

  return (
    <div className="space-y-8">
      {/* Header */}
      <header>
        <h1 className="text-4xl md:text-5xl font-display font-bold tracking-tighter gradient-text-hero mb-2">
          Local Rankings
        </h1>
        <p className="text-[var(--text-muted)] uppercase tracking-[0.15em] text-sm font-display font-bold">Elo ratings from head-to-head comparisons on this machine (K=32, base 1500)</p>
      </header>

      {/* Stats row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div className="glass rounded-lg p-5">
          <div className="text-[var(--text-muted)] text-[10px] font-semibold uppercase tracking-wider mb-1">Total Runs</div>
          <div className="text-2xl font-mono font-bold text-[var(--cs-text)] tracking-tighter">
            {totalRuns.toLocaleString()}
          </div>
        </div>
        <div className="glass rounded-lg p-5">
          <div className="text-[var(--text-muted)] text-[10px] font-semibold uppercase tracking-wider mb-1">Active Models</div>
          <div className="text-2xl font-mono font-bold text-[var(--cs-bronze)] tracking-tighter">
            {models.length}
          </div>
        </div>
        <div className="glass rounded-lg p-5">
          <div className="text-[var(--text-muted)] text-[10px] font-semibold uppercase tracking-wider mb-1">Avg Rating</div>
          <div className="text-2xl font-mono font-bold text-[var(--cs-sage)] tracking-tighter">
            {Math.round(models.reduce((s, m) => s + (m.rating || m.elo || 1500), 0) / models.length)}
          </div>
        </div>
        <div className="glass rounded-lg p-5">
          <div className="text-[var(--text-muted)] text-[10px] font-semibold uppercase tracking-wider mb-1">Top Performer</div>
          <div className="text-2xl font-mono font-bold text-[var(--cs-text)] tracking-tighter truncate">
            {topModel?.name || '--'}
          </div>
        </div>
      </div>

      {/* Leaderboard table */}
      <div className="glass rounded-xl overflow-hidden" style={{ boxShadow: 'var(--shadow-lg)' }}>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-white/8 bg-white/[0.02]">
                <th className="px-6 py-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">Rank</th>
                <th className="px-6 py-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">Model</th>
                <th className="px-6 py-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest text-right">Rating</th>
                <th className="px-6 py-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">Trend</th>
                <th className="px-6 py-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest text-center">W / L / D</th>
                <th className="px-6 py-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">Win %</th>
                <th className="px-6 py-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest text-right">Avg Speed</th>
                <th className="px-6 py-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest text-right">Quality</th>
                <th className="px-6 py-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest text-right">Runs</th>
              </tr>
            </thead>
            <LayoutGroup>
              <tbody className="divide-y divide-white/5">
                <AnimatePresence>
                  {models.map((m, i) => {
                    const color = getModelColor(i)
                    const hist = m.rating_history || m.elo_history || []
                    const change = hist.length >= 2 ? hist[hist.length - 1] - hist[hist.length - 2] : 0
                    const active = result?.models?.some(rm => rm.model === m.name)

                    return (
                      <motion.tr
                        key={m.name}
                        layout
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ type: 'spring', stiffness: 200, damping: 20, delay: i * 0.04 }}
                        className={`hover:bg-white/[0.02] transition-colors ${active ? 'bg-[var(--primary)]/[0.03]' : ''}`}
                      >
                        {/* Rank */}
                        <td className="px-6 py-5 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            {i === 0 && <Crown size={14} className="text-[var(--cs-gold)]" />}
                            <span className={`font-mono ${i === 0 ? 'text-[var(--cs-text)] text-lg' : 'text-[var(--text-dim)] ml-5'}`}>
                              {i + 1}
                            </span>
                          </div>
                        </td>

                        {/* Model name */}
                        <td className="px-6 py-5">
                          <div className="flex items-center gap-3">
                            <div
                              className="w-2 h-2 rounded-full"
                              style={{ background: color }}
                            />
                            <div className="flex flex-col">
                              <span className="text-[var(--cs-text)] font-display font-bold tracking-tight">{m.name}</span>
                              {m.provider && (
                                <span className="text-[10px] text-[var(--text-muted)] font-medium uppercase">{m.provider}</span>
                              )}
                            </div>
                            {active && (
                              <span className="bg-[var(--primary)]/10 text-[var(--primary)] text-[10px] font-bold px-1.5 py-0.5 rounded border border-[var(--primary)]/20">
                                NOW
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Rating */}
                        <td className="px-6 py-5 text-right">
                          <div className="flex flex-col items-end">
                            <span className={`font-mono font-bold text-lg ${
                              (m.rating || m.elo) >= 1600 ? 'text-[var(--cs-sage)]' : (m.rating || m.elo) < 1400 ? 'text-[var(--cs-terracotta)]' : 'text-[var(--cs-text)]'
                            }`}>
                              {Math.round(m.rating || m.elo).toLocaleString()}
                            </span>
                            {change !== 0 && (
                              <span className={`text-[10px] font-mono ${change > 0 ? 'text-[var(--cs-sage)]' : 'text-[var(--cs-terracotta)]'}`}>
                                {change > 0 ? '+' : ''}{Math.round(change)}
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Sparkline */}
                        <td className="px-6 py-5">
                          <Sparkline data={hist} color={color} />
                        </td>

                        {/* W/L/D */}
                        <td className="px-6 py-5 text-center">
                          <div className="font-mono text-sm">
                            <span className="text-[var(--cs-sage)]">{m.wins}</span>
                            <span className="text-[var(--text-muted)] mx-1">/</span>
                            <span className="text-[var(--cs-terracotta)]">{m.losses}</span>
                            <span className="text-[var(--text-muted)] mx-1">/</span>
                            <span className="text-[var(--text-dim)]">{m.draws}</span>
                          </div>
                        </td>

                        {/* Win % bar */}
                        <td className="px-6 py-5">
                          <div className="w-32">
                            <div className="flex justify-between text-[10px] text-[var(--text-dim)] mb-1 font-mono">
                              <span>{m.win_rate.toFixed(1)}%</span>
                            </div>
                            <div className="h-1.5 w-full bg-white/5 rounded-full overflow-hidden">
                              <motion.div
                                className="h-full rounded-full"
                                style={{ background: color }}
                                initial={{ width: 0 }}
                                animate={{ width: `${m.win_rate}%` }}
                                transition={{ delay: 0.2 + i * 0.04 }}
                              />
                            </div>
                          </div>
                        </td>

                        {/* Avg speed */}
                        <td className="px-6 py-5 text-right font-mono text-[var(--text-dim)]">
                          {m.avg_tokens_sec ? (
                            <>
                              {m.avg_tokens_sec.toFixed(1)}
                              <span className="text-[var(--text-muted)] text-[10px] ml-1">t/s</span>
                            </>
                          ) : '--'}
                        </td>

                        {/* Quality */}
                        <td className="px-6 py-5 text-right font-mono text-[var(--text-dim)]">
                          {m.avg_quality ? m.avg_quality.toFixed(2) : '--'}
                        </td>

                        {/* Total runs */}
                        <td className="px-6 py-5 text-right font-mono text-[var(--text-muted)]">
                          {m.total_comparisons.toLocaleString()}
                        </td>
                      </motion.tr>
                    )
                  })}
                </AnimatePresence>
              </tbody>
            </LayoutGroup>
          </table>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-white/5 bg-white/[0.01] flex justify-between items-center">
          <span className="text-[var(--text-muted)] text-xs font-mono">
            {models.length} models, {totalRuns.toLocaleString()} total runs
          </span>
        </div>
      </div>
    </div>
  )
}
