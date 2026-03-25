import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import apiClient from '../utils/apiClient';

const PIE_COLORS = ['#14b8a6', '#0ea5e9', '#22c55e', '#f59e0b', '#f97316', '#ef4444', '#a855f7'];

const formatPercent = (value, digits = 1) =>
  value == null ? 'N/A' : `${Number(value).toFixed(digits)}%`;

const formatMs = (value) =>
  value == null ? 'N/A' : `${Number(value).toFixed(2)} ms`;

const formatNumber = (value) =>
  value == null ? 'N/A' : Number(value).toLocaleString();

const formatPathLabel = (path) => {
  if (path === 'l1_hit') return 'L1 hit';
  if (path === 'l2_hit') return 'L2 hit';
  if (path === 'late_cache_hit') return 'Late cache hit';
  if (path === 'kms_fetch') return 'Cache miss -> KMS fallback';
  if (path === 'kms_miss') return 'Cache miss -> KMS failed/not found';
  if (path === 'blocked') return 'Blocked';
  return path || 'Unknown';
};

const formatCacheOrigin = (trace) => {
  if (trace.prefetched_by_worker) return 'Worker-prefetched';
  if (trace.prefetched_before_request && trace.cache_origin_before === 'request_fetch') return 'Request-cached';
  if (trace.prefetched_before_request && trace.cache_origin_before === 'worker_prefetch') return 'Worker-prefetched';
  if (trace.prefetched_before_request) return 'Warm cache (origin unknown)';
  return 'No';
};

const LiveSimulationDashboard = () => {
  const [session, setSession] = useState(null);
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [error, setError] = useState(null);
  const [selectedScenario, setSelectedScenario] = useState('test');
  const [selectedTraffic, setSelectedTraffic] = useState('normal');
  const [virtualNodes, setVirtualNodes] = useState(3);
  const [maxRequests, setMaxRequests] = useState(1000);
  const [modelPreference, setModelPreference] = useState('best_available');
  const [keyMode, setKeyMode] = useState('auto');
  const [simulateKms, setSimulateKms] = useState(true);

  const pollIntervalRef = useRef(null);
  const sessionIdRef = useRef(null);

  const scenarios = [
    { id: 'test', name: 'Test / Generic Runtime' },
    { id: 'siakad', name: 'SIAKAD Runtime' },
    { id: 'sevima', name: 'SEVIMA Runtime' },
    { id: 'pddikti', name: 'PDDikti Runtime' },
    { id: 'dynamic', name: 'Dynamic Production Runtime' },
  ];

  const trafficTypes = [
    { id: 'normal', name: 'Normal (50 RPS)' },
    { id: 'heavy_load', name: 'Heavy Load (120 RPS)' },
    { id: 'prime_time', name: 'Prime Time (200 RPS)' },
    { id: 'degraded', name: 'Degraded (25 RPS)' },
    { id: 'overload', name: 'Overload (300 RPS)' },
  ];

  const modelPreferences = [
    { id: 'best_available', name: 'Best Available Model' },
    { id: 'active_runtime', name: 'Active Runtime Model' },
  ];

  const keyModes = [
    { id: 'auto', name: 'Auto (Traffic-based)' },
    { id: 'stable', name: 'Stable Keys' },
    { id: 'mixed', name: 'Mixed Rotation' },
    { id: 'high_churn', name: 'High Churn' },
  ];

  const startSession = useCallback(async () => {
    setIsStarting(true);
    setError(null);
    try {
      const response = await apiClient.startLiveSimulationSession({
        scenario: selectedScenario,
        trafficType: selectedTraffic,
        virtualNodes,
        maxRequests,
        modelPreference,
        keyMode,
        simulateKms,
      });
      sessionIdRef.current = response.session_id;
      setSession(response);

      // Start polling for updates
      pollIntervalRef.current = setInterval(async () => {
        try {
          const updatedSession = await apiClient.getLiveSimulationSession(sessionIdRef.current);
          if (updatedSession) {
            setSession(updatedSession);
          }
        } catch (err) {
          console.error('Failed to poll session:', err);
        }
      }, 1000); // Poll every second
    } catch (err) {
      setError(err.message || 'Failed to start simulation session');
    } finally {
      setIsStarting(false);
    }
  }, [selectedScenario, selectedTraffic, virtualNodes, maxRequests, modelPreference, keyMode, simulateKms]);

  const stopSession = useCallback(async () => {
    if (!sessionIdRef.current) return;

    setIsStopping(true);
    try {
      await apiClient.stopLiveSimulationSession(sessionIdRef.current);
      // Session will be updated via polling
    } catch (err) {
      setError(err.message || 'Failed to stop simulation session');
    } finally {
      setIsStopping(false);
    }
  }, []);

  const resetSession = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    sessionIdRef.current = null;
    setSession(null);
    setError(null);
  }, []);

  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  // Prepare chart data
  const pathBreakdownData = session?.pskc_metrics?.path_breakdown || [];
  const latencyTrendData = session?.trace?.slice(-50) || []; // Last 50 requests
  const accuracyData = session?.live_accuracy ? [{
    name: 'Model Accuracy',
    top1: session.live_accuracy.top_1_accuracy * 100,
    top10: session.live_accuracy.top_10_accuracy * 100,
  }] : [];

  const prefetchData = session?.prefetch ? [{
    name: 'Prefetch Performance',
    opportunities: session.prefetch.prefetch_opportunities,
    hits: session.prefetch.verified_prefetch_hits,
    hitRate: session.prefetch.verified_prefetch_hit_rate * 100,
  }] : [];

  // Per-key accuracy data for bar chart
  const perKeyAccuracyData = (session?.per_key_accuracy || []).map((k) => ({
    key: k.key_id?.slice(0, 12),
    fullKey: k.key_id,
    top1: k.top1_accuracy,
    top10: k.top10_accuracy,
    total: k.total,
  }));

  // Accuracy trend data for line chart
  const accuracyTrendData = session?.accuracy_trend || [];

  // Latest trace for prediction feed
  const recentTraces = session?.trace?.slice(-10)?.reverse() || [];
  const latestTrace = recentTraces[0] || null;

  const isRunning = session?.status === 'running';
  const isCompleted = session?.status === 'completed' || session?.status === 'stopped';
  const canStart = !isRunning && !isStarting;
  const canStop = isRunning && !isStopping;

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-dark-border bg-dark-card p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h2 className="text-xl font-semibold">Live Simulation Dashboard</h2>
            <p className="mt-1 text-sm text-slate-400">
              Real-time simulation using actual backend components (Redis, prefetch worker, ML model)
              for model accuracy validation and accountability tracking.
            </p>
            {session && (
              <div className="mt-3 flex items-center gap-4 text-sm">
                <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                  session.status === 'running' ? 'bg-green-500/20 text-green-400' :
                  session.status === 'completed' ? 'bg-blue-500/20 text-blue-400' :
                  session.status === 'stopped' ? 'bg-yellow-500/20 text-yellow-400' :
                  'bg-red-500/20 text-red-400'
                }`}>
                  {session.status?.toUpperCase()}
                </span>
                <span className="text-slate-400">
                  Session: {session.session_id?.slice(0, 8)}...
                </span>
                <span className="text-slate-400">
                  Requests: {formatNumber(session.requests_processed)}
                </span>
              </div>
            )}
          </div>

          <div className="flex gap-2">
            {canStart && (
              <button
                onClick={startSession}
                disabled={isStarting}
                className="rounded-lg bg-accent-blue px-4 py-2 font-semibold text-white transition-colors hover:bg-accent-blue/80 disabled:cursor-not-allowed disabled:bg-slate-600"
              >
                {isStarting ? 'Starting...' : 'Start Live Session'}
              </button>
            )}
            {canStop && (
              <button
                onClick={stopSession}
                disabled={isStopping}
                className="rounded-lg bg-red-600 px-4 py-2 font-semibold text-white transition-colors hover:bg-red-600/80 disabled:cursor-not-allowed disabled:bg-slate-600"
              >
                {isStopping ? 'Stopping...' : 'Stop Session'}
              </button>
            )}
            {session && (
              <button
                onClick={resetSession}
                className="rounded-lg bg-slate-600 px-4 py-2 font-semibold text-white transition-colors hover:bg-slate-600/80"
              >
                Reset
              </button>
            )}
          </div>
        </div>

        {error && (
          <div className="mt-4 rounded-lg bg-red-500/10 border border-red-500/20 p-4">
            <p className="text-red-400 text-sm">{error}</p>
          </div>
        )}

        {/* Configuration Panel */}
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="mb-1 block text-sm text-slate-400">Scenario</label>
            <select
              value={selectedScenario}
              onChange={(e) => setSelectedScenario(e.target.value)}
              disabled={isRunning}
              className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none disabled:opacity-50"
            >
              {scenarios.map((scenario) => (
                <option key={scenario.id} value={scenario.id}>{scenario.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-sm text-slate-400">Traffic Type</label>
            <select
              value={selectedTraffic}
              onChange={(e) => setSelectedTraffic(e.target.value)}
              disabled={isRunning}
              className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none disabled:opacity-50"
            >
              {trafficTypes.map((traffic) => (
                <option key={traffic.id} value={traffic.id}>{traffic.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-sm text-slate-400">Virtual Nodes</label>
            <input
              type="number"
              min="1"
              max="10"
              value={virtualNodes}
              onChange={(e) => setVirtualNodes(Number(e.target.value))}
              disabled={isRunning}
              className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none disabled:opacity-50"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm text-slate-400">Max Requests</label>
            <input
              type="number"
              min="100"
              max="10000"
              value={maxRequests}
              onChange={(e) => setMaxRequests(Number(e.target.value))}
              disabled={isRunning}
              className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none disabled:opacity-50"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm text-slate-400">Model Preference</label>
            <select
              value={modelPreference}
              onChange={(e) => setModelPreference(e.target.value)}
              disabled={isRunning}
              className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none disabled:opacity-50"
            >
              {modelPreferences.map((pref) => (
                <option key={pref.id} value={pref.id}>{pref.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-sm text-slate-400">Key Mode</label>
            <select
              value={keyMode}
              onChange={(e) => setKeyMode(e.target.value)}
              disabled={isRunning}
              className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none disabled:opacity-50"
            >
              {keyModes.map((mode) => (
                <option key={mode.id} value={mode.id}>{mode.name}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="simulateKms"
              checked={simulateKms}
              onChange={(e) => setSimulateKms(e.target.checked)}
              disabled={isRunning}
              className="rounded border-dark-border bg-dark-bg text-accent-blue focus:ring-accent-blue"
            />
            <label htmlFor="simulateKms" className="text-sm text-slate-400">
              Simulate KMS
            </label>
          </div>
        </div>

        <div className="mt-4 rounded-lg border border-dark-border/70 bg-dark-bg p-4 text-sm text-slate-300">
          <p>
            `Previous prediction Top-1` berarti request sebelumnya menebak key berikutnya tepat di peringkat 1.
            `Top-10` berarti key saat ini masih masuk 10 besar tebakan dari request sebelumnya.
          </p>
          <p className="mt-2">
            Worker prefetch yang terpisah secara realistis memanaskan cache bersama lebih dulu.
            Karena itu, bukti yang paling sehat biasanya terlihat sebagai `L2 hit`, lalu request itu sendiri
            mempromosikan key ke `L1` node yang sedang melayani.
          </p>
        </div>
      </div>

      {/* Live Metrics Dashboard */}
      {session && (
        <>
          {/* Key Metrics Row */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <h3 className="text-sm font-medium text-slate-400">PSKC Latency</h3>
              <p className="mt-2 text-2xl font-bold text-white">
                {formatMs(session.pskc_metrics?.avg_latency_ms)}
              </p>
              <p className="text-xs text-slate-500">
                P95: {formatMs(session.pskc_metrics?.p95_latency_ms)} · KMS miss avg: {formatMs(session.pskc_metrics?.kms_avg_latency_ms)}
              </p>
            </div>

            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <h3 className="text-sm font-medium text-slate-400">Baseline Latency</h3>
              <p className="mt-2 text-2xl font-bold text-white">
                {formatMs(session.baseline_metrics?.avg_latency_ms)}
              </p>
              <p className="text-xs text-slate-500">
                Direct KMS avg: {formatMs(session.baseline_metrics?.direct_kms_avg_latency_ms)}
              </p>
            </div>

            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <h3 className="text-sm font-medium text-slate-400">Cache Hit Rate</h3>
              <p className="mt-2 text-2xl font-bold text-green-400">
                {formatPercent(session.pskc_metrics?.cache_hit_rate)}
              </p>
              <p className="text-xs text-slate-500">
                L1: {session.pskc_metrics?.l1_hits || 0}, L2: {session.pskc_metrics?.l2_hits || 0}
              </p>
            </div>

            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <h3 className="text-sm font-medium text-slate-400">Improvement</h3>
              <p className="mt-2 text-2xl font-bold text-accent-blue">
                {formatPercent(session.comparison?.latency_improvement_percent)}
              </p>
              <p className="text-xs text-slate-500">
                {formatMs(session.comparison?.avg_latency_saved_ms)} saved
              </p>
            </div>
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Path Breakdown Pie Chart */}
            <div className="rounded-xl border border-dark-border bg-dark-card p-6">
              <h3 className="text-lg font-semibold mb-4">Request Path Distribution</h3>
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie
                    data={pathBreakdownData}
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    dataKey="value"
                    label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(1)}%`}
                  >
                    {pathBreakdownData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => [formatNumber(value), 'Requests']} />
                </PieChart>
              </ResponsiveContainer>
            </div>

            {/* Latency Trend */}
            <div className="rounded-xl border border-dark-border bg-dark-card p-6">
              <h3 className="text-lg font-semibold mb-4">Latency Trend (Last 50 Requests)</h3>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={latencyTrendData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis
                    dataKey="index"
                    stroke="#9CA3AF"
                    fontSize={12}
                  />
                  <YAxis
                    stroke="#9CA3AF"
                    fontSize={12}
                    tickFormatter={formatMs}
                  />
                  <Tooltip
                    formatter={(value, name) => [formatMs(value), name]}
                    labelFormatter={(label) => `Request ${label}`}
                  />
                  <Line
                    type="monotone"
                    dataKey="latency_ms"
                    stroke="#14b8a6"
                    strokeWidth={2}
                    dot={false}
                  />
                  {latencyTrendData.some(d => d.baseline_latency_ms) && (
                    <Line
                      type="monotone"
                      dataKey="baseline_latency_ms"
                      stroke="#ef4444"
                      strokeWidth={2}
                      strokeDasharray="5 5"
                      dot={false}
                    />
                  )}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Prediction Live Feed */}
          {latestTrace && (
            <div className="rounded-xl border border-dark-border bg-dark-card p-6">
              <h3 className="text-lg font-semibold mb-4">Prediction Live Feed</h3>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {/* Current prediction for next request */}
                <div className="rounded-lg border border-dark-border/70 bg-dark-bg p-4">
                  <p className="text-xs uppercase tracking-wide text-slate-500 mb-3">Model Predicts Next Keys</p>
                  {latestTrace.prediction_preview && latestTrace.prediction_preview.length > 0 ? (
                    <div className="space-y-2">
                      {latestTrace.prediction_preview.map((pred, i) => (
                        <div key={i} className="flex items-center gap-3">
                          <span className={`w-6 h-6 flex items-center justify-center rounded-full text-xs font-bold ${
                            i === 0 ? 'bg-yellow-500/20 text-yellow-400' :
                            i === 1 ? 'bg-slate-500/20 text-slate-300' :
                            'bg-amber-800/20 text-amber-600'
                          }`}>
                            {i + 1}
                          </span>
                          <span className="font-mono text-xs text-slate-300 flex-1 truncate">
                            {pred.key_id}
                          </span>
                          <div className="flex items-center gap-2">
                            <div className="w-20 h-2 rounded-full bg-dark-border overflow-hidden">
                              <div
                                className="h-full rounded-full bg-accent-blue"
                                style={{ width: `${Math.min(pred.confidence * 100, 100)}%` }}
                              />
                            </div>
                            <span className="text-xs text-slate-400 w-12 text-right">
                              {(pred.confidence * 100).toFixed(1)}%
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-slate-500">No predictions available</p>
                  )}
                  <p className="mt-3 text-xs text-slate-500">
                    Source: {latestTrace.prediction_source || 'N/A'} | Prefetch: {latestTrace.prefetch_mode || 'noop'}
                  </p>
                </div>

                {/* Last 5 prediction results */}
                <div className="rounded-lg border border-dark-border/70 bg-dark-bg p-4">
                  <p className="text-xs uppercase tracking-wide text-slate-500 mb-3">Recent Prediction Results</p>
                  <div className="space-y-2">
                    {recentTraces.slice(0, 6).map((trace) => (
                      <div key={trace.index} className="flex items-center gap-2 text-sm">
                        <span className="text-slate-500 w-8 text-right">#{trace.index}</span>
                        <span className="font-mono text-xs text-slate-400 flex-1 truncate">
                          {trace.key_id?.slice(0, 20)}
                        </span>
                        {trace.predicted_on_previous ? (
                          trace.top1_correct ? (
                            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-500/20 text-green-400">
                              Top-1 HIT
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-500/20 text-yellow-300">
                              Top-10 HIT
                            </span>
                          )
                        ) : (
                          <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-red-500/20 text-red-400">
                            MISS
                          </span>
                        )}
                        <span className={`text-xs ${
                          trace.path === 'l1_hit' || trace.path === 'l2_hit' ? 'text-green-400' :
                          trace.path === 'kms_fetch' ? 'text-yellow-400' : 'text-red-400'
                        }`}>
                          {formatPathLabel(trace.path)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Accuracy Trend + Per-Key Accuracy */}
          {(accuracyTrendData.length > 3 || perKeyAccuracyData.length > 0) && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              {/* Accuracy Trend Line Chart */}
              {accuracyTrendData.length > 3 && (
                <div className="rounded-xl border border-dark-border bg-dark-card p-6">
                  <h3 className="text-lg font-semibold mb-4">Prediction Accuracy Trend</h3>
                  <ResponsiveContainer width="100%" height={280}>
                    <LineChart data={accuracyTrendData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis
                        dataKey="index"
                        stroke="#9CA3AF"
                        fontSize={11}
                        label={{ value: 'Request #', position: 'insideBottom', offset: -5, fill: '#9CA3AF', fontSize: 11 }}
                      />
                      <YAxis
                        stroke="#9CA3AF"
                        fontSize={11}
                        domain={[0, 100]}
                        tickFormatter={(v) => `${v}%`}
                      />
                      <Tooltip
                        formatter={(value, name) => [`${value}%`, name === 'top1_running' ? 'Top-1 Accuracy' : 'Top-10 Accuracy']}
                        labelFormatter={(label) => `Request #${label}`}
                        contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                        itemStyle={{ color: '#e2e8f0' }}
                        labelStyle={{ color: '#94a3b8' }}
                      />
                      <Legend
                        formatter={(value) => value === 'top1_running' ? 'Top-1' : 'Top-10'}
                      />
                      <Line
                        type="monotone"
                        dataKey="top1_running"
                        stroke="#3b82f6"
                        strokeWidth={2}
                        dot={false}
                      />
                      <Line
                        type="monotone"
                        dataKey="top10_running"
                        stroke="#22c55e"
                        strokeWidth={2}
                        dot={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* Per-Key Accuracy Bar Chart */}
              {perKeyAccuracyData.length > 0 && (
                <div className="rounded-xl border border-dark-border bg-dark-card p-6">
                  <h3 className="text-lg font-semibold mb-4">Per-Key Prediction Accuracy</h3>
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={perKeyAccuracyData} layout="vertical" margin={{ left: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" horizontal={false} />
                      <XAxis
                        type="number"
                        domain={[0, 100]}
                        stroke="#9CA3AF"
                        fontSize={11}
                        tickFormatter={(v) => `${v}%`}
                      />
                      <YAxis
                        type="category"
                        dataKey="key"
                        stroke="#9CA3AF"
                        fontSize={10}
                        width={90}
                        tick={{ fill: '#94a3b8' }}
                      />
                      <Tooltip
                        formatter={(value, name) => [`${value}%`, name === 'top1' ? 'Top-1' : 'Top-10']}
                        labelFormatter={(label) => `Key: ${label}`}
                        contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                        itemStyle={{ color: '#e2e8f0' }}
                        labelStyle={{ color: '#94a3b8' }}
                      />
                      <Legend
                        formatter={(value) => value === 'top1' ? 'Top-1 Accuracy' : 'Top-10 Accuracy'}
                      />
                      <Bar dataKey="top1" fill="#3b82f6" radius={[0, 4, 4, 0]} barSize={10} />
                      <Bar dataKey="top10" fill="#22c55e" radius={[0, 4, 4, 0]} barSize={10} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          )}

          {/* Model Performance */}
          {accuracyData.length > 0 && (
            <div className="rounded-xl border border-dark-border bg-dark-card p-6">
              <h3 className="text-lg font-semibold mb-4">ML Model Performance</h3>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <div className="text-center">
                  <p className="text-2xl font-bold text-accent-blue">
                    {formatPercent(session.live_accuracy?.top_1_accuracy)}
                  </p>
                  <p className="text-sm text-slate-400">Previous Prediction Top-1</p>
                  <p className="text-xs text-slate-500">
                    {session.live_accuracy?.top_1_hits || 0} / {session.live_accuracy?.prediction_samples || 0} hits
                  </p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold text-green-400">
                    {formatPercent(session.live_accuracy?.top_10_accuracy)}
                  </p>
                  <p className="text-sm text-slate-400">Previous Prediction Top-10</p>
                  <p className="text-xs text-slate-500">
                    {session.live_accuracy?.top_10_hits || 0} / {session.live_accuracy?.prediction_samples || 0} hits
                  </p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold text-yellow-400">
                    {formatPercent(session.prefetch?.verified_prefetch_hit_rate)}
                  </p>
                  <p className="text-sm text-slate-400">Verified Prefetch Hit Rate</p>
                  <p className="text-xs text-slate-500">
                    {session.prefetch?.verified_prefetch_hits || 0} / {session.prefetch?.prefetch_opportunities || 0} opportunities
                  </p>
                </div>
              </div>
              <p className="mt-4 text-xs text-slate-500">
                `Verified` hanya dihitung jika worker benar-benar menyelesaikan prefetch key yang kemudian diminta.
                `Request-cached` berarti key ada di cache karena request sebelumnya sempat fallback ke KMS lalu menyimpannya.
              </p>
              <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
                <div className="rounded-lg border border-dark-border/70 bg-dark-bg/60 p-3">
                  <p className="text-xs uppercase tracking-wide text-slate-500">Worker-prefetched Hits</p>
                  <p className="mt-1 text-lg font-semibold text-emerald-300">
                    {formatNumber(session.prefetch?.worker_prefetched_hits)}
                  </p>
                </div>
                <div className="rounded-lg border border-dark-border/70 bg-dark-bg/60 p-3">
                  <p className="text-xs uppercase tracking-wide text-slate-500">Request-cached Hits</p>
                  <p className="mt-1 text-lg font-semibold text-sky-300">
                    {formatNumber(session.prefetch?.request_cached_hits)}
                  </p>
                </div>
                <div className="rounded-lg border border-dark-border/70 bg-dark-bg/60 p-3">
                  <p className="text-xs uppercase tracking-wide text-slate-500">Unknown Cache Origin</p>
                  <p className="mt-1 text-lg font-semibold text-slate-300">
                    {formatNumber(session.prefetch?.cache_hits_without_origin)}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Recent Trace */}
          {session.trace && session.trace.length > 0 && (
            <div className="rounded-xl border border-dark-border bg-dark-card p-6">
              <h3 className="text-lg font-semibold mb-4">Recent Request Trace</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-dark-border">
                      <th className="text-left py-2 px-3 text-slate-400">#</th>
                      <th className="text-left py-2 px-3 text-slate-400">Key</th>
                      <th className="text-left py-2 px-3 text-slate-400">Path</th>
                      <th className="text-left py-2 px-3 text-slate-400">Latency</th>
                      <th className="text-left py-2 px-3 text-slate-400">Prev Prediction</th>
                      <th className="text-left py-2 px-3 text-slate-400">Next Prediction</th>
                      <th className="text-left py-2 px-3 text-slate-400">Cache Origin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {session.trace.slice(-10).reverse().map((trace) => (
                      <tr key={trace.index} className="border-b border-dark-border/50">
                        <td className="py-2 px-3 text-slate-300">{trace.index}</td>
                        <td className="py-2 px-3 text-slate-300 font-mono text-xs">
                          {trace.key_id?.slice(0, 16)}...
                        </td>
                        <td className="py-2 px-3">
                          <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                            trace.path === 'l1_hit' ? 'bg-green-500/20 text-green-400' :
                            trace.path === 'l2_hit' ? 'bg-blue-500/20 text-blue-400' :
                            trace.path === 'kms_fetch' ? 'bg-yellow-500/20 text-yellow-400' :
                            trace.path === 'kms_miss' ? 'bg-red-500/20 text-red-400' :
                            'bg-slate-500/20 text-slate-400'
                          }`}>
                            {formatPathLabel(trace.path)}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-slate-300">{formatMs(trace.latency_ms)}</td>
                        <td className="py-2 px-3">
                          {trace.predicted_on_previous ? (
                            <span className={trace.top1_correct ? 'text-green-400' : 'text-yellow-300'}>
                              {trace.top1_correct ? 'Top-1' : 'Top-10'}
                            </span>
                          ) : (
                            <span className="text-slate-500">Missed</span>
                          )}
                        </td>
                        <td className="py-2 px-3">
                          {trace.prediction_preview && trace.prediction_preview.length > 0 ? (
                            <div className="flex flex-col gap-0.5">
                              {trace.prediction_preview.slice(0, 2).map((pred, i) => (
                                <span key={i} className="text-xs font-mono text-slate-400">
                                  <span className="text-slate-500">{i + 1}.</span>{' '}
                                  {pred.key_id?.slice(0, 10)}
                                  <span className="text-accent-blue ml-1">{(pred.confidence * 100).toFixed(0)}%</span>
                                </span>
                              ))}
                            </div>
                          ) : (
                            <span className="text-xs text-slate-600">-</span>
                          )}
                        </td>
                        <td className="py-2 px-3">
                          <span className={
                            trace.prefetched_by_worker
                              ? 'text-emerald-300'
                              : trace.prefetched_before_request
                                ? 'text-sky-300'
                                : 'text-slate-500'
                          }>
                            {formatCacheOrigin(trace)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-xs text-slate-500">
                `KMS fallback` berarti cache miss lalu request mengambil key dari KMS. Itu tidak otomatis berarti model salah.
                Penyebabnya bisa prediction miss, worker belum sempat menyelesaikan job, atau key churn/rotasi terlalu cepat.
              </p>
            </div>
          )}

          {/* Honesty Checks */}
          {session.honesty_checks && (
            <div className="rounded-xl border border-dark-border bg-dark-card p-6">
              <h3 className="text-lg font-semibold mb-4">Accountability Checks</h3>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {Object.entries(session.honesty_checks).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between">
                    <span className="text-sm text-slate-400">
                      {key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                    </span>
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                      value === true ? 'bg-green-500/20 text-green-400' :
                      value === false ? 'bg-red-500/20 text-red-400' :
                      'bg-slate-500/20 text-slate-400'
                    }`}>
                      {String(value).toUpperCase()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default LiveSimulationDashboard;
