import React, { useMemo, useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { Network } from 'lucide-react'
import { getModelColor } from '../lib/animations'

const W = 700, H = 480

function useForceLayout(nodes, edges) {
  const [pos, setPos] = useState([])
  const ref = useRef()

  useEffect(() => {
    if (!nodes.length) return
    let p = nodes.map((_, i) => {
      const a = (i / nodes.length) * Math.PI * 2
      return { x: W / 2 + 140 * Math.cos(a), y: H / 2 + 140 * Math.sin(a), vx: 0, vy: 0 }
    })
    let tick = 0
    function sim() {
      if (tick >= 80) { setPos(p.map(({ x, y }) => ({ x, y }))); return }
      const alpha = 1 - tick / 80
      p.forEach(pt => { pt.vx += (W / 2 - pt.x) * 0.01 * alpha; pt.vy += (H / 2 - pt.y) * 0.01 * alpha })
      for (let i = 0; i < p.length; i++)
        for (let j = i + 1; j < p.length; j++) {
          const dx = p[j].x - p[i].x, dy = p[j].y - p[i].y
          const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
          const f = (2500 / (d * d)) * alpha
          p[i].vx -= (dx / d) * f; p[i].vy -= (dy / d) * f
          p[j].vx += (dx / d) * f; p[j].vy += (dy / d) * f
        }
      edges.forEach(({ source, target, weight }) => {
        const dx = p[target].x - p[source].x, dy = p[target].y - p[source].y
        const d = Math.sqrt(dx * dx + dy * dy), f = (d - 160) * 0.005 * weight * alpha
        p[source].vx += (dx / d) * f; p[source].vy += (dy / d) * f
        p[target].vx -= (dx / d) * f; p[target].vy -= (dy / d) * f
      })
      p.forEach(pt => {
        pt.vx *= 0.82; pt.vy *= 0.82; pt.x += pt.vx; pt.y += pt.vy
        pt.x = Math.max(80, Math.min(W - 80, pt.x)); pt.y = Math.max(80, Math.min(H - 80, pt.y))
      })
      tick++
      setPos(p.map(({ x, y }) => ({ x, y })))
      ref.current = requestAnimationFrame(sim)
    }
    ref.current = requestAnimationFrame(sim)
    return () => cancelAnimationFrame(ref.current)
  }, [nodes.length])
  return pos
}

export default function GraphView({ result }) {
  const [hovered, setHovered] = useState(null)
  const models = result?.models || []

  const nodes = useMemo(() => models.map((m, i) => ({
    id: m.model, score: m.overall_score || 5, color: getModelColor(i),
    isWinner: m.model === result?.winner, metrics: m,
  })), [models, result?.winner])

  const edges = useMemo(() => {
    const e = []
    for (let i = 0; i < models.length; i++)
      for (let j = i + 1; j < models.length; j++) {
        const diff = Math.abs((models[i].overall_score || 5) - (models[j].overall_score || 5))
        e.push({ source: i, target: j, weight: Math.max(1 - diff / 10, 0.1) })
      }
    return e
  }, [models])

  const positions = useForceLayout(nodes, edges)

  if (!models.length) return (
    <div className="glass rounded-xl p-12 text-center min-h-[480px] flex flex-col items-center justify-center">
      <Network size={32} className="text-[var(--text-muted)] mb-3" />
      <p className="text-sm text-[var(--text-dim)]">Graph view appears after results are ready</p>
    </div>
  )

  return (
    <div className="glass rounded-xl p-6">
      <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-4">Model Graph</h2>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`}>
        {/* Edges */}
        {edges.map(({ source, target, weight }, i) => {
          const a = positions[source], b = positions[target]
          return a && b ? (
            <motion.line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke="rgba(255,255,255,0.04)" strokeWidth={weight * 3}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 + i * 0.05 }}
            />
          ) : null
        })}
        {/* Nodes */}
        {nodes.map((n, i) => {
          const p = positions[i]; if (!p) return null
          const r = 18 + (n.score / 10) * 22
          const hover = hovered === n.id
          return (
            <g key={n.id}>
              {n.isWinner && (
                <motion.circle cx={p.x} cy={p.y} fill="none" stroke={n.color} strokeWidth={1}
                  animate={{ r: [r + 5, r + 12, r + 5], opacity: [0.1, 0.2, 0.1] }}
                  transition={{ duration: 3, repeat: Infinity }}
                />
              )}
              <motion.circle cx={p.x} cy={p.y} fill={`${n.color}10`} stroke={n.color}
                strokeWidth={hover ? 2 : 1} style={{ cursor: 'pointer' }}
                initial={{ r: 0 }} animate={{ r: hover ? r + 3 : r }}
                transition={{ type: 'spring', stiffness: 200, damping: 15 }}
                onMouseEnter={() => setHovered(n.id)} onMouseLeave={() => setHovered(null)}
              />
              <text x={p.x} y={p.y - r - 10} textAnchor="middle" className="text-[10px] font-medium pointer-events-none" fill="var(--text-dim)">{n.id}</text>
              <text x={p.x} y={p.y + 4} textAnchor="middle" className="text-sm font-bold font-mono pointer-events-none" fill={n.color}>{n.score.toFixed(1)}</text>
              {hover && n.metrics && (
                <foreignObject x={p.x + r + 8} y={p.y - 55} width={170} height={110}>
                  <div className="glass rounded-lg p-3 text-[10px] space-y-1 shadow-2xl">
                    <p className="font-display font-bold text-xs" style={{ color: n.color }}>{n.id}</p>
                    <p className="text-[var(--text-dim)]">Speed: <span className="text-[var(--text)] font-mono">{n.metrics.tokens_per_sec?.toFixed(1) || '--'} tok/s</span></p>
                    <p className="text-[var(--text-dim)]">TTFT: <span className="text-[var(--text)] font-mono">{n.metrics.ttft_ms?.toFixed(0) || '--'}ms</span></p>
                    <p className="text-[var(--text-dim)]">Quality: <span className="text-[var(--text)] font-mono">{n.metrics.overall_score?.toFixed(1) || '--'}/10</span></p>
                  </div>
                </foreignObject>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
