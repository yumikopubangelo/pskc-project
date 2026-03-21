import React, { useState, useEffect, useCallback } from 'react'
import Icon from '../components/Icon'
import apiClient from '../utils/apiClient'

const MLTraining = () => {
  // Form state
  const [numEvents, setNumEvents] = useState(1000)
  const [numKeys, setNumKeys] = useState(100)
  const [numServices, setNumServices] = useState(5)
  const [scenario, setScenario] = useState('dynamic')
  const [trafficProfile, setTrafficProfile] = useState('normal')
  const [durationHours, setDurationHours] = useState(24)

  // UI state
  const [generating, setGenerating] = useState(false)
  const [training, setTraining] = useState(false)
  const [generateResult, setGenerateResult] = useState(null)
  const [trainResult, setTrainResult] = useState(null)
  const [evaluationResult, setEvaluationResult] = useState(null)
  const [error, setError] = useState(null)
  const [mlStatus, setMlStatus] = useState(null)
  const [loadingStatus, setLoadingStatus] = useState(true)
  const [evaluating, setEvaluating] = useState(false)

  // Scenarios and traffic profiles
  const scenarios = [
    { value: 'dynamic', label: 'Dynamic (Default)', description: 'General API patterns' },
    { value: 'siakad', label: 'SIAKAD', description: 'Academic information system' },
    { value: 'sevima', label: 'SEVIMA', description: 'Cloud education platform' },
    { value: 'pddikti', label: 'PDDIKTI', description: 'Higher education data' },
  ]

  const trafficProfiles = [
    { value: 'normal', label: 'Normal', description: 'Regular traffic with 80% cache hits' },
    { value: 'heavy', label: 'Heavy Load', description: 'Increased traffic with 60% cache hits' },
    { value: 'prime_time', label: 'Prime Time', description: 'Peak hours with 50% cache hits' },
    { value: 'overload', label: 'Overload', description: 'High stress with 20% cache hits' },
  ]

  // Load ML status on mount
  const loadMLStatus = useCallback(async () => {
    try {
      setLoadingStatus(true)
      const response = await apiClient.get('/ml/status')
      setMlStatus(response)
    } catch (err) {
      console.error('Failed to load ML status:', err)
      setError('Failed to load ML status')
    } finally {
      setLoadingStatus(false)
    }
  }, [])

  useEffect(() => {
    loadMLStatus()
  }, [loadMLStatus])

  // Generate training data
  const handleGenerateData = async () => {
  // Validate all fields are positive numbers
  if (!numEvents || numEvents <= 0 || !numKeys || numKeys <= 0 || !numServices || numServices <= 0 || !durationHours || durationHours <= 0) {
    setError('All numeric fields must be positive numbers')
    return
  }
  if (numEvents < 100 || numKeys < 10 || numServices > 20 || durationHours > 168) {
    setError('Events min 100, Keys min 10, Services max 20, Duration max 168')
    return
  }

  setGenerating(true)
  setError(null)
  setGenerateResult(null)

  try {
    const response = await apiClient.generateTrainingData({
      num_events: numEvents,
      num_keys: numKeys,
      num_services: numServices,
      scenario: scenario,
      traffic_profile: trafficProfile,
      duration_hours: durationHours,
    })
    setGenerateResult(response)
    await loadMLStatus()
  } catch (err) {
    console.error('Failed to generate training data:', err)
    setError(err.message || 'Failed to generate training data')
  } finally {
    setGenerating(false)
  }
}

  // Train model
  const handleTrainModel = async () => {
    setTraining(true)
    setError(null)
    setTrainResult(null)

    try {
      const response = await apiClient.trainModel({
        force: true,
        reason: 'manual',
      })
      setTrainResult(response)
      // Refresh ML status after training
      await loadMLStatus()
    } catch (err) {
      console.error('Failed to train model:', err)
      setError(err.message || 'Failed to train model')
    } finally {
      setTraining(false)
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

  // Get status badge color
  const getStatusColor = (status) => {
    switch (status) {
      case 'trained':
        return 'bg-green-500/20 text-green-400 border-green-500/30'
      case 'collecting_data':
        return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
      case 'ready_for_training':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/30'
      case 'not_trained':
        return 'bg-red-500/20 text-red-400 border-red-500/30'
      default:
        return 'bg-slate-500/20 text-slate-400 border-slate-500/30'
    }
  }

  // Format timestamp
  const formatTimestamp = (ts) => {
    if (!ts) return 'Not trained yet'
    try {
      return new Date(ts).toLocaleString()
    } catch {
      return ts
    }
  }

  return (
    <div className="min-h-screen p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-display text-white mb-2">ML Training</h1>
          <p className="text-slate-400">
            Generate training data and train the prediction model with organic traffic patterns
          </p>
        </div>

        {/* Error Display */}
        {error && (
          <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-lg">
            <div className="flex items-center gap-3 text-red-400">
              <Icon name="alert" className="w-5 h-5" />
              <span>{error}</span>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column - Configuration */}
          <div className="lg:col-span-2 space-y-6">
            {/* Training Data Generation Card */}
            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-lg bg-accent-blue/20 flex items-center justify-center">
                  <Icon name="database" className="w-5 h-5 text-accent-blue" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-white">Generate Training Data</h2>
                  <p className="text-sm text-slate-400">Create synthetic access patterns</p>
                </div>
              </div>

              {/* Scenario Selection */}
              <div className="mb-6">
                <label className="block text-sm font-medium text-slate-300 mb-3">Scenario</label>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {scenarios.map((s) => (
                    <button
                      key={s.value}
                      onClick={() => setScenario(s.value)}
                      className={`p-3 rounded-lg border text-left transition-all ${
                        scenario === s.value
                          ? 'bg-accent-blue/20 border-accent-blue/50 text-white'
                          : 'bg-dark-bg border-dark-border text-slate-400 hover:border-slate-500'
                      }`}
                    >
                      <div className="font-medium text-sm">{s.label}</div>
                      <div className="text-xs opacity-70 mt-1">{s.description}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Traffic Profile Selection */}
              <div className="mb-6">
                <label className="block text-sm font-medium text-slate-300 mb-3">Traffic Profile</label>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {trafficProfiles.map((t) => (
                    <button
                      key={t.value}
                      onClick={() => setTrafficProfile(t.value)}
                      className={`p-3 rounded-lg border text-left transition-all ${
                        trafficProfile === t.value
                          ? 'bg-accent-purple/20 border-accent-purple/50 text-white'
                          : 'bg-dark-bg border-dark-border text-slate-400 hover:border-slate-500'
                      }`}
                    >
                      <div className="font-medium text-sm">{t.label}</div>
                      <div className="text-xs opacity-70 mt-1">{t.description}</div>
                    </button>
                  ))}
                </div>
              </div>

               {/* Numeric Inputs */}
               <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                 <div>
                   <label className="block text-sm font-medium text-slate-300 mb-2">Events</label>
                   <input
                     type="number"
                     value={numEvents || ''}
                     onChange={(e) => setNumEvents(e.target.value ? parseInt(e.target.value) : '')}
                     className="w-full bg-dark-bg border border-dark-border rounded-lg px-4 py-2 text-white focus:border-accent-blue focus:outline-none"
                     min={0}
                     max={10000}
                   />
                 </div>
                 <div>
                   <label className="block text-sm font-medium text-slate-300 mb-2">Keys</label>
                   <input
                     type="number"
                     value={numKeys || ''}
                     onChange={(e) => setNumKeys(e.target.value ? parseInt(e.target.value) : '')}
                     className="w-full bg-dark-bg border border-dark-border rounded-lg px-4 py-2 text-white focus:border-accent-blue focus:outline-none"
                     min={0}
                     max={1000}
                   />
                 </div>
                 <div>
                   <label className="block text-sm font-medium text-slate-300 mb-2">Services</label>
                   <input
                     type="number"
                     value={numServices || ''}
                     onChange={(e) => setNumServices(e.target.value ? parseInt(e.target.value) : '')}
                     className="w-full bg-dark-bg border border-dark-border rounded-lg px-4 py-2 text-white focus:border-accent-blue focus:outline-none"
                     min={0}
                     max={20}
                   />
                 </div>
                 <div>
                   <label className="block text-sm font-medium text-slate-300 mb-2">Duration (hours)</label>
                   <input
                     type="number"
                     value={durationHours || ''}
                     onChange={(e) => setDurationHours(e.target.value ? parseInt(e.target.value) : '')}
                     className="w-full bg-dark-bg border border-dark-border rounded-lg px-4 py-2 text-white focus:border-accent-blue focus:outline-none"
                     min={0}
                     max={168}
                   />
                 </div>
               </div>

              {/* Generate Button */}
              <button
                onClick={handleGenerateData}
                disabled={generating}
                className={`w-full flex items-center justify-center gap-2 px-6 py-3 rounded-lg font-medium transition-all ${
                  generating
                    ? 'bg-slate-600 cursor-not-allowed'
                    : 'bg-accent-blue hover:bg-accent-blue/80'
                }`}
              >
                {generating ? (
                  <>
                    <Icon name="loader" className="w-5 h-5 animate-spin" />
                    <span>Generating...</span>
                  </>
                ) : (
                  <>
                    <Icon name="database" className="w-5 h-5" />
                    <span>Generate Training Data</span>
                  </>
                )}
              </button>

              {/* Generate Result */}
              {generateResult && (
                <div className="mt-4 p-4 bg-green-500/10 border border-green-500/30 rounded-lg">
                  <div className="flex items-center gap-2 text-green-400 mb-2">
                    <Icon name="check" className="w-5 h-5" />
                    <span className="font-medium">Data Generated Successfully</span>
                  </div>
                  <div className="grid grid-cols-3 gap-4 text-sm">
                    <div>
                      <span className="text-slate-400">Events Generated:</span>
                      <span className="text-white ml-2">{generateResult.events_generated}</span>
                    </div>
                    <div>
                      <span className="text-slate-400">Events Imported:</span>
                      <span className="text-white ml-2">{generateResult.events_imported}</span>
                    </div>
                    <div>
                      <span className="text-slate-400">Scenario:</span>
                      <span className="text-white ml-2">{generateResult.scenario}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Model Training Card */}
            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-lg bg-accent-purple/20 flex items-center justify-center">
                  <Icon name="cpu" className="w-5 h-5 text-accent-purple" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-white">Train Model</h2>
                  <p className="text-sm text-slate-400">Train the ML model with generated data</p>
                </div>
              </div>

              <div className="bg-dark-bg rounded-lg p-4 mb-6">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-400">Available Samples:</span>
                  <span className="text-white font-medium">
                    {mlStatus ? mlStatus.sample_count || 0 : 'Loading...'}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm mt-2">
                  <span className="text-slate-400">Minimum Required:</span>
                  <span className="text-white font-medium">100</span>
                </div>
              </div>

              {/* Train Button */}
              <button
                onClick={handleTrainModel}
                disabled={training}
                className={`w-full flex items-center justify-center gap-2 px-6 py-3 rounded-lg font-medium transition-all ${
                  training
                    ? 'bg-slate-600 cursor-not-allowed'
                    : 'bg-accent-purple hover:bg-accent-purple/80'
                }`}
              >
                {training ? (
                  <>
                    <Icon name="loader" className="w-5 h-5 animate-spin" />
                    <span>Training...</span>
                  </>
                ) : (
                  <>
                    <Icon name="cpu" className="w-5 h-5" />
                    <span>Train Model</span>
                  </>
                )}
              </button>

              {/* Train Result */}
              {trainResult && (
                <div className={`mt-4 p-4 border rounded-lg ${
                  trainResult.model_accepted
                    ? 'bg-green-500/10 border-green-500/30'
                    : 'bg-yellow-500/10 border-yellow-500/30'
                }`}>
                  <div className={`flex items-center gap-2 mb-2 ${
                    trainResult.model_accepted ? 'text-green-400' : 'text-yellow-400'
                  }`}>
                    <Icon name={trainResult.model_accepted ? 'check' : 'info'} className="w-5 h-5" />
                    <span className="font-medium">
                      {trainResult.model_accepted
                        ? 'Training Completed and Model Updated'
                        : 'Training Evaluated, Existing Version Retained'}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <span className="text-slate-400">Model Version:</span>
                      <span className="text-white ml-2">{trainResult.model_version || 'N/A'}</span>
                    </div>
                    <div>
                      <span className="text-slate-400">Samples Used:</span>
                      <span className="text-white ml-2">{trainResult.sample_count || 'N/A'}</span>
                    </div>
                    <div>
                      <span className="text-slate-400">Accuracy:</span>
                      <span className="text-white ml-2">
                        {trainResult.val_accuracy != null ? `${(trainResult.val_accuracy * 100).toFixed(1)}%` : 'N/A'}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400">Top-10:</span>
                      <span className="text-white ml-2">
                        {trainResult.val_top_10_accuracy != null ? `${(trainResult.val_top_10_accuracy * 100).toFixed(1)}%` : 'N/A'}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400">Training Time:</span>
                      <span className="text-white ml-2">
                        {trainResult.training_time_s != null ? `${trainResult.training_time_s.toFixed(2)}s` : 'N/A'}
                      </span>
                    </div>
                  </div>
                  {!trainResult.model_accepted && (
                    <div className="mt-3 text-sm text-yellow-300/90">
                      Active version tetap dipakai karena model baru belum menunjukkan peningkatan yang cukup.
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Right Column - Model Status */}
          <div className="space-y-6">
            {/* Current Model Status */}
            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-lg bg-accent-green/20 flex items-center justify-center">
                  <Icon name="info" className="w-5 h-5 text-accent-green" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-white">Model Status</h2>
                  <p className="text-sm text-slate-400">Current ML model information</p>
                </div>
              </div>

              {loadingStatus ? (
                <div className="flex items-center justify-center py-8">
                  <Icon name="loader" className="w-8 h-8 animate-spin text-slate-400" />
                </div>
              ) : mlStatus ? (
                <div className="space-y-4">
                  {/* Model Name */}
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Model Name</div>
                    <div className="text-white font-medium">{mlStatus.model_name || 'pskc_model'}</div>
                  </div>

                  {/* Model Version */}
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Version</div>
                    <div className="text-white font-mono">{mlStatus.model_version || 'v0.0.0'}</div>
                  </div>

                  {/* Status */}
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Status</div>
                    <span className={`inline-flex px-3 py-1 rounded-full text-xs font-medium border ${getStatusColor(mlStatus.status_code)}`}>
                      {mlStatus.status_code === 'trained' ? 'Trained' : 
                       mlStatus.status_code === 'collecting_data' ? 'Collecting Data' :
                       mlStatus.status_code === 'ready_for_training' ? 'Ready for Training' :
                       mlStatus.status_code === 'not_trained' ? 'Not Trained' : mlStatus.status_code}
                    </span>
                  </div>

                  {/* Accuracy */}
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Accuracy</div>
                    <div className="flex items-baseline gap-2">
                      <span className="text-2xl font-bold text-white">
                        {mlStatus.model_accuracy != null && !isNaN(mlStatus.model_accuracy) 
                          ? `${(mlStatus.model_accuracy * 100).toFixed(1)}%` 
                          : 'N/A'}
                      </span>
                      {mlStatus.is_learning && (
                        <span className="text-xs text-yellow-400 flex items-center gap-1">
                          <Icon name="loader" className="w-3 h-3 animate-spin" />
                          Learning
                        </span>
                      )}
                    </div>
                    <div className="mt-1 text-xs text-slate-400">
                      Top-10: {mlStatus.model_top_10_accuracy != null && !isNaN(mlStatus.model_top_10_accuracy)
                        ? `${(mlStatus.model_top_10_accuracy * 100).toFixed(1)}%`
                        : 'N/A'}
                    </div>
                  </div>

                  {/* Last Trained */}
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Last Trained</div>
                    <div className="text-white text-sm">{formatTimestamp(mlStatus.last_trained_at)}</div>
                  </div>

                  {/* Stage */}
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Stage</div>
                    <div className="text-white">{mlStatus.model_stage || 'production'}</div>
                  </div>

                  {mlStatus.last_training_attempt && (
                    <div>
                      <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Last Training Attempt</div>
                      <div className="text-sm text-slate-300">
                        {mlStatus.last_training_attempt.accepted ? 'Accepted' : 'Retained current version'}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-center py-8 text-slate-400">
                  <Icon name="alert" className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p>Failed to load model status</p>
                </div>
              )}
            </div>

            {/* Quick Actions */}
            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <h3 className="text-lg font-semibold text-white mb-4">Quick Actions</h3>
              <div className="space-y-3">
                <button
                  onClick={loadMLStatus}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-dark-bg hover:bg-dark-border rounded-lg text-slate-300 hover:text-white transition-all"
                >
                  <Icon name="refresh" className="w-4 h-4" />
                  <span>Refresh Status</span>
                </button>
                <button
                  onClick={handleEvaluateModel}
                  disabled={evaluating}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-dark-bg hover:bg-dark-border rounded-lg text-slate-300 hover:text-white transition-all disabled:opacity-60"
                >
                  <Icon name={evaluating ? "loader" : "cpu"} className={`w-4 h-4 ${evaluating ? 'animate-spin' : ''}`} />
                  <span>{evaluating ? 'Evaluating...' : 'Evaluate Model'}</span>
                </button>
                <button
                  onClick={() => apiClient.post('/ml/data/import').then(() => loadMLStatus())}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-dark-bg hover:bg-dark-border rounded-lg text-slate-300 hover:text-white transition-all"
                >
                  <Icon name="database" className="w-4 h-4" />
                  <span>Import Default Data</span>
                </button>
                <button
                  onClick={() => apiClient.post('/ml/retrain').then(() => loadMLStatus())}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-dark-bg hover:bg-dark-border rounded-lg text-slate-300 hover:text-white transition-all"
                >
                  <Icon name="cpu" className="w-4 h-4" />
                  <span>Quick Retrain</span>
                </button>
              </div>
            </div>

            {evaluationResult && (
              <div className="bg-dark-card border border-dark-border rounded-xl p-6">
                <h3 className="text-lg font-semibold text-white mb-4">Latest Evaluation</h3>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Top-1 Accuracy</div>
                    <div className="text-white font-semibold">
                      {evaluationResult.top_1_accuracy != null ? `${(evaluationResult.top_1_accuracy * 100).toFixed(1)}%` : 'N/A'}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Top-10 Accuracy</div>
                    <div className="text-white font-semibold">
                      {evaluationResult.top_10_accuracy != null ? `${(evaluationResult.top_10_accuracy * 100).toFixed(1)}%` : 'N/A'}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Test Samples</div>
                    <div className="text-white">{evaluationResult.test_samples ?? 'N/A'}</div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Active Version</div>
                    <div className="text-white font-mono">{evaluationResult.active_version || 'N/A'}</div>
                  </div>
                </div>
              </div>
            )}

            {/* Help Text */}
            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <h3 className="text-lg font-semibold text-white mb-4">How It Works</h3>
              <div className="space-y-4 text-sm text-slate-400">
                <div className="flex gap-3">
                  <div className="w-6 h-6 rounded-full bg-accent-blue/20 flex items-center justify-center flex-shrink-0">
                    <span className="text-accent-blue text-xs font-bold">1</span>
                  </div>
                  <p>Select a scenario and traffic profile that matches your system</p>
                </div>
                <div className="flex gap-3">
                  <div className="w-6 h-6 rounded-full bg-accent-purple/20 flex items-center justify-center flex-shrink-0">
                    <span className="text-accent-purple text-xs font-bold">2</span>
                  </div>
                  <p>Generate synthetic training data with realistic access patterns</p>
                </div>
                <div className="flex gap-3">
                  <div className="w-6 h-6 rounded-full bg-green-500/20 flex items-center justify-center flex-shrink-0">
                    <span className="text-green-400 text-xs font-bold">3</span>
                  </div>
                  <p>Train the model to learn prefetching patterns</p>
                </div>
                <div className="flex gap-3">
                  <div className="w-6 h-6 rounded-full bg-yellow-500/20 flex items-center justify-center flex-shrink-0">
                    <span className="text-yellow-400 text-xs font-bold">4</span>
                  </div>
                  <p>Model continuously learns from live traffic (incremental learning)</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default MLTraining
