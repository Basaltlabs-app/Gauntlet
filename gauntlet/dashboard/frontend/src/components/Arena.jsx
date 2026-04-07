import React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Crown, Layers } from 'lucide-react'
import { staggerContainer, staggerItem } from '../lib/animations'
import RaceTrack from './RaceTrack'
import ModelCard from './ModelCard'

export default function Arena({ models, modelStates, result, isJudging }) {
  const allDone = result !== null
  const generating = Object.values(modelStates).some(s => s?.status === 'generating')

  return (
    <div className="space-y-5">
      {/* Race track */}
      <RaceTrack models={models} modelStates={modelStates} result={result} />

      {/* Status */}
      <AnimatePresence mode="wait">
        {generating && !allDone && (
          <motion.div
            key="gen"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex items-center justify-center gap-3 py-3"
          >
            <div className="w-4 h-4 border-2 border-[var(--primary)] border-t-transparent rounded-full animate-spin" />
            <span className="text-xs text-[var(--text-dim)]">Models generating...</span>
          </motion.div>
        )}

        {isJudging && (
          <motion.div
            key="judge"
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="flex items-center justify-center gap-3 py-3"
          >
            <div className="w-4 h-4 border-2 border-[var(--secondary)] border-t-transparent rounded-full animate-spin" />
            <span className="text-xs text-[var(--secondary)]">Evaluating quality...</span>
          </motion.div>
        )}

        {allDone && result.winner && (
          <motion.div
            key="winner"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: 'spring', stiffness: 200, damping: 20 }}
            className="glass-medium highlight-winner rounded-xl p-6 text-center"
          >
            <div className="inline-flex items-center gap-4">
              <div className="w-10 h-10 rounded-lg bg-[var(--cs-sage)]/10 border border-[var(--cs-sage)]/20 flex items-center justify-center">
                <Crown size={18} className="text-[var(--cs-sage)]" />
              </div>
              <div className="text-left">
                <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">Winner</p>
                <p className="text-xl font-display font-bold text-[var(--cs-sage)]">{result.winner}</p>
              </div>
            </div>

            {result.judge_model && (
              <p className="text-[10px] text-[var(--text-muted)] mt-3">Evaluated by {result.judge_model}</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Model output cards */}
      {allDone && result.models && (
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 lg:grid-cols-2 gap-4"
        >
          {result.models.map((m, i) => (
            <motion.div key={m.model} variants={staggerItem}>
              <ModelCard model={m} index={i} winner={result.winner} />
            </motion.div>
          ))}
        </motion.div>
      )}

      {/* Empty state */}
      {!generating && !allDone && models.length === 0 && (
        <div className="glass rounded-xl p-16 text-center">
          <Layers size={36} className="mx-auto text-[var(--text-muted)] mb-4" />
          <p className="text-[var(--text-dim)]">Waiting for comparison...</p>
          <p className="text-xs text-[var(--text-muted)] mt-1">Run gauntlet with --dashboard to stream results here</p>
        </div>
      )}
    </div>
  )
}
