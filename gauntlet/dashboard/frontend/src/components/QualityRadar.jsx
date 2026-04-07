import React, { useMemo } from 'react'
import { motion } from 'framer-motion'
import { Loader2, Target } from 'lucide-react'
import { getModelColor } from '../lib/animations'
import ModelCard from './ModelCard'

const DIMS = ['correctness', 'completeness', 'clarity', 'code_quality']
const LABELS = ['Correctness', 'Completeness', 'Clarity', 'Code Quality']
const SIZE = 320
const CX = SIZE / 2
const CY = SIZE / 2
const R = 120
const ANGLE_STEP = 360 / DIMS.length

function polar(angle, radius) {
  const rad = (angle - 90) * (Math.PI / 180)
  return { x: CX + radius * Math.cos(rad), y: CY + radius * Math.sin(rad) }
}

export default function QualityRadar({ result, isJudging }) {
  const models = result?.models?.filter(m => m.quality_scores && Object.keys(m.quality_scores).length > 0) || []

  const paths = useMemo(() =>
    models.map((m, idx) => {
      const pts = DIMS.map((d, i) => polar(i * ANGLE_STEP, R * ((m.quality_scores[d] || 0) / 10)))
      return {
        d: pts.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' ') + 'Z',
        color: getModelColor(idx),
        model: m.model,
        score: m.overall_score,
      }
    }), [models])

  if (isJudging) {
    return (
      <div className="glass rounded-xl p-12 flex flex-col items-center justify-center min-h-[400px]">
        <div className="w-6 h-6 border-2 border-[var(--secondary)] border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-sm text-[var(--text-dim)]">Evaluating quality...</p>
      </div>
    )
  }

  if (!models.length) {
    return (
      <div className="glass rounded-xl p-12 text-center min-h-[400px] flex flex-col items-center justify-center">
        <Target size={32} className="text-[var(--text-muted)] mb-3" />
        <p className="text-sm text-[var(--text-dim)]">Quality scores appear after evaluation</p>
        <p className="text-[10px] text-[var(--text-muted)] mt-1">Run without --no-judge to enable</p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="glass rounded-xl p-6">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-4">
          Quality Radar
        </h2>

        <div className="flex flex-col items-center">
          <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
            {/* Concentric rings */}
            {[0.25, 0.5, 0.75, 1].map((s, i) => (
              <circle key={i} cx={CX} cy={CY} r={R * s} fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth={1} />
            ))}
            {/* Axes */}
            {DIMS.map((_, i) => {
              const end = polar(i * ANGLE_STEP, R)
              return <line key={i} x1={CX} y1={CY} x2={end.x} y2={end.y} stroke="rgba(255,255,255,0.05)" strokeWidth={1} />
            })}
            {/* Model polygons */}
            {paths.map(({ d, color, model }, i) => (
              <motion.path
                key={model}
                d={d}
                fill={`${color}10`}
                stroke={color}
                strokeWidth={2}
                strokeLinejoin="round"
                initial={{ opacity: 0, pathLength: 0 }}
                animate={{ opacity: 1, pathLength: 1 }}
                transition={{ duration: 0.8, delay: i * 0.2 }}
              />
            ))}
            {/* Dots */}
            {models.map((m, mi) =>
              DIMS.map((d, di) => {
                const p = polar(di * ANGLE_STEP, R * ((m.quality_scores[d] || 0) / 10))
                return (
                  <motion.circle
                    key={`${m.model}-${d}`}
                    cx={p.x} cy={p.y} r={3}
                    fill={getModelColor(mi)}
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ delay: 0.6 + mi * 0.1 + di * 0.05 }}
                  />
                )
              })
            )}
            {/* Labels */}
            {LABELS.map((label, i) => {
              const p = polar(i * ANGLE_STEP, R + 28)
              return (
                <text key={label} x={p.x} y={p.y} textAnchor="middle" dominantBaseline="middle"
                  className="text-[10px]" fill="var(--text-dim)">
                  {label}
                </text>
              )
            })}
          </svg>

          {/* Legend */}
          <div className="flex flex-wrap gap-5 mt-4 justify-center">
            {models.map((m, i) => (
              <div key={m.model} className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full" style={{ background: getModelColor(i) }} />
                <span className="text-xs font-mono" style={{ color: getModelColor(i) }}>{m.model}</span>
                {m.overall_score && (
                  <span className="text-[10px] font-mono text-[var(--text-muted)]">{m.overall_score.toFixed(1)}/10</span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Model cards below radar */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {models.map((m, i) => (
          <ModelCard key={m.model} model={m} index={i} winner={result?.winner} />
        ))}
      </div>
    </div>
  )
}
