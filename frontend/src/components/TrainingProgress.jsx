/**
 * TrainingProgress.jsx - Real-time training progress component (dark theme)
 *
 * Premium dark-themed progress display with:
 * - Multi-step phase pipeline with animated active indicator
 * - Animated gradient progress bar
 * - Live metrics with glassmorphism cards
 * - Elapsed/remaining time counters
 * - Per-model accuracy display
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { TrainingProgressWebSocket, TrainingProgressPoller } from '../utils/progressClient';
import Icon from './Icon';

const PHASES = [
  { key: 'loading_data', label: 'Load', icon: 'database' },
  { key: 'preprocessing', label: 'Preprocess', icon: 'settings' },
  { key: 'feature_engineering', label: 'Features', icon: 'layers' },
  { key: 'data_balancing', label: 'Balance', icon: 'sliders' },
  { key: 'splitting', label: 'Split', icon: 'git-branch' },
  { key: 'training_rf', label: 'RF', icon: 'cpu' },
  { key: 'training_lstm', label: 'LSTM', icon: 'cpu' },
  { key: 'updating_markov', label: 'Markov', icon: 'cpu' },
  { key: 'evaluation', label: 'Evaluate', icon: 'check' },
  { key: 'saving_model', label: 'Save', icon: 'save' },
];

const PHASE_NAMES = {
  idle: 'Idle',
  loading_data: 'Loading Data',
  preprocessing: 'Preprocessing',
  feature_engineering: 'Feature Engineering',
  data_balancing: 'Balancing Data',
  data_augmentation: 'Augmenting Data',
  splitting: 'Splitting Data',
  training_lstm: 'Training LSTM',
  training_rf: 'Training Random Forest',
  updating_markov: 'Updating Markov Chain',
  evaluation: 'Evaluation',
  saving_model: 'Saving Model',
  completed: 'Completed',
  failed: 'Failed',
};

function getPhaseIndex(phase) {
  const idx = PHASES.findIndex(p => p.key === phase);
  if (phase === 'completed') return PHASES.length;
  if (phase === 'data_augmentation') return PHASES.findIndex(p => p.key === 'data_balancing');
  return idx >= 0 ? idx : -1;
}

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
      total_samples: 0,
    },
    elapsed_seconds: 0,
    estimated_remaining_seconds: null,
  });

  const [isConnected, setIsConnected] = useState(false);
  const [trainingStarted, setTrainingStarted] = useState(false);
  const [logMessages, setLogMessages] = useState([]);
  const progressClientRef = useRef(null);
  const elapsedTimerRef = useRef(null);
  const isActiveRef = useRef(false);
  const timeoutRef = useRef(null);
  const hasSeenProgressRef = useRef(false);
  const MAX_WAIT_TIME_MS = 600000;

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

  const addLog = useCallback((msg) => {
    if (!msg) return;
    setLogMessages(prev => [...prev.slice(-19), { text: msg, time: new Date().toLocaleTimeString() }]);
  }, []);

  useEffect(() => {
    timeoutRef.current = setTimeout(() => {
      if (!hasSeenProgressRef.current) {
        setIsConnected(false);
        stopElapsedTimer();
        if (onComplete) {
          onComplete({
            success: false,
            phase: 'failed',
            progress: 0,
            details: { error: 'Connection timeout' },
          });
        }
      }
    }, MAX_WAIT_TIME_MS);

    const handleUpdate = (update, isPoller = false) => {
      const latestUpdate = isPoller ? (update.latest_update || update) : update;
      if (isPoller && !latestUpdate) return;
      if (latestUpdate._source === 'saved_state') return;

      hasSeenProgressRef.current = true;
      const phase = latestUpdate.phase || (isPoller ? latestUpdate.phase : null);
      if (phase && phase !== 'idle') {
        setTrainingStarted(true);
        setIsConnected(true);
      }

      if (latestUpdate.message) addLog(latestUpdate.message);

      const elapsed = typeof (isPoller ? update.elapsed_seconds : latestUpdate.elapsed_seconds) === 'number'
        ? (isPoller ? update.elapsed_seconds : latestUpdate.elapsed_seconds)
        : null;

      setProgress(prev => {
        const elapsedVal = elapsed !== null ? elapsed : prev.elapsed_seconds;
        let newMetrics = { ...prev.metrics };
        const details = latestUpdate.details || {};
        if (details) newMetrics = { ...newMetrics, ...details };
        if (latestUpdate.train_accuracy !== undefined) newMetrics.train_accuracy = latestUpdate.train_accuracy;
        if (latestUpdate.val_accuracy !== undefined) newMetrics.val_accuracy = latestUpdate.val_accuracy;
        if (latestUpdate.train_loss !== undefined) newMetrics.train_loss = latestUpdate.train_loss;
        if (latestUpdate.val_loss !== undefined) newMetrics.val_loss = latestUpdate.val_loss;
        if (latestUpdate.epoch !== undefined) newMetrics.epoch = latestUpdate.epoch;
        if (latestUpdate.total_epochs !== undefined) newMetrics.total_epochs = latestUpdate.total_epochs;
        if (latestUpdate.samples_processed !== undefined) newMetrics.samples_processed = latestUpdate.samples_processed;
        if (latestUpdate.total_samples !== undefined) newMetrics.total_samples = latestUpdate.total_samples;
        if (details.total_samples !== undefined) newMetrics.total_samples = details.total_samples;

        const pct = latestUpdate.progress_percent ?? (isPoller ? latestUpdate.progress_percent : prev.progress_percent) ?? prev.progress_percent;

        return {
          ...prev,
          current_phase: phase || prev.current_phase,
          progress_percent: pct,
          latest_update: latestUpdate,
          elapsed_seconds: elapsedVal,
          estimated_remaining_seconds: calculateETA(pct, elapsedVal),
          metrics: newMetrics,
        };
      });

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
            phase,
            progress: latestUpdate.progress_percent,
            details: latestUpdate.details || {},
          });
        }
      }
    };

    if (useWebSocket) {
      const wsClient = new TrainingProgressWebSocket();
      progressClientRef.current = wsClient;
      wsClient.onUpdate((update) => handleUpdate(update, false));
      wsClient.connect();
      setIsConnected(true);
      return () => {
        clearTimeout(timeoutRef.current);
        stopElapsedTimer();
        wsClient.disconnect();
      };
    } else {
      const poller = new TrainingProgressPoller();
      progressClientRef.current = poller;
      poller.onUpdate((update) => handleUpdate(update, true));
      poller.start();
      return () => {
        clearTimeout(timeoutRef.current);
        stopElapsedTimer();
        poller.stop();
      };
    }
  }, [onComplete, useWebSocket, startElapsedTimer, stopElapsedTimer, addLog]);

  const calculateETA = (percent, elapsed) => {
    if (percent === 0 || elapsed === 0) return null;
    const totalEstimated = (elapsed / percent) * 100;
    return Math.max(0, totalEstimated - elapsed);
  };

  const formatSeconds = s => {
    if (!s) return '--';
    if (s < 60) return `${Math.round(s)}s`;
    const m = Math.floor(s / 60);
    const r = Math.round(s % 60);
    return `${m}m ${r}s`;
  };

  const formatPercent = val => {
    if (val === null || val === undefined || isNaN(val)) return '--';
    const n = Number(val);
    return n <= 1 ? `${(n * 100).toFixed(1)}%` : `${n.toFixed(1)}%`;
  };

  const activePhaseIndex = getPhaseIndex(progress.current_phase);
  const isComplete = progress.current_phase === 'completed';
  const isFailed = progress.current_phase === 'failed';

  if (!trainingStarted) {
    return (
      <div className="rounded-3xl border border-dark-border bg-dark-card p-6">
        <div className="flex items-center gap-3 py-6 justify-center text-slate-400">
          <div className="h-5 w-5 rounded-full border-2 border-slate-600 border-t-accent-blue animate-spin" />
          <span className="text-sm">Waiting for training to start...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-3xl border border-dark-border bg-dark-card p-6 space-y-6 animate-slide-in">
      {/* Header */}
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-semibold text-white">Training Progress</h2>
        <div className="flex items-center gap-2">
          <div className={`h-2.5 w-2.5 rounded-full ${isConnected ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]' : isFailed ? 'bg-red-400' : 'bg-slate-500'}`} />
          <span className="text-xs text-slate-400">{isConnected ? 'Live' : isFailed ? 'Failed' : 'Polling'}</span>
        </div>
      </div>

      {/* Phase Pipeline */}
      <div className="relative">
        <div className="flex items-center justify-between">
          {PHASES.map((phase, idx) => {
            const isDone = idx < activePhaseIndex || isComplete;
            const isActive = idx === activePhaseIndex && !isComplete && !isFailed;
            return (
              <div key={phase.key} className="flex flex-col items-center relative z-10" style={{ flex: 1 }}>
                <div
                  className={`h-8 w-8 rounded-full flex items-center justify-center text-xs font-bold transition-all duration-500 ${
                    isDone
                      ? 'bg-emerald-500/20 border-2 border-emerald-500 text-emerald-400'
                      : isActive
                        ? 'bg-accent-blue/20 border-2 border-accent-blue text-accent-blue shadow-[0_0_12px_rgba(37,99,235,0.4)] animate-pulse'
                        : 'bg-dark-bg border border-dark-border text-slate-600'
                  }`}
                >
                  {isDone ? '✓' : idx + 1}
                </div>
                <span className={`mt-1.5 text-[10px] leading-tight text-center ${isActive ? 'text-accent-blue font-semibold' : isDone ? 'text-emerald-400/70' : 'text-slate-600'}`}>
                  {phase.label}
                </span>
              </div>
            );
          })}
        </div>
        {/* Connecting lines */}
        <div className="absolute top-4 left-[5%] right-[5%] h-0.5 bg-dark-border -z-0" />
        <div
          className="absolute top-4 left-[5%] h-0.5 bg-gradient-to-r from-emerald-500 to-accent-blue transition-all duration-700 -z-0"
          style={{ width: `${Math.min(100, (activePhaseIndex / (PHASES.length - 1)) * 90)}%` }}
        />
      </div>

      {/* Current Phase Label */}
      <div className="flex items-center gap-3">
        <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
          isComplete ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30' :
          isFailed ? 'bg-red-500/15 text-red-300 border border-red-500/30' :
          'bg-accent-blue/15 text-blue-300 border border-accent-blue/30'
        }`}>
          {!isComplete && !isFailed && <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse" />}
          {PHASE_NAMES[progress.current_phase] || progress.current_phase}
        </span>
        {progress.latest_update?.message && (
          <span className="text-xs text-slate-500 truncate">{progress.latest_update.message}</span>
        )}
      </div>

      {/* Progress Bar */}
      <div>
        <div className="flex justify-between items-center mb-2">
          <span className="text-sm text-slate-400">Overall Progress</span>
          <span className="text-lg font-bold tabular-nums text-white">{(progress.progress_percent || 0).toFixed(1)}%</span>
        </div>
        <div className="w-full h-3 rounded-full bg-dark-bg border border-dark-border overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ease-out ${
              isComplete ? 'bg-emerald-500' :
              isFailed ? 'bg-red-500' :
              'progress-gradient-bar'
            }`}
            style={{ width: `${progress.progress_percent || 0}%` }}
          />
        </div>
      </div>

      {/* Time Info */}
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-2xl border border-dark-border bg-dark-bg p-3">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Elapsed</div>
          <div className="mt-1 text-lg font-semibold tabular-nums text-white">{formatSeconds(progress.elapsed_seconds)}</div>
        </div>
        <div className="rounded-2xl border border-dark-border bg-dark-bg p-3">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Remaining</div>
          <div className="mt-1 text-lg font-semibold tabular-nums text-white">
            {progress.estimated_remaining_seconds ? formatSeconds(progress.estimated_remaining_seconds) : '--'}
          </div>
        </div>
        <div className="rounded-2xl border border-dark-border bg-dark-bg p-3">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Est. Total</div>
          <div className="mt-1 text-lg font-semibold tabular-nums text-white">
            {progress.estimated_remaining_seconds ? formatSeconds(progress.elapsed_seconds + progress.estimated_remaining_seconds) : '--'}
          </div>
        </div>
      </div>

      {/* Metrics */}
      {(progress.metrics.total_epochs > 0 || progress.metrics.train_accuracy !== null || progress.metrics.val_accuracy !== null) && (
        <div className="space-y-3">
          <div className="text-sm font-medium text-slate-300">Training Metrics</div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {progress.metrics.total_epochs > 0 && (
              <div className="rounded-2xl border border-accent-blue/20 bg-accent-blue/5 p-3">
                <div className="text-[10px] uppercase tracking-widest text-blue-400/60">Epoch</div>
                <div className="mt-1 text-lg font-bold tabular-nums text-blue-300">
                  {progress.metrics.epoch} / {progress.metrics.total_epochs}
                </div>
              </div>
            )}
            {progress.metrics.total_samples > 0 && (
              <div className="rounded-2xl border border-sky-500/20 bg-sky-500/5 p-3">
                <div className="text-[10px] uppercase tracking-widest text-sky-400/60">Samples</div>
                <div className="mt-1 text-lg font-bold tabular-nums text-sky-300">
                  {(progress.metrics.total_samples || 0).toLocaleString()}
                </div>
              </div>
            )}
            {progress.metrics.val_accuracy !== null && (
              <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-3">
                <div className="text-[10px] uppercase tracking-widest text-emerald-400/60">Val Accuracy</div>
                <div className="mt-1 text-lg font-bold tabular-nums text-emerald-300">
                  {formatPercent(progress.metrics.val_accuracy)}
                </div>
              </div>
            )}
            {progress.metrics.train_accuracy !== null && (
              <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-3">
                <div className="text-[10px] uppercase tracking-widest text-emerald-400/60">Train Accuracy</div>
                <div className="mt-1 text-lg font-bold tabular-nums text-emerald-300">
                  {formatPercent(progress.metrics.train_accuracy)}
                </div>
              </div>
            )}
            {progress.metrics.train_loss !== null && (
              <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-3">
                <div className="text-[10px] uppercase tracking-widest text-amber-400/60">Train Loss</div>
                <div className="mt-1 text-lg font-bold tabular-nums text-amber-300">
                  {Number(progress.metrics.train_loss).toFixed(4)}
                </div>
              </div>
            )}
            {progress.metrics.val_loss !== null && (
              <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-3">
                <div className="text-[10px] uppercase tracking-widest text-amber-400/60">Val Loss</div>
                <div className="mt-1 text-lg font-bold tabular-nums text-amber-300">
                  {Number(progress.metrics.val_loss).toFixed(4)}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* No metrics yet */}
      {progress.metrics.train_accuracy === null && progress.metrics.val_accuracy === null && progress.metrics.train_loss === null && progress.metrics.total_samples === 0 && (
        <div className="text-center text-sm text-slate-500 py-3">
          Waiting for training metrics...
        </div>
      )}

      {/* Live Log Feed */}
      {logMessages.length > 0 && (
        <div className="rounded-2xl border border-dark-border bg-dark-bg p-3">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Live Log</div>
          <div className="max-h-28 overflow-y-auto space-y-1 scrollbar-thin">
            {logMessages.map((log, i) => (
              <div key={i} className="flex gap-2 text-xs">
                <span className="text-slate-600 tabular-nums shrink-0">{log.time}</span>
                <span className="text-slate-400 truncate">{log.text}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Status Messages */}
      {isFailed && (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4">
          <div className="flex items-center gap-2 text-red-300 font-semibold">
            <Icon name="alert" className="h-5 w-5" />
            <span>Training Failed</span>
          </div>
          <div className="mt-1 text-xs text-red-200/70">Check the API logs for more details.</div>
        </div>
      )}

      {isComplete && (
        <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-4">
          <div className="flex items-center gap-2 text-emerald-300 font-semibold">
            <Icon name="check" className="h-5 w-5" />
            <span>Training Completed</span>
          </div>
          <div className="mt-1 text-xs text-emerald-200/70">Model has been trained and saved.</div>
        </div>
      )}
    </div>
  );
}
