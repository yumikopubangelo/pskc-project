import React, { useState, useEffect } from 'react'
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'

const SecurityTesting = () => {
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState(null)
  const [summary, setSummary] = useState(null)
  const [selectedTest, setSelectedTest] = useState('all')
  const [numAttempts, setNumAttempts] = useState(100)

  const runSecurityTests = async () => {
    setLoading(true)
    try {
      const response = await fetch(`/api/security/testing/run?test_type=${selectedTest}&num_attempts=${numAttempts}`, {
        method: 'POST',
      })
      const data = await response.json()
      if (data.success) {
        setResults(data.results)
        setSummary(data.summary)
      }
    } catch (error) {
      console.error('Security tests failed:', error)
    }
    setLoading(false)
  }

  const getSecurityResults = async () => {
    try {
      const response = await fetch('/api/security/testing/results')
      const data = await response.json()
      if (data.test_results && data.test_results.length > 0) {
        setResults(data.test_results.reduce((acc, r) => {
          acc[r.attack_type] = r
          return acc
        }, {}))
        setSummary(data.security_summary)
      }
    } catch (error) {
      console.error('Failed to get results:', error)
    }
  }

  useEffect(() => {
    getSecurityResults()
  }, [])

  const testTypes = [
    { id: 'all', name: 'All Tests', icon: '🛡️' },
    { id: 'brute_force', name: 'Brute Force', icon: '🔓' },
    { id: 'sql_injection', name: 'SQL Injection', icon: '💉' },
    { id: 'xss', name: 'XSS', icon: '⚡' },
    { id: 'credential_stuffing', name: 'Credential Stuffing', icon: '👤' },
    { id: 'rate_limit_violation', name: 'Rate Limit', icon: '⏱️' },
    { id: 'api_abuse', name: 'API Abuse', icon: '🔗' },
  ]

  const attackData = results ? Object.entries(results).map(([key, value]) => ({
    name: key.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase()),
    detection_rate: (value.detection_rate * 100).toFixed(1),
    block_rate: (value.block_rate * 100).toFixed(1),
    detected: value.detected_count,
    blocked: value.blocked_count,
    total: value.total_attempts,
  })) : []

  const COLORS = ['#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#3B82F6', '#EC4899']

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Security Testing</h1>
          <p className="text-slate-400">Cybersecurity simulation and attack detection testing</p>
        </div>
      </div>

      {/* Control Panel */}
      <div className="bg-dark-card rounded-xl border border-dark-border p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Run Security Tests</h2>
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="block text-sm text-slate-400 mb-1">Test Type</label>
            <select
              value={selectedTest}
              onChange={(e) => setSelectedTest(e.target.value)}
              className="bg-dark-bg border border-dark-border rounded-lg px-4 py-2 text-white w-48"
            >
              {testTypes.map((type) => (
                <option key={type.id} value={type.id}>
                  {type.icon} {type.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Attempts per Test</label>
            <input
              type="number"
              value={numAttempts}
              onChange={(e) => setNumAttempts(Number(e.target.value))}
              className="bg-dark-bg border border-dark-border rounded-lg px-4 py-2 text-white w-32"
              min={10}
              max={1000}
            />
          </div>
          <button
            onClick={runSecurityTests}
            disabled={loading}
            className="bg-accent-blue hover:bg-accent-blue/80 disabled:opacity-50 text-white px-6 py-2 rounded-lg font-medium transition-colors"
          >
            {loading ? 'Running...' : 'Run Tests'}
          </button>
        </div>
      </div>

      {/* Security Score */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-dark-card rounded-xl border border-dark-border p-6 col-span-2">
            <div className="text-sm text-slate-400 mb-1">Overall Security Score</div>
            <div className="flex items-end gap-4">
              <div className="text-5xl font-bold text-white">{summary.security_score.toFixed(0)}</div>
              <div className="text-slate-400 mb-2">/ 100</div>
            </div>
            <div className="mt-2 h-2 bg-dark-bg rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400"
                style={{ width: `${summary.security_score}%` }}
              />
            </div>
          </div>
          <div className="bg-dark-card rounded-xl border border-dark-border p-6">
            <div className="text-sm text-slate-400 mb-1">Detection Rate</div>
            <div className="text-3xl font-bold text-emerald-400">{(summary.avg_detection_rate * 100).toFixed(1)}%</div>
          </div>
          <div className="bg-dark-card rounded-xl border border-dark-border p-6">
            <div className="text-sm text-slate-400 mb-1">Block Rate</div>
            <div className="text-3xl font-bold text-emerald-400">{(summary.avg_block_rate * 100).toFixed(1)}%</div>
          </div>
        </div>
      )}

      {/* Attack Results Chart */}
      {attackData.length > 0 && (
        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Detection & Block Rates by Attack Type</h2>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={attackData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="name" stroke="#9CA3AF" angle={-45} textAnchor="end" height={80} />
                <YAxis stroke="#9CA3AF" />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                  labelStyle={{ color: '#fff' }}
                />
                <Legend />
                <Bar dataKey="detection_rate" name="Detection Rate %" fill="#3B82F6" />
                <Bar dataKey="block_rate" name="Block Rate %" fill="#10B981" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Attack Type Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {testTypes.filter(t => t.id !== 'all').map((testType) => {
          const result = results && results[testType.id]
          return (
            <div key={testType.id} className="bg-dark-card rounded-xl border border-dark-border p-6">
              <div className="flex items-center gap-3 mb-4">
                <span className="text-2xl">{testType.icon}</span>
                <h3 className="text-lg font-semibold text-white">{testType.name}</h3>
              </div>
              {result ? (
                <div className="space-y-3">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Detection Rate</span>
                    <span className="text-emerald-400 font-semibold">{(result.detection_rate * 100).toFixed(1)}%</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Block Rate</span>
                    <span className="text-emerald-400 font-semibold">{(result.block_rate * 100).toFixed(1)}%</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Total Attempts</span>
                    <span className="text-white">{result.total_attempts}</span>
                  </div>
                  <div className="pt-3 border-t border-dark-border">
                    <div className="text-xs text-slate-400 mb-2">Recommendations:</div>
                    <ul className="text-xs text-slate-300 space-y-1">
                      {result.recommendations.slice(0, 2).map((rec, i) => (
                        <li key={i} className="flex items-start gap-1">
                          <span className="text-emerald-400">•</span>
                          {rec}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : (
                <div className="text-slate-500 text-sm">No test results yet</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default SecurityTesting
