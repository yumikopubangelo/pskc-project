import React, { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
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
import Icon from '../components/Icon'
import { apiClient } from '../utils/apiClient'

function EmptyChartState({ title, description }) {
  return (
    <div className="h-72 rounded-2xl border border-dashed border-dark-border bg-dark-bg/40 flex items-center justify-center px-6 text-center">
      <div>
        <div className="text-white font-semibold mb-2">{title}</div>
        <div className="text-sm text-slate-400">{description}</div>
      </div>
    </div>
  )
}

function StatusCard({ title, value, helper, icon, tone = 'text-white', pill }) {
  return (
    <div className="rounded-2xl border border-dark-border bg-dark-card/80 p-5 shadow-[0_20px_60px_rgba(0,0,0,0.18)]">
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-slate-400">{title}</div>
        <div className="w-10 h-10 rounded-xl border border-dark-border bg-dark-bg/70 flex items-center justify-center text-slate-200">
          <Icon name={icon} className="w-5 h-5" />
        </div>
      </div>
      <div className={`text-3xl font-bold ${tone}`}>{value}</div>
      {pill ? (
        <div className="mt-2 inline-flex items-center rounded-full border border-dark-border bg-dark-bg/80 px-2.5 py-1 text-xs text-slate-300">
          {pill}
        </div>
      ) : null}
      <div className="mt-3 text-xs text-slate-500 leading-5">{helper}</div>
    </div>
  )
}

function DetailRow({ label, value, valueClass = 'text-white' }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <span className="text-sm text-slate-400">{label}</span>
      <span className={`text-sm font-medium text-right ${valueClass}`}>{value}</span>
    </div>
  )
}

function DashboardPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [metrics, setMetrics] = useState({
    connected: false,
    cacheHitRate: 0,
    avgLatency: 0,
    totalRequests: 0,
    activeKeys: 0,
    keysCached: 0,
    cacheHits: 0,
    cacheMisses: 0,
    modelLoaded: false,
    modelStatus: 'unknown',
    modelVersion: 'N/A',
    modelStage: 'unknown',
    modelAccuracy: null,
    modelTop10Accuracy: null,
    validationSamples: null,
    confidence: 'low',
    prefetchAvailable: false,
    prefetchQueue: 0,
    prefetchRetry: 0,
    prefetchDlq: 0,
  })
  const [latencyData, setLatencyData] = useState([])
  const [cacheDistribution, setCacheDistribution] = useState([])
  const [accuracyData, setAccuracyData] = useState([])

  useEffect(() => {
    let active = true

    const fetchDashboard = async () => {
      try {
        const [health, metricsData, cacheStats, latency, cache, accuracy, modelStatus, prefetch] = await Promise.all([
          apiClient.getHealth(),
          apiClient.getMetrics(),
          apiClient.getCacheStats(),
          apiClient.getLatencyChartData(),
          apiClient.getCacheDistributionData(),
          apiClient.getAccuracyChartData(),
          apiClient.getModelStatus(),
          apiClient.getPrefetchMetrics(),
        ])

        if (!active) {
          return
        }

        setMetrics({
          connected: health.status === 'healthy',
          cacheHitRate: Number(metricsData.cache_hit_rate || 0) * 100,
          avgLatency: Number(metricsData.avg_latency_ms || 0),
          totalRequests: Number(metricsData.total_requests || 0),
          activeKeys: Number(metricsData.active_keys || 0),
          keysCached: Number(cacheStats.size || 0),
          cacheHits: Number(metricsData.cache_hits || 0),
          cacheMisses: Number(metricsData.cache_misses || 0),
          modelLoaded: Boolean(modelStatus.model_loaded),
          modelStatus: modelStatus.status_code || 'unknown',
          modelVersion: modelStatus.model_version || 'N/A',
          modelStage: modelStatus.model_stage || 'unknown',
          modelAccuracy: modelStatus.model_accuracy,
          modelTop10Accuracy: modelStatus.model_top_10_accuracy,
          validationSamples: modelStatus.accepted_validation_samples,
          confidence: modelStatus.accuracy_confidence || 'low',
          prefetchAvailable: Boolean(prefetch.available),
          prefetchQueue: Number(prefetch.queue_length || 0),
          prefetchRetry: Number(prefetch.retry_length || 0),
          prefetchDlq: Number(prefetch.dlq_length || 0),
        })

        setLatencyData(Array.isArray(latency.data) ? latency.data : [])
        setCacheDistribution(Array.isArray(cache.data) ? cache.data : [])
        setAccuracyData(Array.isArray(accuracy.data) ? accuracy.data : [])
        setError(null)
      } catch (err) {
        if (!active) {
          return
        }
        console.error('Failed to fetch dashboard metrics:', err)
        setError('Runtime dashboard could not read backend data.')
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }

    fetchDashboard()
    const interval = setInterval(fetchDashboard, 5000)
    return () => {
      active = false
      clearInterval(interval)
    }
  }, [])

  const connectionLabel = error
    ? 'Backend unavailable'
    : loading
      ? 'Loading runtime snapshot'
      : metrics.connected
        ? 'Connected'
        : 'Waiting for backend'

  const modelStatusLabel = metrics.modelStatus.replace(/_/g, ' ')
  const cachePathData = cacheDistribution.length > 0
    ? cacheDistribution
    : [
        { name: 'Cache Hits', value: metrics.cacheHits, color: '#10B981' },
        { name: 'Cache Misses', value: metrics.cacheMisses, color: '#EF4444' },
      ].filter(item => item.value > 0)

  const accuracyDomain = (() => {
    const values = accuracyData.flatMap(item => [item.accuracy, item.top_10_accuracy]).filter(value => typeof value === 'number')
    if (!values.length) {
      return [0, 100]
    }
    return [Math.max(0, Math.floor(Math.min(...values) - 5)), Math.min(100, Math.ceil(Math.max(...values) + 5))]
  })()

  const headlineCards = [
    {
      title: 'Cache Efficiency',
      value: `${metrics.cacheHitRate.toFixed(1)}%`,
      helper: `${metrics.cacheHits.toLocaleString()} hits • ${metrics.cacheMisses.toLocaleString()} misses`,
      icon: 'target',
      tone: 'text-accent-green',
      pill: metrics.totalRequests > 0 ? 'Measured live' : 'No traffic yet',
    },
    {
      title: 'Average Latency',
      value: `${Math.round(metrics.avgLatency)} ms`,
      helper: 'Rata-rata latency request dari runtime metrics endpoint.',
      icon: 'lightning',
      tone: 'text-accent-blue',
      pill: metrics.totalRequests > 0 ? 'Observed at runtime' : null,
    },
    {
      title: 'Runtime Model',
      value: metrics.modelVersion,
      helper: `${metrics.modelStage} • ${metrics.validationSamples == null ? 'unknown eval basis' : `${metrics.validationSamples} val samples`}`,
      icon: 'brain',
      tone: 'text-warning-orange',
      pill: metrics.modelLoaded ? 'Model bound to runtime' : modelStatusLabel,
    },
    {
      title: 'Prefetch Queue',
      value: metrics.prefetchAvailable ? metrics.prefetchQueue.toLocaleString() : 'N/A',
      helper: metrics.prefetchAvailable
        ? `${metrics.prefetchRetry.toLocaleString()} retry • ${metrics.prefetchDlq.toLocaleString()} DLQ`
        : 'Redis/prefetch queue tidak tersedia di runtime saat ini.',
      icon: 'refresh',
      tone: metrics.prefetchAvailable ? 'text-white' : 'text-slate-500',
      pill: metrics.prefetchAvailable ? 'Worker-backed' : 'Unavailable',
    },
  ]

  return (
    <div className="min-h-screen py-10">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-8">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-3xl border border-dark-border bg-[radial-gradient(circle_at_top_left,_rgba(37,99,235,0.12),_transparent_35%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.10),_transparent_28%)] bg-dark-card/80 p-8"
        >
          <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-6">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-dark-border bg-dark-bg/70 px-4 py-2 text-sm text-slate-300">
                <span className={`w-2 h-2 rounded-full ${error ? 'bg-danger-red' : 'bg-accent-green animate-pulse'}`} />
                <span>{connectionLabel}</span>
              </div>
              <h1 className="mt-6 text-4xl md:text-5xl font-display font-bold text-white">PSKC Runtime Dashboard</h1>
              <p className="mt-4 max-w-2xl text-slate-300 leading-7">
                Dashboard ini difokuskan untuk operational view: bagaimana cache berjalan sekarang, model apa yang aktif,
                seberapa besar tekanan request yang sedang masuk, dan apakah prefetch worker benar-benar tersedia.
              </p>
            </div>

            <div className="rounded-2xl border border-dark-border bg-dark-bg/60 p-5 min-w-[280px]">
              <div className="text-sm text-slate-400 mb-3">Runtime snapshot</div>
              <DetailRow label="Requests" value={metrics.totalRequests.toLocaleString()} />
              <DetailRow label="Cached Keys" value={metrics.keysCached.toLocaleString()} />
              <DetailRow label="Active Keys Seen" value={metrics.activeKeys.toLocaleString()} />
              <DetailRow
                label="Model Top-1"
                value={metrics.modelAccuracy == null ? 'N/A' : `${(metrics.modelAccuracy * 100).toFixed(1)}%`}
                valueClass="text-accent-green"
              />
              <DetailRow
                label="Model Top-10"
                value={metrics.modelTop10Accuracy == null ? 'N/A' : `${(metrics.modelTop10Accuracy * 100).toFixed(1)}%`}
                valueClass="text-accent-blue"
              />
              <DetailRow label="Confidence" value={metrics.confidence} />
            </div>
          </div>
        </motion.div>

        {error ? (
          <div className="rounded-2xl border border-danger-red/40 bg-danger-red/10 px-5 py-4 text-sm text-slate-200">
            {error} Halaman tetap terbuka, tetapi angka di bawah hanya akan terisi jika backend berhasil dibaca.
          </div>
        ) : null}

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          {headlineCards.map(card => (
            <StatusCard key={card.title} {...card} />
          ))}
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-[1.25fr_0.75fr] gap-6">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-3xl border border-dark-border bg-dark-card/80 p-6"
          >
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-xl font-semibold text-white">Cache Posture</h2>
                <div className="text-sm text-slate-400 mt-1">Ringkasan request path yang benar-benar lewat backend.</div>
              </div>
              <div className="w-11 h-11 rounded-xl border border-dark-border bg-dark-bg/70 flex items-center justify-center text-accent-blue">
                <Icon name="database" className="w-5 h-5" />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 mb-6">
              <div className="rounded-2xl bg-dark-bg/70 border border-dark-border p-4">
                <div className="text-sm text-slate-400">Cache Hit Rate</div>
                <div className="text-2xl font-bold text-accent-green mt-2">{metrics.cacheHitRate.toFixed(1)}%</div>
              </div>
              <div className="rounded-2xl bg-dark-bg/70 border border-dark-border p-4">
                <div className="text-sm text-slate-400">Average Latency</div>
                <div className="text-2xl font-bold text-accent-blue mt-2">{Math.round(metrics.avgLatency)} ms</div>
              </div>
            </div>

            {cachePathData.length > 0 ? (
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={cachePathData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={70}
                      outerRadius={100}
                      paddingAngle={4}
                    >
                      {cachePathData.map(item => (
                        <Cell key={item.name} fill={item.color} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyChartState
                title="Belum ada distribusi cache"
                description="Jalankan request nyata atau simulasi realtime agar dashboard bisa menunjukkan pembagian hit dan miss."
              />
            )}
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-3xl border border-dark-border bg-dark-card/80 p-6"
          >
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-xl font-semibold text-white">Model Runtime</h2>
                <div className="text-sm text-slate-400 mt-1">Model yang sedang dibaca runtime sekarang.</div>
              </div>
              <div className="w-11 h-11 rounded-xl border border-dark-border bg-dark-bg/70 flex items-center justify-center text-warning-orange">
                <Icon name="brain" className="w-5 h-5" />
              </div>
            </div>
            <div className="space-y-1">
              <DetailRow label="Version" value={metrics.modelVersion} />
              <DetailRow label="Stage" value={metrics.modelStage} />
              <DetailRow label="Status" value={modelStatusLabel} />
              <DetailRow
                label="Top-1 Accuracy"
                value={metrics.modelAccuracy == null ? 'N/A' : `${(metrics.modelAccuracy * 100).toFixed(1)}%`}
                valueClass="text-accent-green"
              />
              <DetailRow
                label="Top-10 Accuracy"
                value={metrics.modelTop10Accuracy == null ? 'N/A' : `${(metrics.modelTop10Accuracy * 100).toFixed(1)}%`}
                valueClass="text-accent-blue"
              />
              <DetailRow
                label="Accuracy Basis"
                value={metrics.validationSamples == null ? 'Unknown' : `${metrics.validationSamples} val samples`}
              />
              <DetailRow label="Confidence" value={metrics.confidence} />
            </div>

            <div className="mt-5 rounded-2xl border border-dark-border bg-dark-bg/70 p-4 text-sm text-slate-300 leading-6">
              Runtime status ini menunjukkan model yang benar-benar dipakai sistem saat ini.
              Jika histori training di halaman lain menunjukkan angka berbeda, biasanya itu karena halaman tersebut sedang menampilkan run training di database,
              bukan active registry model yang sedang melayani request.
            </div>
          </motion.div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-3xl border border-dark-border bg-dark-card/80 p-6"
          >
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-xl font-semibold text-white">Latency Comparison</h2>
                <div className="text-sm text-slate-400 mt-1">Perbandingan data latency yang tersedia dari backend.</div>
              </div>
              <Icon name="trend" className="w-5 h-5 text-accent-blue" />
            </div>
            {latencyData.length > 0 ? (
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={latencyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="name" stroke="#9CA3AF" fontSize={11} />
                    <YAxis stroke="#9CA3AF" fontSize={11} />
                    <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }} />
                    <Legend />
                    <Bar dataKey="withoutPSKC" name="Without PSKC" fill="#EF4444" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="withPSKC" name="With PSKC" fill="#10B981" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyChartState
                title="Latency comparison belum tersedia"
                description="Chart ini akan terisi jika backend sudah menyimpan data pembanding yang relevan."
              />
            )}
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-3xl border border-dark-border bg-dark-card/80 p-6"
          >
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-xl font-semibold text-white">ML Accuracy History</h2>
                <div className="text-sm text-slate-400 mt-1">History akurasi training yang tersimpan.</div>
              </div>
              <Icon name="chart" className="w-5 h-5 text-warning-orange" />
            </div>
            {accuracyData.length > 0 ? (
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={accuracyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis dataKey="time" stroke="#9CA3AF" fontSize={11} />
                    <YAxis domain={accuracyDomain} stroke="#9CA3AF" fontSize={11} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                      formatter={(value, name) => [
                        `${Number(value).toFixed(1)}%`,
                        name === 'accuracy' ? 'Top-1 Accuracy' : 'Top-10 Accuracy',
                      ]}
                    />
                    <Legend />
                    <Line type="monotone" dataKey="accuracy" stroke="#3B82F6" strokeWidth={3} name="Top-1 Accuracy" />
                    <Line type="monotone" dataKey="top_10_accuracy" stroke="#10B981" strokeWidth={2} name="Top-10 Accuracy" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyChartState
                title="Belum ada history akurasi"
                description="Setelah training/evaluasi tersimpan, grafik ini akan menunjukkan perubahan top-1 dan top-10."
              />
            )}
          </motion.div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <div className="rounded-3xl border border-dark-border bg-dark-card/80 p-6">
            <h2 className="text-xl font-semibold text-white mb-4">Operational Notes</h2>
            <div className="space-y-4 text-sm leading-6 text-slate-300">
              <p>
                Dashboard ini sengaja menampilkan runtime state, bukan angka demo.
                Kalau backend belum punya data, chart akan kosong, bukan diisi dummy.
              </p>
              <p>
                Cache hit rate yang tinggi menunjukkan PSKC berhasil menahan fallback ke KMS.
                Tapi nilai itu baru bermakna kalau request volume dan cached key count juga ikut dibaca bersama.
              </p>
            </div>
          </div>

          <div className="rounded-3xl border border-dark-border bg-dark-card/80 p-6">
            <h2 className="text-xl font-semibold text-white mb-4">Next Drilldown</h2>
            <div className="space-y-3">
              <a href="/simulation" className="flex items-center justify-between rounded-2xl border border-dark-border bg-dark-bg/60 px-4 py-3 hover:border-accent-blue/40 transition-colors">
                <span className="text-slate-200">Realtime Simulation</span>
                <Icon name="play" className="w-5 h-5 text-accent-blue" />
              </a>
              <a href="/model-intelligence" className="flex items-center justify-between rounded-2xl border border-dark-border bg-dark-bg/60 px-4 py-3 hover:border-accent-blue/40 transition-colors">
                <span className="text-slate-200">Model Intelligence</span>
                <Icon name="brain" className="w-5 h-5 text-accent-blue" />
              </a>
              <a href="/ml-training" className="flex items-center justify-between rounded-2xl border border-dark-border bg-dark-bg/60 px-4 py-3 hover:border-accent-blue/40 transition-colors">
                <span className="text-slate-200">ML Training</span>
                <Icon name="upload" className="w-5 h-5 text-accent-blue" />
              </a>
            </div>
          </div>

          <div className="rounded-3xl border border-dark-border bg-dark-card/80 p-6">
            <h2 className="text-xl font-semibold text-white mb-4">Current Runtime Take</h2>
            <div className="space-y-3 text-sm text-slate-300 leading-6">
              <div>
                <span className="text-slate-500">Cache posture:</span>{' '}
                {metrics.totalRequests > 0
                  ? `request traffic sudah masuk dan cache hit rate saat ini ${metrics.cacheHitRate.toFixed(1)}%.`
                  : 'belum ada traffic yang cukup untuk menilai efektivitas cache.'}
              </div>
              <div>
                <span className="text-slate-500">Model posture:</span>{' '}
                {metrics.modelVersion === 'N/A'
                  ? 'runtime belum punya model aktif yang bisa diidentifikasi.'
                  : `runtime sedang menunjuk ke model ${metrics.modelVersion} (${metrics.modelStage}).`}
              </div>
              <div>
                <span className="text-slate-500">Prefetch posture:</span>{' '}
                {metrics.prefetchAvailable
                  ? `queue aktif dengan ${metrics.prefetchQueue.toLocaleString()} item menunggu.`
                  : 'queue prefetch belum tersedia atau Redis belum terbaca.'}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default DashboardPage
