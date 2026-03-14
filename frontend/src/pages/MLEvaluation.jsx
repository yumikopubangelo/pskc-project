import React, { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar } from 'recharts'

const MLEvaluation = () => {
  const [loading, setLoading] = useState(false)
  const [metrics, setMetrics] = useState(null)
  const [confusionMatrix, setConfusionMatrix] = useState(null)
  const [confidenceDist, setConfidenceDist] = useState(null)
  const [numSamples, setNumSamples] = useState(500)

  const runEvaluation = async () => {
    setLoading(true)
    try {
      const response = await fetch(`/api/ml/evaluation/run?num_samples=${numSamples}`, {
        method: 'POST',
      })
      const data = await response.json()
      if (data.success) {
        setMetrics(data.metrics)
        setConfusionMatrix(data.confusion_matrix)
        setConfidenceDist(data.confidence_distribution)
      }
    } catch (error) {
      console.error('Evaluation failed:', error)
    }
    setLoading(false)
  }

  const getEvaluationResults = async () => {
    try {
      const response = await fetch('/api/ml/evaluation/results')
      const data = await response.json()
      if (data.history && data.history.length > 0) {
        setMetrics(data.history[data.history.length - 1])
        setConfusionMatrix(data.confusion_matrix)
        setConfidenceDist(data.confidence_distribution)
      }
    } catch (error) {
      console.error('Failed to get results:', error)
    }
  }

  useEffect(() => {
    getEvaluationResults()
  }, [])

  const confidenceData = confidenceDist ? Object.entries(confidenceDist.buckets).map(([range, count]) => ({
    range,
    count,
  })) : []

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">ML Model Evaluation</h1>
          <p className="text-slate-400">Comprehensive model performance testing and metrics</p>
        </div>
      </div>

      {/* Control Panel */}
      <div className="bg-dark-card rounded-xl border border-dark-border p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Run Evaluation</h2>
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="block text-sm text-slate-400 mb-1">Test Samples</label>
            <input
              type="number"
              value={numSamples}
              onChange={(e) => setNumSamples(Number(e.target.value))}
              className="bg-dark-bg border border-dark-border rounded-lg px-4 py-2 text-white w-40"
              min={100}
              max={5000}
            />
          </div>
          <button
            onClick={runEvaluation}
            disabled={loading}
            className="bg-accent-blue hover:bg-accent-blue/80 disabled:opacity-50 text-white px-6 py-2 rounded-lg font-medium transition-colors"
          >
            {loading ? 'Running...' : 'Run Evaluation'}
          </button>
        </div>
      </div>

      {/* Metrics Display */}
      {metrics && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-dark-card rounded-xl border border-dark-border p-6">
            <div className="text-sm text-slate-400 mb-1">Precision</div>
            <div className="text-3xl font-bold text-white">{(metrics.precision * 100).toFixed(1)}%</div>
          </div>
          <div className="bg-dark-card rounded-xl border border-dark-border p-6">
            <div className="text-sm text-slate-400 mb-1">Recall</div>
            <div className="text-3xl font-bold text-white">{(metrics.recall * 100).toFixed(1)}%</div>
          </div>
          <div className="bg-dark-card rounded-xl border border-dark-border p-6">
            <div className="text-sm text-slate-400 mb-1">F1-Score</div>
            <div className="text-3xl font-bold text-white">{(metrics.f1_score * 100).toFixed(1)}%</div>
          </div>
          <div className="bg-dark-card rounded-xl border border-dark-border p-6">
            <div className="text-sm text-slate-400 mb-1">Accuracy</div>
            <div className="text-3xl font-bold text-white">{(metrics.accuracy * 100).toFixed(1)}%</div>
          </div>
        </div>
      )}

      {/* Confidence Distribution */}
      {confidenceDist && (
        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Prediction Confidence Distribution</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={confidenceData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="range" stroke="#9CA3AF" />
                <YAxis stroke="#9CA3AF" />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                  labelStyle={{ color: '#fff' }}
                />
                <Bar dataKey="count" fill="#3B82F6" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 text-center">
            <span className="text-slate-400">Average Confidence: </span>
            <span className="text-white font-semibold">{(confidenceDist.avg_confidence * 100).toFixed(1)}%</span>
            <span className="text-slate-400 ml-2">({confidenceDist.total_predictions} predictions)</span>
          </div>
        </div>
      )}

      {/* Confusion Matrix */}
      {confusionMatrix && confusionMatrix.matrix && (
        <div className="bg-dark-card rounded-xl border border-dark-border p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Confusion Matrix</h2>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="p-2 text-slate-400"></th>
                  {confusionMatrix.labels.slice(0, 10).map((label) => (
                    <th key={label} className="p-2 text-slate-400 text-xs">{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {confusionMatrix.labels.slice(0, 10).map((actualLabel, i) => (
                  <tr key={actualLabel}>
                    <td className="p-2 text-slate-400 text-xs">{actualLabel}</td>
                    {confusionMatrix.matrix[i]?.slice(0, 10).map((value, j) => (
                      <td
                        key={j}
                        className={`p-2 text-center ${
                          i === j
                            ? 'bg-green-900/50 text-green-400'
                            : value > 0
                            ? 'bg-red-900/50 text-red-400'
                            : 'text-slate-500'
                        }`}
                      >
                        {value}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 text-center text-slate-400">
            Total Samples: {confusionMatrix.total_samples} | Accuracy: {(confusionMatrix.accuracy * 100).toFixed(1)}%
          </div>
        </div>
      )}

      {/* Target Metrics */}
      <div className="bg-dark-card rounded-xl border border-dark-border p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Target Metrics (80% Accuracy Goal)</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="text-center p-4 rounded-lg bg-dark-bg">
            <div className="text-2xl font-bold text-emerald-400">80%</div>
            <div className="text-sm text-slate-400">Target Accuracy</div>
          </div>
          <div className="text-center p-4 rounded-lg bg-dark-bg">
            <div className="text-2xl font-bold text-emerald-400">80%</div>
            <div className="text-sm text-slate-400">Target Precision</div>
          </div>
          <div className="text-center p-4 rounded-lg bg-dark-bg">
            <div className="text-2xl font-bold text-emerald-400">80%</div>
            <div className="text-sm text-slate-400">Target Recall</div>
          </div>
          <div className="text-center p-4 rounded-lg bg-dark-bg">
            <div className="text-2xl font-bold text-emerald-400">80%</div>
            <div className="text-sm text-slate-400">Target F1-Score</div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default MLEvaluation
