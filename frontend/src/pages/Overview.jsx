import React, { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import Icon from '../components/Icon'
import { apiClient } from '../utils/apiClient'

function StatCard({ label, value, helper, icon, tone = 'text-white' }) {
  return (
    <div className="rounded-2xl border border-dark-border bg-dark-card/80 p-5 shadow-[0_20px_60px_rgba(0,0,0,0.18)]">
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-slate-400">{label}</div>
        <div className="w-10 h-10 rounded-xl border border-dark-border bg-dark-bg/70 flex items-center justify-center text-slate-200">
          <Icon name={icon} className="w-5 h-5" />
        </div>
      </div>
      <div className={`text-3xl font-bold ${tone}`}>{value}</div>
      <div className="mt-2 text-xs text-slate-500">{helper}</div>
    </div>
  )
}

function FlowCard({ step, title, body, icon }) {
  return (
    <div className="rounded-2xl border border-dark-border bg-dark-card/70 p-5">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-accent-blue mb-1">{step}</div>
          <div className="text-lg font-semibold text-white">{title}</div>
        </div>
        <div className="w-10 h-10 rounded-xl bg-dark-bg/70 border border-dark-border flex items-center justify-center text-accent-blue">
          <Icon name={icon} className="w-5 h-5" />
        </div>
      </div>
      <p className="text-sm leading-6 text-slate-400">{body}</p>
    </div>
  )
}

function Overview() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [snapshot, setSnapshot] = useState({
    connected: false,
    cacheHitRate: 0,
    avgLatency: 0,
    totalRequests: 0,
    activeKeys: 0,
    cachedKeys: 0,
    modelVersion: 'N/A',
    modelStage: 'unknown',
    modelAccuracy: null,
    modelTop10Accuracy: null,
    modelStatus: 'unknown',
    validationSamples: null,
    confidence: 'low',
  })

  useEffect(() => {
    let active = true

    const fetchOverview = async () => {
      try {
        const [health, metrics, cacheStats, modelStatus] = await Promise.all([
          apiClient.getHealth(),
          apiClient.getMetrics(),
          apiClient.getCacheStats(),
          apiClient.getModelStatus(),
        ])

        if (!active) {
          return
        }

        setSnapshot({
          connected: health.status === 'healthy',
          cacheHitRate: Number(metrics.cache_hit_rate || 0) * 100,
          avgLatency: Number(metrics.avg_latency_ms || 0),
          totalRequests: Number(metrics.total_requests || 0),
          activeKeys: Number(metrics.active_keys || 0),
          cachedKeys: Number(cacheStats.size || 0),
          modelVersion: modelStatus.model_version || 'N/A',
          modelStage: modelStatus.model_stage || 'unknown',
          modelAccuracy: modelStatus.model_accuracy,
          modelTop10Accuracy: modelStatus.model_top_10_accuracy,
          modelStatus: modelStatus.status_code || 'unknown',
          validationSamples: modelStatus.accepted_validation_samples,
          confidence: modelStatus.accuracy_confidence || 'low',
        })
        setError(null)
      } catch (err) {
        if (!active) {
          return
        }
        console.error('Failed to load overview data:', err)
        setError('Backend overview data is currently unavailable.')
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }

    fetchOverview()
    const interval = setInterval(fetchOverview, 5000)
    return () => {
      active = false
      clearInterval(interval)
    }
  }, [])

  const connectionLabel = error
    ? 'Backend unavailable'
    : loading
      ? 'Reading backend snapshot'
      : snapshot.connected
        ? 'Backend connected'
        : 'Waiting for backend'

  const modelStatusLabel = snapshot.modelStatus.replace(/_/g, ' ')

  return (
    <div className="min-h-screen">
      <section className="relative overflow-hidden py-20 lg:py-28">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(37,99,235,0.16),_transparent_32%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.12),_transparent_28%)]" />
        <div className="absolute inset-0 grid-pattern opacity-20" />

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="max-w-4xl"
          >
            <div className="inline-flex items-center gap-2 rounded-full border border-accent-blue/30 bg-accent-blue/10 px-4 py-2 text-sm text-accent-blue">
              <span className={`w-2 h-2 rounded-full ${error ? 'bg-danger-red' : 'bg-accent-green animate-pulse'}`} />
              <span>{connectionLabel}</span>
            </div>

            <h1 className="mt-8 text-4xl md:text-6xl font-display font-bold leading-tight text-white">
              PSKC:
              <span className="block text-gradient mt-2">Predictive Secure Key Caching</span>
            </h1>

            <p className="mt-6 max-w-3xl text-lg md:text-xl leading-8 text-slate-300">
              PSKC adalah arsitektur cache kunci yang mencoba memprediksi kunci apa yang akan diminta berikutnya,
              lalu memanaskannya secara aman ke cache berlapis sebelum request jatuh ke KMS.
              Tujuannya sederhana: menurunkan latency, mengurangi tekanan ke KMS, dan tetap menjaga jalur pengambilan kunci tetap aman dan terukur.
            </p>

            <div className="mt-10 flex flex-col sm:flex-row gap-4">
              <a
                href="/dashboard"
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent-blue px-6 py-3 text-white font-medium hover:bg-blue-500 transition-colors"
              >
                <Icon name="gauge" className="w-5 h-5" />
                Open Runtime Dashboard
              </a>
              <a
                href="/simulation"
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-dark-border bg-dark-card/70 px-6 py-3 text-slate-200 hover:border-accent-blue/50 transition-colors"
              >
                <Icon name="play" className="w-5 h-5" />
                Open Realtime Simulation
              </a>
              <a
                href="/model-intelligence"
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-dark-border bg-dark-card/70 px-6 py-3 text-slate-200 hover:border-accent-blue/50 transition-colors"
              >
                <Icon name="brain" className="w-5 h-5" />
                Open Model Intelligence
              </a>
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="mt-14 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4"
          >
            <StatCard
              label="Cache Hit Rate"
              value={`${snapshot.cacheHitRate.toFixed(1)}%`}
              helper="Proporsi request yang tidak perlu fetch ulang dari KMS."
              icon="target"
              tone="text-accent-green"
            />
            <StatCard
              label="Average Latency"
              value={`${Math.round(snapshot.avgLatency)} ms`}
              helper="Rata-rata latency request yang dicatat backend."
              icon="lightning"
              tone="text-accent-blue"
            />
            <StatCard
              label="Requests Observed"
              value={snapshot.totalRequests.toLocaleString()}
              helper="Jumlah request yang sudah tercatat oleh runtime metrics."
              icon="activity"
              tone="text-white"
            />
            <StatCard
              label="Runtime Model"
              value={snapshot.modelVersion}
              helper={`${snapshot.modelStage} • ${snapshot.validationSamples == null ? 'unknown eval basis' : `${snapshot.validationSamples} val samples`}`}
              icon="brain"
              tone="text-warning-orange"
            />
          </motion.div>
        </div>
      </section>

      <section className="py-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-[1.2fr_0.8fr] gap-6">
            <div className="rounded-3xl border border-dark-border bg-dark-card/80 p-8">
              <div className="text-sm uppercase tracking-[0.24em] text-accent-blue mb-3">What PSKC does</div>
              <h2 className="text-2xl md:text-3xl font-display font-bold text-white mb-4">
                Mengurangi fallback ke KMS tanpa mengorbankan keamanan
              </h2>
              <div className="space-y-4 text-slate-300 leading-7">
                <p>
                  Dalam sistem biasa, saat kunci tidak ada di cache, request harus langsung mengambil ke KMS.
                  Pada traffic tinggi, ini menambah latency dan membebani layanan kunci pusat.
                </p>
                <p>
                  PSKC menambahkan dua hal penting: prediksi akses berikutnya dan cache berlapis.
                  Prediksi dipakai untuk memberi tahu prefetch worker kunci mana yang layak dipanaskan,
                  sementara cache berlapis memberi jalur cepat melalui L1 dan L2 sebelum melakukan fallback ke KMS.
                </p>
                <p>
                  Nilai utamanya bukan sekadar “AI ada”, tetapi bahwa seluruh alurnya bisa diukur:
                  cache hit rate, latency, drift model, queue prefetch, dan runtime model yang aktif.
                </p>
              </div>
            </div>

            <div className="rounded-3xl border border-dark-border bg-dark-card/80 p-8">
              <div className="text-sm uppercase tracking-[0.24em] text-accent-blue mb-3">Live backend proof</div>
              <div className="space-y-5">
                <div>
                  <div className="text-sm text-slate-400 mb-1">Connection</div>
                  <div className="text-lg font-semibold text-white">{snapshot.connected ? 'Healthy' : 'Unavailable'}</div>
                </div>
                <div>
                  <div className="text-sm text-slate-400 mb-1">Cached Keys</div>
                  <div className="text-lg font-semibold text-white">{snapshot.cachedKeys.toLocaleString()}</div>
                </div>
                <div>
                  <div className="text-sm text-slate-400 mb-1">Active Keys Seen</div>
                  <div className="text-lg font-semibold text-white">{snapshot.activeKeys.toLocaleString()}</div>
                </div>
                <div>
                  <div className="text-sm text-slate-400 mb-1">Runtime Accuracy</div>
                  <div className="text-lg font-semibold text-white">
                    {snapshot.modelAccuracy == null ? 'N/A' : `${(snapshot.modelAccuracy * 100).toFixed(1)}%`}
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    {snapshot.modelTop10Accuracy == null
                      ? `${snapshot.confidence} confidence • top-10 not available`
                      : `Top-10 ${(snapshot.modelTop10Accuracy * 100).toFixed(1)}% • ${snapshot.confidence} confidence`}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-slate-400 mb-1">Runtime Status</div>
                  <div className="text-lg font-semibold text-white capitalize">{modelStatusLabel}</div>
                </div>
              </div>
              {error ? (
                <div className="mt-6 rounded-xl border border-danger-red/40 bg-danger-red/10 px-4 py-3 text-sm text-slate-200">
                  {error}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </section>

      <section className="py-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="mb-10">
            <div className="text-sm uppercase tracking-[0.24em] text-accent-blue mb-3">Request flow</div>
            <h2 className="text-2xl md:text-3xl font-display font-bold text-white">Bagaimana PSKC bekerja di runtime</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-4">
            <FlowCard
              step="01"
              icon="grid"
              title="Request arrives"
              body="Request datang dengan key id dan service id. Sistem mengaudit request dan memeriksa jalur yang aman."
            />
            <FlowCard
              step="02"
              icon="lightning"
              title="L1 cache"
              body="API node memeriksa cache lokal paling cepat. Jika key ada di sini, latency menjadi paling rendah."
            />
            <FlowCard
              step="03"
              icon="database"
              title="L2 Redis"
              body="Jika L1 miss, sistem mencoba shared encrypted cache di Redis. Hit di L2 masih jauh lebih murah daripada ke KMS."
            />
            <FlowCard
              step="04"
              icon="shield"
              title="KMS fallback"
              body="Jika L1 dan L2 miss, request mengambil key dari KMS. Jalur ini aman, tetapi lebih mahal secara latency."
            />
            <FlowCard
              step="05"
              icon="brain"
              title="Predict and prefetch"
              body="Model memprediksi jalur request berikutnya, lalu worker mem-prefetch key yang dianggap paling layak ke cache."
            />
          </div>
        </div>
      </section>
    </div>
  )
}

export default Overview
