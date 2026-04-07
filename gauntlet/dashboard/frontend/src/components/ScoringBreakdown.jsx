import React from 'react'
import { motion } from 'framer-motion'
import { Target, TrendingUp } from 'lucide-react'
import { getModelColor, staggerContainer, staggerItem } from '../lib/animations'

export default function ScoringBreakdown({ scoring }) {
  if (!scoring || !scoring.models?.length) return null

  return (
    <motion.div
      variants={staggerContainer}
      initial="hidden"
      animate="show"
      className="glass rounded-xl p-6 space-y-5"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Target size={14} className="text-[var(--primary)]" />
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
            Scoring Breakdown
          </h2>
        </div>
        <span className="text-[10px] font-mono text-[var(--text-muted)]">{scoring.formula}</span>
      </div>

      {/* Model score bars */}
      <div className="space-y-4">
        {scoring.models.map((ms, i) => {
          const color = getModelColor(i)
          const isWinner = ms.rank === 1
          const maxComposite = scoring.models[0]?.composite || 1

          return (
            <motion.div key={ms.model} variants={staggerItem}>
              {/* Model name + composite */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full" style={{ background: color }} />
                  <span className="text-sm font-display font-semibold" style={{ color }}>
                    {ms.model}
                  </span>
                  {isWinner && (
                    <span className="text-[9px] bg-[var(--cs-sage)]/12 text-[var(--cs-sage)] px-1.5 py-0.5 rounded font-bold border border-[var(--cs-sage)]/18">
                      #1
                    </span>
                  )}
                </div>
                <span className="text-lg font-bold font-mono" style={{ color: isWinner ? 'var(--cs-sage)' : color }}>
                  {(ms.composite * 100).toFixed(0)}
                  <span className="text-[10px] text-[var(--text-muted)] font-normal">/100</span>
                </span>
              </div>

              {/* Composite bar */}
              <div className="h-2.5 bg-white/[0.03] rounded-full overflow-hidden border border-white/5 mb-3">
                <motion.div
                  className="h-full rounded-full"
                  style={{
                    background: isWinner
                      ? `linear-gradient(90deg, ${color}30, var(--cs-sage))`
                      : `linear-gradient(90deg, ${color}15, ${color}50)`,
                  }}
                  initial={{ width: 0 }}
                  animate={{ width: `${(ms.composite / maxComposite) * 100}%` }}
                  transition={{ type: 'spring', mass: 1, stiffness: 60, damping: 15, delay: i * 0.15 }}
                />
              </div>

              {/* Component breakdown */}
              <div className="grid grid-cols-3 gap-2">
                {ms.components.map(comp => {
                  const isLeading = comp.rank === 1 && scoring.models.length > 1
                  return (
                    <div
                      key={comp.metric}
                      className={`rounded-lg px-3 py-2 text-center ${
                        isLeading ? 'bg-[var(--cs-sage)]/5 border border-[var(--cs-sage)]/12' : 'bg-white/[0.02] border border-white/5'
                      }`}
                    >
                      <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">{comp.metric}</p>
                      <p className="text-sm font-mono font-bold mt-0.5" style={{ color: isLeading ? 'var(--cs-sage)' : 'var(--text)' }}>
                        {comp.raw}
                      </p>
                      <div className="flex items-center justify-center gap-1 mt-1">
                        <span className="text-[9px] text-[var(--text-muted)]">{comp.weight}</span>
                        {isLeading && <TrendingUp size={9} className="text-[var(--cs-sage)]" />}
                      </div>
                    </div>
                  )
                })}
              </div>
            </motion.div>
          )
        })}
      </div>

      {/* Winner reason */}
      {scoring.winner_reason && (
        <motion.div
          variants={staggerItem}
          className="bg-white/[0.02] rounded-lg p-4 border border-white/5"
        >
          <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-2">Why {scoring.winner} won</p>
          <p className="text-xs text-[var(--text-dim)] leading-relaxed">{scoring.winner_reason}</p>
        </motion.div>
      )}
    </motion.div>
  )
}
