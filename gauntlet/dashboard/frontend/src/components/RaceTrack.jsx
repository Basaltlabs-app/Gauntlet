import React, { useMemo } from 'react'
import { motion } from 'framer-motion'
import { Timer, CheckCircle2, AlertCircle, Clock } from 'lucide-react'
import { getModelColor } from '../lib/animations'

export default function RaceTrack({ models, modelStates, result }) {
  const maxTokens = useMemo(() => {
    let max = 1
    for (const state of Object.values(modelStates)) {
      if (state?.tokens > max) max = state.tokens
    }
    if (result?.models) {
      for (const m of result.models) {
        if (m.total_tokens > max) max = m.total_tokens
      }
    }
    return max
  }, [modelStates, result])

  const modelList = result?.models ? result.models.map(m => m.model) : models
  if (!modelList.length) return null

  return (
    <div className="glass rounded-xl p-6">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--text-muted)]">
          Token Progress
        </h2>
        <span className="text-[10px] text-[var(--text-muted)] font-mono">{maxTokens} max</span>
      </div>

      <div className="space-y-5">
        {modelList.map((modelName, index) => {
          const name = typeof modelName === 'string' ? modelName : modelName
          const state = modelStates[name] || {}
          const final_ = result?.models?.find(m => m.model === name)
          const color = getModelColor(index)

          const tokens = final_?.total_tokens || state.tokens || 0
          const tps = final_?.tokens_per_sec || state.tokensPerSec
          const ttft = final_?.ttft_ms || state.ttft
          const totalTime = final_?.total_time_s
          const progress = maxTokens > 0 ? Math.min(tokens / maxTokens, 1) : 0
          const isWinner = result?.winner === name
          const isDone = state.status === 'done' || !!final_
          const isError = state.status === 'error'
          const isActive = state.status === 'generating'

          return (
            <div key={name}>
              {/* Model header */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2.5">
                  <motion.div
                    className="w-2 h-2 rounded-full"
                    style={{ background: color }}
                    animate={isActive ? { opacity: [1, 0.4, 1] } : {}}
                    transition={isActive ? { duration: 1.2, repeat: Infinity } : {}}
                  />
                  <span className="text-sm font-semibold" style={{ color }}>{name}</span>
                  {isWinner && (
                    <motion.span
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      transition={{ type: 'spring', stiffness: 300, delay: 0.2 }}
                      className="text-[10px] bg-[var(--cs-sage)]/10 text-[var(--cs-sage)] px-2 py-0.5 rounded font-semibold border border-[var(--cs-sage)]/15"
                    >
                      WINNER
                    </motion.span>
                  )}
                  {isError && <AlertCircle size={13} className="text-[var(--cs-terracotta)]" />}
                </div>

                <div className="flex items-center gap-4 text-[11px] font-mono text-[var(--text-dim)]">
                  {tps != null && (
                    <span className="flex items-center gap-1">
                      <Timer size={11} style={{ color }} />
                      <span style={{ color }}>{tps.toFixed(1)}</span> tok/s
                    </span>
                  )}
                  {ttft != null && (
                    <span className="flex items-center gap-1">
                      <Clock size={11} />
                      {ttft.toFixed(0)}ms
                    </span>
                  )}
                  {totalTime != null && <span>{totalTime.toFixed(1)}s</span>}
                  <span>{tokens} tok</span>
                  {isDone && <CheckCircle2 size={13} className="text-[var(--cs-sage)]" />}
                </div>
              </div>

              {/* Race bar */}
              <div className="relative h-8 bg-white/[0.02] rounded-lg overflow-hidden border border-white/5">
                {/* Progress bar */}
                <motion.div
                  className="absolute inset-y-0 left-0 rounded-lg"
                  style={{
                    background: `linear-gradient(90deg, ${color}08, ${color}30)`,
                    borderRight: `2px solid ${color}`,
                  }}
                  initial={{ width: '0%' }}
                  animate={{ width: `${Math.max(progress * 100, 0.5)}%` }}
                  transition={{ type: 'spring', mass: 1, stiffness: 80, damping: 18 }}
                />

                {/* Active pulse */}
                {isActive && (
                  <motion.div
                    className="absolute inset-y-0 w-20"
                    style={{
                      background: `linear-gradient(90deg, transparent, ${color}08, transparent)`,
                      left: `${Math.max(progress * 100 - 6, 0)}%`,
                    }}
                    animate={{ opacity: [0.2, 0.5, 0.2] }}
                    transition={{ duration: 1.2, repeat: Infinity }}
                  />
                )}

                {/* Percentage */}
                {progress > 0.1 && (
                  <motion.span
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-mono font-bold"
                    style={{ color, opacity: 0.5 }}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 0.5 }}
                  >
                    {(progress * 100).toFixed(0)}%
                  </motion.span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
