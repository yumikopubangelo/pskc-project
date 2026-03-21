import React, { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  Legend,
} from 'recharts'
import Icon from '../components/Icon'
import { apiClient } from '../utils/apiClient'

function EmptyChartState({ title, description }) {
  return (
    <div className="h-64 rounded-xl border border-dashed border-dark-border bg-dark-bg/40 flex items-center justify-center text-center px-6">
      <div>
        <div className="text-white font-semibold mb-2">{title}</div>
        <div className="text-sm text-slate-400">{description}</div>
      </div>
    </div>
  )
}

function DashboardPage() {
  const backendOnly = { allowMockFallback: false }
  const [timeRange, setTimeRange] = useState('24h')
  const [metrics, setMetrics] = useState({
    cacheHitRate: 0,
    avgLatency: 0,
    totalRequests: 0,
    activeKeys: 0,
    keysCached: 0,
    cacheHits: 0,
    cacheMisses: 0,
    modelLoaded: false,
    mlSampleCount: 0,
    modelStatus: 'not_trained',
    modelAccuracy: 0,
    modelTop10Accuracy: 0,
    modelVersion: 'N/A',
    lastTrainingOutcome: 'unknown',
  })
  const [latencyData, setLatencyData] = useState([])
  const [cacheDistribution, setCacheDistribution] = useState([])
  const [accuracyData, setAccuracyData] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const [metricsData, cacheStats, latency, cache, accuracy, modelStatus] = await Promise.all([
          apiClient.getMetrics(backendOnly),
          apiClient.getCacheStats(backendOnly),
          apiClient.getLatencyChartData(backendOnly),
          apiClient.getCacheDistributionData(backendOnly),
          apiClient.getAccuracyChartData(backendOnly),
          apiClient.getModelStatus(backendOnly),
        ])

        setMetrics({
          cacheHitRate: (metricsData.cache_hit_rate || 0) * 100,
          avgLatency: metricsData.avg_latency_ms || 0,
          totalRequests: metricsData.total_requests || 0,
          activeKeys: metricsData.active_keys || 0,
          keysCached: cacheStats.size || 0,
          cacheHits: metricsData.cache_hits || 0,
          cacheMisses: metricsData.cache_misses || 0,
          modelLoaded: modelStatus.status_code === 'trained',
          mlSampleCount: modelStatus.sample_count || 0,
          modelStatus: modelStatus.status_code || 'unknown',
          modelAccuracy: (modelStatus.model_accuracy || 0) * 100,
          modelTop10Accuracy: (modelStatus.model_top_10_accuracy || 0) * 100,
          modelVersion: modelStatus.model_version || 'N/A',
          lastTrainingOutcome: modelStatus?.last_training_attempt?.accepted ? 'accepted' : 'retained',
        })

        setLatencyData(Array.isArray(latency.data) ? latency.data : [])
        setCacheDistribution(Array.isArray(cache.data) ? cache.data : [])
        setAccuracyData(Array.isArray(accuracy.data) ? accuracy.data : [])
        setError(null)
      } catch (err) {
        console.error('Failed to fetch metrics:', err)
        setError('Failed to connect to backend')
        setMetrics({
          cacheHitRate: 0,
          avgLatency: 0,
          totalRequests: 0,
          activeKeys: 0,
          keysCached: 0,
          cacheHits: 0,
          cacheMisses: 0,
          modelLoaded: false,
          mlSampleCount: 0,
          modelStatus: 'unavailable',
          modelAccuracy: 0,
          modelTop10Accuracy: 0,
          modelVersion: 'N/A',
          lastTrainingOutcome: 'unknown',
        })
        setLatencyData([])
        setCacheDistribution([])
        setAccuracyData([])
      } finally {
        setLoading(false)
      }
    }

    fetchMetrics()
    const interval = setInterval(fetchMetrics, 5000)
    return () => clearInterval(interval)
  }, [])

  const metricCards = [
    {
      title: 'Cache Hit Rate',
      value: `${metrics.cacheHitRate.toFixed(1)}%`,
      icon: 'target',
      valueClass: 'text-accent-green',
      helper: metrics.totalRequests > 0 ? `${metrics.cacheHits} hit / ${metrics.cacheMisses} miss` : 'No request data yet',
    },
    {
      title: 'Avg Latency',
      value: `${Math.round(metrics.avgLatency)}ms`,
      icon: 'lightning',
      valueClass: 'text-accent-blue',
      helper: metrics.totalRequests > 0 ? 'Observed request latency' : 'No latency samples yet',
    },
    {
      title: 'Total Requests',
      value: metrics.totalRequests.toLocaleString(),
      icon: 'activity',
      valueClass: 'text-accent-blue',
      helper: 'Recorded by backend metrics endpoint',
    },
    {
      title: 'Keys Cached',
      value: metrics.keysCached.toLocaleString(),
      icon: 'lock',
      valueClass: 'text-warning-orange',
      helper: 'Current active keys in cache',
    },
  ]

  const modelStatusLabel = metrics.modelLoaded
    ? 'Loaded'
    : metrics.modelStatus === 'artifact_present'
    ? 'Artifact present'
    : metrics.modelStatus === 'collecting_data'
    ? 'Collecting data'
    : metrics.modelStatus === 'ready_for_training'
    ? 'Ready for training'
    : metrics.modelStatus === 'not_trained'
    ? 'Not trained'
    : metrics.modelStatus.replace(/_/g, ' ')

  const connectionLabel = error ? 'Backend unavailable' : loading ? 'Loading' : 'Connected'
  const connectionDotClass = error ? 'bg-danger-red' : 'bg-accent-green animate-pulse'
  const accuracyValues = accuracyData.flatMap((item) => [item.accuracy, item.top_10_accuracy]).filter((value) => typeof value === 'number')
  const accuracyDomain = accuracyValues.length > 0
    ? [Math.max(0, Math.floor(Math.min(...accuracyValues) - 5)), Math.min(100, Math.ceil(Math.max(...accuracyValues) + 5))]
    : [0, 100]
  const modelVersionLabel = metrics.modelVersion && metrics.modelVersion !== 'N/A' ? metrics.modelVersion : 'N/A'

  return (
    <div className="min-h-screen py-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-8"
        >
          <div>
            <h1 className="text-3xl md:text-4xl font-display font-bold text-white mb-2">Dashboard</h1>
            <p className="text-slate-400">Backend metrics only. No dummy fallback is rendered on this page.</p>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 bg-dark-card rounded-lg p-1 border border-dark-border">
              {['1h', '6h', '24h', '7d'].map((range) => (
                <button
                  key={range}
                  type="button"
                  onClick={() => setTimeRange(range)}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    timeRange === range ? 'bg-accent-blue text-white' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  {range}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${connectionDotClass}`} />
              <span className="text-sm text-slate-400">{connectionLabel}</span>
            </div>
          </div>
        </motion.div>

        {error ? (
          <div className="mb-6 rounded-xl border border-danger-red/40 bg-danger-red/10 px-4 py-3 text-sm text-slate-200">
            {error}. Dashboard menampilkan state kosong sampai backend bisa menyediakan data nyata.
          </div>
        ) : null}

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.1 }}
          className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8"
        >
          {metricCards.map((metric, index) => (
            <motion.div
              key={metric.title}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 + index * 0.1 }}
              className="metric-card"
            >
              <div className="flex items-center justify-between mb-3">
                <span className="w-9 h-9 rounded-lg bg-dark-bg/70 border border-dark-border flex items-center justify-center text-slate-200">
                  <Icon name={metric.icon} className="w-4 h-4" />
                </span>
                <span className="text-xs font-mono px-2 py-1 rounded bg-dark-bg/70 text-slate-400">
                  {loading ? 'Loading' : 'Real'}
                </span>
              </div>
              <div className={`text-3xl font-bold mb-1 ${metric.valueClass}`}>{metric.value}</div>
              <div className="text-slate-400 text-sm">{metric.title}</div>
              <div className="text-xs text-slate-500 mt-2">{metric.helper}</div>
            </motion.div>
          ))}
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
          className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8"
        >
          <div className="gradient-card rounded-lg p-4 border border-dark-border">
            <div className="text-slate-400 text-sm mb-1">Total Requests</div>
            <div className="text-xl font-bold text-white font-mono">{metrics.totalRequests.toLocaleString()}</div>
          </div>
          <div className="gradient-card rounded-lg p-4 border border-dark-border">
            <div className="text-slate-400 text-sm mb-1">Active Keys</div>
            <div className="text-xl font-bold text-white font-mono">{metrics.activeKeys}</div>
          </div>
          <div className="gradient-card rounded-lg p-4 border border-dark-border">
            <div className="text-slate-400 text-sm mb-1">Cache Hits</div>
            <div className="text-xl font-bold text-white font-mono">{metrics.cacheHits}</div>
          </div>
          <div className="gradient-card rounded-lg p-4 border border-dark-border">
            <div className="text-slate-400 text-sm mb-1">Model Status</div>
            <div className="text-xl font-bold text-white font-mono">{modelStatusLabel}</div>
            <div className="text-xs text-slate-500 mt-1">
              {modelVersionLabel} · Top-1 {metrics.modelAccuracy.toFixed(1)}% · Top-10 {metrics.modelTop10Accuracy.toFixed(1)}%
            </div>
          </div>
        </motion.div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.3 }}
            className="gradient-card rounded-xl border border-dark-border p-6"
          >
            <h3 className="text-lg font-semibold text-white mb-4">Latency Comparison</h3>
            {latencyData.length > 0 ? (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={latencyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" stroke="#94a3b8" fontSize={12} />
                    <YAxis stroke="#94a3b8" fontSize={12} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: '8px',
                      }}
                    />
                    <Legend />
                    <Bar dataKey="withoutPSKC" name="Without PSKC" fill="#dc2626" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="withPSKC" name="With PSKC" fill="#059669" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyChartState
                title="Belum ada data latency comparison"
                description="Backend belum memiliki dataset perbandingan runtime without vs with PSKC yang valid."
              />
            )}
          </motion.div>

          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.4 }}
            className="gradient-card rounded-xl border border-dark-border p-6"
          >
            <h3 className="text-lg font-semibold text-white mb-4">Cache Distribution</h3>
            {cacheDistribution.length > 0 ? (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={cacheDistribution}
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={90}
                      paddingAngle={5}
                      dataKey="value"
                    >
                      {cacheDistribution.map((entry) => (
                        <Cell key={entry.name} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: '8px',
                      }}
                    />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyChartState
                title="Belum ada data distribusi cache"
                description="Chart ini akan muncul setelah backend mencatat request cache hit atau miss nyata."
              />
            )}
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          className="gradient-card rounded-xl border border-dark-border p-6"
        >
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-white">ML Accuracy Over Time</h3>
            <span className="text-sm text-slate-400">Persisted training history</span>
          </div>
          {accuracyData.length > 0 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={accuracyData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="time" stroke="#94a3b8" fontSize={12} />
                  <YAxis domain={accuracyDomain} stroke="#94a3b8" fontSize={12} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1e293b',
                      border: '1px solid #334155',
                      borderRadius: '8px',
                    }}
                    formatter={(value, name) => [`${Number(value).toFixed(1)}%`, name === 'accuracy' ? 'Top-1 Accuracy' : 'Top-10 Accuracy']}
                  />
                  <Line
                    type="monotone"
                    dataKey="accuracy"
                    stroke="#2563eb"
                    strokeWidth={3}
                    dot={{ fill: '#2563eb', strokeWidth: 2, r: 4 }}
                    activeDot={{ r: 6, fill: '#2563eb' }}
                    name="Top-1 Accuracy"
                  />
                  <Line
                    type="monotone"
                    dataKey="top_10_accuracy"
                    stroke="#22c55e"
                    strokeWidth={2}
                    dot={{ fill: '#22c55e', strokeWidth: 2, r: 3 }}
                    activeDot={{ r: 5, fill: '#22c55e' }}
                    name="Top-10 Accuracy"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyChartState
              title="Belum ada data akurasi ML"
              description="Sistem belum memiliki history training atau evaluasi model yang bisa divisualisasikan."
            />
          )}
        </motion.div>
      </div>
    </div>
  )
}

export default DashboardPage
