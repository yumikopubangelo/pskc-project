/**
 * DataGenerationProgress.jsx - Real-time data generation progress
 *
 * Displays data generation progress with:
 * - Events processed / total
 * - Progress percentage
 * - Estimated time remaining
 * - Generation rate (events/second)
 */

import React, { useState, useEffect, useRef } from 'react';
import { DataGenerationProgressWebSocket, DataGenerationProgressPoller } from '../utils/progressClient';

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

    // Initialize progress tracking
    if (useWebSocket) {
      const wsClient = new DataGenerationProgressWebSocket();
      progressClientRef.current = wsClient;

      wsClient.onUpdate((update) => {
        setProgress(update);
        setIsConnected(true);

        // Track if we've seen actual progress (processed > 0)
        if (update.processed > 0) {
          hasSeenProgressRef.current = true;
        }

        // Server sends done:true when complete
        // Only consider done if we've seen actual progress or server explicitly says done
        const done = update.done === true ||
          (hasSeenProgressRef.current && update.processed >= update.total && update.total > 0);
        
        if (done && !isDone) {
          setIsDone(true);
          setIsConnected(false);
          clearTimeout(timeoutId);
          
          // Ensure minimum display time before calling onComplete
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
      });

      wsClient.connect();

      return () => {
        clearTimeout(timeoutId);
        wsClient.disconnect();
      };
    } else {
      // Fallback to polling
      const poller = new DataGenerationProgressPoller();
      progressClientRef.current = poller;

      poller.onUpdate((update) => {
        setProgress(update);
        setIsConnected(true);

        // Track if we've seen actual progress (processed > 0)
        if (update.processed > 0) {
          hasSeenProgressRef.current = true;
        }

        const done = update.done === true ||
          (hasSeenProgressRef.current && update.processed >= update.total && update.total > 0);
        
        if (done && !isDone) {
          setIsDone(true);
          poller.stop();
          clearTimeout(timeoutId);
          
          // Ensure minimum display time before calling onComplete
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
      });

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
    <div className="w-full bg-white rounded-lg shadow-lg p-6 border border-blue-200">
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold text-gray-800">Data Generation Progress</h2>
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-sm text-gray-600">{isConnected ? 'Generating' : 'Complete'}</span>
        </div>
      </div>

      {/* Event Count */}
      <div className="mb-6">
        <div className="flex justify-between items-center mb-2">
          <span className="text-gray-700 font-medium">Events Generated</span>
          <span className="text-lg font-bold text-blue-600">
            {formatNumber(progress.processed)} / {formatNumber(progress.total)}
          </span>
        </div>
        <div className="text-gray-600 text-sm">
          {progress.total > 0 ? `${((progress.processed / progress.total) * 100).toFixed(1)}% complete` : 'Starting...'}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mb-6">
        <div className="flex justify-between items-center mb-2">
          <span className="text-gray-700 font-medium">Progress</span>
          <span className="text-lg font-bold text-blue-600">{(progress.percent || 0).toFixed(1)}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-4 overflow-hidden">
          <div
            className="h-full bg-blue-500 transition-all duration-300 ease-out"
            style={{ width: `${progress.percent}%` }}
          />
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-blue-50 p-4 rounded-lg">
          <div className="text-gray-600 text-sm">Rate</div>
          <div className="text-xl font-bold text-blue-600">
            {(progress.events_per_second || 0).toFixed(0)}
          </div>
          <div className="text-gray-500 text-xs">events/sec</div>
        </div>

        <div className="bg-purple-50 p-4 rounded-lg">
          <div className="text-gray-600 text-sm">Elapsed</div>
          <div className="text-xl font-bold text-purple-600">
            {formatSeconds(progress.elapsed_seconds)}
          </div>
        </div>

        <div className="bg-orange-50 p-4 rounded-lg">
          <div className="text-gray-600 text-sm">ETA</div>
          <div className="text-xl font-bold text-orange-600">
            {formatSeconds(progress.eta_seconds)}
          </div>
        </div>

        <div className="bg-green-50 p-4 rounded-lg">
          <div className="text-gray-600 text-sm">Total Time</div>
          <div className="text-xl font-bold text-green-600">
            {formatSeconds(progress.elapsed_seconds + progress.eta_seconds)}
          </div>
        </div>
      </div>

      {/* Info Message */}
      <div className="mt-6 text-center text-gray-600">
        {isDone ? (
          <div className="text-green-600 font-semibold">
            ✓ Data generation complete! Ready to start training.
          </div>
        ) : progress.total > 0 ? (
          <div>
            Generating {formatNumber(progress.total)} training events...
            <br />
            <span className="text-sm">
              {progress.events_per_second > 0
                ? `${Math.round((progress.total - progress.processed) / progress.events_per_second)} seconds remaining`
                : 'Calculating...'}
            </span>
          </div>
        ) : (
          <div className="text-gray-500">Initializing data generation...</div>
        )}
      </div>
    </div>
  );
}
