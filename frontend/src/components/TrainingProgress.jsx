/**
 * TrainingProgress.jsx - Real-time training progress component
 * 
 * Displays real-time training progress with:
 * - Progress bar showing completion percentage
 * - Current training phase indicator
 * - Live metrics (accuracy, loss, epoch)
 * - Estimated time remaining
 * - Per-model accuracy display
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { TrainingProgressWebSocket, TrainingProgressPoller } from '../utils/progressClient';

const PHASE_NAMES = {
  'idle': 'Idle',
  'loading_data': 'Loading Data',
  'preprocessing': 'Preprocessing',
  'feature_engineering': 'Feature Engineering',
  'data_balancing': 'Balancing Data',
  'data_augmentation': 'Augmenting Data',
  'splitting': 'Splitting Data',
  'training_lstm': 'Training LSTM',
  'training_rf': 'Training Random Forest',
  'updating_markov': 'Updating Markov Chain',
  'evaluation': 'Evaluation',
  'saving_model': 'Saving Model',
  'completed': 'Completed',
  'failed': 'Failed'
};

const PHASE_COLORS = {
  'idle': 'bg-gray-400',
  'loading_data': 'bg-blue-400',
  'preprocessing': 'bg-blue-500',
  'feature_engineering': 'bg-cyan-500',
  'data_balancing': 'bg-teal-500',
  'data_augmentation': 'bg-green-500',
  'splitting': 'bg-green-500',
  'training_lstm': 'bg-purple-600',
  'training_rf': 'bg-purple-600',
  'updating_markov': 'bg-purple-600',
  'evaluation': 'bg-orange-500',
  'saving_model': 'bg-yellow-500',
  'completed': 'bg-green-600',
  'failed': 'bg-red-600'
};

export default function TrainingProgress({ onComplete, useWebSocket = false }) {
  const [progress, setProgress] = useState({
    current_phase: 'idle',
    progress_percent: 0,
    latest_update: null,
    metrics: {
      train_accuracy: null,
      val_accuracy: null,
      train_loss: null,
      val_loss: null,
      epoch: 0,
      total_epochs: 0,
      samples_processed: 0,
      total_samples: 0
    },
    elapsed_seconds: 0,
    estimated_remaining_seconds: null
  });

  const [isConnected, setIsConnected] = useState(false);
  // true once we receive a non-idle phase — prevents rendering before training starts
  const [trainingStarted, setTrainingStarted] = useState(false);
  const progressClientRef = useRef(null);
  const elapsedTimerRef = useRef(null);
  const isActiveRef = useRef(false);
  const timeoutRef = useRef(null);
  const hasSeenProgressRef = useRef(false);
  // Only fire onComplete(failed) if training started but no completion received after 10 min
  const MAX_WAIT_TIME_MS = 600000;

  // Start local 1s interval to smoothly increment elapsed time between WS messages
  const startElapsedTimer = useCallback(() => {
    if (elapsedTimerRef.current) return;
    isActiveRef.current = true;
    elapsedTimerRef.current = setInterval(() => {
      if (!isActiveRef.current) return;
      setProgress(prev => {
        const phase = prev.current_phase;
        if (phase === 'completed' || phase === 'failed' || phase === 'idle') return prev;
        return { ...prev, elapsed_seconds: prev.elapsed_seconds + 1 };
      });
    }, 1000);
  }, []);

  const stopElapsedTimer = useCallback(() => {
    isActiveRef.current = false;
    if (elapsedTimerRef.current) {
      clearInterval(elapsedTimerRef.current);
      elapsedTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    // Set a timeout to handle cases where WebSocket doesn't connect or doesn't receive updates
    timeoutRef.current = setTimeout(() => {
      if (!hasSeenProgressRef.current) {
        console.log('Training progress timeout - calling onComplete');
        setIsConnected(false);
        stopElapsedTimer();
        if (onComplete) {
          onComplete({
            success: false,
            phase: 'failed',
            progress: 0,
            details: { error: 'WebSocket connection timeout' },
          });
        }
      }
    }, MAX_WAIT_TIME_MS);

    // Initialize progress tracking (WebSocket or polling)
    if (useWebSocket) {
      const wsClient = new TrainingProgressWebSocket();
      progressClientRef.current = wsClient;

      wsClient.onUpdate((update) => {
        if (update._source === 'saved_state') return;

        hasSeenProgressRef.current = true;
        if (update.phase && update.phase !== 'idle') {
          setTrainingStarted(true);
        }

        const elapsed = typeof update.elapsed_seconds === 'number'
          ? update.elapsed_seconds
          : null;

        setProgress(prev => {
          const elapsedVal = elapsed !== null ? elapsed : prev.elapsed_seconds;

          let newMetrics = { ...prev.metrics };
          if (update.details) {
            newMetrics = { ...newMetrics, ...update.details };
          }
          if (update.train_accuracy !== undefined) newMetrics.train_accuracy = update.train_accuracy;
          if (update.val_accuracy !== undefined) newMetrics.val_accuracy = update.val_accuracy;
          if (update.train_loss !== undefined) newMetrics.train_loss = update.train_loss;
          if (update.val_loss !== undefined) newMetrics.val_loss = update.val_loss;
          if (update.epoch !== undefined) newMetrics.epoch = update.epoch;
          if (update.total_epochs !== undefined) newMetrics.total_epochs = update.total_epochs;
          if (update.samples_processed !== undefined) newMetrics.samples_processed = update.samples_processed;
          if (update.total_samples !== undefined) newMetrics.total_samples = update.total_samples;

          return {
            ...prev,
            current_phase: update.phase || prev.current_phase,
            progress_percent: update.progress_percent ?? prev.progress_percent,
            latest_update: update,
            elapsed_seconds: elapsedVal,
            estimated_remaining_seconds: calculateETA(update.progress_percent ?? prev.progress_percent, elapsedVal),
            metrics: newMetrics,
          };
        });

        const phase = update.phase;
        if (phase && phase !== 'idle' && phase !== 'completed' && phase !== 'failed') {
          startElapsedTimer();
        }

        if (phase === 'completed' || phase === 'failed') {
          stopElapsedTimer();
          setIsConnected(false);
          clearTimeout(timeoutRef.current);
          if (onComplete) {
            onComplete({
              success: phase === 'completed',
              phase: phase,
              progress: update.progress_percent,
              details: update.details || {},
            });
          }
        }
      });

      wsClient.connect();
      setIsConnected(true);

      return () => {
        clearTimeout(timeoutRef.current);
        stopElapsedTimer();
        wsClient.disconnect();
      };
    } else {
      // Fallback to polling
      const poller = new TrainingProgressPoller();
      progressClientRef.current = poller;

      poller.onUpdate((update) => {
        const latestUpdate = update.latest_update;
        if (latestUpdate) {
          hasSeenProgressRef.current = true;
          if (latestUpdate.phase && latestUpdate.phase !== 'idle') {
            setTrainingStarted(true);
            setIsConnected(true);
          }

          const pct = latestUpdate.progress_percent ?? 0;
          const details = latestUpdate.details || {};
          setProgress(prev => ({
            ...prev,
            ...update,
            current_phase: latestUpdate.phase || 'idle',
            progress_percent: pct,
            estimated_remaining_seconds: calculateETA(pct, update.elapsed_seconds ?? 0),
            metrics: { ...prev.metrics, ...details },
          }));

          if (latestUpdate.phase === 'completed' || latestUpdate.phase === 'failed') {
            poller.stop();
            clearTimeout(timeoutRef.current);
            if (onComplete) {
              onComplete({
                success: latestUpdate.phase === 'completed',
                phase: latestUpdate.phase,
                progress: update.progress_percent
              });
            }
          }
        }
      });

      poller.start();

      return () => {
        clearTimeout(timeoutRef.current);
        stopElapsedTimer();
        poller.stop();
      };
    }
  }, [onComplete, useWebSocket, startElapsedTimer, stopElapsedTimer]);

  const calculateETA = (percent, elapsed) => {
    if (percent === 0 || elapsed === 0) return null;
    const totalEstimated = (elapsed / percent) * 100;
    return Math.max(0, totalEstimated - elapsed);
  };

  const formatSeconds = (seconds) => {
    if (!seconds) return '--';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  const formatPercent = (val) => {
    if (val === null || val === undefined || isNaN(val)) return '--';
    // If val is already a percentage (0-100), don't multiply
    // If val is a decimal (0-1), multiply by 100
    const numVal = Number(val);
    if (numVal <= 1) {
      return `${(numVal * 100).toFixed(1)}%`;
    }
    return `${numVal.toFixed(1)}%`;
  };

  if (!trainingStarted) {
    return (
      <div className="w-full bg-white rounded-lg shadow-lg p-6 border border-gray-200">
        <div className="flex items-center gap-3 text-gray-500 py-4">
          <div className="w-4 h-4 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin" />
          <span>Waiting for training to start...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full bg-white rounded-lg shadow-lg p-6 border border-gray-200">
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold text-gray-800">Training Progress</h2>
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-green-500' : 'bg-gray-400'}`} />
          <span className="text-sm text-gray-600">{isConnected ? 'Live' : 'Polling'}</span>
        </div>
      </div>

      {/* Phase Indicator */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <span className={`px-4 py-2 rounded-full text-white font-semibold ${PHASE_COLORS[progress.current_phase] || 'bg-gray-500'}`}>
            {PHASE_NAMES[progress.current_phase] || progress.current_phase}
          </span>
          {progress.latest_update && (
            <span className="text-gray-600 text-sm">{progress.latest_update.message}</span>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mb-6">
        <div className="flex justify-between items-center mb-2">
          <span className="text-gray-700 font-medium">Progress</span>
          <span className="text-lg font-bold text-blue-600">{(progress.progress_percent || 0).toFixed(1)}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-4 overflow-hidden">
          <div
            className={`h-full ${PHASE_COLORS[progress.current_phase] || 'bg-blue-500'} transition-all duration-300 ease-out`}
            style={{ width: `${progress.progress_percent || 0}%` }}
          />
        </div>
      </div>

      {/* Time Info */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-gray-50 p-4 rounded-lg">
          <div className="text-gray-600 text-sm">Elapsed</div>
          <div className="text-xl font-bold text-gray-800">{formatSeconds(progress.elapsed_seconds)}</div>
        </div>
        <div className="bg-gray-50 p-4 rounded-lg">
          <div className="text-gray-600 text-sm">Remaining</div>
          <div className="text-xl font-bold text-gray-800">
            {progress.estimated_remaining_seconds ? formatSeconds(progress.estimated_remaining_seconds) : '--'}
          </div>
        </div>
        <div className="bg-gray-50 p-4 rounded-lg">
          <div className="text-gray-600 text-sm">Est. Total</div>
          <div className="text-xl font-bold text-gray-800">
            {progress.estimated_remaining_seconds ? formatSeconds(progress.elapsed_seconds + progress.estimated_remaining_seconds) : '--'}
          </div>
        </div>
      </div>

      {/* Metrics */}
      <div className="border-t pt-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">Training Metrics</h3>
        
        {/* Epoch Info */}
        {progress.metrics.total_epochs > 0 && (
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div className="bg-blue-50 p-4 rounded-lg">
              <div className="text-gray-600 text-sm">Epoch</div>
              <div className="text-2xl font-bold text-blue-600">
                {progress.metrics.epoch} / {progress.metrics.total_epochs}
              </div>
            </div>
            <div className="bg-blue-50 p-4 rounded-lg">
              <div className="text-gray-600 text-sm">Samples</div>
              <div className="text-2xl font-bold text-blue-600">
                {progress.metrics.samples_processed.toLocaleString()} / {progress.metrics.total_samples.toLocaleString()}
              </div>
            </div>
          </div>
        )}

        {/* Accuracy & Loss */}
        {(progress.metrics.train_accuracy !== null || progress.metrics.val_accuracy !== null || progress.metrics.train_loss !== null) && (
          <div className="grid grid-cols-2 gap-4">
            {progress.metrics.train_accuracy !== null && (
              <div className="bg-green-50 p-4 rounded-lg">
                <div className="text-gray-600 text-sm">Train Accuracy</div>
                <div className="text-xl font-bold text-green-600">
                  {formatPercent(progress.metrics.train_accuracy)}
                </div>
              </div>
            )}
            {progress.metrics.val_accuracy !== null && (
              <div className="bg-green-50 p-4 rounded-lg">
                <div className="text-gray-600 text-sm">Val Accuracy</div>
                <div className="text-xl font-bold text-green-600">
                  {formatPercent(progress.metrics.val_accuracy)}
                </div>
              </div>
            )}
            {progress.metrics.train_loss !== null && (
              <div className="bg-orange-50 p-4 rounded-lg">
                <div className="text-gray-600 text-sm">Train Loss</div>
                <div className="text-xl font-bold text-orange-600">
                  {progress.metrics.train_loss.toFixed(4)}
                </div>
              </div>
            )}
            {progress.metrics.val_loss !== null && (
              <div className="bg-orange-50 p-4 rounded-lg">
                <div className="text-gray-600 text-sm">Val Loss</div>
                <div className="text-xl font-bold text-orange-600">
                  {progress.metrics.val_loss.toFixed(4)}
                </div>
              </div>
            )}
          </div>
        )}

        {/* No metrics yet */}
        {progress.metrics.train_accuracy === null && progress.metrics.val_accuracy === null && progress.metrics.train_loss === null && (
          <div className="text-center text-gray-500 py-4">
            Waiting for training metrics...
          </div>
        )}
      </div>

      {/* Status Messages */}
      {progress.current_phase === 'failed' && (
        <div className="mt-6 bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="text-red-800 font-semibold">Training Failed</div>
          <div className="text-red-700 text-sm">Check the logs for more details.</div>
        </div>
      )}

      {progress.current_phase === 'completed' && (
        <div className="mt-6 bg-green-50 border border-green-200 rounded-lg p-4">
          <div className="text-green-800 font-semibold">✓ Training Completed</div>
          <div className="text-green-700 text-sm">Model has been trained and saved.</div>
        </div>
      )}
    </div>
  );
}
