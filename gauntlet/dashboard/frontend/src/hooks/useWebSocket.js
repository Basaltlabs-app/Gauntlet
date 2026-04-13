import { useState, useEffect, useCallback, useRef } from 'react'

/**
 * WebSocket hook for real-time comparison streaming.
 *
 * Events received:
 *   config   - initial setup (models, prompt)
 *   start    - model generation started
 *   token    - streaming token received
 *   done     - model generation complete
 *   error    - model error
 *   judging  - judge is evaluating
 *   result   - final comparison result
 *   leaderboard - updated leaderboard data
 */
export function useWebSocket(url) {
  const [status, setStatus] = useState('connecting') // connecting | connected | disconnected
  const [config, setConfig] = useState(null)          // { models, prompt }
  const [modelStates, setModelStates] = useState({})  // { [model]: { status, metrics, tokens, output } }
  const [result, setResult] = useState(null)           // final ComparisonResult
  const [leaderboard, setLeaderboard] = useState(null) // leaderboard data
  const [isJudging, setIsJudging] = useState(false)
  const [events, setEvents] = useState([])             // raw event log

  // Benchmark streaming state
  const [benchmarkState, setBenchmarkState] = useState(null)
  // Health check streaming state
  const [healthState, setHealthState] = useState(null)
  // healthState shape:
  // {
  //   status: 'running' | 'complete' | 'error' | 'stopping',
  //   model: '',
  //   totalProbes: 0,
  //   probes: [],               // [{name, category, status, score, duration_s, ...}]
  //   result: null,             // final health check result
  //   error: null,
  // }

  // benchmarkState shape:
  // {
  //   status: 'idle' | 'running' | 'complete' | 'stopped',
  //   models: [],
  //   suiteInfo: [],            // [{name, category, description}]
  //   totalTests: 0,
  //   currentModel: null,
  //   currentModelIndex: 0,
  //   totalModels: 0,
  //   tests: {},                // { [model]: [{name, category, status, passed, score_pct, duration_s, description}] }
  //   results: null,            // final results array
  // }

  const wsRef = useRef(null)
  const reconnectRef = useRef(null)
  const hasResultRef = useRef(false)
  const reconnectAttempts = useRef(0)
  const maxReconnects = 5

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setStatus('connected')
      reconnectAttempts.current = 0
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      setEvents(prev => [...prev, data])

      switch (data.type) {
        case 'config':
          setConfig({ models: data.models, prompt: data.prompt })
          // Initialize model states
          const initial = {}
          data.models.forEach(m => {
            initial[m] = { status: 'waiting', metrics: null, tokens: 0, output: '', tokensPerSec: null }
          })
          setModelStates(initial)
          break

        case 'start':
          setModelStates(prev => ({
            ...prev,
            [data.model]: { ...prev[data.model], status: 'generating' },
          }))
          break

        case 'token':
          setModelStates(prev => ({
            ...prev,
            [data.model]: {
              ...prev[data.model],
              status: 'generating',
              tokens: data.metrics?.tokens || 0,
              tokensPerSec: data.metrics?.tokens_per_sec || null,
              ttft: data.metrics?.ttft_ms || null,
              totalTextLength: data.total_text_length || 0,
            },
          }))
          break

        case 'done':
          setModelStates(prev => ({
            ...prev,
            [data.model]: {
              ...prev[data.model],
              status: 'done',
              metrics: data.metrics,
              output: data.metrics?.output || '',
              tokens: data.metrics?.total_tokens || prev[data.model]?.tokens || 0,
              tokensPerSec: data.metrics?.tokens_per_sec || null,
            },
          }))
          break

        case 'error':
          setModelStates(prev => ({
            ...prev,
            [data.model]: {
              ...prev[data.model],
              status: 'error',
              metrics: data.metrics,
              output: data.metrics?.output || 'Error occurred',
            },
          }))
          break

        case 'judging':
          setIsJudging(true)
          break

        case 'result':
          setIsJudging(false)
          setResult(data.data)
          hasResultRef.current = true
          break

        case 'leaderboard':
          setLeaderboard(data.data)
          break

        case 'idle':
          // Dashboard opened without a comparison - that's fine
          break

        case 'ping':
          // Keep-alive, ignore
          break

        // ── Benchmark streaming events ──────────────────────────
        case 'benchmark_start':
          setBenchmarkState({
            status: 'running',
            models: data.models,
            suiteInfo: data.suite_info,
            totalTests: data.total_tests,
            currentModel: null,
            currentModelIndex: 0,
            totalModels: data.models.length,
            tests: {},
            results: null,
          })
          break

        case 'benchmark_model_start':
          setBenchmarkState(prev => {
            if (!prev) return prev
            // Pre-populate test entries for this model as 'pending'
            const modelTests = prev.suiteInfo.map(t => ({
              name: t.name,
              category: t.category,
              description: t.description,
              status: 'pending',
              passed: null,
              score_pct: null,
              duration_s: null,
            }))
            return {
              ...prev,
              currentModel: data.model,
              currentModelIndex: data.model_index,
              tests: { ...prev.tests, [data.model]: modelTests },
            }
          })
          break

        case 'benchmark_test_start':
          setBenchmarkState(prev => {
            if (!prev) return prev
            const modelTests = [...(prev.tests[data.model] || [])]
            if (modelTests[data.test_index]) {
              modelTests[data.test_index] = {
                ...modelTests[data.test_index],
                status: 'running',
              }
            }
            return {
              ...prev,
              tests: { ...prev.tests, [data.model]: modelTests },
            }
          })
          break

        case 'benchmark_test_done':
          setBenchmarkState(prev => {
            if (!prev) return prev
            const modelTests = [...(prev.tests[data.model] || [])]
            if (modelTests[data.test_index]) {
              modelTests[data.test_index] = {
                ...modelTests[data.test_index],
                status: 'done',
                passed: data.passed,
                score_pct: data.score_pct,
                duration_s: data.duration_s,
                category: data.category,
                description: data.description,
              }
            }
            return {
              ...prev,
              tests: { ...prev.tests, [data.model]: modelTests },
            }
          })
          break

        case 'benchmark_model_done':
          setBenchmarkState(prev => {
            if (!prev) return prev
            return { ...prev }
          })
          break

        case 'benchmark_complete':
          setBenchmarkState(prev => {
            if (!prev) return prev
            return {
              ...prev,
              status: 'complete',
              results: data.results,
            }
          })
          break

        case 'benchmark_stopped':
          setBenchmarkState(prev => {
            if (!prev) return prev
            return {
              ...prev,
              status: 'stopped',
              results: data.partial_results,
            }
          })
          break

        case 'benchmark_stopping':
          setBenchmarkState(prev => {
            if (!prev) return prev
            return { ...prev, status: 'stopping' }
          })
          break

        // ── Health check streaming events ───────────────────────
        case 'health_start':
          setHealthState({
            status: 'running',
            model: data.model,
            totalProbes: data.total_probes,
            probes: [],
            result: null,
            error: null,
          })
          break

        case 'health_probe_done':
          setHealthState(prev => {
            if (!prev) return prev
            return {
              ...prev,
              probes: [...prev.probes, {
                name: data.name,
                category: data.category,
                status: 'done',
                score: data.score,
                passed: data.passed,
                duration_s: data.duration_s,
                description: data.description,
              }],
            }
          })
          break

        case 'health_complete':
          setHealthState(prev => ({
            ...prev,
            status: 'complete',
            result: data.result,
          }))
          break

        case 'health_error':
          setHealthState(prev => ({
            ...prev,
            status: 'error',
            error: data.error,
          }))
          break

        case 'health_stopping':
          setHealthState(prev => prev ? { ...prev, status: 'stopping' } : prev)
          break
      }
    }

    ws.onclose = () => {
      setStatus('disconnected')
      // Reconnect with backoff, max 5 attempts
      if (!hasResultRef.current && reconnectAttempts.current < maxReconnects) {
        reconnectAttempts.current += 1
        const delay = Math.min(3000 * reconnectAttempts.current, 15000)
        reconnectRef.current = setTimeout(() => connect(), delay)
      }
    }

    ws.onerror = () => {
      setStatus('disconnected')
    }
  }, [url, result])

  useEffect(() => {
    connect()
    return () => {
      if (wsRef.current) wsRef.current.close()
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
    }
  }, [connect])

  // Force reconnect (called when user starts a run from the dashboard)
  const reconnect = useCallback(() => {
    if (wsRef.current) wsRef.current.close()
    if (reconnectRef.current) clearTimeout(reconnectRef.current)
    // Reset state
    setConfig(null)
    setModelStates({})
    setResult(null)
    setIsJudging(false)
    setEvents([])
    hasResultRef.current = false
    // Reconnect after a brief delay to let the server update
    setTimeout(() => connect(), 500)
  }, [connect])

  // Send a message to the server (for benchmark commands etc.)
  const sendMessage = useCallback((msg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  // Reset benchmark state
  const resetBenchmark = useCallback(() => {
    setBenchmarkState(null)
  }, [])

  // Reset health check state
  const resetHealth = useCallback(() => {
    setHealthState(null)
  }, [])

  return {
    status,
    config,
    modelStates,
    result,
    leaderboard,
    isJudging,
    events,
    reconnect,
    sendMessage,
    benchmarkState,
    resetBenchmark,
    healthState,
    resetHealth,
  }
}
