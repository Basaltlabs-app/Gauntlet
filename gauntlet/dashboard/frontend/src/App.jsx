import React, { useState, useMemo } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Layers, Gauge, Timer, Target, Network, ListOrdered, BookOpen, Globe, FlaskConical } from 'lucide-react'
import { useWebSocket } from './hooks/useWebSocket'
import { pageTransition, getModelColor } from './lib/animations'
import Arena from './components/Arena'
import SpeedChart from './components/SpeedChart'
import QualityRadar from './components/QualityRadar'
import GraphView from './components/GraphView'
import Leaderboard from './components/Leaderboard'
import ScoringBreakdown from './components/ScoringBreakdown'
import ControlPanel from './components/ControlPanel'
import BenchmarkPanel from './components/BenchmarkPanel'
import HelpPanel from './components/HelpPanel'
import CommunityPanel from './components/CommunityPanel'

const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`

const TABS = [
  { id: 'test', label: 'Test', icon: FlaskConical },
  { id: 'speed', label: 'Speed', icon: Timer },
  { id: 'quality', label: 'Quality', icon: Target },
  { id: 'graph', label: 'Graph', icon: Network },
  { id: 'rankings', label: 'Rankings', icon: ListOrdered },
  { id: 'community', label: 'Community', icon: Globe },
  { id: 'help', label: 'Docs', icon: BookOpen },
]

function StatusDot({ status }) {
  const cls = {
    connected: 'status-success',
    connecting: 'status-warning animate-pulse',
    disconnected: 'status-error',
  }
  return <span className={`w-1.5 h-1.5 rounded-full ${cls[status] || cls.disconnected}`} />
}

export default function App() {
  const { status, config, modelStates, result, leaderboard, isJudging, reconnect, sendMessage, benchmarkState, resetBenchmark } = useWebSocket(WS_URL)
  const [activeTab, setActiveTab] = useState('test')
  const [selectedModels, setSelectedModels] = useState([])

  const models = config?.models || []
  const prompt = config?.prompt || ''
  const idle = !prompt && !result && models.length === 0

  const progress = useMemo(() => {
    const total = models.length
    const done = Object.values(modelStates).filter(s => s?.status === 'done' || s?.status === 'error').length
    const generating = Object.values(modelStates).some(s => s?.status === 'generating')
    return { total, done, generating, complete: result !== null }
  }, [models, modelStates, result])

  return (
    <div className="min-h-screen relative">

      {/* Warm ambient light */}
      <div className="bg-ambient" />

      {/* ---- NAVIGATION ---- */}
      <header className="fixed top-0 w-full z-[200] nav-bar">
        <div className="max-w-[var(--content-max-width)] mx-auto px-8 h-14 flex items-center justify-between">
          {/* Brand */}
          <div className="flex items-center gap-8">
            <span className="text-[15px] font-display font-bold tracking-[0.08em] uppercase text-[var(--cs-text)]">
              Gauntlet
            </span>

            {/* Progress indicator */}
            {progress.generating && !progress.complete && (
              <motion.div
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                className="flex items-center gap-2"
              >
                <div className="w-1.5 h-1.5 rounded-full bg-[var(--cs-bronze)] animate-pulse" />
                <span className="text-xs text-[var(--text-muted)] font-mono">
                  {progress.done}/{progress.total}
                </span>
              </motion.div>
            )}
            {progress.complete && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-xs text-[var(--cs-sage)] font-medium"
              >
                Complete
              </motion.span>
            )}
          </div>

          {/* Status */}
          <div className="flex items-center gap-2">
            <StatusDot status={status} />
            <span className="text-[10px] text-[var(--text-muted)] font-mono uppercase tracking-widest">
              {status}
            </span>
          </div>
        </div>
      </header>

      {/* ---- PROMPT BAR ---- */}
      {prompt && (
        <div className="max-w-[var(--content-max-width)] mx-auto px-8 pt-[4.5rem] relative z-[var(--z-content)]">
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1, duration: 0.3 }}
            className="glass rounded-xl px-6 py-4"
          >
            <div className="flex items-start gap-4">
              <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mt-0.5 shrink-0 font-semibold">
                Prompt
              </span>
              <p className="text-sm text-[var(--text-dim)] font-mono leading-relaxed">
                {prompt.length > 300 ? prompt.slice(0, 300) + '...' : prompt}
              </p>
            </div>
            {models.length > 0 && (
              <div className="flex items-center gap-3 mt-3 pt-3 border-t border-white/5">
                <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-semibold">
                  Models
                </span>
                <div className="flex gap-2">
                  {models.map((m, i) => (
                    <span
                      key={m}
                      className="text-xs font-mono px-2.5 py-0.5 rounded-md"
                      style={{
                        color: getModelColor(i),
                        background: `${getModelColor(i)}10`,
                        border: `1px solid ${getModelColor(i)}18`,
                      }}
                    >
                      {m}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </motion.div>
        </div>
      )}

      {/* ---- TAB NAVIGATION ---- */}
      <nav className="max-w-[var(--content-max-width)] mx-auto px-8 pt-5 relative z-[var(--z-content)]" style={{ marginTop: prompt ? 0 : '3.5rem' }}>
        <div className="flex items-center gap-1 border-b border-white/5 pb-px">
          {TABS.map(tab => {
            const Icon = tab.icon
            const active = activeTab === tab.id
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-all duration-200 rounded-t-md ${
                  active
                    ? 'text-[var(--cs-text)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-dim)]'
                }`}
              >
                {active && (
                  <motion.div
                    layoutId="activeTab"
                    className="absolute bottom-0 left-2 right-2 h-[2px] rounded-full bg-[var(--cs-bronze)]"
                    transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                  />
                )}
                <Icon size={14} className={active ? 'text-[var(--cs-bronze)]' : ''} />
                <span>{tab.label}</span>
              </button>
            )
          })}
        </div>
      </nav>

      {/* ---- MAIN CONTENT ---- */}
      <main className="max-w-[var(--content-max-width)] mx-auto px-8 py-8 relative z-[var(--z-content)]">
        <AnimatePresence mode="wait">
          <motion.div key={activeTab} {...pageTransition}>

            {activeTab === 'test' && (
              idle && !benchmarkState?.status ? (
                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.1 }}
                >
                  <ControlPanel
                    onRunStarted={reconnect}
                    onModelsSelected={setSelectedModels}
                    sendMessage={sendMessage}
                    benchmarkState={benchmarkState}
                    resetBenchmark={resetBenchmark}
                  />
                </motion.div>
              ) : benchmarkState?.status ? (
                <BenchmarkPanel
                  selectedModels={selectedModels}
                  sendMessage={sendMessage}
                  benchmarkState={benchmarkState}
                  resetBenchmark={resetBenchmark}
                />
              ) : (
                <div className="space-y-5">
                  <Arena models={models} modelStates={modelStates} result={result} isJudging={isJudging} />
                  {result?.scoring && <ScoringBreakdown scoring={result.scoring} />}
                </div>
              )
            )}

            {activeTab === 'speed' && (
              <SpeedChart models={models} modelStates={modelStates} result={result} />
            )}

            {activeTab === 'quality' && (
              <QualityRadar result={result} isJudging={isJudging} />
            )}

            {activeTab === 'graph' && (
              <GraphView result={result} />
            )}

            {activeTab === 'rankings' && (
              <Leaderboard data={leaderboard} result={result} />
            )}

            {activeTab === 'community' && (
              <CommunityPanel />
            )}

            {activeTab === 'help' && (
              <HelpPanel />
            )}

          </motion.div>
        </AnimatePresence>
      </main>

      {/* ---- FOOTER ---- */}
      <footer className="w-full py-10 relative z-[var(--z-content)]">
        <div className="divider mb-8" />
        <div className="max-w-[var(--content-max-width)] mx-auto px-8 flex flex-col items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium uppercase tracking-[0.2em] text-[var(--text-muted)]">
              Built by
            </span>
            <a href="https://basaltlabs.app" target="_blank" rel="noopener noreferrer"
               className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--accent)] hover:opacity-80 transition-opacity">
              Basalt Labs
            </a>
          </div>
          <p className="text-[11px] font-mono text-[var(--text-muted)] opacity-50">
            Behavioral reliability under pressure
          </p>
        </div>
      </footer>
    </div>
  )
}
