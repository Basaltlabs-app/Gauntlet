import React, { useState } from 'react'
import { motion } from 'framer-motion'
import { ChevronDown, ChevronUp, Crown, Timer, Clock, Target, HardDrive } from 'lucide-react'
import { getModelColor } from '../lib/animations'

export default function ModelCard({ model, index, winner }) {
  const [expanded, setExpanded] = useState(false)
  const color = getModelColor(index)
  const isWinner = model.model === winner
  const isError = model.output?.startsWith('[ERROR]')

  const stats = [
    { icon: Timer, label: 'Speed', value: model.tokens_per_sec ? `${model.tokens_per_sec.toFixed(1)}` : '--', unit: 'tok/s' },
    { icon: Clock, label: 'TTFT', value: model.ttft_ms ? `${model.ttft_ms.toFixed(0)}` : '--', unit: 'ms' },
    { icon: Clock, label: 'Total', value: model.total_time_s ? `${model.total_time_s.toFixed(1)}` : '--', unit: 's' },
    { icon: Target, label: 'Quality', value: model.overall_score ? `${model.overall_score.toFixed(1)}` : '--', unit: '/10' },
    { icon: HardDrive, label: 'Tokens', value: model.total_tokens || '--', unit: '' },
  ]

  return (
    <motion.div
      layout
      className={`glass rounded-xl overflow-hidden transition-all ${
        isWinner ? 'highlight-winner' : isError ? 'border-[var(--cs-terracotta)]/20' : ''
      }`}
      whileHover={{ y: -1 }}
      transition={{ type: 'spring', stiffness: 300, damping: 25 }}
    >
      {/* Top accent line */}
      <div
        className="h-[2px] w-full"
        style={{
          background: isWinner
            ? `linear-gradient(90deg, transparent, ${color}40, transparent)`
            : `linear-gradient(90deg, transparent, ${color}20, transparent)`,
        }}
      />

      {/* Header */}
      <div className="px-5 pt-4 pb-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className="w-2.5 h-2.5 rounded-full"
            style={{ background: color }}
          />
          <h3 className="font-display font-bold text-sm" style={{ color }}>{model.model}</h3>
          {isWinner && <Crown size={14} className="text-[var(--cs-sage)]" />}
          {model.provider && model.provider !== 'ollama' && (
            <span className="text-[10px] bg-white/4 px-2 py-0.5 rounded text-[var(--text-dim)] border border-white/5">
              {model.provider}
            </span>
          )}
        </div>
      </div>

      {/* Stats grid */}
      <div className="px-5 pb-4 grid grid-cols-5 gap-3">
        {stats.map(({ icon: Icon, label, value, unit }) => (
          <div key={label} className="text-center">
            <Icon size={11} className="mx-auto text-[var(--text-muted)] mb-1" />
            <p className="text-[10px] text-[var(--text-muted)]">{label}</p>
            <p className="text-xs font-mono font-bold text-[var(--text)]">
              {value}<span className="text-[var(--text-dim)] font-normal">{unit}</span>
            </p>
          </div>
        ))}
      </div>

      {/* Quality scores */}
      {model.quality_scores && Object.keys(model.quality_scores).length > 0 && (
        <div className="px-5 pb-4">
          <div className="flex gap-1.5">
            {Object.entries(model.quality_scores).map(([key, score]) => {
              const pct = (score / 10) * 100
              const barColor = score >= 8 ? 'var(--cs-sage)' : score >= 6 ? 'var(--cs-gold)' : 'var(--cs-terracotta)'
              return (
                <div key={key} className="flex-1">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[9px] text-[var(--text-muted)] capitalize">{key.replace('_', ' ')}</span>
                    <span className="text-[10px] font-mono font-bold" style={{ color: barColor }}>{score}</span>
                  </div>
                  <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                    <motion.div
                      className="h-full rounded-full"
                      style={{ background: barColor }}
                      initial={{ width: 0 }}
                      animate={{ width: `${pct}%` }}
                      transition={{ duration: 0.5, delay: 0.2 }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Expandable output */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-5 py-2.5 flex items-center justify-between text-[11px] text-[var(--text-muted)] hover:text-[var(--text-dim)] border-t border-white/5 transition-colors"
      >
        <span>{expanded ? 'Hide output' : 'Show output'}</span>
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>

      <motion.div
        initial={false}
        animate={{ height: expanded ? 'auto' : 0 }}
        transition={{ type: 'spring', stiffness: 200, damping: 25 }}
        className="overflow-hidden"
      >
        <pre className="px-5 pb-5 text-[11px] text-[var(--text-dim)] font-mono whitespace-pre-wrap leading-relaxed max-h-80 overflow-auto">
          {model.output || 'No output'}
        </pre>
      </motion.div>
    </motion.div>
  )
}
