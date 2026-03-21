import React, { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Icon from '../components/Icon'
import { apiClient } from '../utils/apiClient'

function MLPipeline() {
  const backendOnly = { allowMockFallback: false }
  const [activeStep, setActiveStep] = useState(0)
  const [mlStatus, setMlStatus] = useState({
    status: 'loading',
    model_loaded: false,
    last_training: null,
    sample_count: 0,
  })
  const [predictions, setPredictions] = useState([])
  const [loading, setLoading] = useState(true)
  const [retraining, setRetraining] = useState(false)
  const [error, setError] = useState(null)
  const [actionMessage, setActionMessage] = useState(null)

  const formatTimestamp = (value) => {
    if (!value) {
      return 'No training record'
    }

    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) {
      return 'Invalid timestamp'
    }

    return parsed.toLocaleString()
  }

  const fetchMLStatus = async () => {
    try {
      const [statusData, predictionData] = await Promise.all([
        apiClient.getModelStatus(backendOnly),
        apiClient.getPredictions(backendOnly),
      ])

      setMlStatus({
        status: statusData.status_code || 'unknown',
        model_loaded: statusData.model_loaded || false,
        last_training: statusData.last_trained_at,
        sample_count: statusData.sample_count || 0,
      })
      setPredictions(Array.isArray(predictionData.predictions) ? predictionData.predictions : [])
      setError(null)
    } catch (err) {
      console.error('Failed to fetch ML status:', err)
      setMlStatus({
        status: 'unavailable',
        model_loaded: false,
        last_training: null,
        sample_count: 0,
      })
      setPredictions([])
      setError('Failed to load ML status from backend')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchMLStatus()
  }, [])

  const handleRetrain = async () => {
    setRetraining(true)
    setActionMessage(null)

    try {
      const response = await apiClient.triggerRetraining(backendOnly)
      await fetchMLStatus()
      setActionMessage(response.message || 'Retraining finished')
    } catch (err) {
      console.error('Failed to retrain model:', err)
      setActionMessage('Failed to trigger backend retraining')
      setError('Failed to trigger backend retraining')
    } finally {
      setRetraining(false)
    }
  }

  const pipelineHealthLabel = mlStatus.model_loaded
    ? 'Loaded'
    : mlStatus.status === 'artifact_present'
    ? 'Artifact present'
    : mlStatus.status === 'not_trained'
    ? 'Not trained'
    : mlStatus.status.replace(/_/g, ' ')

  const steps = [
    {
      id: 'data-collection',
      title: 'Data Collection',
      description:
        'Gathering key access patterns, request frequencies, and system metrics from all nodes in the distributed system.',
      icon: 'database',
      details: 'The data collection module continuously monitors:',
      points: [
        'API request timestamps and endpoints',
        'User authentication patterns',
        'Service-to-service key accesses',
        'Cache hit/miss events',
        'System load metrics',
      ],
      code: `class DataCollector:
    def __init__(self, config):
        self.buffer = EventBuffer(max_size=10000)
        self.metrics = MetricsCollector()

    async def collect(self, event: KeyAccessEvent):
        # Enrich event with metadata
        event.enrich(
            timestamp=datetime.utcnow(),
            node_id=get_node_id(),
            access_pattern=self.detect_pattern(event)
        )

        # Buffer for batch processing
        await self.buffer.add(event)

        # Emit real-time metrics
        self.metrics.increment('key_access_total')`,
      progress: 100,
    },
    {
      id: 'feature-engineering',
      title: 'Feature Engineering',
      description: 'Transforming raw data into meaningful features for ML model training and prediction.',
      icon: 'network',
      details: 'Key features extracted include:',
      points: [
        'Temporal patterns (hour, day, weekday)',
        'Access frequency per key',
        'User behavior sequences',
        'Service dependency graphs',
        'Historical cache states',
      ],
      code: `class FeatureEngineer:
    def extract_features(self, events: List[KeyAccessEvent]) -> FeatureVector:
        features = FeatureVector()

        # Temporal features
        features['hour_sin'] = np.sin(2 * np.pi * events[-1].hour / 24)
        features['hour_cos'] = np.cos(2 * np.pi * events[-1].hour / 24)

        # Frequency features
        features['key_frequency'] = self.compute_frequency(events)

        # Sequence features
        features['pattern_embedding'] = self.encode_sequence(events)

        return features.normalize()`,
      progress: 100,
    },
    {
      id: 'model-training',
      title: 'Model Training',
      description:
        'Training the prediction model using historical data to identify patterns and predict future key requests.',
      icon: 'brain',
      details: 'Training pipeline includes:',
      points: [
        'LSTM-based sequence model',
        'Attention mechanism for pattern detection',
        'Online learning for continuous improvement',
        'Cross-validation for model selection',
        'Hyperparameter optimization',
      ],
      code: `class ModelTrainer:
    def __init__(self, config):
        self.model = LSTMPredictor(
            hidden_dim=256,
            num_layers=3,
            attention_heads=4
        )
        self.optimizer = AdamW(lr=1e-3)

    async def train_epoch(self, batch: Batch):
        self.model.train()

        for sequence, labels in batch:
            prediction = self.model(sequence)
            loss = self.compute_loss(prediction, labels)

            loss.backward()
            self.optimizer.step()
            self.optimizer.zero_grad()

        return loss.item()`,
      progress: 100,
    },
    {
      id: 'prediction-precaching',
      title: 'Prediction and Pre-caching',
      description:
        'Using the trained model to predict future key requests and proactively caching keys before they are needed.',
      icon: 'lightning',
      details: 'The prediction engine:',
      points: [
        'Runs predictions every 100ms',
        'Generates top-K predicted keys',
        'Prioritizes by confidence score',
        'Triggers pre-cache operations',
        'Updates cache policy dynamically',
      ],
      code: `class PredictionEngine:
    def __init__(self, model, cache_client):
        self.model = model
        self.cache = cache_client
        self.confidence_threshold = 0.7

    async def predict_and_precache(self):
        # Generate predictions
        predictions = await self.model.predict(
            window_size=100,
            top_k=10
        )

        # Pre-cache high-confidence predictions
        for key, confidence in predictions:
            if confidence >= self.confidence_threshold:
                await self.cache.precache(
                    key=key,
                    ttl=self.compute_ttl(confidence)
                )`,
      progress: 100,
    },
    {
      id: 'monitoring',
      title: 'Monitoring and Feedback',
      description: 'Continuous monitoring of model performance and feedback loop for model improvement.',
      icon: 'chart',
      details: 'Monitoring encompasses:',
      points: [
        'Real-time accuracy tracking',
        'Latency impact measurement',
        'Cache hit rate monitoring',
        'Anomaly detection',
        'Automatic retraining triggers',
      ],
      code: `class ModelMonitor:
    def __init__(self, alert_service):
        self.metrics = PrometheusClient()
        self.alerts = alert_service

    async def record_prediction(self, prediction, actual):
        # Update accuracy metrics
        correct = prediction == actual
        self.metrics.increment('prediction_total')
        self.metrics.increment('prediction_correct', value=1 if correct else 0)

        # Check for anomalies
        accuracy = await self.metrics.get('prediction_accuracy')
        if accuracy < 0.85:
            await self.alerts.trigger('accuracy_degradation')`,
      progress: 100,
    },
  ]

  return (
    <div className="min-h-screen py-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center mb-8"
        >
          <h1 className="text-3xl md:text-4xl font-display font-bold text-white mb-4">ML Pipeline</h1>
          <p className="text-slate-400 max-w-2xl mx-auto">
            Explore the machine learning pipeline while reading real backend model status and prediction output.
          </p>
        </motion.div>

        {error ? (
          <div className="mb-8 rounded-xl border border-danger-red/40 bg-danger-red/10 px-4 py-3 text-sm text-slate-200">
            {error}. Halaman ini tidak lagi mengisi status ML dengan angka dummy.
          </div>
        ) : null}

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.1 }}
          className="gradient-card rounded-xl border border-dark-border p-6 mb-8"
        >
          <h3 className="text-lg font-semibold text-white mb-6">Pipeline Progress</h3>
          <div className="flex items-center justify-between gap-1">
            {steps.map((step, index) => (
              <React.Fragment key={step.id}>
                <div className="flex flex-col items-center">
                  <button
                    type="button"
                    onClick={() => setActiveStep(index)}
                    className={`w-12 h-12 rounded-full flex items-center justify-center transition-all ${
                      activeStep === index
                        ? 'bg-accent-blue glow-blue scale-110'
                        : index < activeStep
                        ? 'bg-accent-green'
                        : 'bg-dark-border'
                    }`}
                  >
                    {index < activeStep ? (
                      <Icon name="check" className="w-5 h-5 text-white" />
                    ) : (
                      <Icon name={step.icon} className="w-5 h-5 text-white" />
                    )}
                  </button>
                  <span
                    className={`text-xs mt-2 text-center hidden md:block ${
                      activeStep === index ? 'text-white' : 'text-slate-500'
                    }`}
                  >
                    {step.title}
                  </span>
                </div>
                {index < steps.length - 1 && (
                  <div className="flex-1 h-1 mx-2 bg-dark-border rounded-full overflow-hidden">
                    <motion.div className="h-full bg-accent-green" initial={{ width: 0 }} animate={{ width: index < activeStep ? '100%' : '0%' }} />
                  </div>
                )}
              </React.Fragment>
            ))}
          </div>
        </motion.div>

        <AnimatePresence mode="wait">
          <motion.div
            key={activeStep}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
            className="grid grid-cols-1 lg:grid-cols-2 gap-8"
          >
            <div className="space-y-6">
              <div className="gradient-card rounded-xl border border-dark-border p-6">
                <div className="flex items-center gap-4 mb-4">
                  <div className="w-14 h-14 rounded-xl bg-accent-blue/15 border border-accent-blue/40 flex items-center justify-center">
                    <Icon name={steps[activeStep].icon} className="w-7 h-7 text-accent-blue" />
                  </div>
                  <div>
                    <h3 className="text-2xl font-semibold text-white">{steps[activeStep].title}</h3>
                    <span className="text-accent-green text-sm">
                      Step {activeStep + 1} of {steps.length}
                    </span>
                  </div>
                </div>
                <p className="text-slate-400 mb-4">{steps[activeStep].description}</p>
                <p className="text-slate-300 font-medium mb-2">{steps[activeStep].details}</p>
                <ul className="space-y-2">
                  {steps[activeStep].points.map((point) => (
                    <li key={point} className="flex items-start gap-2 text-slate-400">
                      <span className="w-1.5 h-1.5 rounded-full bg-accent-blue mt-2 flex-shrink-0" />
                      <span>{point}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="gradient-card rounded-xl border border-dark-border p-6">
                <h4 className="text-lg font-semibold text-white mb-4">Current Pipeline Status</h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm mb-4">
                  <div className="rounded-lg bg-dark-bg/70 border border-dark-border p-3">
                    <div className="text-slate-500">Pipeline status</div>
                    <div className={`font-mono mt-1 ${error ? 'text-danger-red' : 'text-accent-green'}`}>
                      {loading ? 'Loading' : pipelineHealthLabel}
                    </div>
                  </div>
                  <div className="rounded-lg bg-dark-bg/70 border border-dark-border p-3">
                    <div className="text-slate-500">Samples</div>
                    <div className="text-white font-mono mt-1">{mlStatus.sample_count || 0}</div>
                  </div>
                  <div className="rounded-lg bg-dark-bg/70 border border-dark-border p-3">
                    <div className="text-slate-500">Predictions returned</div>
                    <div className="text-white font-mono mt-1">{predictions.length}</div>
                  </div>
                  <div className="rounded-lg bg-dark-bg/70 border border-dark-border p-3">
                    <div className="text-slate-500">Last training</div>
                    <div className="text-white font-mono mt-1 text-xs">{formatTimestamp(mlStatus.last_training)}</div>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 mb-4">
                  <button
                    type="button"
                    onClick={handleRetrain}
                    disabled={retraining}
                    className={`btn-primary text-sm ${retraining ? 'opacity-60 cursor-not-allowed' : ''}`}
                  >
                    {retraining ? 'Retraining...' : 'Run backend retraining'}
                  </button>
                  <button type="button" onClick={fetchMLStatus} className="btn-secondary text-sm">
                    Refresh status
                  </button>
                </div>
                {actionMessage ? (
                  <div className="rounded-lg bg-dark-bg/70 border border-dark-border px-3 py-2 text-sm text-slate-300 mb-4">
                    {actionMessage}
                  </div>
                ) : null}
                <div className="rounded-lg bg-dark-bg/70 border border-dark-border p-4">
                  <div className="text-slate-400 text-sm mb-3">Prediction output</div>
                  {predictions.length > 0 ? (
                    <div className="space-y-2">
                      {predictions.slice(0, 5).map((prediction, index) => (
                        <div key={`${prediction.key_id || prediction.key || 'prediction'}-${index}`} className="flex items-center justify-between text-sm">
                          <span className="text-slate-300">{prediction.key_id || prediction.key || `prediction-${index + 1}`}</span>
                          <span className="text-accent-blue font-mono">
                            {prediction.confidence !== undefined ? `${Number(prediction.confidence).toFixed(2)}` : 'n/a'}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-slate-500">
                      Backend belum mengembalikan prediction list. Ini lebih jujur daripada mengisi angka demo.
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="gradient-card rounded-xl border border-dark-border p-6">
              <div className="flex items-center justify-between mb-4">
                <h4 className="text-lg font-semibold text-white">Implementation</h4>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 bg-accent-green rounded-full animate-pulse" />
                  <span className="text-sm text-slate-400">Python</span>
                </div>
              </div>
              <div className="code-block overflow-x-auto">
                <pre className="text-sm">
                  <code
                    dangerouslySetInnerHTML={{
                      __html: steps[activeStep].code
                        .replace(/class/g, '<span class="keyword">class</span>')
                        .replace(/def/g, '<span class="keyword">def</span>')
                        .replace(/async/g, '<span class="keyword">async</span>')
                        .replace(/await/g, '<span class="keyword">await</span>')
                        .replace(/self/g, '<span class="keyword">self</span>')
                        .replace(/return/g, '<span class="keyword">return</span>')
                        .replace(/if/g, '<span class="keyword">if</span>')
                        .replace(/for/g, '<span class="keyword">for</span>')
                        .replace(/in/g, '<span class="keyword">in</span>')
                        .replace(/True|False/g, '<span class="keyword">$&</span>')
                        .replace(/#.*/g, '<span class="comment">$&</span>')
                        .replace(/"[^"]*"/g, '<span class="string">$&</span>')
                        .replace(/'[^']*'/g, '<span class="string">$&</span>')
                        .replace(/\b\d+\b/g, '<span class="number">$&</span>'),
                    }}
                  />
                </pre>
              </div>
            </div>
          </motion.div>
        </AnimatePresence>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3 }}
          className="flex justify-between mt-8"
        >
          <button
            type="button"
            onClick={() => setActiveStep(Math.max(0, activeStep - 1))}
            disabled={activeStep === 0}
            className={`btn-secondary ${activeStep === 0 ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            <span className="flex items-center gap-2">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
              Previous
            </span>
          </button>
          <button
            type="button"
            onClick={() => setActiveStep(Math.min(steps.length - 1, activeStep + 1))}
            disabled={activeStep === steps.length - 1}
            className={`btn-primary ${activeStep === steps.length - 1 ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            <span className="flex items-center gap-2">
              Next
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </span>
          </button>
        </motion.div>
      </div>
    </div>
  )
}

export default MLPipeline
