import React, { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import Icon from '../components/Icon'
import { apiClient } from '../utils/apiClient'

const toneClasses = {
  blue: {
    iconWrap: 'bg-accent-blue/20 border-accent-blue/30',
    iconText: 'text-accent-blue',
    badge: 'bg-accent-blue/20 text-accent-blue border border-accent-blue/35',
  },
  green: {
    iconWrap: 'bg-accent-green/20 border-accent-green/30',
    iconText: 'text-accent-green',
    badge: 'bg-accent-green/20 text-accent-green border border-accent-green/35',
  },
  red: {
    iconWrap: 'bg-danger-red/20 border-danger-red/30',
    iconText: 'text-danger-red',
    badge: 'bg-danger-red/20 text-danger-red border border-danger-red/35',
  },
  orange: {
    iconWrap: 'bg-warning-orange/20 border-warning-orange/30',
    iconText: 'text-warning-orange',
    badge: 'bg-warning-orange/20 text-warning-orange border border-warning-orange/35',
  },
}

function Overview() {
  const backendOnly = { allowMockFallback: false }
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [backendState, setBackendState] = useState({
    connected: false,
    cacheHitRate: 0,
    avgLatency: 0,
    totalRequests: 0,
    activeKeys: 0,
    keysCached: 0,
    modelStatus: 'not_trained',
    modelLoaded: false,
    sampleCount: 0,
  })

  useEffect(() => {
    const fetchOverview = async () => {
      try {
        const [health, metrics, cacheStats, modelStatus] = await Promise.all([
          apiClient.getHealth(backendOnly),
          apiClient.getMetrics(backendOnly),
          apiClient.getCacheStats(backendOnly),
          apiClient.getModelStatus(backendOnly),
        ])

        setBackendState({
          connected: health.status === 'healthy',
          cacheHitRate: (metrics.cache_hit_rate || 0) * 100,
          avgLatency: metrics.avg_latency_ms || 0,
          totalRequests: metrics.total_requests || 0,
          activeKeys: metrics.active_keys || 0,
          keysCached: cacheStats.size || 0,
          modelStatus: modelStatus.status || 'unknown',
          modelLoaded: Boolean(modelStatus.model_loaded),
          sampleCount: modelStatus.sample_count || 0,
        })
        setError(null)
      } catch (err) {
        console.error('Failed to load overview data:', err)
        setBackendState({
          connected: false,
          cacheHitRate: 0,
          avgLatency: 0,
          totalRequests: 0,
          activeKeys: 0,
          keysCached: 0,
          modelStatus: 'unavailable',
          modelLoaded: false,
          sampleCount: 0,
        })
        setError('Backend overview data is unavailable')
      } finally {
        setLoading(false)
      }
    }

    fetchOverview()
    const interval = setInterval(fetchOverview, 5000)
    return () => clearInterval(interval)
  }, [])

  const modelStatusLabel = useMemo(() => {
    if (backendState.modelLoaded) {
      return 'Model loaded'
    }
    if (backendState.modelStatus === 'artifact_present') {
      return 'Artifact present'
    }
    if (backendState.modelStatus === 'not_trained') {
      return 'Not trained'
    }
    return backendState.modelStatus.replace(/_/g, ' ')
  }, [backendState.modelLoaded, backendState.modelStatus])

  const features = [
    {
      title: 'Prediktif',
      description:
        'Status model dan pipeline prediksi dibaca langsung dari backend. Jika model belum ada, halaman ini menampilkannya apa adanya.',
      icon: 'brain',
      tone: 'blue',
      stats: modelStatusLabel,
    },
    {
      title: 'Latensi Rendah',
      description:
        'Ringkasan latensi dan throughput diambil dari endpoint metrics backend, bukan angka presentasi yang ditulis manual.',
      icon: 'lightning',
      tone: 'green',
      stats: backendState.totalRequests > 0 ? `${Math.round(backendState.avgLatency)}ms avg` : 'No traffic yet',
    },
    {
      title: 'Aman',
      description:
        'Status cache aktif, total key yang tersimpan, dan jalur request nyata dipantau dari FastAPI runtime yang sedang berjalan.',
      icon: 'shield',
      tone: 'red',
      stats: `${backendState.activeKeys} active keys`,
    },
    {
      title: 'Adaptif',
      description:
        'Cache hit rate dan perubahan perilaku request tercermin dari metrik backend yang terus diperbarui setiap beberapa detik.',
      icon: 'refresh',
      tone: 'orange',
      stats: `${backendState.cacheHitRate.toFixed(1)}% hit`,
    },
  ]

  const stats = [
    { value: `${backendState.cacheHitRate.toFixed(1)}%`, label: 'Cache Hit Rate', valueClass: 'text-accent-blue' },
    { value: `${Math.round(backendState.avgLatency)}ms`, label: 'Avg Latency', valueClass: 'text-accent-green' },
    { value: backendState.totalRequests.toLocaleString(), label: 'Total Requests', valueClass: 'text-accent-blue' },
    { value: modelStatusLabel, label: 'Model Status', valueClass: 'text-accent-green' },
  ]

  const steps = [
    {
      step: '01',
      title: 'Data Collection',
      description: 'Backend merekam key access, hit/miss cache, dan latency request yang sudah benar-benar terjadi.',
      icon: 'database',
    },
    {
      step: '02',
      title: 'ML Prediction',
      description: 'Artefak model dan status pipeline ML dibaca dari backend. Jika belum terlatih, status itu ditampilkan langsung.',
      icon: 'brain',
    },
    {
      step: '03',
      title: 'Pre-caching',
      description: 'Dashboard dan simulation console memakai hasil backend, sehingga efek cache dapat dibandingkan tanpa angka demo lokal.',
      icon: 'lightning',
    },
  ]

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.2,
      },
    },
  }

  const itemVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.5 } },
  }

  const connectionLabel = error ? 'Backend unavailable' : loading ? 'Loading backend' : backendState.connected ? 'Backend connected' : 'Waiting for backend'

  return (
    <div className="min-h-screen">
      <section className="relative py-20 lg:py-32 overflow-hidden">
        <div className="absolute inset-0 grid-pattern opacity-30" />
        <div className="absolute top-20 left-10 w-72 h-72 bg-accent-blue/20 rounded-full blur-3xl animate-pulse-slow" />
        <div
          className="absolute bottom-20 right-10 w-96 h-96 bg-accent-green/10 rounded-full blur-3xl animate-pulse-slow"
          style={{ animationDelay: '1s' }}
        />

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8 }}
            className="text-center"
          >
            <div className="inline-flex items-center gap-2 bg-accent-blue/10 border border-accent-blue/30 rounded-full px-4 py-2 mb-8">
              <span className={`w-2 h-2 rounded-full ${error ? 'bg-danger-red' : 'bg-accent-green animate-pulse'}`} />
              <span className="text-accent-blue font-mono text-sm">{connectionLabel}</span>
            </div>

            <h1 className="hero-title text-4xl md:text-6xl lg:text-7xl font-display font-bold mb-6">
              <span className="text-white">Predictive </span>
              <span className="text-gradient">Secure Key</span>
              <br />
              <span className="text-white">Caching</span>
            </h1>

            <p className="text-xl text-slate-400 max-w-3xl mx-auto mb-10">
              Landing page ini sekarang memakai status backend nyata untuk ringkasan performa, cache, dan model ML.
            </p>

            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <a href="/node-graph" className="btn-primary text-lg px-8 py-4 inline-flex items-center justify-center gap-2">
                <span>Explore Architecture</span>
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                </svg>
              </a>
              <a href="/simulation" className="btn-secondary text-lg px-8 py-4 inline-flex items-center justify-center gap-2">
                <span>Run Simulation</span>
              </a>
            </div>
          </motion.div>

          {error ? (
            <div className="mt-8 rounded-xl border border-danger-red/40 bg-danger-red/10 px-4 py-3 text-sm text-slate-200 text-center">
              {error}. Halaman tetap terbuka, tetapi metrik di bawah menampilkan state kosong yang jujur.
            </div>
          ) : null}

          <motion.div
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.4 }}
            className="mt-20 grid grid-cols-2 md:grid-cols-4 gap-4"
          >
            {stats.map((stat) => (
              <div key={stat.label} className="metric-card text-center">
                <div className={`text-3xl font-bold mb-1 ${stat.valueClass}`}>{stat.value}</div>
                <div className="text-slate-400 text-sm">{stat.label}</div>
              </div>
            ))}
          </motion.div>
        </div>
      </section>

      <section className="py-20 relative">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <motion.div initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }} className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-display font-bold text-white mb-4">Key Features</h2>
            <p className="text-slate-400 max-w-2xl mx-auto">
              Bagian ini tetap menjelaskan kapabilitas PSKC, tetapi badge statusnya sekarang diambil dari backend yang aktif.
            </p>
          </motion.div>

          <motion.div
            variants={containerVariants}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="grid grid-cols-1 md:grid-cols-2 gap-6"
          >
            {features.map((feature) => {
              const tone = toneClasses[feature.tone]
              return (
                <motion.div key={feature.title} variants={itemVariants} className="card-hover gradient-card rounded-xl p-6 border border-dark-border">
                  <div className="flex items-start gap-4">
                    <div className={`w-14 h-14 rounded-xl border flex items-center justify-center flex-shrink-0 ${tone.iconWrap}`}>
                      <Icon name={feature.icon} className={`w-7 h-7 ${tone.iconText}`} />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-2 gap-3">
                        <h3 className="text-xl font-semibold text-white">{feature.title}</h3>
                        <span className={`text-xs font-mono px-2 py-1 rounded whitespace-nowrap ${tone.badge}`}>{feature.stats}</span>
                      </div>
                      <p className="text-slate-400 leading-relaxed">{feature.description}</p>
                    </div>
                  </div>
                </motion.div>
              )
            })}
          </motion.div>
        </div>
      </section>

      <section className="py-20 bg-dark-card/50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <motion.div initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }} className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-display font-bold text-white mb-4">How PSKC Works</h2>
            <p className="text-slate-400 max-w-2xl mx-auto">Pipa data dan cache sekarang dipresentasikan dengan konteks status runtime backend.</p>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {steps.map((item, index) => (
              <motion.div
                key={item.step}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.2 }}
                className="relative"
              >
                <div className="text-6xl font-display font-bold text-dark-border absolute -top-4 -left-2">{item.step}</div>
                <div className="pt-8 pl-4">
                  <div className="w-11 h-11 rounded-lg bg-accent-blue/15 border border-accent-blue/30 flex items-center justify-center mb-4">
                    <Icon name={item.icon} className="w-6 h-6 text-accent-blue" />
                  </div>
                  <h3 className="text-xl font-semibold text-white mb-2">{item.title}</h3>
                  <p className="text-slate-400">{item.description}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      <section className="py-20">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true }}
            className="gradient-card rounded-2xl p-8 md:p-12 text-center border border-dark-border"
          >
            <h2 className="text-3xl md:text-4xl font-display font-bold text-white mb-4">Ready to Inspect Real Backend State?</h2>
            <p className="text-slate-400 mb-8 max-w-xl mx-auto">
              Simulation, dashboard, dan ML pipeline sekarang memakai backend sebagai sumber data utama, bukan angka demo lokal.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <a href="/dashboard" className="btn-primary px-8 py-3">
                View Dashboard
              </a>
              <a href="/ml-pipeline" className="btn-secondary px-8 py-3">
                Explore ML Pipeline
              </a>
            </div>
          </motion.div>
        </div>
      </section>
    </div>
  )
}

export default Overview
