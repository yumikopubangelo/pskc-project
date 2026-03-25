import React, { useState, useEffect, useCallback } from 'react';
import apiClient from '../utils/apiClient';

const MLStatus = () => {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastSyncTime, setLastSyncTime] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  const fetchStatus = useCallback(async () => {
    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), 5000); // 5s timeout

    try {
      const data = await apiClient.getModelStatus();
      clearTimeout(timeoutId);
      setStatus(data);
      setError(null);
      setLastSyncTime(new Date().toLocaleTimeString());
      setRetryCount(0);
      setLoading(false);
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') {
        setError('Request timeout (5s). Server may be unresponsive.');
      } else {
        setError('Failed to fetch ML status. Retrying...');
      }
      setRetryCount(prev => prev + 1);
      setLoading(false);
      console.error('MLStatus fetch error:', err);
    }
  }, []);

  useEffect(() => {
    // Initial fetch
    fetchStatus();
    
    // Set up interval - but use a more intelligent retry strategy
    const pollInterval = error ? 5000 : 15000; // 5s if error, 15s if ok
    const interval = setInterval(fetchStatus, pollInterval);
    
    return () => clearInterval(interval);
  }, [fetchStatus, error]);

  const getStageColor = (stage) => {
    switch (stage) {
      case 'production':
        return 'text-green-400';
      case 'staging':
        return 'text-yellow-400';
      case 'archived':
        return 'text-gray-500';
      case 'validation':
        return 'text-blue-400';
      default:
        return 'text-white';
    }
  };

  const getStatusPill = (text, colorClass) => (
    <span className={`px-2 py-1 text-xs font-semibold rounded-full ${colorClass}`}>
      {text}
    </span>
  );

  const activeAccuracy = status?.model_accuracy;
  const activeTop10 = status?.model_top_10_accuracy;
  const activeValidationSamples = status?.accepted_validation_samples;
  const activeAccuracyConfidence = status?.accuracy_confidence;
  const activeAccuracyWarning = status?.accuracy_warning;
  const lastAttemptAccuracy = status?.last_attempt_accuracy;
  const lastAttemptTop10 = status?.last_attempt_top_10_accuracy;
  const lastAttemptAccepted = status?.last_attempt_accepted;
  const lastAttemptValidationSamples = status?.last_attempt_validation_samples;
  const lastAttemptConfidence = status?.last_attempt_accuracy_confidence;

  const renderLifecyclePill = () => {
    if (status?.status_code !== 'trained') {
      return getStatusPill('Learning', 'bg-blue-500/30 text-blue-300');
    }
    if (lastAttemptAccepted === false) {
      return getStatusPill('Retained Active Model', 'bg-yellow-500/30 text-yellow-300');
    }
    return getStatusPill('Active', 'bg-green-500/30 text-green-300');
  };

  const renderConfidencePill = (confidence) => {
    if (confidence === 'high') {
      return getStatusPill('High Confidence', 'bg-green-500/20 text-green-300');
    }
    if (confidence === 'medium') {
      return getStatusPill('Medium Confidence', 'bg-yellow-500/20 text-yellow-300');
    }
    return getStatusPill('Low Confidence', 'bg-amber-500/20 text-amber-300');
  };

  return (
    <div className="bg-dark-card rounded-lg p-4 border border-dark-border h-full">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-lg font-semibold">ML Model Status</h2>
        <div className="flex items-center gap-2 text-xs">
          {loading && <span className="text-blue-400">Loading...</span>}
          {!loading && !error && <span className="text-green-400">✓ Connected</span>}
          {error && <span className="text-red-400">✗ Error</span>}
          {lastSyncTime && <span className="text-gray-500">Synced: {lastSyncTime}</span>}
        </div>
      </div>
      
      {error && (
        <div className="mb-3 p-2 bg-red-500/10 border border-red-500/30 rounded text-red-300 text-sm">
          <p>{error} (Attempt {retryCount})</p>
          <button
            onClick={fetchStatus}
            className="mt-2 px-3 py-1 bg-red-600 hover:bg-red-700 rounded text-xs font-semibold transition-colors"
          >
            Retry Now
          </button>
        </div>
      )}
      
      {!status && !error && <p className="text-gray-400">Loading status...</p>}
      {status && (
        <div className="space-y-3 text-sm">
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Model Name:</span>
            <span className="font-mono text-blue-300">{status.model_name}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Active Version:</span>
            <span className="font-semibold text-white">{status.model_version || 'N/A'}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Stage:</span>
            {getStatusPill(status.model_stage, getStageColor(status.model_stage))}
          </div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Active Accuracy:</span>
            <span className={`font-semibold ${(activeAccuracy > 0.85 && !isNaN(activeAccuracy)) ? 'text-green-400' : 'text-yellow-400'}`}>
              {isNaN(activeAccuracy) ? 'N/A' : `${(activeAccuracy * 100).toFixed(2)}%`}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Active Top-10:</span>
            <span className="font-semibold text-white">
              {activeTop10 == null || isNaN(activeTop10) ? 'N/A' : `${(activeTop10 * 100).toFixed(2)}%`}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Accuracy Basis:</span>
            <span className="text-gray-300">
              {activeValidationSamples == null ? 'Unknown' : `${activeValidationSamples} val samples`}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Metric Confidence:</span>
            {renderConfidencePill(activeAccuracyConfidence)}
          </div>
          {activeAccuracyWarning && (
            <p className="text-xs text-amber-300/90">
              {activeAccuracyWarning}
            </p>
          )}
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Status:</span>
            {renderLifecyclePill()}
          </div>
          {status.last_training_attempt && (
            <div className="pt-2 border-t border-dark-border space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Latest Attempt:</span>
                <span className={lastAttemptAccepted === false ? 'text-yellow-300' : 'text-slate-200'}>
                  {lastAttemptAccepted === false ? 'Rejected' : lastAttemptAccepted === true ? 'Accepted' : 'Unknown'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Attempt Top-1:</span>
                <span className="text-slate-200">
                  {lastAttemptAccuracy == null || isNaN(lastAttemptAccuracy) ? 'N/A' : `${(lastAttemptAccuracy * 100).toFixed(2)}%`}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Attempt Top-10:</span>
                <span className="text-slate-200">
                  {lastAttemptTop10 == null || isNaN(lastAttemptTop10) ? 'N/A' : `${(lastAttemptTop10 * 100).toFixed(2)}%`}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Attempt Basis:</span>
                <span className="text-slate-200">
                  {lastAttemptValidationSamples == null ? 'Unknown' : `${lastAttemptValidationSamples} val samples`}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Attempt Confidence:</span>
                {renderConfidencePill(lastAttemptConfidence)}
              </div>
              {lastAttemptAccepted === false && (
                <p className="text-xs text-yellow-300/90">
                  Attempt terakhir tidak dipromosikan. Active model tetap memakai versi sebelumnya.
                </p>
              )}
            </div>
          )}
          <div className="flex justify-between items-center pt-2 border-t border-dark-border">
            <span className="text-gray-400">Last Trained:</span>
            <span className="text-gray-300">
              {status.last_trained_at ? new Date(status.last_trained_at).toLocaleString() : 'Not trained yet'}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

export default MLStatus;
