import React, { useState, useEffect, useCallback } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, BarChart, Bar, PieChart, Pie, Cell
} from 'recharts'

const COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899']
const STATUS_COLORS = { production: '#10B981', staging: '#F59E0B', dev: '#3B82F6', archived: '#6B7280' }

const ModelIntelligence = () => {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedVersion, setSelectedVersion] = useState(null)
  const [autoRefresh, setAutoRefresh] = useState(true)

  const fetchDashboard = useCallback(async () => {
    try {
      const res = await fetch('/api/models/intelligence/dashboard')
      const json = await res.json()
      setData(json)
      setError(json.error || null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDashboard()
    if (!autoRefresh) return
    const interval = setInterval(fetchDashboard, 10000)
    return () => clearInterval(interval)
  }, [fetchDashboard, autoRefresh])

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="animate-spin w-10 h-10 border-4 border-accent-blue border-t-transparent rounded-full mx-auto mb-4" />
          <p className="text-slate-400">Loading model intelligence...</p>
        </div>
      </div>
    )
  }

  const summary = data?.summary || {}
  const versions = data?.versions || []
  const accuracyTrend = data?.accuracy_trend || []
  const perKeyMetrics = data?.per_key_metrics || []
  const retrainHistory = data?.retraining_history || []
  const riverOnline = data?.river_online || {}
  const latestVersion = summary.latest_version

  // Prepare accuracy trend chart data
  const trendData = accuracyTrend.map(t => ({
    version: `v${t.version}`,
    'Top-1 Accuracy': t.accuracy != null ? +(t.accuracy * 100).toFixed(1) : null,
    'Top-10 Accuracy': t.top_10_accuracy != null ? +(t.top_10_accuracy * 100).toFixed(1) : null,
  }))

  // Per-key chart data
  const perKeyData = perKeyMetrics.map(pk => ({
    key: pk.key?.length > 12 ? pk.key.slice(0, 12) + '...' : pk.key,
    accuracy: pk.accuracy != null ? +(pk.accuracy * 100).toFixed(1) : 0,
    drift: pk.drift_score != null ? +(pk.drift_score * 100).toFixed(1) : 0,
    predictions: pk.total_predictions || 0,
  }))

  // Version status distribution for pie chart
  const statusCounts = {}
  versions.forEach(v => {
    statusCounts[v.status] = (statusCounts[v.status] || 0) + 1
  })
  const statusData = Object.entries(statusCounts).map(([name, value]) => ({ name, value }))

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Model Intelligence</h1>
          <p className="text-slate-400">Comprehensive model lifecycle, training, and performance dashboard</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-400">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={e => setAutoRefresh(e.target.checked)}
              className="rounded border-dark-border"
            />
            Auto-refresh
          </label>
          <button
            onClick={fetchDashboard}
            className="bg-dark-card border border-dark-border hover:border-accent-blue text-white px-4 py-2 rounded-lg text-sm transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-500/50 rounded-xl p-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <SummaryCard
          label="Total Versions"
          value={summary.total_versions || 0}
          color="text-accent-blue"
        />
        <SummaryCard
          label="Latest Version"
          value={latestVersion ? `v${latestVersion.version_number}` : 'N/A'}
          sub={latestVersion?.status}
          statusColor={STATUS_COLORS[latestVersion?.status]}
        />
        <SummaryCard
          label="Overall Accuracy"
          value={summary.overall_accuracy != null ? `${(summary.overall_accuracy * 100).toFixed(1)}%` : 'N/A'}
          color={summary.overall_accuracy >= 0.6 ? 'text-emerald-400' : 'text-amber-400'}
        />
        <SummaryCard
          label="Total Predictions"
          value={summary.total_predictions?.toLocaleString() || '0'}
          color="text-purple-400"
        />
        <SummaryCard
          label="River Online"
          value={riverOnline.initialized ? `${riverOnline.learn_count || 0} learned` : 'Offline'}
          sub={riverOnline.model_type || ''}
          color={riverOnline.initialized ? 'text-emerald-400' : 'text-slate-500'}
        />
      </div>

      {/* Two-column layout: Training Paths + Accuracy Trend */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Training Paths */}
        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Training Paths</h2>
          <div className="space-y-4">
            <div className="bg-dark-bg rounded-lg p-4 border-l-4 border-accent-blue">
              <div className="flex items-center justify-between mb-2">
                <span className="text-white font-medium">Scheduled Training</span>
                <span className="text-xs bg-accent-blue/20 text-accent-blue px-2 py-1 rounded">Full Retrain</span>
              </div>
              <p className="text-sm text-slate-400">
                Heavy batch training that creates new model versions.
                Uses all available data (7 days, up to 170K events).
                Produces versioned models persisted to database.
              </p>
              {latestVersion?.training && (
                <div className="mt-2 text-xs text-slate-500">
                  Last: {latestVersion.training.samples_count?.toLocaleString()} samples,{' '}
                  {latestVersion.training.duration_seconds
                    ? `${latestVersion.training.duration_seconds.toFixed(1)}s`
                    : 'unknown duration'}
                </div>
              )}
            </div>

            <div className="bg-dark-bg rounded-lg p-4 border-l-4 border-emerald-500">
              <div className="flex items-center justify-between mb-2">
                <span className="text-white font-medium">River Online Learning</span>
                <span className="text-xs bg-emerald-500/20 text-emerald-400 px-2 py-1 rounded">Incremental</span>
              </div>
              <p className="text-sm text-slate-400">
                Lightweight drift-triggered adaptation using River's Adaptive Forest.
                Processes recent events incrementally without blocking scheduled training.
                No version bump — adapts the running model in-place.
              </p>
              <div className="mt-2 flex gap-4 text-xs text-slate-500">
                <span>Samples learned: {riverOnline.learn_count || 0}</span>
                <span>Model: {riverOnline.model_type || 'N/A'}</span>
                <span>Status: {riverOnline.initialized ? 'Active' : 'Inactive'}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Accuracy Trend */}
        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Accuracy Trend Across Versions</h2>
          {trendData.length > 0 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="version" stroke="#9CA3AF" fontSize={12} />
                  <YAxis stroke="#9CA3AF" domain={[0, 100]} unit="%" fontSize={12} />
                  <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} />
                  <Legend />
                  <Line type="monotone" dataKey="Top-1 Accuracy" stroke="#3B82F6" strokeWidth={2} dot={{ r: 4 }} />
                  <Line type="monotone" dataKey="Top-10 Accuracy" stroke="#10B981" strokeWidth={2} dot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-slate-500">
              No accuracy data available yet. Train your model to see trends.
            </div>
          )}
        </div>
      </div>

      {/* Model Versions Table */}
      <div className="bg-dark-card rounded-xl border border-dark-border p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Model Versions</h2>
          <div className="flex gap-2">
            {statusData.map(s => (
              <span
                key={s.name}
                className="text-xs px-2 py-1 rounded"
                style={{ backgroundColor: STATUS_COLORS[s.name] + '20', color: STATUS_COLORS[s.name] }}
              >
                {s.name}: {s.value}
              </span>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-400 border-b border-dark-border">
                <th className="pb-3 pr-4">Version</th>
                <th className="pb-3 pr-4">Status</th>
                <th className="pb-3 pr-4">Accuracy</th>
                <th className="pb-3 pr-4">Top-10</th>
                <th className="pb-3 pr-4">Samples</th>
                <th className="pb-3 pr-4">Predictions</th>
                <th className="pb-3 pr-4">Created</th>
              </tr>
            </thead>
            <tbody>
              {versions.map(v => {
                const acc = v.metrics?.accuracy || v.metrics?.val_accuracy
                const top10 = v.metrics?.top_10_accuracy || v.metrics?.val_top_10_accuracy
                return (
                  <tr
                    key={v.version_id}
                    className={`border-b border-dark-border/50 cursor-pointer hover:bg-dark-bg/50 transition-colors ${
                      selectedVersion === v.version_id ? 'bg-accent-blue/10' : ''
                    }`}
                    onClick={() => setSelectedVersion(selectedVersion === v.version_id ? null : v.version_id)}
                  >
                    <td className="py-3 pr-4">
                      <span className="text-white font-medium">v{v.version_number}</span>
                      <span className="text-slate-500 text-xs ml-2">#{v.version_id}</span>
                    </td>
                    <td className="py-3 pr-4">
                      <span
                        className="text-xs px-2 py-1 rounded font-medium"
                        style={{ backgroundColor: STATUS_COLORS[v.status] + '20', color: STATUS_COLORS[v.status] }}
                      >
                        {v.status}
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-white">
                      {acc != null ? `${(acc * 100).toFixed(1)}%` : '-'}
                    </td>
                    <td className="py-3 pr-4 text-white">
                      {top10 != null ? `${(top10 * 100).toFixed(1)}%` : '-'}
                    </td>
                    <td className="py-3 pr-4 text-slate-300">
                      {v.training?.samples_count?.toLocaleString() || '-'}
                    </td>
                    <td className="py-3 pr-4 text-slate-300">
                      {v.predictions?.total?.toLocaleString() || '0'}
                      {v.predictions?.accuracy != null && (
                        <span className="text-xs text-slate-500 ml-1">
                          ({(v.predictions.accuracy * 100).toFixed(0)}%)
                        </span>
                      )}
                    </td>
                    <td className="py-3 pr-4 text-slate-400 text-xs">
                      {new Date(v.created_at).toLocaleString()}
                    </td>
                  </tr>
                )
              })}
              {versions.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-500">
                    No model versions found. Train your model to see versions here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Version Detail Panel */}
        {selectedVersion && (() => {
          const v = versions.find(x => x.version_id === selectedVersion)
          if (!v) return null
          return (
            <div className="mt-4 bg-dark-bg rounded-lg p-4 border border-dark-border/50">
              <h3 className="text-white font-medium mb-3">
                v{v.version_number} Detail
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                {Object.entries(v.metrics || {}).map(([name, value]) => (
                  <div key={name}>
                    <div className="text-slate-400 text-xs">{name}</div>
                    <div className="text-white font-medium">
                      {typeof value === 'number' ? (value < 1 ? `${(value * 100).toFixed(2)}%` : value.toFixed(4)) : value}
                    </div>
                  </div>
                ))}
              </div>
              {v.training && (
                <div className="mt-3 pt-3 border-t border-dark-border/50 text-sm">
                  <span className="text-slate-400">Training: </span>
                  <span className="text-white">
                    {v.training.samples_count?.toLocaleString()} samples |{' '}
                    {v.training.duration_seconds ? `${v.training.duration_seconds.toFixed(1)}s` : 'N/A'} |{' '}
                    Acc: {v.training.accuracy_before != null ? `${(v.training.accuracy_before * 100).toFixed(1)}%` : '?'}
                    {' \u2192 '}
                    {v.training.accuracy_after != null ? `${(v.training.accuracy_after * 100).toFixed(1)}%` : '?'}
                  </span>
                </div>
              )}
            </div>
          )
        })()}
      </div>

      {/* Bottom row: Per-Key Metrics + Retraining History */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Per-Key Accuracy */}
        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Per-Key Accuracy (Latest Version)</h2>
          {perKeyData.length > 0 ? (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={perKeyData} layout="vertical" margin={{ left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis type="number" domain={[0, 100]} unit="%" stroke="#9CA3AF" fontSize={11} />
                  <YAxis type="category" dataKey="key" stroke="#9CA3AF" fontSize={11} width={100} />
                  <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} />
                  <Legend />
                  <Bar dataKey="accuracy" fill="#3B82F6" name="Accuracy %" barSize={12} />
                  <Bar dataKey="drift" fill="#F59E0B" name="Drift %" barSize={12} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-72 flex items-center justify-center text-slate-500">
              No per-key metrics available.
            </div>
          )}
        </div>

        {/* Retraining History */}
        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Retraining History</h2>
          {retrainHistory.length > 0 ? (
            <div className="space-y-3 max-h-72 overflow-y-auto">
              {retrainHistory.map(r => (
                <div key={r.id} className="bg-dark-bg rounded-lg p-3 flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${
                        r.status === 'completed' ? 'bg-emerald-400' :
                        r.status === 'running' ? 'bg-amber-400 animate-pulse' :
                        r.status === 'failed' ? 'bg-red-400' : 'bg-slate-400'
                      }`} />
                      <span className="text-white text-sm font-medium">
                        Drift: {r.drift_score?.toFixed(3)}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500 mt-1">
                      {r.event_count} events | {new Date(r.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="text-right">
                    {r.accuracy_before != null && r.accuracy_after != null ? (
                      <div className="text-sm">
                        <span className="text-slate-400">{(r.accuracy_before * 100).toFixed(1)}%</span>
                        <span className="text-slate-500 mx-1">{'\u2192'}</span>
                        <span className={r.improvement > 0 ? 'text-emerald-400' : 'text-red-400'}>
                          {(r.accuracy_after * 100).toFixed(1)}%
                        </span>
                      </div>
                    ) : (
                      <span className="text-xs text-slate-500">{r.status}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="h-72 flex items-center justify-center text-slate-500">
              No retraining events recorded yet.
            </div>
          )}
        </div>
      </div>

      {/* River Online Learning Detail */}
      {riverOnline.initialized && (
        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">River Online Learning Status</h2>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <DetailCard label="Model Type" value={riverOnline.model_type || 'N/A'} />
            <DetailCard label="Samples Processed" value={riverOnline.sample_count?.toLocaleString() || '0'} />
            <DetailCard label="Drift Adaptations" value={riverOnline.learn_count?.toLocaleString() || '0'} />
            <DetailCard label="Recent Predictions" value={riverOnline.recent_predictions_count || 0} />
            <DetailCard label="Status" value={riverOnline.initialized ? 'Active' : 'Inactive'} color={riverOnline.initialized ? 'text-emerald-400' : 'text-red-400'} />
          </div>
        </div>
      )}
    </div>
  )
}

const SummaryCard = ({ label, value, sub, color = 'text-white', statusColor }) => (
  <div className="bg-dark-card rounded-xl border border-dark-border p-5">
    <div className="text-sm text-slate-400 mb-1">{label}</div>
    <div className={`text-2xl font-bold ${color}`}>{value}</div>
    {sub && (
      <div className="text-xs mt-1" style={{ color: statusColor || '#94A3B8' }}>
        {sub}
      </div>
    )}
  </div>
)

const DetailCard = ({ label, value, color = 'text-white' }) => (
  <div className="bg-dark-bg rounded-lg p-3">
    <div className="text-xs text-slate-400 mb-1">{label}</div>
    <div className={`text-lg font-semibold ${color}`}>{value}</div>
  </div>
)

export default ModelIntelligence
