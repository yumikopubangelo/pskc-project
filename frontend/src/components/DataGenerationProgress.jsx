/**
 * DataGenerationProgress.jsx - Real-time data generation progress (dark theme)
 *
 * Premium dark-themed progress display with:
 * - Animated gradient progress bar
 * - Live metrics with glassmorphism cards
 * - Elapsed/remaining time counters
 * - Consistent styling with MLTraining page
 */

import React, { useState, useEffect, useRef } from 'react';
import { DataGenerationProgressWebSocket, DataGenerationProgressPoller } from '../utils/progressClient';
import Icon from './Icon';

export default function DataGenerationProgress({ onComplete, useWebSocket = false }) {
  const [progress, setProgress] = useState({
    processed: 0,
    total: 0,
    percent: 0,
    elapsed_seconds: 0,
    eta_seconds: 0,
    events_per_second: 0,
    timestamp: null
  });

  const [isConnected, setIsConnected] = useState(false);
  const [isDone, setIsDone] = useState(false);
  const progressClientRef = useRef(null);
  const startTimeRef = useRef(Date.now());
  const hasSeenProgressRef = useRef(false);
  const MIN_DISPLAY_TIME_MS = 2000;
  // Only fire timeout if generation started but never completed (5 minutes)
  const MAX_WAIT_TIME_MS = 300000;

  useEffect(() => {
    const timeoutId = setTimeout(() => {
      if (!isDone && hasSeenProgressRef.current) {
        console.log('Data generation timeout after 5 minutes - calling onComplete');
        setIsDone(true);
        setIsConnected(false);
        if (onComplete) {
          onComplete({
            success: true,
            processed: progress.processed || 0,
            total: progress.total || 0,
          });
        }
      }
    }, MAX_WAIT_TIME_MS);

    const handleUpdate = (update) => {
      setProgress(update);
      setIsConnected(true);

      if (update.processed > 0) {
        hasSeenProgressRef.current = true;
      }

      const done = update.done === true ||
        (hasSeenProgressRef.current && update.processed >= update.total && update.total > 0);
      
      if (done && !isDone) {
        setIsDone(true);
        if (progressClientRef.current?.stop) progressClientRef.current.stop();
        if (progressClientRef.current?.disconnect) progressClientRef.current.disconnect();
        setIsConnected(false);
        clearTimeout(timeoutId);
        
        const elapsed = Date.now() - startTimeRef.current;
        const remainingTime = Math.max(0, MIN_DISPLAY_TIME_MS - elapsed);
        
        setTimeout(() => {
          if (onComplete) {
            onComplete({
              success: true,
              processed: update.processed,
              total: update.total,
            });
          }
        }, remainingTime);
      }
    };

    if (useWebSocket) {
      const wsClient = new DataGenerationProgressWebSocket();
      progressClientRef.current = wsClient;
      wsClient.onUpdate(handleUpdate);
      wsClient.connect();

      return () => {
        clearTimeout(timeoutId);
        wsClient.disconnect();
      };
    } else {
      const poller = new DataGenerationProgressPoller();
      progressClientRef.current = poller;
      poller.onUpdate(handleUpdate);
      poller.start();

      return () => {
        clearTimeout(timeoutId);
        poller.stop();
      };
    }
  }, [onComplete, useWebSocket, isDone]);

  const formatSeconds = (seconds) => {
    if (!seconds) return '--';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  const formatNumber = (num) => {
    if (!num) return '0';
    return num.toLocaleString();
  };

  return (
    <div className="rounded-3xl border border-dark-border bg-dark-card p-6 space-y-6 animate-slide-in">
      {/* Header */}
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-semibold text-white">Data Generation Progress</h2>
        <div className="flex items-center gap-2">
          <div className={`h-2.5 w-2.5 rounded-full ${isConnected ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]' : 'bg-slate-500'}`} />
          <span className="text-xs text-slate-400">{isConnected ? 'Generating' : 'Complete'}</span>
        </div>
      </div>

      {/* Progress Info */}
      <div className="flex justify-between items-end">
        <div>
          <div className="text-sm font-medium text-slate-400 mb-1">Events Generated</div>
          <div className="text-2xl font-bold text-white tabular-nums">
            <span className="text-accent-blue">{formatNumber(progress.processed)}</span>
            <span className="text-slate-500 text-lg mx-2">/</span>
            {formatNumber(progress.total)}
          </div>
        </div>
        <div className="text-right">
          <div className="text-sm text-slate-400 mb-1">
            {progress.total > 0 ? `${((progress.processed / progress.total) * 100).toFixed(1)}% complete` : 'Starting...'}
          </div>
          <div className="text-xl font-bold text-accent-blue tabular-nums">
            {(progress.percent || 0).toFixed(1)}%
          </div>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="w-full h-3 rounded-full bg-dark-bg border border-dark-border overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300 ease-out progress-gradient-bar"
          style={{ width: `${progress.percent || 0}%` }}
        />
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="rounded-2xl border border-accent-blue/20 bg-accent-blue/5 p-4 relative overflow-hidden group">
          <div className="absolute -right-4 -top-4 opacity-10 group-hover:opacity-20 transition-opacity">
            <Icon name="activity" className="h-16 w-16 text-accent-blue" />
          </div>
          <div className="text-[11px] uppercase tracking-wider text-blue-400/70 font-medium mb-1 relative z-10">Rate</div>
          <div className="flex items-baseline gap-1.5 relative z-10">
            <div className="text-2xl font-bold tabular-nums text-blue-300">
              {(progress.events_per_second || 0).toFixed(0)}
            </div>
            <div className="text-xs text-blue-400/50">evt/s</div>
          </div>
        </div>

        <div className="rounded-2xl border border-purple-500/20 bg-purple-500/5 p-4 relative overflow-hidden group">
          <div className="absolute -right-4 -top-4 opacity-10 group-hover:opacity-20 transition-opacity">
             <Icon name="clock" className="h-16 w-16 text-purple-500" />
          </div>
          <div className="text-[11px] uppercase tracking-wider text-purple-400/70 font-medium mb-1 relative z-10">Elapsed</div>
          <div className="text-2xl font-bold tabular-nums text-purple-300 relative z-10">
            {formatSeconds(progress.elapsed_seconds)}
          </div>
        </div>

        <div className="rounded-2xl border border-orange-500/20 bg-orange-500/5 p-4 relative overflow-hidden group">
          <div className="absolute -right-4 -top-4 opacity-10 group-hover:opacity-20 transition-opacity">
            <Icon name="fast-forward" className="h-16 w-16 text-orange-500" />
          </div>
          <div className="text-[11px] uppercase tracking-wider text-orange-400/70 font-medium mb-1 relative z-10">Remaining</div>
          <div className="text-2xl font-bold tabular-nums text-orange-300 relative z-10">
            {formatSeconds(progress.eta_seconds)}
          </div>
        </div>

        <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-4 relative overflow-hidden group">
          <div className="absolute -right-4 -top-4 opacity-10 group-hover:opacity-20 transition-opacity">
            <Icon name="calendar" className="h-16 w-16 text-emerald-500" />
          </div>
          <div className="text-[11px] uppercase tracking-wider text-emerald-400/70 font-medium mb-1 relative z-10">Total Time</div>
          <div className="text-2xl font-bold tabular-nums text-emerald-300 relative z-10">
            {formatSeconds(progress.elapsed_seconds + progress.eta_seconds)}
          </div>
        </div>
      </div>

      {/* Info Message */}
      <div className="mt-2 text-center">
        {isDone ? (
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-sm font-medium">
            <Icon name="check" className="h-4 w-4" />
            Data generation complete! Ready for training.
          </div>
        ) : progress.total > 0 ? (
          <div className="text-sm text-slate-400">
            Generating <span className="text-white font-medium">{formatNumber(progress.total)}</span> synthetic training events...
          </div>
        ) : (
          <div className="text-sm text-slate-500 flex items-center justify-center gap-2">
            <div className="h-4 w-4 rounded-full border-2 border-slate-600 border-t-slate-400 animate-spin" />
            Initializing data generation cluster...
          </div>
        )}
      </div>
    </div>
  );
}
