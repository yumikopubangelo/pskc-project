import React, { useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import Icon from './Icon'
import { apiClient } from '../utils/apiClient'

function NodeGraph() {
  const backendOnly = { allowMockFallback: false }
  const [pskcMode, setPskcMode] = useState(false)
  const [activeFlow, setActiveFlow] = useState(null)
  const [flowRunning, setFlowRunning] = useState(false)
  const [packets, setPackets] = useState([])
  const [backendState, setBackendState] = useState({
    connected: false,
    totalRequests: 0,
    activeKeys: 0,
    cacheHitRate: 0,
  })
  const [error, setError] = useState(null)
  const svgRef = useRef(null)

  const nodes = [
    { id: 'client', label: 'Client', code: 'CL', x: 90, y: 200, color: '#60a5fa' },
    { id: 'gateway', label: 'Auth Gateway', code: 'GW', x: 280, y: 200, color: '#34d399' },
    { id: 'cache', label: 'Local Cache', code: 'LC', x: 470, y: 200, color: '#fbbf24' },
    { id: 'ml', label: 'ML Engine', code: 'ML', x: 470, y: 80, color: '#a78bfa' },
    { id: 'kms', label: 'KMS', code: 'KM', x: 660, y: 200, color: '#f87171' },
  ]

  const connections = [
    { from: 'client', to: 'gateway', label: 'Request' },
    { from: 'gateway', to: 'cache', label: 'Check Cache' },
    { from: 'gateway', to: 'kms', label: 'Direct Lookup' },
    { from: 'gateway', to: 'ml', label: 'Predict' },
    { from: 'ml', to: 'cache', label: 'Pre-cache' },
    { from: 'cache', to: 'gateway', label: 'Cache Response' },
    { from: 'kms', to: 'gateway', label: 'KMS Response' },
    { from: 'gateway', to: 'client', label: 'Result' },
  ]

  const requestFlow = pskcMode
    ? ['client', 'gateway', 'ml', 'cache', 'gateway', 'client']
    : ['client', 'gateway', 'kms', 'gateway', 'client']

  useEffect(() => {
    const fetchBackendState = async () => {
      try {
        const [health, metrics] = await Promise.all([
          apiClient.getHealth(backendOnly),
          apiClient.getMetrics(backendOnly),
        ])

        setBackendState({
          connected: health.status === 'healthy',
          totalRequests: metrics.total_requests || 0,
          activeKeys: metrics.active_keys || 0,
          cacheHitRate: (metrics.cache_hit_rate || 0) * 100,
        })
        setError(null)
      } catch (err) {
        console.error('Failed to load node graph backend state:', err)
        setBackendState({
          connected: false,
          totalRequests: 0,
          activeKeys: 0,
          cacheHitRate: 0,
        })
        setError('Backend unavailable')
      }
    }

    fetchBackendState()
    const interval = setInterval(fetchBackendState, 5000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (!flowRunning || !activeFlow) {
      return undefined
    }

    const interval = setInterval(() => {
      const newPacket = {
        id: Date.now() + Math.random(),
        path: activeFlow,
        progress: 0,
      }
      setPackets((prev) => [...prev, newPacket])
    }, pskcMode ? 1100 : 1500)

    return () => clearInterval(interval)
  }, [flowRunning, activeFlow, pskcMode])

  useEffect(() => {
    if (!packets.length) {
      return undefined
    }

    const speed = pskcMode ? 3.1 : 1.9
    const interval = setInterval(() => {
      setPackets((prev) => prev.map((packet) => ({ ...packet, progress: packet.progress + speed })).filter((packet) => packet.progress < 100))
    }, 20)

    return () => clearInterval(interval)
  }, [packets, pskcMode])

  const getNodePosition = (nodeId) => nodes.find((node) => node.id === nodeId)

  const isConnectionActive = (from, to) => {
    if (!activeFlow) {
      return false
    }

    for (let index = 0; index < activeFlow.length - 1; index += 1) {
      if (activeFlow[index] === from && activeFlow[index + 1] === to) {
        return true
      }
    }

    return false
  }

  const handleSendRequest = () => {
    setActiveFlow(requestFlow)
    setFlowRunning(true)
  }

  const handleReset = () => {
    setFlowRunning(false)
    setPackets([])
    setActiveFlow(null)
    setPskcMode(false)
  }

  return (
    <div className="min-h-screen py-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center mb-8"
        >
          <h1 className="text-3xl md:text-4xl font-display font-bold text-white mb-4">Microservices Architecture</h1>
          <p className="text-slate-400 max-w-2xl mx-auto mb-8">
            Conceptual service flow of PSKC. Runtime badges and counters below are loaded from the backend.
          </p>

          <div className="inline-flex items-center gap-2 rounded-full border border-accent-blue/30 bg-accent-blue/10 px-4 py-2 mb-6">
            <span className={`w-2 h-2 rounded-full ${error ? 'bg-danger-red' : 'bg-accent-green animate-pulse'}`} />
            <span className="text-accent-blue text-sm font-mono">
              {error ? 'Backend unavailable' : backendState.connected ? 'Backend connected' : 'Waiting for backend'}
            </span>
          </div>

          <div className="flex items-center justify-center gap-4">
            <span className={`text-sm ${!pskcMode ? 'text-white' : 'text-slate-500'}`}>Without PSKC</span>
            <button
              type="button"
              onClick={() => {
                setPskcMode((prev) => !prev)
                setPackets([])
                setActiveFlow(null)
                setFlowRunning(false)
              }}
              className={`toggle-switch ${pskcMode ? 'active' : ''}`}
            >
              <span className="sr-only">Toggle PSKC Mode</span>
            </button>
            <span className={`text-sm ${pskcMode ? 'text-white' : 'text-slate-500'}`}>With PSKC</span>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
          className="gradient-card rounded-2xl border border-dark-border overflow-hidden"
        >
          <div className="relative">
            <svg ref={svgRef} viewBox="0 0 800 350" className="w-full h-auto" style={{ minHeight: '350px' }}>
              <defs>
                <pattern id="graph-grid" width="40" height="40" patternUnits="userSpaceOnUse">
                  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#334155" strokeWidth="0.5" opacity="0.3" />
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill="url(#graph-grid)" />

              {connections.map((connection) => {
                const fromNode = getNodePosition(connection.from)
                const toNode = getNodePosition(connection.to)
                const active = isConnectionActive(connection.from, connection.to)

                return (
                  <g key={`${connection.from}-${connection.to}`}>
                    <line
                      x1={fromNode.x + 40}
                      y1={fromNode.y + 30}
                      x2={toNode.x - 40}
                      y2={toNode.y + 30}
                      stroke={active ? '#2563eb' : '#334155'}
                      strokeWidth={active ? 3 : 2}
                      className={active ? 'animate-pulse' : ''}
                    />
                    {active && (
                      <circle r="4" fill="#2563eb">
                        <animateMotion
                          dur={pskcMode ? '1.1s' : '1.6s'}
                          repeatCount="indefinite"
                          path={`M${fromNode.x + 40},${fromNode.y + 30} L${toNode.x - 40},${toNode.y + 30}`}
                        />
                      </circle>
                    )}
                  </g>
                )
              })}

              {packets.map((packet) => {
                const path = packet.path
                const segmentIndex = Math.floor((packet.progress / 100) * (path.length - 1))
                const segmentProgress = (packet.progress / 100) * (path.length - 1) - segmentIndex

                if (segmentIndex >= path.length - 1) {
                  return null
                }

                const fromNode = getNodePosition(path[segmentIndex])
                const toNode = getNodePosition(path[segmentIndex + 1])

                const x = fromNode.x + 40 + (toNode.x - fromNode.x - 80) * segmentProgress
                const y = fromNode.y + 30 + (toNode.y - fromNode.y) * segmentProgress

                return <circle key={packet.id} cx={x} cy={y} r="6" fill={pskcMode ? '#059669' : '#2563eb'} className="animate-pulse" />
              })}

              {nodes.map((node) => {
                const active = activeFlow && activeFlow.includes(node.id)

                return (
                  <g key={node.id} className="cursor-pointer">
                    <circle
                      cx={node.x + 40}
                      cy={node.y + 30}
                      r="45"
                      fill={node.color}
                      opacity="0.15"
                      className={active ? 'animate-pulse' : ''}
                    />
                    <circle
                      cx={node.x + 40}
                      cy={node.y + 30}
                      r="35"
                      fill="#1e293b"
                      stroke={active ? node.color : '#334155'}
                      strokeWidth={active ? 3 : 2}
                    />
                    <text
                      x={node.x + 40}
                      y={node.y + 35}
                      textAnchor="middle"
                      fill="#f8fafc"
                      fontSize="12"
                      fontFamily="DM Mono"
                      fontWeight="700"
                    >
                      {node.code}
                    </text>
                    <text
                      x={node.x + 40}
                      y={node.y + 90}
                      textAnchor="middle"
                      fill="#f1f5f9"
                      fontSize="12"
                      fontFamily="DM Sans"
                    >
                      {node.label}
                    </text>
                  </g>
                )
              })}
            </svg>
          </div>

          <div className="p-6 border-t border-dark-border">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <button type="button" onClick={handleSendRequest} className="btn-primary">
                  <span className="flex items-center gap-2">
                    <Icon name="play" className="w-4 h-4" />
                    Send Request
                  </span>
                </button>
                <button type="button" onClick={handleReset} className="btn-secondary">
                  Reset
                </button>
              </div>

              <div className="flex items-center gap-6 text-sm">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-full bg-accent-blue" />
                  <span className="text-slate-400">Active Flow</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-full bg-dark-border" />
                  <span className="text-slate-400">Inactive</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className={`w-6 h-1 rounded-full ${pskcMode ? 'bg-accent-green' : 'bg-accent-blue'} animate-pulse`} />
                  <span className="text-slate-400">Data Packet</span>
                </div>
              </div>
            </div>
          </div>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-8">
          {[
            {
              title: 'Runtime Status',
              description: error
                ? 'Backend metrics are currently unavailable.'
                : `Total requests recorded by backend: ${backendState.totalRequests.toLocaleString()}.`,
              icon: 'refresh',
              active: backendState.connected,
            },
            {
              title: 'Active Cache Surface',
              description: `Active keys: ${backendState.activeKeys}. Current cache hit rate: ${backendState.cacheHitRate.toFixed(1)}%.`,
              icon: 'lightning',
              active: backendState.activeKeys > 0,
            },
            {
              title: 'Architecture View',
              description: pskcMode
                ? 'Animation shows the conceptual predictive path while backend counters remain live.'
                : 'Toggle PSKC mode to compare conceptual direct lookup path against predictive cache path.',
              icon: 'trend',
              active: pskcMode,
            },
          ].map((info) => (
            <motion.div
              key={info.title}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className={`gradient-card rounded-xl p-6 border ${info.active ? 'border-accent-blue glow-blue' : 'border-dark-border'}`}
            >
              <div className="flex items-center gap-3 mb-3">
                <span className="w-10 h-10 rounded-lg bg-dark-bg/70 border border-dark-border flex items-center justify-center text-accent-blue">
                  <Icon name={info.icon} className="w-5 h-5" />
                </span>
                <h3 className="text-lg font-semibold text-white">{info.title}</h3>
              </div>
              <p className="text-slate-400 text-sm">{info.description}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default NodeGraph
