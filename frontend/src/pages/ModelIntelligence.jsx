import React, { useCallback, useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

const COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899']
const STATUS_COLORS = {
  production: '#10B981',
  staging: '#F59E0B',
  development: '#3B82F6',
  archived: '#6B7280',
  rejected: '#EF4444',
}

const formatPercent = (value, digits = 1) => {
  if (value == null || Number.isNaN(Number(value))) return 'N/A'
  return `${(Number(value) * 100).toFixed(digits)}%`
}

const formatNumber = value => {
  if (value == null || Number.isNaN(Number(value))) return '0'
  return Number(value).toLocaleString()
}

const formatDuration = seconds => {
  if (seconds == null || Number.isNaN(Number(seconds))) return 'N/A'
  if (seconds < 60) return `${Number(seconds).toFixed(1)}s`
  const minutes = Math.floor(Number(seconds) / 60)
  const remaining = Math.round(Number(seconds) % 60)
  return `${minutes}m ${remaining}s`
}

const formatVersion = version => {
  if (version == null || version === '') return 'N/A'
  const label = String(version)
  return label.toLowerCase().startsWith('v') ? label : `v${label}`
}

const formatTimestamp = value => {
  if (!value) return 'N/A'
  return new Date(value).toLocaleString()
}

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
    if (!autoRefresh) return undefined
    const interval = setInterval(fetchDashboard, 10000)
    return () => clearInterval(interval)
  }, [autoRefresh, fetchDashboard])

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
  const trainingHistory = data?.training_history || []
  const accuracyTrend = data?.accuracy_trend || []
  const perKeyMetrics = data?.per_key_metrics || []
  const retrainHistory = data?.retraining_history || []
  const riverOnline = data?.river_online || {}
  const driftStatus = data?.drift_status || {}
  const recentPredictionLogs = data?.recent_prediction_logs || []
  const trainingPaths = data?.training_paths || {}
  const latestVersion = summary.latest_version
  const activeVersion = summary.active_version
  const selectedVersionData = versions.find(item => item.version_id === selectedVersion) || null

  const trendData = accuracyTrend.map(item => ({
    version: formatVersion(item.version),
    status: item.status,
    accuracy: item.accuracy != null ? +(Number(item.accuracy) * 100).toFixed(2) : null,
    top10: item.top_10_accuracy != null ? +(Number(item.top_10_accuracy) * 100).toFixed(2) : null,
  }))

  const trainingChartData = trainingHistory
    .slice(0, 12)
    .reverse()
    .map(item => ({
      version: formatVersion(item.version_number),
      samples: Number(item.samples_count || 0),
      accuracy: item.accuracy_after != null ? +(Number(item.accuracy_after) * 100).toFixed(2) : null,
    }))

  const perKeyChartData = perKeyMetrics
    .slice(0, 8)
    .map(metric => ({
      key: metric.key?.length > 18 ? `${metric.key.slice(0, 18)}...` : metric.key,
      accuracy: metric.accuracy != null ? +(Number(metric.accuracy) * 100).toFixed(1) : 0,
      drift: metric.drift_score != null ? +(Number(metric.drift_score) * 100).toFixed(1) : 0,
    }))

  const statusCounts = {}
  versions.forEach(version => {
    const status = String(version.status || 'unknown').toLowerCase()
    statusCounts[status] = (statusCounts[status] || 0) + 1
  })
  const statusData = Object.entries(statusCounts).map(([name, value]) => ({ name, value }))

  const predictorDrift = driftStatus.predictor || {}
  const trainerDrift = driftStatus.trainer || {}
  const perKeyDrift = driftStatus.per_key || {}
  const onlineTraining = trainingPaths.online_training || {}
  const fullTraining = trainingPaths.full_training || {}

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Model Intelligence Dashboard</h1>
          <p className="text-slate-400">
            Full version registry, training history, River online learning, drift status, and live prediction logs.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-400">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={event => setAutoRefresh(event.target.checked)}
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
        <div className="bg-red-900/30 border border-red-500/50 rounded-xl p-4 text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-4">
        <SummaryCard
          label="Total Versions"
          value={formatNumber(summary.total_versions)}
          sub={`${formatNumber(summary.accepted_versions)} accepted / ${formatNumber(summary.rejected_versions)} rejected`}
          color="text-accent-blue"
        />
        <SummaryCard
          label="Active Version"
          value={activeVersion ? formatVersion(activeVersion.version_number) : 'N/A'}
          sub={activeVersion?.status || 'No production row'}
          statusColor={STATUS_COLORS[String(activeVersion?.status || '').toLowerCase()]}
        />
        <SummaryCard
          label="Latest Version"
          value={latestVersion ? formatVersion(latestVersion.version_number) : 'N/A'}
          sub={latestVersion?.runtime_version || latestVersion?.status || 'N/A'}
        />
        <SummaryCard
          label="Overall Accuracy"
          value={formatPercent(summary.overall_accuracy)}
          color={(summary.overall_accuracy || 0) >= 0.6 ? 'text-emerald-400' : 'text-amber-400'}
        />
        <SummaryCard
          label="Prediction Logs"
          value={formatNumber(summary.total_predictions)}
          sub={`${recentPredictionLogs.length} recent logs loaded`}
          color="text-purple-400"
        />
        <SummaryCard
          label="River Online"
          value={riverOnline.initialized ? `${formatNumber(riverOnline.learn_count)} updates` : 'Offline'}
          sub={riverOnline.model_type || 'adaptive_forest'}
          color={riverOnline.initialized ? 'text-emerald-400' : 'text-slate-500'}
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Training Paths</h2>
          <div className="space-y-4">
            <PathCard
              label="Scheduled / Manual"
              badge="Full Retrain"
              badgeClass="bg-accent-blue/20 text-accent-blue"
              body="Creates a persisted model version, writes version metadata to the database, and becomes the source for model lifecycle history."
              stats={[
                `Runs recorded: ${formatNumber(fullTraining.runs_total)}`,
                `Latest run: ${formatTimestamp(fullTraining.latest_run?.training_end_time || fullTraining.latest_run?.training_start_time)}`,
                `Latest samples: ${formatNumber(fullTraining.latest_run?.samples_count)}`,
              ]}
            />
            <PathCard
              label="Drift-Triggered Online"
              badge="River partial_fit"
              badgeClass="bg-emerald-500/20 text-emerald-400"
              body="Uses River incremental learning in-place so simulation traffic can adapt the runtime model without creating a new persisted model version."
              stats={[
                `Initialized: ${onlineTraining.initialized ? 'Yes' : 'No'}`,
                `Online updates: ${formatNumber(onlineTraining.online_learning_count)}`,
                `Last update: ${formatTimestamp(onlineTraining.last_online_learning)}`,
              ]}
            />
          </div>
        </div>

        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Drift Status</h2>
          <div className="grid grid-cols-2 gap-3">
            <DetailCard
              label="Predictor Drift Score"
              value={predictorDrift.drift_score != null ? Number(predictorDrift.drift_score).toFixed(4) : 'N/A'}
              color={(predictorDrift.drift_score || 0) >= 0.3 ? 'text-amber-400' : 'text-white'}
            />
            <DetailCard
              label="Tracked Outcomes"
              value={formatNumber(predictorDrift.outcome_count)}
            />
            <DetailCard
              label="Trainer Drift Count"
              value={formatNumber(trainerDrift.drift_count)}
            />
            <DetailCard
              label="Keys With Drift"
              value={formatNumber(perKeyDrift.keys_with_drift)}
              color={(perKeyDrift.keys_with_drift || 0) > 0 ? 'text-amber-400' : 'text-white'}
            />
            <DetailCard
              label="Avg Per-Key Drift"
              value={perKeyDrift.avg_drift_score != null ? Number(perKeyDrift.avg_drift_score).toFixed(4) : '0.0000'}
            />
            <DetailCard
              label="Max Per-Key Drift"
              value={perKeyDrift.max_drift_score != null ? Number(perKeyDrift.max_drift_score).toFixed(4) : '0.0000'}
            />
          </div>
          <div className="mt-4 text-xs text-slate-500 space-y-1">
            <div>Predictor ensemble uses live outcome feedback.</div>
            <div>Trainer drift status reflects runtime cache hit/miss monitoring.</div>
          </div>
        </div>

        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Version Status Mix</h2>
          {statusData.length > 0 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={statusData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={55}
                    outerRadius={85}
                    paddingAngle={3}
                  >
                    {statusData.map((entry, index) => (
                      <Cell
                        key={entry.name}
                        fill={STATUS_COLORS[entry.name] || COLORS[index % COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-slate-500">
              No model versions recorded yet.
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Accuracy Trend by Version</h2>
          {trendData.length > 0 ? (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="version" stroke="#9CA3AF" fontSize={11} />
                  <YAxis stroke="#9CA3AF" domain={[0, 100]} unit="%" fontSize={11} />
                  <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} />
                  <Legend />
                  <Line type="monotone" dataKey="accuracy" stroke="#3B82F6" strokeWidth={2} name="Top-1 Accuracy" />
                  <Line type="monotone" dataKey="top10" stroke="#10B981" strokeWidth={2} name="Top-10 Accuracy" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState label="No accuracy trend available yet." />
          )}
        </div>

        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Training Volume and Outcome</h2>
          {trainingChartData.length > 0 ? (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={trainingChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="version" stroke="#9CA3AF" fontSize={11} />
                  <YAxis yAxisId="left" stroke="#9CA3AF" fontSize={11} />
                  <YAxis yAxisId="right" orientation="right" stroke="#9CA3AF" fontSize={11} unit="%" />
                  <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} />
                  <Legend />
                  <Bar yAxisId="left" dataKey="samples" fill="#8B5CF6" name="Samples" radius={[4, 4, 0, 0]} />
                  <Line yAxisId="right" type="monotone" dataKey="accuracy" stroke="#10B981" strokeWidth={2} name="Accuracy %" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState label="No full training history recorded yet." />
          )}
        </div>
      </div>

      <div className="bg-dark-card rounded-xl border border-dark-border p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Model Versions</h2>
          <div className="text-xs text-slate-500">
            Click a row to inspect metrics, runtime label, and training metadata.
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-400 border-b border-dark-border">
                <th className="pb-3 pr-4">Version</th>
                <th className="pb-3 pr-4">Status</th>
                <th className="pb-3 pr-4">Runtime Label</th>
                <th className="pb-3 pr-4">Top-1</th>
                <th className="pb-3 pr-4">Top-10</th>
                <th className="pb-3 pr-4">Training Samples</th>
                <th className="pb-3 pr-4">Prediction Accuracy</th>
                <th className="pb-3 pr-4">Created</th>
              </tr>
            </thead>
            <tbody>
              {versions.map(version => {
                const acc = version.metrics?.accuracy ?? version.metrics?.val_accuracy
                const top10 = version.metrics?.top_10_accuracy ?? version.metrics?.val_top_10_accuracy
                const status = String(version.status || '').toLowerCase()
                return (
                  <tr
                    key={version.version_id}
                    className={`border-b border-dark-border/50 cursor-pointer hover:bg-dark-bg/50 transition-colors ${
                      selectedVersion === version.version_id ? 'bg-accent-blue/10' : ''
                    }`}
                    onClick={() => setSelectedVersion(selectedVersion === version.version_id ? null : version.version_id)}
                  >
                    <td className="py-3 pr-4">
                      <div className="text-white font-medium">{formatVersion(version.version_number)}</div>
                      <div className="text-xs text-slate-500">#{version.version_id}</div>
                    </td>
                    <td className="py-3 pr-4">
                      <StatusPill status={status} />
                    </td>
                    <td className="py-3 pr-4 text-slate-300">{version.runtime_version || 'N/A'}</td>
                    <td className="py-3 pr-4 text-white">{formatPercent(acc)}</td>
                    <td className="py-3 pr-4 text-white">{formatPercent(top10)}</td>
                    <td className="py-3 pr-4 text-slate-300">{formatNumber(version.training?.samples_count)}</td>
                    <td className="py-3 pr-4 text-slate-300">
                      {formatPercent(version.predictions?.accuracy)}
                      <span className="text-xs text-slate-500 ml-2">
                        {formatNumber(version.predictions?.correct)} / {formatNumber(version.predictions?.total)}
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-slate-400 text-xs">{formatTimestamp(version.created_at)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {selectedVersionData && (
          <div className="mt-4 bg-dark-bg rounded-lg border border-dark-border/60 p-4 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-white font-medium">
                {formatVersion(selectedVersionData.version_number)} detail
              </h3>
              <StatusPill status={String(selectedVersionData.status || '').toLowerCase()} />
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <DetailCard label="Runtime Version" value={selectedVersionData.runtime_version || 'N/A'} />
              <DetailCard label="Created" value={formatTimestamp(selectedVersionData.created_at)} />
              <DetailCard label="Train Duration" value={formatDuration(selectedVersionData.training?.duration_seconds)} />
              <DetailCard label="Predictions Logged" value={formatNumber(selectedVersionData.predictions?.total)} />
            </div>
            <div>
              <div className="text-sm text-slate-400 mb-2">Metrics</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {Object.entries(selectedVersionData.metrics || {}).map(([name, value]) => (
                  <DetailCard
                    key={name}
                    label={name}
                    value={typeof value === 'number' && value <= 1 ? formatPercent(value, 2) : String(value)}
                  />
                ))}
              </div>
            </div>
            {selectedVersionData.metrics_json && (
              <div>
                <div className="text-sm text-slate-400 mb-2">Decision Metadata</div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <DetailCard label="Accepted" value={String(selectedVersionData.metrics_json.accepted ?? 'N/A')} />
                  <DetailCard label="Reason" value={selectedVersionData.metrics_json.reason || 'N/A'} />
                  <DetailCard label="Decision" value={selectedVersionData.metrics_json.decision_reason || 'N/A'} />
                  <DetailCard label="Runtime Label" value={selectedVersionData.metrics_json.runtime_version || 'N/A'} />
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Training History</h2>
          {trainingHistory.length > 0 ? (
            <div className="max-h-96 overflow-y-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-400 border-b border-dark-border">
                    <th className="pb-3 pr-4">Version</th>
                    <th className="pb-3 pr-4">Status</th>
                    <th className="pb-3 pr-4">Samples</th>
                    <th className="pb-3 pr-4">Accuracy</th>
                    <th className="pb-3 pr-4">Duration</th>
                    <th className="pb-3 pr-4">Ended</th>
                  </tr>
                </thead>
                <tbody>
                  {trainingHistory.map(item => (
                    <tr key={item.id} className="border-b border-dark-border/40">
                      <td className="py-3 pr-4 text-white">{formatVersion(item.version_number)}</td>
                      <td className="py-3 pr-4"><StatusPill status={String(item.status || '').toLowerCase()} /></td>
                      <td className="py-3 pr-4 text-slate-300">{formatNumber(item.samples_count)}</td>
                      <td className="py-3 pr-4 text-slate-300">
                        {formatPercent(item.accuracy_before)}
                        <span className="text-slate-500 mx-1">-&gt;</span>
                        {formatPercent(item.accuracy_after)}
                      </td>
                      <td className="py-3 pr-4 text-slate-300">{formatDuration(item.duration_seconds)}</td>
                      <td className="py-3 pr-4 text-slate-400 text-xs">{formatTimestamp(item.training_end_time)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState label="No training history found in TrainingMetadata." />
          )}
        </div>

        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">River Online Learning</h2>
          <div className="grid grid-cols-2 gap-3">
            <DetailCard label="Initialized" value={riverOnline.initialized ? 'Yes' : 'No'} color={riverOnline.initialized ? 'text-emerald-400' : 'text-slate-500'} />
            <DetailCard label="Model Type" value={riverOnline.model_type || 'N/A'} />
            <DetailCard label="Samples Processed" value={formatNumber(riverOnline.sample_count)} />
            <DetailCard label="Learn Count" value={formatNumber(riverOnline.learn_count)} />
            <DetailCard label="Recent Predictions" value={formatNumber(riverOnline.recent_predictions_count)} />
            <DetailCard label="Last Online Update" value={formatTimestamp(onlineTraining.last_online_learning)} />
          </div>
          <div className="mt-4 bg-dark-bg rounded-lg p-4 border border-dark-border/50">
            <div className="text-sm text-slate-400 mb-2">Last Online Learning Result</div>
            <pre className="text-xs text-slate-300 whitespace-pre-wrap break-words">
              {JSON.stringify(onlineTraining.last_online_learning_result || riverOnline.last_online_learning_result || {}, null, 2)}
            </pre>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Per-Key Performance Snapshot</h2>
          {perKeyChartData.length > 0 ? (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={perKeyChartData} layout="vertical" margin={{ left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis type="number" domain={[0, 100]} unit="%" stroke="#9CA3AF" fontSize={11} />
                  <YAxis type="category" dataKey="key" stroke="#9CA3AF" fontSize={11} width={140} />
                  <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} />
                  <Legend />
                  <Bar dataKey="accuracy" fill="#3B82F6" name="Accuracy %" barSize={12} />
                  <Bar dataKey="drift" fill="#F59E0B" name="Drift %" barSize={12} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState label="No per-key metrics available for the latest version." />
          )}
        </div>

        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Retraining History</h2>
          {retrainHistory.length > 0 ? (
            <div className="space-y-3 max-h-72 overflow-y-auto">
              {retrainHistory.map(item => (
                <div key={item.id} className="bg-dark-bg rounded-lg p-3 flex items-center justify-between">
                  <div>
                    <div className="text-white font-medium">{item.status || 'unknown'}</div>
                    <div className="text-xs text-slate-500 mt-1">
                      Drift {item.drift_score?.toFixed(4)} · {formatNumber(item.event_count)} events
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm text-slate-300">
                        {formatPercent(item.accuracy_before)} -&gt; {formatPercent(item.accuracy_after)}
                    </div>
                    <div className={`text-xs ${(item.improvement || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {(item.improvement || 0).toFixed(2)}%
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState label="No retraining history recorded yet." />
          )}
        </div>
      </div>

      <div className="bg-dark-card rounded-xl border border-dark-border p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Recent Prediction Logs</h2>
        {recentPredictionLogs.length > 0 ? (
          <div className="overflow-x-auto max-h-[28rem]">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-400 border-b border-dark-border">
                  <th className="pb-3 pr-4">Time</th>
                  <th className="pb-3 pr-4">Version</th>
                  <th className="pb-3 pr-4">Key</th>
                  <th className="pb-3 pr-4">Predicted</th>
                  <th className="pb-3 pr-4">Actual</th>
                  <th className="pb-3 pr-4">Correct</th>
                  <th className="pb-3 pr-4">Confidence</th>
                  <th className="pb-3 pr-4">Latency</th>
                </tr>
              </thead>
              <tbody>
                {recentPredictionLogs.map(log => (
                  <tr key={log.id} className="border-b border-dark-border/40">
                    <td className="py-3 pr-4 text-slate-400 text-xs">{formatTimestamp(log.timestamp)}</td>
                    <td className="py-3 pr-4 text-slate-300">{formatVersion(log.version_number)}</td>
                    <td className="py-3 pr-4 text-white">{log.key}</td>
                    <td className="py-3 pr-4 text-slate-300">{log.predicted_value || 'N/A'}</td>
                    <td className="py-3 pr-4 text-slate-300">{log.actual_value || 'N/A'}</td>
                    <td className="py-3 pr-4">
                      <span className={`text-xs px-2 py-1 rounded ${
                        log.is_correct === true
                          ? 'bg-emerald-500/20 text-emerald-400'
                          : log.is_correct === false
                            ? 'bg-red-500/20 text-red-400'
                            : 'bg-slate-500/20 text-slate-300'
                      }`}>
                        {log.is_correct === true ? 'Correct' : log.is_correct === false ? 'Wrong' : 'Pending'}
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-slate-300">
                      {log.confidence != null ? formatPercent(log.confidence, 2) : 'N/A'}
                    </td>
                    <td className="py-3 pr-4 text-slate-300">
                      {log.latency_ms != null ? `${Number(log.latency_ms).toFixed(2)} ms` : 'N/A'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState label="No prediction logs recorded yet. Runtime prediction traces will appear here after requests flow through the predictor." />
        )}
      </div>
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
  <div className="bg-dark-bg rounded-lg p-3 border border-dark-border/50">
    <div className="text-xs text-slate-400 mb-1">{label}</div>
    <div className={`text-sm font-semibold ${color}`}>{value}</div>
  </div>
)

const StatusPill = ({ status }) => (
  <span
    className="text-xs px-2 py-1 rounded font-medium"
    style={{
      backgroundColor: `${STATUS_COLORS[status] || '#64748B'}20`,
      color: STATUS_COLORS[status] || '#CBD5E1',
    }}
  >
    {status || 'unknown'}
  </span>
)

const EmptyState = ({ label }) => (
  <div className="h-48 flex items-center justify-center text-slate-500">
    {label}
  </div>
)

const PathCard = ({ label, badge, badgeClass, body, stats }) => (
  <div className="bg-dark-bg rounded-lg p-4 border border-dark-border/50">
    <div className="flex items-center justify-between mb-2">
      <span className="text-white font-medium">{label}</span>
      <span className={`text-xs px-2 py-1 rounded ${badgeClass}`}>{badge}</span>
    </div>
    <p className="text-sm text-slate-400">{body}</p>
    <div className="mt-3 space-y-1 text-xs text-slate-500">
      {stats.map(item => (
        <div key={item}>{item}</div>
      ))}
    </div>
  </div>
)

export default ModelIntelligence
