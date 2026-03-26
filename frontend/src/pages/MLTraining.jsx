import React, { useCallback, useEffect, useMemo, useState } from 'react'
import Icon from '../components/Icon'
import apiClient from '../utils/apiClient'
import TrainingProgress from '../components/TrainingProgress'
import DataGenerationProgress from '../components/DataGenerationProgress'

const scenarios = [
  { value: 'dynamic', label: 'Dynamic', description: 'General API traffic patterns.' },
  { value: 'siakad', label: 'SIAKAD', description: 'Academic workflows with repeated reads.' },
  { value: 'sevima', label: 'SEVIMA', description: 'Cloud education style access bursts.' },
  { value: 'pddikti', label: 'PDDIKTI', description: 'Higher-education sync and reporting patterns.' },
]

const trafficProfiles = [
  { value: 'normal', label: 'Normal', description: 'Baseline traffic with moderate repetition.' },
  { value: 'heavy', label: 'Heavy', description: 'Higher RPM with lower cache stability.' },
  { value: 'prime_time', label: 'Prime Time', description: 'Peak-hour bursts and short-lived sessions.' },
  { value: 'overload', label: 'Overload', description: 'Stress traffic with more churn and misses.' },
]

const qualityProfiles = [
  {
    value: 'fast',
    label: 'Fast',
    description: 'Quick sanity-check retrain with tighter caps.',
    accent: 'border-sky-500/40 bg-sky-500/10 text-sky-300',
  },
  {
    value: 'balanced',
    label: 'Balanced',
    description: 'Recommended default between quality and runtime.',
    accent: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  },
  {
    value: 'thorough',
    label: 'Thorough',
    description: 'Best quality within a bounded 30-60 minute budget.',
    accent: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  },
]

const formatTimestamp = value => {
  if (!value) return 'N/A'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

const formatPercent = value => {
  if (value == null || Number.isNaN(Number(value))) return 'N/A'
  return `${(Number(value) * 100).toFixed(1)}%`
}

const formatNumber = value => {
  if (value == null || Number.isNaN(Number(value))) return '0'
  return Number(value).toLocaleString()
}

const formatDuration = seconds => {
  if (seconds == null || Number.isNaN(Number(seconds))) return 'N/A'
  if (Number(seconds) < 60) return `${Number(seconds).toFixed(1)}s`
  const minutes = Math.floor(Number(seconds) / 60)
  const remaining = Math.round(Number(seconds) % 60)
  return `${minutes}m ${remaining}s`
}

const formatVersion = value => {
  if (!value) return 'N/A'
  const label = String(value)
  return label.toLowerCase().startsWith('v') ? label : `v${label}`
}

const SummaryTile = ({ label, value, hint, accent = 'text-white' }) => (
  <div className="rounded-2xl border border-dark-border bg-dark-card p-4">
    <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{label}</div>
    <div className={`mt-2 text-2xl font-semibold ${accent}`}>{value}</div>
    {hint ? <div className="mt-2 text-xs text-slate-400">{hint}</div> : null}
  </div>
)

const InfoRow = ({ label, value, valueClassName = 'text-white' }) => (
  <div className="flex items-start justify-between gap-4 py-2">
    <span className="text-sm text-slate-400">{label}</span>
    <span className={`text-sm text-right ${valueClassName}`}>{value}</span>
  </div>
)

const SelectGrid = ({ items, selected, onSelect }) => (
  <div className="grid gap-3 md:grid-cols-3">
    {items.map(item => {
      const active = selected === item.value
      return (
        <button
          key={item.value}
          type="button"
          onClick={() => onSelect(item.value)}
          className={`rounded-2xl border p-4 text-left transition-all ${
            active
              ? item.accent || 'border-accent-blue/50 bg-accent-blue/10 text-white'
              : 'border-dark-border bg-dark-bg text-slate-300 hover:border-slate-500'
          }`}
        >
          <div className="text-sm font-semibold">{item.label}</div>
          <div className="mt-2 text-xs opacity-80">{item.description}</div>
        </button>
      )
    })}
  </div>
)

const MLTraining = () => {
  const [numEvents, setNumEvents] = useState(2000)
  const [numKeys, setNumKeys] = useState(150)
  const [numServices, setNumServices] = useState(6)
  const [scenario, setScenario] = useState('dynamic')
  const [trafficProfile, setTrafficProfile] = useState('normal')
  const [durationHours, setDurationHours] = useState(24)
  const [qualityProfile, setQualityProfile] = useState('balanced')
  const [timeBudgetMinutes, setTimeBudgetMinutes] = useState(30)

  const [generating, setGenerating] = useState(false)
  const [training, setTraining] = useState(false)
  const [evaluating, setEvaluating] = useState(false)
  const [showGenerationProgress, setShowGenerationProgress] = useState(false)
  const [showTrainingProgress, setShowTrainingProgress] = useState(false)

  const [generateResult, setGenerateResult] = useState(null)
  const [trainSummary, setTrainSummary] = useState(null)
  const [trainingStartedInfo, setTrainingStartedInfo] = useState(null)
  const [evaluationResult, setEvaluationResult] = useState(null)
  const [estimatedData, setEstimatedData] = useState(null)
  const [trainingPlan, setTrainingPlan] = useState(null)
  const [savedProgressState, setSavedProgressState] = useState(null)
  const [mlStatus, setMlStatus] = useState(null)
  const [error, setError] = useState(null)
  const [loadingStatus, setLoadingStatus] = useState(true)
  const [estimatingData, setEstimatingData] = useState(false)
  const [loadingPlan, setLoadingPlan] = useState(false)

  const selectedProfile = useMemo(
    () => qualityProfiles.find(item => item.value === qualityProfile) || qualityProfiles[1],
    [qualityProfile],
  )

  const loadMLStatus = useCallback(async () => {
    try {
      setLoadingStatus(true)
      const response = await apiClient.get('/ml/status')
      setMlStatus(response)
      return response
    } catch (err) {
      console.error('Failed to load ML status:', err)
      setError('Failed to load ML status')
      return null
    } finally {
      setLoadingStatus(false)
    }
  }, [])

  const loadTrainingPlan = useCallback(async () => {
    try {
      setLoadingPlan(true)
      const response = await apiClient.getTrainingPlan({
        quality_profile: qualityProfile,
        time_budget_minutes: timeBudgetMinutes,
      })
      setTrainingPlan(response)
    } catch (err) {
      console.error('Failed to load training plan:', err)
    } finally {
      setLoadingPlan(false)
    }
  }, [qualityProfile, timeBudgetMinutes])

  const estimateDataGeneration = useCallback(async () => {
    if (!numEvents || !numKeys || !numServices || !durationHours) {
      setEstimatedData(null)
      return
    }

    setEstimatingData(true)
    try {
      const response = await apiClient.get('/ml/training/generate/estimate', {
        params: {
          num_events: numEvents,
          num_keys: numKeys,
          num_services: numServices,
          scenario,
          traffic_profile: trafficProfile,
          duration_hours: durationHours,
        },
      })
      setEstimatedData(response)
    } catch (err) {
      console.error('Failed to estimate data generation:', err)
      setEstimatedData(null)
    } finally {
      setEstimatingData(false)
    }
  }, [durationHours, numEvents, numKeys, numServices, scenario, trafficProfile])

  const checkSavedProgress = useCallback(async () => {
    try {
      const response = await apiClient.get('/ml/training/state')
      if (!response?.state) return
      setSavedProgressState(response.state)
      const phase = response.state.phase
      if (phase && !['idle', 'completed', 'failed'].includes(phase)) {
        setShowTrainingProgress(true)
      }
    } catch (err) {
      console.debug('No saved progress state found:', err)
    }
  }, [])

  useEffect(() => {
    loadMLStatus()
    loadTrainingPlan()
    checkSavedProgress()
  }, [checkSavedProgress, loadMLStatus, loadTrainingPlan])

  useEffect(() => {
    const timer = setTimeout(() => {
      estimateDataGeneration()
    }, 400)
    return () => clearTimeout(timer)
  }, [estimateDataGeneration])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadTrainingPlan()
    }, 250)
    return () => clearTimeout(timer)
  }, [loadTrainingPlan])

  const handleGenerationComplete = useCallback(() => {
    setShowGenerationProgress(false)
  }, [])

  const handleTrainingComplete = useCallback(async result => {
    setShowTrainingProgress(false)
    setTraining(false)
    const statusResponse = await loadMLStatus()
    await loadTrainingPlan()

    const lastAttempt = statusResponse?.last_training_attempt || {}
    const details = result?.details || {}
    const accepted =
      details.model_accepted ??
      statusResponse?.last_attempt_accepted ??
      lastAttempt.accepted ??
      false

    setTrainSummary({
      model_accepted: Boolean(accepted),
      val_accuracy: details.val_accuracy ?? statusResponse?.last_attempt_accuracy,
      val_top_10_accuracy:
        details.val_top_10_accuracy ?? statusResponse?.last_attempt_top_10_accuracy,
      training_time_s: details.training_time_s,
      sample_count: details.sample_count ?? statusResponse?.last_attempt_sample_count,
      quality_profile:
        details.quality_profile ??
        trainingStartedInfo?.quality_profile ??
        qualityProfile,
      time_budget_minutes:
        details.time_budget_minutes ??
        trainingStartedInfo?.time_budget_minutes ??
        timeBudgetMinutes,
      estimated_training_minutes:
        details.estimated_training_minutes ??
        trainingPlan?.estimated_training_minutes,
      active_version: statusResponse?.model_version,
      status_detail: statusResponse?.status_detail,
      accuracy_confidence: statusResponse?.last_attempt_accuracy_confidence,
    })
    setTrainingStartedInfo(null)
  }, [loadMLStatus, loadTrainingPlan, qualityProfile, timeBudgetMinutes, trainingPlan, trainingStartedInfo])

  const handleGenerateData = async () => {
    if (!numEvents || numEvents <= 0 || !numKeys || numKeys <= 0 || !numServices || numServices <= 0 || !durationHours || durationHours <= 0) {
      setError('All numeric fields must be positive numbers')
      return
    }
    if (numEvents < 100 || numKeys < 10 || numServices < 1 || durationHours < 1) {
      setError('Events min 100, Keys min 10, Services min 1, Duration min 1 hour')
      return
    }

    setError(null)
    setGenerateResult(null)
    setGenerating(true)
    setShowGenerationProgress(true)

    try {
      const response = await apiClient.generateTrainingData({
        num_events: numEvents,
        num_keys: numKeys,
        num_services: numServices,
        scenario,
        traffic_profile: trafficProfile,
        duration_hours: durationHours,
      })
      setGenerateResult(response)
      await loadMLStatus()
      await loadTrainingPlan()
    } catch (err) {
      console.error('Failed to generate training data:', err)
      setError(err.message || 'Failed to generate training data')
    } finally {
      setGenerating(false)
    }
  }

  const handleTrainModel = async () => {
    setError(null)
    setTrainSummary(null)
    setTraining(true)
    setShowTrainingProgress(true)

    try {
      const response = await apiClient.trainModel({
        force: true,
        reason: 'manual',
        quality_profile: qualityProfile,
        time_budget_minutes: timeBudgetMinutes,
      })
      setTrainingStartedInfo(response)
    } catch (err) {
      console.error('Failed to train model:', err)
      setShowTrainingProgress(false)
      setTraining(false)
      setError(err.message || 'Failed to train model')
    }
  }

  const handleResetModel = async () => {
    if (!window.confirm(
      'Reset model state?\n\nIni akan menghapus model aktif dan memaksa training berikutnya dievaluasi dari baseline baru. Data event tidak akan dihapus.'
    )) {
      return
    }

    setError(null)
    try {
      await apiClient.post('/ml/training/reset-model')
      setTrainSummary(null)
      await loadMLStatus()
      await loadTrainingPlan()
      window.alert('Model berhasil direset. Jalankan full training lagi untuk membuat baseline aktif baru.')
    } catch (err) {
      console.error('Failed to reset model:', err)
      setError(err.message || 'Failed to reset model')
    }
  }

  const handleEvaluateModel = async () => {
    setEvaluating(true)
    setError(null)
    try {
      const response = await apiClient.evaluateModel()
      setEvaluationResult(response)
      await loadMLStatus()
    } catch (err) {
      console.error('Failed to evaluate model:', err)
      setError(err.message || 'Failed to evaluate model')
    } finally {
      setEvaluating(false)
    }
  }

  const modelStatusTone = mlStatus?.status_code === 'trained'
    ? 'text-emerald-300'
    : mlStatus?.status_code === 'ready_for_training'
      ? 'text-sky-300'
      : 'text-amber-300'

  return (
    <div className="min-h-screen p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="rounded-3xl border border-dark-border bg-dark-card p-6">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Model Training</div>
              <h1 className="mt-2 text-3xl font-display text-white">Full Training Control Center</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
                Halaman ini sekarang memisahkan data generation, full retraining, dan evaluation. Full retraining membuat versi model persisted baru.
                Drift-triggered adaptation tetap berjalan di jalur River online learning dan tidak memblokir simulasi.
              </p>
            </div>
            <div className="rounded-2xl border border-dark-border bg-dark-bg px-4 py-3 text-sm text-slate-300">
              <div className="font-medium text-white">Selected Full-Training Profile</div>
              <div className="mt-1">{selectedProfile.label} • Budget {timeBudgetMinutes} min</div>
              <div className="mt-1 text-xs text-slate-500">{selectedProfile.description}</div>
            </div>
          </div>
        </div>

        {error ? (
          <div className="rounded-2xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
            <div className="flex items-center gap-2">
              <Icon name="alert" className="h-5 w-5" />
              <span>{error}</span>
            </div>
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <SummaryTile
            label="Active Version"
            value={formatVersion(mlStatus?.model_version)}
            hint={mlStatus?.model_stage || 'development'}
            accent="text-sky-300"
          />
          <SummaryTile
            label="Active Accuracy"
            value={formatPercent(mlStatus?.model_accuracy)}
            hint={`Top-10 ${formatPercent(mlStatus?.model_top_10_accuracy)} • ${mlStatus?.accuracy_confidence || 'unknown'} confidence`}
            accent="text-emerald-300"
          />
          <SummaryTile
            label="Collector Samples"
            value={formatNumber(mlStatus?.sample_count)}
            hint={`Accepted validation ${formatNumber(mlStatus?.accepted_validation_samples)}`}
            accent="text-white"
          />
          <SummaryTile
            label="Current Status"
            value={loadingStatus ? 'Loading...' : String(mlStatus?.status_code || 'unknown').replaceAll('_', ' ')}
            hint={mlStatus?.status_detail || 'runtime status'}
            accent={modelStatusTone}
          />
        </div>

        <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
          <div className="space-y-6">
            <div className="rounded-3xl border border-dark-border bg-dark-card p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-xl font-semibold text-white">Generate Training Data</h2>
                  <p className="mt-2 text-sm text-slate-400">
                    Bangun dataset sintetis yang menyerupai pola beban sistem Anda sebelum menjalankan full retrain.
                  </p>
                </div>
                {estimatingData ? <Icon name="loader" className="h-5 w-5 animate-spin text-slate-400" /> : null}
              </div>

              <div className="mt-6 space-y-6">
                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">Scenario</div>
                  <SelectGrid items={scenarios} selected={scenario} onSelect={setScenario} />
                </div>

                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">Traffic Profile</div>
                  <SelectGrid items={trafficProfiles} selected={trafficProfile} onSelect={setTrafficProfile} />
                </div>

                <div className="grid gap-4 md:grid-cols-4">
                  <label className="block">
                    <div className="mb-2 text-sm text-slate-300">Events</div>
                    <input
                      type="number"
                      min={100}
                      value={numEvents}
                      onChange={event => setNumEvents(Number(event.target.value || 0))}
                      className="w-full rounded-xl border border-dark-border bg-dark-bg px-4 py-3 text-white focus:border-accent-blue focus:outline-none"
                    />
                  </label>
                  <label className="block">
                    <div className="mb-2 text-sm text-slate-300">Keys</div>
                    <input
                      type="number"
                      min={10}
                      value={numKeys}
                      onChange={event => setNumKeys(Number(event.target.value || 0))}
                      className="w-full rounded-xl border border-dark-border bg-dark-bg px-4 py-3 text-white focus:border-accent-blue focus:outline-none"
                    />
                  </label>
                  <label className="block">
                    <div className="mb-2 text-sm text-slate-300">Services</div>
                    <input
                      type="number"
                      min={1}
                      value={numServices}
                      onChange={event => setNumServices(Number(event.target.value || 0))}
                      className="w-full rounded-xl border border-dark-border bg-dark-bg px-4 py-3 text-white focus:border-accent-blue focus:outline-none"
                    />
                  </label>
                  <label className="block">
                    <div className="mb-2 text-sm text-slate-300">Duration (hours)</div>
                    <input
                      type="number"
                      min={1}
                      value={durationHours}
                      onChange={event => setDurationHours(Number(event.target.value || 0))}
                      className="w-full rounded-xl border border-dark-border bg-dark-bg px-4 py-3 text-white focus:border-accent-blue focus:outline-none"
                    />
                  </label>
                </div>

                {estimatedData ? (
                  <div className="rounded-2xl border border-sky-500/30 bg-sky-500/10 p-4">
                    <div className="mb-3 text-sm font-medium text-sky-200">Generation Estimate</div>
                    <div className="grid gap-3 md:grid-cols-3">
                      <InfoRow label="Estimated Events" value={formatNumber(estimatedData.estimated_events)} valueClassName="text-sky-200" />
                      <InfoRow label="Approx. Size" value={estimatedData.estimated_size_formatted} />
                      <InfoRow label="Traffic Multiplier" value={`${estimatedData.traffic_profile_multiplier}x`} />
                    </div>
                  </div>
                ) : null}

                <button
                  type="button"
                  onClick={handleGenerateData}
                  disabled={generating}
                  className={`inline-flex w-full items-center justify-center gap-2 rounded-2xl px-5 py-3 font-medium transition ${
                    generating
                      ? 'cursor-not-allowed bg-slate-700 text-slate-300'
                      : 'bg-accent-blue text-white hover:bg-accent-blue/85'
                  }`}
                >
                  <Icon name={generating ? 'loader' : 'database'} className={`h-5 w-5 ${generating ? 'animate-spin' : ''}`} />
                  <span>{generating ? 'Generating Training Data...' : 'Generate Training Data'}</span>
                </button>

                {generateResult ? (
                  <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm">
                    <div className="flex items-center gap-2 font-medium text-emerald-300">
                      <Icon name="check" className="h-5 w-5" />
                      <span>Generation started successfully</span>
                    </div>
                    <div className="mt-3 grid gap-2 md:grid-cols-3">
                      <InfoRow label="Scenario" value={generateResult.scenario || scenario} />
                      <InfoRow label="Requested Events" value={formatNumber(numEvents)} />
                      <InfoRow label="Traffic Profile" value={trafficProfile} />
                    </div>
                  </div>
                ) : null}
              </div>
            </div>

            {showGenerationProgress ? (
              <DataGenerationProgress onComplete={handleGenerationComplete} />
            ) : null}

            <div className="rounded-3xl border border-dark-border bg-dark-card p-6">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <h2 className="text-xl font-semibold text-white">Full Retraining Strategy</h2>
                  <p className="mt-2 text-sm text-slate-400">
                    Profile ini mempengaruhi banyaknya data yang dipakai, budget training, dan hyperparameter utama untuk full retraining.
                  </p>
                </div>
                <div className="rounded-2xl border border-dark-border bg-dark-bg px-4 py-3 text-sm text-slate-300">
                  Online drift adaptation tetap berjalan terpisah via River `partial_fit`.
                </div>
              </div>

              <div className="mt-6">
                <div className="mb-3 text-sm font-medium text-slate-300">Quality Profile</div>
                <SelectGrid items={qualityProfiles} selected={qualityProfile} onSelect={setQualityProfile} />
              </div>

              <div className="mt-6 rounded-2xl border border-dark-border bg-dark-bg p-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="text-sm font-medium text-white">Time Budget</div>
                    <div className="mt-1 text-xs text-slate-500">Bound the full retrain so it stays practical on CPU deployments.</div>
                  </div>
                  <div className="text-lg font-semibold text-white">{timeBudgetMinutes} min</div>
                </div>
                <input
                  type="range"
                  min={5}
                  max={60}
                  step={5}
                  value={timeBudgetMinutes}
                  onChange={event => setTimeBudgetMinutes(Number(event.target.value))}
                  className="mt-4 w-full"
                />
              </div>

              <div className="mt-6 rounded-2xl border border-dark-border bg-dark-bg p-4">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium text-white">Training Plan</div>
                  {loadingPlan ? <Icon name="loader" className="h-4 w-4 animate-spin text-slate-400" /> : null}
                </div>

                {trainingPlan ? (
                  <div className="mt-4 space-y-4">
                    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                      <SummaryTile
                        label="Estimated Runtime"
                        value={`${trainingPlan.estimated_training_minutes || 0} min`}
                        hint={`Budget ${trainingPlan.time_budget_minutes || timeBudgetMinutes} min`}
                        accent="text-emerald-300"
                      />
                      <SummaryTile
                        label="Collector Window"
                        value={`${Math.round((trainingPlan.window_seconds || 0) / 3600)} h`}
                        hint="Full retrain data window"
                        accent="text-sky-300"
                      />
                      <SummaryTile
                        label="Event Cap"
                        value={formatNumber(trainingPlan.max_events)}
                        hint={`Current collector ${formatNumber(trainingPlan.collector?.total_events)}`}
                      />
                      <SummaryTile
                        label="Tracked Keys"
                        value={formatNumber(trainingPlan.collector?.unique_keys)}
                        hint={`Services ${formatNumber(trainingPlan.collector?.unique_services)}`}
                      />
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="rounded-2xl border border-dark-border bg-dark-card p-4">
                        <div className="text-sm font-semibold text-white">Ensemble Hyperparameters</div>
                        <div className="mt-3 space-y-2">
                          <InfoRow label="RF Trees" value={formatNumber(trainingPlan.hyperparameters?.random_forest?.n_estimators)} />
                          <InfoRow label="RF Max Depth" value={formatNumber(trainingPlan.hyperparameters?.random_forest?.max_depth)} />
                          <InfoRow label="LSTM Hidden Size" value={formatNumber(trainingPlan.hyperparameters?.lstm?.hidden_size)} />
                          <InfoRow label="LSTM Epoch Cap" value={formatNumber(trainingPlan.hyperparameters?.lstm?.epochs)} />
                          <InfoRow label="Batch Size" value={formatNumber(trainingPlan.hyperparameters?.lstm?.batch_size)} />
                        </div>
                      </div>
                      <div className="rounded-2xl border border-dark-border bg-dark-card p-4">
                        <div className="text-sm font-semibold text-white">Training Pipeline Controls</div>
                        <div className="mt-3 space-y-2">
                          <InfoRow label="Feature Selection" value={formatNumber(trainingPlan.hyperparameters?.training?.n_selected_features)} />
                          <InfoRow label="Augmentation Factor" value={`${Number(trainingPlan.hyperparameters?.training?.augmentation_factor || 0).toFixed(2)}x`} />
                          <InfoRow label="Balancing Strategy" value={String(trainingPlan.hyperparameters?.training?.data_balancing || 'auto')} />
                          <InfoRow label="Profile" value={trainingPlan.quality_profile} valueClassName="text-emerald-300" />
                        </div>
                      </div>
                    </div>

                    <div className="rounded-2xl border border-amber-500/25 bg-amber-500/10 p-4 text-sm text-amber-100">
                      {trainingPlan.notes}
                    </div>
                  </div>
                ) : (
                  <div className="mt-3 text-sm text-slate-500">Training plan not available yet.</div>
                )}
              </div>
              <div className="mt-6 flex flex-col gap-3 md:flex-row">
                <button
                  type="button"
                  onClick={handleTrainModel}
                  disabled={training}
                  className={`inline-flex flex-1 items-center justify-center gap-2 rounded-2xl px-5 py-3 font-medium transition ${
                    training
                      ? 'cursor-not-allowed bg-slate-700 text-slate-300'
                      : 'bg-accent-purple text-white hover:bg-accent-purple/85'
                  }`}
                >
                  <Icon name={training ? 'loader' : 'cpu'} className={`h-5 w-5 ${training ? 'animate-spin' : ''}`} />
                  <span>{training ? 'Training In Progress...' : 'Start Full Retraining'}</span>
                </button>
                <button
                  type="button"
                  onClick={handleEvaluateModel}
                  disabled={evaluating}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl border border-dark-border bg-dark-bg px-5 py-3 font-medium text-slate-200 transition hover:border-slate-500"
                >
                  <Icon name={evaluating ? 'loader' : 'refresh'} className={`h-5 w-5 ${evaluating ? 'animate-spin' : ''}`} />
                  <span>{evaluating ? 'Evaluating...' : 'Evaluate Active Model'}</span>
                </button>
                <button
                  type="button"
                  onClick={handleResetModel}
                  disabled={training}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl border border-red-700/50 bg-red-900/30 px-5 py-3 font-medium text-red-200 transition hover:bg-red-800/40"
                >
                  <Icon name="trash" className="h-5 w-5" />
                  <span>Reset Model</span>
                </button>
              </div>
            </div>

            {showTrainingProgress ? (
              <TrainingProgress onComplete={handleTrainingComplete} />
            ) : null}

            {trainSummary ? (
              <div className={`rounded-3xl border p-6 ${
                trainSummary.model_accepted
                  ? 'border-emerald-500/30 bg-emerald-500/10'
                  : 'border-amber-500/30 bg-amber-500/10'
              }`}>
                <div className={`flex items-center gap-3 text-lg font-semibold ${
                  trainSummary.model_accepted ? 'text-emerald-200' : 'text-amber-200'
                }`}>
                  <Icon name={trainSummary.model_accepted ? 'check' : 'info'} className="h-5 w-5" />
                  <span>{trainSummary.model_accepted ? 'Training accepted and active model updated' : 'Training completed, existing active version retained'}</span>
                </div>
                <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  <SummaryTile label="Validation Top-1" value={formatPercent(trainSummary.val_accuracy)} hint={trainSummary.accuracy_confidence || 'attempt confidence'} />
                  <SummaryTile label="Validation Top-10" value={formatPercent(trainSummary.val_top_10_accuracy)} hint={`Profile ${trainSummary.quality_profile || qualityProfile}`} />
                  <SummaryTile label="Samples Used" value={formatNumber(trainSummary.sample_count)} hint={`Budget ${trainSummary.time_budget_minutes || timeBudgetMinutes} min`} />
                  <SummaryTile label="Training Time" value={formatDuration(trainSummary.training_time_s)} hint={`Estimated ${trainSummary.estimated_training_minutes || trainingPlan?.estimated_training_minutes || 0} min`} />
                </div>
              </div>
            ) : null}
          </div>

          <div className="space-y-6">
            <div className="rounded-3xl border border-dark-border bg-dark-card p-6">
              <h2 className="text-xl font-semibold text-white">Runtime Model Status</h2>
              <p className="mt-2 text-sm text-slate-400">
                Active runtime metadata and the latest accepted vs latest attempted training evidence.
              </p>
              {loadingStatus ? (
                <div className="mt-6 flex items-center gap-3 text-slate-400">
                  <Icon name="loader" className="h-5 w-5 animate-spin" />
                  <span>Loading runtime status...</span>
                </div>
              ) : (
                <div className="mt-6 divide-y divide-dark-border">
                  <InfoRow label="Model Name" value={mlStatus?.model_name || 'pskc_model'} />
                  <InfoRow label="Active Version" value={formatVersion(mlStatus?.model_version)} valueClassName="font-mono text-sky-300" />
                  <InfoRow label="Stage" value={mlStatus?.model_stage || 'development'} />
                  <InfoRow label="Active Top-1" value={formatPercent(mlStatus?.model_accuracy)} />
                  <InfoRow label="Active Top-10" value={formatPercent(mlStatus?.model_top_10_accuracy)} />
                  <InfoRow label="Accuracy Basis" value={`${formatNumber(mlStatus?.accepted_validation_samples)} val samples`} />
                  <InfoRow label="Confidence" value={mlStatus?.accuracy_confidence || 'unknown'} valueClassName="text-amber-200" />
                  <InfoRow label="Last Trained" value={formatTimestamp(mlStatus?.last_trained_at)} />
                  <InfoRow label="Latest Attempt Top-1" value={formatPercent(mlStatus?.last_attempt_accuracy)} />
                  <InfoRow label="Latest Attempt Top-10" value={formatPercent(mlStatus?.last_attempt_top_10_accuracy)} />
                  <InfoRow label="Latest Attempt Result" value={mlStatus?.last_attempt_accepted ? 'Accepted' : 'Retained active model'} valueClassName={mlStatus?.last_attempt_accepted ? 'text-emerald-300' : 'text-amber-300'} />
                </div>
              )}
            </div>

            <div className="rounded-3xl border border-dark-border bg-dark-card p-6">
              <h2 className="text-xl font-semibold text-white">Quick Actions</h2>
              <div className="mt-5 space-y-3">
                <button
                  type="button"
                  onClick={async () => {
                    await loadMLStatus()
                    await loadTrainingPlan()
                  }}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-dark-border bg-dark-bg px-4 py-3 text-slate-200 transition hover:border-slate-500"
                >
                  <Icon name="refresh" className="h-4 w-4" />
                  <span>Refresh Runtime Status</span>
                </button>
                <button
                  type="button"
                  onClick={() => apiClient.post('/ml/data/import').then(async () => {
                    await loadMLStatus()
                    await loadTrainingPlan()
                  })}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-dark-border bg-dark-bg px-4 py-3 text-slate-200 transition hover:border-slate-500"
                >
                  <Icon name="database" className="h-4 w-4" />
                  <span>Import Default Dataset</span>
                </button>
                <button
                  type="button"
                  onClick={() => apiClient.post('/ml/retrain').then(loadMLStatus)}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-dark-border bg-dark-bg px-4 py-3 text-slate-200 transition hover:border-slate-500"
                >
                  <Icon name="cpu" className="h-4 w-4" />
                  <span>Quick Runtime Retrain</span>
                </button>
              </div>
            </div>

            {evaluationResult ? (
              <div className="rounded-3xl border border-dark-border bg-dark-card p-6">
                <h2 className="text-xl font-semibold text-white">Latest Evaluation</h2>
                <div className="mt-5 grid gap-4 md:grid-cols-2">
                  <SummaryTile label="Top-1" value={formatPercent(evaluationResult.top_1_accuracy)} />
                  <SummaryTile label="Top-10" value={formatPercent(evaluationResult.top_10_accuracy)} />
                  <SummaryTile label="Test Samples" value={formatNumber(evaluationResult.test_samples)} />
                  <SummaryTile label="Evaluated Version" value={formatVersion(evaluationResult.active_version)} />
                </div>
              </div>
            ) : null}

            <div className="rounded-3xl border border-dark-border bg-dark-card p-6">
              <h2 className="text-xl font-semibold text-white">Operational Notes</h2>
              <div className="mt-4 space-y-4 text-sm leading-6 text-slate-400">
                <p>Full retraining creates a persisted model version and appears in Model Intelligence history.</p>
                <p>Drift-triggered online learning uses River `partial_fit` and is intentionally separated so simulation can keep running.</p>
                <p>Validation accuracy here is honest validation on the held-out split. Live simulation accuracy can still differ if traffic drift or key churn is higher than the validation basis.</p>
                {savedProgressState ? (
                  <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-3 text-amber-100">
                    Saved progress detected: phase <span className="font-semibold">{savedProgressState.phase}</span>.
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default MLTraining
