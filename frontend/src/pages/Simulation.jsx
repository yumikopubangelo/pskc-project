import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import MLStatus from '../components/MLStatus';
import ScenarioSimulationLab from '../components/ScenarioSimulationLab';
import LiveSimulationDashboard from '../components/LiveSimulationDashboard';

const TERMINAL_STATUSES = new Set(['completed', 'stopped', 'failed']);
const PIE_COLORS = ['#14b8a6', '#0ea5e9', '#f59e0b', '#ef4444', '#a855f7'];

const formatFractionPercent = (value, digits = 1) =>
  value == null ? 'N/A' : `${(Number(value) * 100).toFixed(digits)}%`;

const formatPercent = (value, digits = 2) =>
  value == null ? 'N/A' : `${Number(value).toFixed(digits)}%`;

const formatMs = (value) =>
  value == null ? 'N/A' : `${Number(value).toFixed(2)} ms`;

const getStatusTone = (status) => {
  if (status === 'running' || status === 'stopping') return 'text-blue-300';
  if (status === 'completed') return 'text-green-300';
  if (status === 'failed') return 'text-red-300';
  if (status === 'stopped') return 'text-yellow-300';
  return 'text-slate-300';
};

const getPathTone = (path) => {
  if (path === 'l1_hit') return 'text-emerald-300';
  if (path === 'l2_hit') return 'text-sky-300';
  if (path === 'kms_fetch') return 'text-amber-300';
  if (path === 'kms_miss') return 'text-red-300';
  if (path === 'blocked') return 'text-fuchsia-300';
  return 'text-slate-300';
};

const formatPathLabel = (path) => {
  if (path === 'l1_hit') return 'L1 hit';
  if (path === 'l2_hit') return 'L2 hit';
  if (path === 'late_cache_hit') return 'Late cache hit';
  if (path === 'kms_fetch') return 'Cache miss -> KMS fallback';
  if (path === 'kms_miss') return 'Cache miss -> KMS failed/not found';
  if (path === 'blocked') return 'Blocked';
  return path || 'unknown';
};

const formatCacheOriginLabel = (row) => {
  if (row.prefetched_by_worker || row.cache_origin_before === 'worker_prefetch') return 'Worker-prefetched';
  if (row.prefetched_before_request && row.cache_origin_before === 'request_fetch') return 'Request-cached';
  if (row.prefetched_before_request) return 'Warm cache (origin unknown)';
  return 'No';
};

const Simulation = () => {
  const pollerRef = useRef(null);
  const eventSourceRef = useRef(null);
  const [error, setError] = useState(null);
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [liveSession, setLiveSession] = useState(null);
  const [transportMode, setTransportMode] = useState('idle');
  const [simulationView, setSimulationView] = useState('realtime');

  const [selectedScenario, setSelectedScenario] = useState('test');
  const [selectedTrafficType, setSelectedTrafficType] = useState('normal');
  const [seedData, setSeedData] = useState(true);
  const [simulateKms, setSimulateKms] = useState(true);
  const [modelPreference, setModelPreference] = useState('best_available');
  const [keyMode, setKeyMode] = useState('auto');
  const [virtualNodes, setVirtualNodes] = useState(3);

  const scenarios = [
    { value: 'test', label: 'Test (Default)' },
    { value: 'siakad', label: 'SIAKAD (Academic)' },
    { value: 'sevima', label: 'SEVIMA (Cloud Learning)' },
    { value: 'pddikti', label: 'PDDikti (Higher Education)' },
    { value: 'dynamic', label: 'Dynamic Production' },
  ];

  const trafficTypes = [
    { value: 'normal', label: 'Normal' },
    { value: 'heavy_load', label: 'Heavy Load' },
    { value: 'prime_time', label: 'Prime Time' },
    { value: 'degraded', label: 'Degraded' },
    { value: 'overload', label: 'Overload' },
  ];
  const keyModes = [
    { value: 'auto', label: 'Auto by Traffic' },
    { value: 'stable', label: 'Stable Keys' },
    { value: 'mixed', label: 'Mixed Rotation' },
    { value: 'high_churn', label: 'High Churn' },
  ];

  const cleanupLiveTransport = useCallback(() => {
    if (pollerRef.current) {
      window.clearInterval(pollerRef.current);
      pollerRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const fetchSnapshot = useCallback(async (id) => {
    try {
      const snapshot = await apiClient.getLiveSimulationSession(id);
      setLiveSession(snapshot);
      if (TERMINAL_STATUSES.has(snapshot.status)) {
        cleanupLiveTransport();
      }
    } catch (err) {
      setError(err.message || 'Failed to fetch live simulation snapshot');
      cleanupLiveTransport();
    }
  }, [cleanupLiveTransport]);

  const startPolling = useCallback((id) => {
    cleanupLiveTransport();
    setTransportMode('polling');
    fetchSnapshot(id);
    pollerRef.current = window.setInterval(() => {
      fetchSnapshot(id);
    }, 1000);
  }, [cleanupLiveTransport, fetchSnapshot]);

  const startEventStream = useCallback((id) => {
    if (typeof window === 'undefined' || typeof window.EventSource === 'undefined') {
      startPolling(id);
      return;
    }

    cleanupLiveTransport();
    setTransportMode('sse');
    const source = new window.EventSource(apiClient.getLiveSimulationStreamUrl(id));
    eventSourceRef.current = source;

    source.addEventListener('snapshot', (event) => {
      try {
        const snapshot = JSON.parse(event.data);
        setLiveSession(snapshot);
        if (TERMINAL_STATUSES.has(snapshot.status)) {
          cleanupLiveTransport();
        }
      } catch (err) {
        console.error('Failed to parse simulation stream snapshot', err);
      }
    });

    source.addEventListener('end', () => {
      cleanupLiveTransport();
    });

    source.onerror = () => {
      if (eventSourceRef.current) {
        cleanupLiveTransport();
        startPolling(id);
      }
    };
  }, [cleanupLiveTransport, startPolling]);

  useEffect(() => () => cleanupLiveTransport(), [cleanupLiveTransport]);

  const handleStartSimulation = useCallback(async () => {
    setIsStarting(true);
    setError(null);
    try {
      const session = await apiClient.startLiveSimulationSession({
        seedData,
        scenario: selectedScenario,
        trafficType: selectedTrafficType,
        simulateKms,
        modelPreference,
        keyMode,
        virtualNodes,
      });
      setLiveSession(session);
      setSessionId(session.session_id);
      startEventStream(session.session_id);
    } catch (err) {
      setError(err.message || 'Failed to start live simulation');
    } finally {
      setIsStarting(false);
    }
  }, [keyMode, modelPreference, seedData, selectedScenario, selectedTrafficType, simulateKms, startEventStream, virtualNodes]);

  const handleStopSimulation = useCallback(async () => {
    if (!sessionId) return;
    setIsStopping(true);
    setError(null);
    try {
      const snapshot = await apiClient.stopLiveSimulationSession(sessionId);
      setLiveSession(snapshot);
      cleanupLiveTransport();
    } catch (err) {
      setError(err.message || 'Failed to stop live simulation');
    } finally {
      setIsStopping(false);
    }
  }, [cleanupLiveTransport, sessionId]);

  const simulationStatus = liveSession?.status || 'not_started';
  const componentStatus = liveSession?.component_status || {};
  const model = liveSession?.model || {};
  const traceRows = Array.isArray(liveSession?.trace) ? liveSession.trace : [];
  const keyBreakdown = Array.isArray(liveSession?.key_breakdown) ? liveSession.key_breakdown : [];

  const latencyChartData = useMemo(
    () => traceRows.map((row) => ({ index: row.index, pskc: row.latency_ms, directKms: row.baseline_latency_ms })),
    [traceRows],
  );
  const cachePathData = useMemo(
    () => (Array.isArray(liveSession?.pskc_metrics?.path_breakdown) ? liveSession.pskc_metrics.path_breakdown : []),
    [liveSession],
  );
  const latencyComparisonData = useMemo(
    () => ([
      { name: 'With PSKC', latency: liveSession?.pskc_metrics?.avg_latency_ms || 0 },
      { name: 'Direct KMS', latency: liveSession?.baseline_metrics?.avg_latency_ms || 0 },
    ]),
    [liveSession],
  );
  const predictionSummaryData = useMemo(
    () => ([
      { name: 'Live Top-1', accuracy: liveSession?.live_accuracy?.top_1_accuracy || 0 },
      { name: 'Live Top-10', accuracy: liveSession?.live_accuracy?.top_10_accuracy || 0 },
      { name: 'Verified Prefetch', accuracy: liveSession?.prefetch?.verified_prefetch_hit_rate || 0 },
    ]),
    [liveSession],
  );

  const startDisabled = isStarting || simulationStatus === 'running' || simulationStatus === 'stopping';
  const stopDisabled = !sessionId || isStopping || TERMINAL_STATUSES.has(simulationStatus) || simulationStatus === 'not_started';

  return (
    <div className="container mx-auto p-4 text-white">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">PSKC Simulation Console</h1>
          <p className="text-sm text-slate-400 mt-1 max-w-3xl">
            <strong>Realtime:</strong> Backend hidup dengan komponen asli.{' '}
            <strong>Scenario Lab:</strong> Menggunakan folder simulation/ untuk benchmark.{' '}
            <strong>Live Dashboard:</strong> Simulasi real-time menggunakan Redis, prefetch worker, dan ML model untuk validasi akurasi.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="inline-flex rounded-xl border border-dark-border bg-dark-card p-1">
            <button
              onClick={() => setSimulationView('realtime')}
              className={`rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${
                simulationView === 'realtime' ? 'bg-accent-blue text-white' : 'text-slate-300 hover:text-white'
              }`}
            >
              Realtime
            </button>
            <button
              onClick={() => setSimulationView('scenario_lab')}
              className={`rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${
                simulationView === 'scenario_lab' ? 'bg-accent-blue text-white' : 'text-slate-300 hover:text-white'
              }`}
            >
              Scenario Lab
            </button>
            <button
              onClick={() => setSimulationView('live_dashboard')}
              className={`rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${
                simulationView === 'live_dashboard' ? 'bg-accent-blue text-white' : 'text-slate-300 hover:text-white'
              }`}
            >
              Live Dashboard
            </button>
          </div>
          {simulationView === 'realtime' && (
            <>
              <div className="rounded-lg border border-dark-border bg-dark-card px-4 py-2">
                <div className="text-xs uppercase tracking-wide text-slate-400">Status</div>
                <div className={`font-semibold ${getStatusTone(simulationStatus)}`}>{simulationStatus}</div>
              </div>
              <button
                onClick={handleStartSimulation}
                disabled={startDisabled}
                className="rounded-lg bg-accent-blue px-4 py-2 font-semibold text-white transition-colors hover:bg-accent-blue/80 disabled:cursor-not-allowed disabled:bg-slate-600"
              >
                {isStarting ? 'Starting...' : 'Start Realtime Simulation'}
              </button>
              <button
                onClick={handleStopSimulation}
                disabled={stopDisabled}
                className="rounded-lg border border-slate-600 px-4 py-2 font-semibold text-slate-200 transition-colors hover:border-red-400 hover:text-red-300 disabled:cursor-not-allowed disabled:text-slate-500"
              >
                {isStopping ? 'Stopping...' : 'Stop'}
              </button>
            </>
          )}
        </div>
      </div>

      {simulationView === 'scenario_lab' && <ScenarioSimulationLab />}

      {simulationView === 'live_dashboard' && <LiveSimulationDashboard />}

      {simulationView === 'realtime' && (
        <>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 mb-6">
        <div className="lg:col-span-2 rounded-xl border border-dark-border bg-dark-card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Simulation Controls</h2>
            <div className="text-xs text-slate-400">
              Mode: realtime, no fixed duration
              {transportMode !== 'idle' ? ` · transport ${transportMode.toUpperCase()}` : ''}
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
            <div>
              <label className="block text-sm text-slate-400 mb-1">Scenario</label>
              <select
                value={selectedScenario}
                onChange={(event) => setSelectedScenario(event.target.value)}
                className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none"
              >
                {scenarios.map((scenario) => (
                  <option key={scenario.value} value={scenario.value}>{scenario.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Traffic Profile</label>
              <select
                value={selectedTrafficType}
                onChange={(event) => setSelectedTrafficType(event.target.value)}
                className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none"
              >
                {trafficTypes.map((trafficType) => (
                  <option key={trafficType.value} value={trafficType.value}>{trafficType.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Model Preference</label>
              <select
                value={modelPreference}
                onChange={(event) => setModelPreference(event.target.value)}
                className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none"
              >
                <option value="best_available">Best Verified Model</option>
                <option value="active_runtime">Active Runtime Model</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Key Realism</label>
              <select
                value={keyMode}
                onChange={(event) => setKeyMode(event.target.value)}
                className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none"
              >
                {keyModes.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Virtual API Nodes</label>
              <input
                type="number"
                min="1"
                max="12"
                value={virtualNodes}
                onChange={(event) => {
                  const value = Number.parseInt(event.target.value, 10);
                  setVirtualNodes(Number.isNaN(value) ? 1 : Math.min(12, Math.max(1, value)));
                }}
                className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none"
              />
            </div>
            <div className="space-y-3">
              <label className="flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="checkbox"
                  checked={seedData}
                  onChange={(event) => setSeedData(event.target.checked)}
                  className="h-4 w-4 accent-accent-blue"
                />
                Seed collector if model missing
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="checkbox"
                  checked={simulateKms}
                  onChange={(event) => setSimulateKms(event.target.checked)}
                  className="h-4 w-4 accent-accent-blue"
                />
                Measure direct-KMS baseline
              </label>
            </div>
          </div>
        </div>
        <div className="lg:col-span-1">
          <MLStatus />
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-red-200">
          {error}
        </div>
      )}

      {liveSession && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <div className="text-sm text-slate-400 mb-1">Requests Processed</div>
              <div className="text-3xl font-bold">{liveSession.requests_processed || 0}</div>
              <div className="text-xs text-slate-500 mt-2">Session ID: {liveSession.session_id?.slice(0, 8) || 'N/A'}</div>
            </div>
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <div className="text-sm text-slate-400 mb-1">Live Top-1</div>
              <div className="text-3xl font-bold">{formatPercent(liveSession.live_accuracy?.top_1_accuracy, 2)}</div>
              <div className="text-xs text-slate-500 mt-2">
                {liveSession.live_accuracy?.prediction_samples || 0} grounded samples
              </div>
            </div>
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <div className="text-sm text-slate-400 mb-1">Live Top-10</div>
              <div className="text-3xl font-bold">{formatPercent(liveSession.live_accuracy?.top_10_accuracy, 2)}</div>
              <div className="text-xs text-slate-500 mt-2">Compared to the next request in the same stream</div>
            </div>
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <div className="text-sm text-slate-400 mb-1">Avg Latency Saved</div>
              <div className="text-3xl font-bold">{formatMs(liveSession.comparison?.avg_latency_saved_ms)}</div>
              <div className="text-xs text-slate-500 mt-2">
                {formatPercent(liveSession.comparison?.latency_improvement_percent, 2)} vs direct KMS
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-dark-border bg-dark-card p-5">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
              <div>
                <h2 className="text-lg font-semibold">Model Used by Simulation</h2>
                <p className="text-sm text-slate-400 mt-1">
                  Simulation memakai model terbaik menurut preference yang dipilih, lalu performanya diuji lagi lewat live trace.
                </p>
              </div>
              <div className={`text-sm font-semibold ${model.is_active_runtime ? 'text-emerald-300' : 'text-amber-300'}`}>
                {model.is_active_runtime ? 'Using active runtime model' : 'Using better verified shadow model'}
              </div>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4 mt-4">
              <div className="rounded-lg border border-dark-border/70 bg-dark-bg p-4">
                <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">Selected Version</div>
                <div className="font-mono text-white">{model.version || 'N/A'}</div>
              </div>
              <div className="rounded-lg border border-dark-border/70 bg-dark-bg p-4">
                <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">Source</div>
                <div className="text-white">{model.source || 'N/A'}</div>
              </div>
              <div className="rounded-lg border border-dark-border/70 bg-dark-bg p-4">
                <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">Metric Basis</div>
                <div className="text-white">
                  {model.metric_name || 'N/A'}
                  {model.metric_value != null ? ` (${formatFractionPercent(model.metric_value, 1)})` : ''}
                </div>
              </div>
              <div className="rounded-lg border border-dark-border/70 bg-dark-bg p-4">
                <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">Active Runtime</div>
                <div className="font-mono text-white">{componentStatus.active_model_version || 'N/A'}</div>
              </div>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-xl border border-dark-border bg-dark-card p-5">
              <h2 className="text-lg font-semibold mb-4">Component Proof</h2>
              <div className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-400">Redis / L2 Cache</span>
                  <span className={componentStatus.redis_available ? 'text-emerald-300' : 'text-red-300'}>
                    {componentStatus.redis_available ? 'Verified' : 'Unavailable'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Prefetch Queue</span>
                  <span className={componentStatus.prefetch_queue_available ? 'text-emerald-300' : 'text-red-300'}>
                    {componentStatus.prefetch_queue_available ? 'Verified' : 'Unavailable'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Prefetch Worker</span>
                  <span className={componentStatus.prefetch_worker_active ? 'text-emerald-300' : 'text-amber-300'}>
                    {componentStatus.prefetch_worker_active ? 'Active' : 'Not verified'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">KMS Provider</span>
                  <span className="text-white">{componentStatus.kms_provider || 'generic'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Virtual API Nodes</span>
                  <span className="text-white">{componentStatus.virtual_node_count ?? virtualNodes}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Model Loaded</span>
                  <span className={componentStatus.model_loaded ? 'text-emerald-300' : 'text-red-300'}>
                    {componentStatus.model_loaded ? 'Yes' : 'No'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">L1 Cache Size</span>
                  <span className="text-white">{componentStatus.l1_cache_size ?? 0}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Virtual L1 Total</span>
                  <span className="text-white">{componentStatus.virtual_l1_cache_size ?? 0}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">L2 Cache Size</span>
                  <span className="text-white">{componentStatus.l2_cache_size ?? 0}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Worker Completed Delta</span>
                  <span className="text-white">{liveSession.prefetch?.worker_completed_delta ?? 0}</span>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-dark-border bg-dark-card p-5">
              <h2 className="text-lg font-semibold mb-4">Honesty Checks</h2>
              <div className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-400">Ground Truth Next Request</span>
                  <span className="text-emerald-300">
                    {liveSession.honesty_checks?.uses_ground_truth_next_request ? 'Enabled' : 'No'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Explicit Cache Path Tracking</span>
                  <span className="text-emerald-300">
                    {liveSession.honesty_checks?.cache_path_tracked_explicitly ? 'Enabled' : 'No'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Prediction Samples</span>
                  <span className="text-white">{liveSession.honesty_checks?.prediction_sample_count ?? 0}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Same Stream for Baseline</span>
                  <span className="text-white">
                    {liveSession.honesty_checks?.uses_same_request_stream_for_baseline ? 'Yes' : 'No'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Stable Simulation Keys</span>
                  <span className="text-white">
                    {liveSession.honesty_checks?.stable_simulation_keys ? 'Yes' : 'No'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Key Mode</span>
                  <span className="text-white">{liveSession.honesty_checks?.key_mode || keyMode}</span>
                </div>
                <p className="pt-2 text-slate-400">
                  Nilai live hanya dihitung jika prediksi memang dibandingkan dengan request berikutnya pada stream yang sama.
                </p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <div className="rounded-xl border border-dark-border bg-dark-card p-5">
              <h2 className="text-lg font-semibold mb-4">Latency: PSKC vs Direct KMS</h2>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={latencyChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="index" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="pskc" stroke="#14b8a6" dot={false} name="With PSKC" />
                    <Line type="monotone" dataKey="directKms" stroke="#f59e0b" dot={false} name="Direct KMS" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="rounded-xl border border-dark-border bg-dark-card p-5">
              <h2 className="text-lg font-semibold mb-4">Cache Path Breakdown</h2>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={cachePathData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100}>
                      {cachePathData.map((entry, index) => (
                        <Cell key={`${entry.name}-${index}`} fill={entry.color || PIE_COLORS[index % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <div className="rounded-xl border border-dark-border bg-dark-card p-5">
              <h2 className="text-lg font-semibold mb-4">Accuracy and Prefetch Evidence</h2>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={predictionSummaryData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="accuracy" fill="#38bdf8" radius={[6, 6, 0, 0]} name="Percent" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
                <div className="rounded-lg border border-dark-border/70 bg-dark-bg p-4">
                  <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">Worker-prefetched Hits</div>
                  <div className="text-lg font-semibold text-emerald-300">
                    {liveSession.prefetch?.worker_prefetched_hits ?? 0}
                  </div>
                </div>
                <div className="rounded-lg border border-dark-border/70 bg-dark-bg p-4">
                  <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">Request-cached Hits</div>
                  <div className="text-lg font-semibold text-sky-300">
                    {liveSession.prefetch?.request_cached_hits ?? 0}
                  </div>
                </div>
                <div className="rounded-lg border border-dark-border/70 bg-dark-bg p-4">
                  <div className="text-xs uppercase tracking-wide text-slate-400 mb-1">Unknown Origin Hits</div>
                  <div className="text-lg font-semibold text-slate-300">
                    {liveSession.prefetch?.cache_hits_without_origin ?? 0}
                  </div>
                </div>
              </div>
              <p className="mt-3 text-xs text-slate-500">
                `Verified Prefetch` adalah metrik ketat: hanya dihitung bila key yang diminta memang diprediksi
                sebelumnya, worker menyelesaikan prefetch-nya, lalu request berikutnya benar-benar memanfaatkan cache hangat itu.
              </p>
            </div>

            <div className="rounded-xl border border-dark-border bg-dark-card p-5">
              <h2 className="text-lg font-semibold mb-4">Average Latency Comparison</h2>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={latencyComparisonData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="latency" fill="#34d399" radius={[6, 6, 0, 0]} name="Avg Latency (ms)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <div className="rounded-xl border border-dark-border bg-dark-card p-5">
              <h2 className="text-lg font-semibold mb-4">PSKC vs No-PSKC Summary</h2>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="rounded-lg border border-dark-border/70 bg-dark-bg p-4">
                  <div className="text-sm text-slate-400 mb-2">With PSKC</div>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-slate-400">Avg Latency</span>
                      <span className="text-white">{formatMs(liveSession.pskc_metrics?.avg_latency_ms)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">P95 Latency</span>
                      <span className="text-white">{formatMs(liveSession.pskc_metrics?.p95_latency_ms)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Cache Hit Rate</span>
                      <span className="text-white">{formatPercent(liveSession.pskc_metrics?.cache_hit_rate, 2)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">L1 / L2 / KMS</span>
                      <span className="text-white">
                        {liveSession.pskc_metrics?.l1_hits ?? 0} / {liveSession.pskc_metrics?.l2_hits ?? 0} / {liveSession.pskc_metrics?.kms_fetches ?? 0}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="rounded-lg border border-dark-border/70 bg-dark-bg p-4">
                  <div className="text-sm text-slate-400 mb-2">Without PSKC</div>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-slate-400">Avg Latency</span>
                      <span className="text-white">{formatMs(liveSession.baseline_metrics?.avg_latency_ms)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">P95 Latency</span>
                      <span className="text-white">{formatMs(liveSession.baseline_metrics?.p95_latency_ms)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Direct KMS Requests</span>
                      <span className="text-white">{liveSession.baseline_metrics?.direct_kms_requests ?? 0}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Simulation Mode</span>
                      <span className="text-white">{liveSession.simulate_kms ? 'Measured live' : 'Disabled'}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-dark-border bg-dark-card p-5">
              <h2 className="text-lg font-semibold mb-4">Most Active Keys</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b border-dark-border text-left text-slate-400">
                    <tr>
                      <th className="py-2 pr-4">Key</th>
                      <th className="py-2 pr-4">Total</th>
                      <th className="py-2 pr-4">L1</th>
                      <th className="py-2 pr-4">L2</th>
                      <th className="py-2 pr-4">KMS</th>
                      <th className="py-2 pr-4">Miss</th>
                    </tr>
                  </thead>
                  <tbody>
                    {keyBreakdown.map((row) => (
                      <tr key={row.key_id} className="border-b border-dark-border/50">
                        <td className="py-2 pr-4 font-mono text-xs text-slate-200">{row.key_id}</td>
                        <td className="py-2 pr-4">{row.total}</td>
                        <td className="py-2 pr-4 text-emerald-300">{row.l1_hits}</td>
                        <td className="py-2 pr-4 text-sky-300">{row.l2_hits}</td>
                        <td className="py-2 pr-4 text-amber-300">{row.kms_fetches}</td>
                        <td className="py-2 pr-4 text-red-300">{row.kms_misses}</td>
                      </tr>
                    ))}
                    {keyBreakdown.length === 0 && (
                      <tr>
                        <td className="py-4 text-slate-500" colSpan={6}>Belum ada trace key untuk session ini.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-dark-border bg-dark-card p-5">
            <h2 className="text-lg font-semibold mb-4">Request Trace</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-dark-border text-left text-slate-400">
                  <tr>
                    <th className="py-2 pr-4">#</th>
                    <th className="py-2 pr-4">Node</th>
                    <th className="py-2 pr-4">Service</th>
                    <th className="py-2 pr-4">Key</th>
                    <th className="py-2 pr-4">Path</th>
                    <th className="py-2 pr-4">Prev Prediction Top-1</th>
                    <th className="py-2 pr-4">Prev Prediction Top-10</th>
                    <th className="py-2 pr-4">Cache Origin</th>
                    <th className="py-2 pr-4">PSKC Latency</th>
                    <th className="py-2 pr-4">Direct KMS</th>
                    <th className="py-2 pr-4">Saved</th>
                  </tr>
                </thead>
                <tbody>
                  {traceRows.slice().reverse().map((row) => (
                    <tr key={`${row.index}-${row.key_id}`} className="border-b border-dark-border/50">
                      <td className="py-2 pr-4">{row.index}</td>
                      <td className="py-2 pr-4">{row.node_id || 'N/A'}</td>
                      <td className="py-2 pr-4">{row.service_id}</td>
                      <td className="py-2 pr-4 font-mono text-xs text-slate-200">{row.key_id}</td>
                      <td className={`py-2 pr-4 font-semibold ${getPathTone(row.path)}`}>{formatPathLabel(row.path)}</td>
                      <td className={`py-2 pr-4 ${row.top1_correct ? 'text-emerald-300' : 'text-slate-400'}`}>
                        {row.predicted_on_previous ? (row.top1_correct ? 'Correct' : 'Wrong') : 'N/A'}
                      </td>
                      <td className={`py-2 pr-4 ${row.top10_correct ? 'text-emerald-300' : 'text-slate-400'}`}>
                        {row.predicted_on_previous ? (row.top10_correct ? 'Found' : 'Missed') : 'N/A'}
                      </td>
                      <td className={`py-2 pr-4 ${
                        row.prefetched_by_worker
                          ? 'text-emerald-300'
                          : row.prefetched_before_request
                            ? 'text-sky-300'
                            : 'text-slate-400'
                      }`}>
                        {formatCacheOriginLabel(row)}
                      </td>
                      <td className="py-2 pr-4">{formatMs(row.latency_ms)}</td>
                      <td className="py-2 pr-4">{formatMs(row.baseline_latency_ms)}</td>
                      <td className={row.latency_saved_ms > 0 ? 'py-2 pr-4 text-emerald-300' : 'py-2 pr-4 text-slate-400'}>
                        {formatMs(row.latency_saved_ms)}
                      </td>
                    </tr>
                  ))}
                  {traceRows.length === 0 && (
                    <tr>
                      <td className="py-4 text-slate-500" colSpan={11}>
                        Session belum menghasilkan trace. Start simulation untuk mulai melihat request hidup.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-slate-500">
              Kolom previous prediction membandingkan request saat ini dengan tebakan yang dibuat pada request sebelumnya
              di stream service yang sama. `Cache Origin = Worker-prefetched` berarti worker benar-benar memanaskan key
              itu sebelum request masuk. `Request-cached` berarti key sudah ada di cache karena request sebelumnya pernah
              fallback ke KMS lalu menyimpannya ke cache. Jadi `L2 hit` tidak selalu berarti worker prefetch berhasil.
              `KMS fallback` sendiri berarti cache miss lalu request mengambil key dari KMS; ini tidak otomatis berarti
              model salah, karena bisa juga worker belum sempat selesai atau key sudah berotasi terlalu cepat.
            </p>
          </div>
        </div>
      )}
        </>
      )}
    </div>
  );
};

export default Simulation;
