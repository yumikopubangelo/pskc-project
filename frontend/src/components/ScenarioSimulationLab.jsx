import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
import MLStatus from './MLStatus';

const PIE_COLORS = ['#14b8a6', '#0ea5e9', '#22c55e', '#f59e0b', '#f97316', '#ef4444', '#a855f7'];

const formatPercent = (value, digits = 1) =>
  value == null ? 'N/A' : `${Number(value).toFixed(digits)}%`;

const formatMs = (value) =>
  value == null ? 'N/A' : `${Number(value).toFixed(2)} ms`;

const formatDetails = (details) => {
  if (!details || typeof details !== 'object') {
    return 'N/A';
  }

  return Object.entries(details)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(', ');
};

const ScenarioSimulationLab = () => {
  const [catalog, setCatalog] = useState(null);
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [catalogError, setCatalogError] = useState(null);
  const [runError, setRunError] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [selectedScenario, setSelectedScenario] = useState('');
  const [selectedProfile, setSelectedProfile] = useState('');
  const [requestCount, setRequestCount] = useState(1000);
  const [result, setResult] = useState(null);

  const loadCatalog = useCallback(async () => {
    setLoadingCatalog(true);
    setCatalogError(null);
    try {
      const payload = await apiClient.getSimulationScenarios();
      setCatalog(payload);

      const scenarios = Array.isArray(payload?.scenarios) ? payload.scenarios : [];
      const defaultScenarioId = payload?.default_scenario || scenarios[0]?.id || '';
      const defaultScenario = scenarios.find((item) => item.id === defaultScenarioId) || scenarios[0];

      if (defaultScenario) {
        setSelectedScenario(defaultScenario.id);
        setSelectedProfile(defaultScenario.profiles?.[0]?.id || '');
        setRequestCount(defaultScenario.default_request_count || 1000);
      }
    } catch (error) {
      setCatalogError(error.message || 'Failed to load simulation scenarios');
    } finally {
      setLoadingCatalog(false);
    }
  }, []);

  useEffect(() => {
    loadCatalog();
  }, [loadCatalog]);

  const scenarios = Array.isArray(catalog?.scenarios) ? catalog.scenarios : [];
  const activeScenario = useMemo(
    () => scenarios.find((item) => item.id === selectedScenario) || null,
    [scenarios, selectedScenario],
  );
  const activeProfiles = activeScenario?.profiles || [];
  const availableViews = Array.isArray(catalog?.available_views) ? catalog.available_views : [];

  const latencyTrendData = Array.isArray(result?.charts?.latency_trend) ? result.charts.latency_trend : [];
  const cacheFlow = result?.integrated_simulation?.cache_flow || {};
  const traceView = result?.integrated_simulation?.detailed_trace || {};
  const pathComparisonData = Array.isArray(cacheFlow.path_comparison) ? cacheFlow.path_comparison : [];
  const withPathBreakdown = Array.isArray(cacheFlow?.with_pskc?.path_breakdown) ? cacheFlow.with_pskc.path_breakdown : [];
  const tracePreview = Array.isArray(traceView.trace_preview) ? traceView.trace_preview : [];
  const layerBreakdown = Array.isArray(traceView.layer_breakdown) ? traceView.layer_breakdown : [];

  const cacheSummaryData = useMemo(
    () => ([
      {
        name: 'Avg Latency',
        without_pskc: cacheFlow?.without_pskc?.avg_latency_ms || 0,
        with_pskc: cacheFlow?.with_pskc?.avg_latency_ms || 0,
      },
      {
        name: 'P95 Latency',
        without_pskc: cacheFlow?.without_pskc?.p95_latency_ms || 0,
        with_pskc: cacheFlow?.with_pskc?.p95_latency_ms || 0,
      },
      {
        name: 'Cache Hit %',
        without_pskc: cacheFlow?.without_pskc?.cache_hit_rate || 0,
        with_pskc: cacheFlow?.with_pskc?.cache_hit_rate || 0,
      },
    ]),
    [cacheFlow],
  );

  const handleScenarioChange = useCallback((event) => {
    const scenarioId = event.target.value;
    setSelectedScenario(scenarioId);
    const scenario = scenarios.find((item) => item.id === scenarioId);
    setSelectedProfile(scenario?.profiles?.[0]?.id || '');
    setRequestCount(scenario?.default_request_count || 1000);
  }, [scenarios]);

  const handleRun = useCallback(async () => {
    if (!selectedScenario) {
      setRunError('Scenario belum dipilih.');
      return;
    }

    setIsRunning(true);
    setRunError(null);
    try {
      const response = await apiClient.runSimulation({
        scenario: selectedScenario,
        profile_id: selectedProfile || null,
        request_count: requestCount,
      });
      const payload = await apiClient.getSimulationResults(response.simulation_id);
      setResult(payload);
    } catch (error) {
      setRunError(error.message || 'Failed to run scenario simulation');
    } finally {
      setIsRunning(false);
    }
  }, [requestCount, selectedProfile, selectedScenario]);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2 rounded-xl border border-dark-border bg-dark-card p-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-lg font-semibold">Scenario Lab</h2>
              <p className="mt-1 max-w-3xl text-sm text-slate-400">
                Mode ini memakai folder <span className="font-mono text-slate-300">simulation/</span> yang Anda update.
                Hasilnya menggabungkan benchmark referensi, cache-flow cepat, dan trace preview detail.
              </p>
            </div>
            <button
              onClick={handleRun}
              disabled={loadingCatalog || isRunning || !selectedScenario}
              className="rounded-lg bg-accent-blue px-4 py-2 font-semibold text-white transition-colors hover:bg-accent-blue/80 disabled:cursor-not-allowed disabled:bg-slate-600"
            >
              {isRunning ? 'Running...' : 'Run Scenario Lab'}
            </button>
          </div>

          <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div>
              <label className="mb-1 block text-sm text-slate-400">Scenario</label>
              <select
                value={selectedScenario}
                onChange={handleScenarioChange}
                className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none"
              >
                {scenarios.map((scenario) => (
                  <option key={scenario.id} value={scenario.id}>{scenario.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm text-slate-400">Profile</label>
              <select
                value={selectedProfile}
                onChange={(event) => setSelectedProfile(event.target.value)}
                className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none"
              >
                {activeProfiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>{profile.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm text-slate-400">Requests</label>
              <input
                type="number"
                min="50"
                max="10000"
                value={requestCount}
                onChange={(event) => {
                  const value = Number.parseInt(event.target.value, 10);
                  setRequestCount(Number.isNaN(value) ? 50 : Math.min(10000, Math.max(50, value)));
                }}
                className="w-full rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-white focus:border-accent-blue focus:outline-none"
              />
            </div>
            <div className="rounded-lg border border-dark-border/70 bg-dark-bg p-3">
              <div className="text-xs uppercase tracking-wide text-slate-500">Frontend Views</div>
              <div className="mt-2 space-y-1 text-sm text-slate-200">
                {availableViews.length > 0 ? availableViews.map((view) => (
                  <div key={view.id}>{view.name}</div>
                )) : <div>Scenario Lab</div>}
              </div>
            </div>
          </div>

          {activeScenario && (
            <div className="mt-5 rounded-xl border border-dark-border/70 bg-dark-bg p-4">
              <div className="text-sm text-slate-300">{activeScenario.summary}</div>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
                <div>
                  <div className="text-xs uppercase tracking-wide text-slate-500">Category</div>
                  <div className="text-sm text-white">{activeScenario.category}</div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wide text-slate-500">Expected Hit Rate</div>
                  <div className="text-sm text-white">{formatPercent((activeScenario.expected_hit_rate || 0) * 100, 1)}</div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wide text-slate-500">Target P99</div>
                  <div className="text-sm text-white">{formatMs(activeScenario.target_p99_ms)}</div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="xl:col-span-1">
          <MLStatus />
        </div>
      </div>

      {loadingCatalog && (
        <div className="rounded-xl border border-dark-border bg-dark-card p-4 text-slate-300">
          Loading simulation catalog...
        </div>
      )}

      {catalogError && (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-red-200">
          {catalogError}
        </div>
      )}

      {runError && (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-red-200">
          {runError}
        </div>
      )}

      {result && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <div className="mb-1 text-sm text-slate-400">Avg Latency Reduction</div>
              <div className="text-3xl font-bold">{formatPercent(result.comparison?.latency_reduction_pct, 1)}</div>
              <div className="mt-2 text-xs text-slate-500">Reference scenario comparison</div>
            </div>
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <div className="mb-1 text-sm text-slate-400">P99 Reduction</div>
              <div className="text-3xl font-bold">{formatPercent(result.comparison?.p99_reduction_pct, 1)}</div>
              <div className="mt-2 text-xs text-slate-500">Against no-PSKC baseline</div>
            </div>
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <div className="mb-1 text-sm text-slate-400">Time Saved</div>
              <div className="text-3xl font-bold">{result.comparison?.time_saved_seconds ?? 0}s</div>
              <div className="mt-2 text-xs text-slate-500">Aggregate savings across the batch</div>
            </div>
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <div className="mb-1 text-sm text-slate-400">Cache-Flow Avg Saved</div>
              <div className="text-3xl font-bold">{formatMs(cacheFlow?.comparison?.avg_latency_saved_ms)}</div>
              <div className="mt-2 text-xs text-slate-500">
                {formatPercent(cacheFlow?.comparison?.kms_fetch_reduction_pct, 1)} fewer KMS fetches
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <div className="rounded-xl border border-dark-border bg-dark-card p-5">
              <h3 className="mb-4 text-lg font-semibold">Reference Latency Trend</h3>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={latencyTrendData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="request" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="withoutLatency" stroke="#f59e0b" dot={false} name="Without PSKC" />
                    <Line type="monotone" dataKey="withLatency" stroke="#14b8a6" dot={false} name="With PSKC" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="rounded-xl border border-dark-border bg-dark-card p-5">
              <h3 className="mb-4 text-lg font-semibold">Cache-Flow Summary</h3>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={cacheSummaryData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="without_pskc" fill="#f59e0b" radius={[6, 6, 0, 0]} name="Without PSKC" />
                    <Bar dataKey="with_pskc" fill="#14b8a6" radius={[6, 6, 0, 0]} name="With PSKC" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <div className="rounded-xl border border-dark-border bg-dark-card p-5">
              <h3 className="mb-4 text-lg font-semibold">Updated Path Breakdown</h3>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={withPathBreakdown} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100}>
                      {withPathBreakdown.map((entry, index) => (
                        <Cell key={`${entry.name}-${index}`} fill={entry.color || PIE_COLORS[index % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="rounded-xl border border-dark-border bg-dark-card p-5">
              <h3 className="mb-4 text-lg font-semibold">Path Comparison</h3>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={pathComparisonData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="without_pskc" fill="#f59e0b" radius={[6, 6, 0, 0]} name="Without PSKC" />
                    <Bar dataKey="with_pskc" fill="#22c55e" radius={[6, 6, 0, 0]} name="With PSKC" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <div className="rounded-xl border border-dark-border bg-dark-card p-5 xl:col-span-2">
              <h3 className="mb-4 text-lg font-semibold">Trace Preview from Updated Simulation</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b border-dark-border text-left text-slate-400">
                    <tr>
                      <th className="py-2 pr-4">#</th>
                      <th className="py-2 pr-4">Service</th>
                      <th className="py-2 pr-4">Key</th>
                      <th className="py-2 pr-4">Layer</th>
                      <th className="py-2 pr-4">Path</th>
                      <th className="py-2 pr-4">Latency</th>
                      <th className="py-2 pr-4">Success</th>
                      <th className="py-2 pr-4">Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tracePreview.map((row) => (
                      <tr key={`${row.index}-${row.key_id}`} className="border-b border-dark-border/50">
                        <td className="py-2 pr-4">{row.index}</td>
                        <td className="py-2 pr-4">{row.service_id}</td>
                        <td className="py-2 pr-4 font-mono text-xs text-slate-200">{row.key_id}</td>
                        <td className="py-2 pr-4">{row.cache_layer}</td>
                        <td className="py-2 pr-4">{row.path}</td>
                        <td className="py-2 pr-4">{formatMs(row.latency_ms)}</td>
                        <td className={`py-2 pr-4 ${row.success ? 'text-emerald-300' : 'text-red-300'}`}>
                          {row.success ? 'Yes' : 'No'}
                        </td>
                        <td className="py-2 pr-4 text-xs text-slate-400">{formatDetails(row.details)}</td>
                      </tr>
                    ))}
                    {tracePreview.length === 0 && (
                      <tr>
                        <td className="py-4 text-slate-500" colSpan={8}>
                          Trace preview belum tersedia untuk hasil ini.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="space-y-6">
              <div className="rounded-xl border border-dark-border bg-dark-card p-5">
                <h3 className="mb-4 text-lg font-semibold">Component Proof</h3>
                <div className="space-y-3 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Predictor</span>
                    <span className="text-emerald-300">{traceView?.component_proof?.predictor_enabled ? 'Enabled' : 'No'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">L1 Cache</span>
                    <span className="text-emerald-300">{traceView?.component_proof?.l1_cache_enabled ? 'Enabled' : 'No'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">L2 Cache</span>
                    <span className="text-emerald-300">{traceView?.component_proof?.l2_cache_enabled ? 'Enabled' : 'No'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Prefetch</span>
                    <span className="text-emerald-300">{traceView?.component_proof?.prefetch_enabled ? 'Enabled' : 'No'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">KMS Fallback</span>
                    <span className="text-emerald-300">{traceView?.component_proof?.kms_fallback_enabled ? 'Enabled' : 'No'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Prefetch Processed</span>
                    <span className="text-white">{traceView?.aggregate?.prefetch_jobs_processed ?? 0}</span>
                  </div>
                </div>
              </div>

              <div className="rounded-xl border border-dark-border bg-dark-card p-5">
                <h3 className="mb-4 text-lg font-semibold">Trace Layer Breakdown</h3>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={layerBreakdown} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80}>
                        {layerBreakdown.map((entry, index) => (
                          <Cell key={`${entry.name}-${index}`} fill={entry.color || PIE_COLORS[index % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-xl border border-dark-border bg-dark-card p-5">
                <h3 className="mb-4 text-lg font-semibold">Why This View Matters</h3>
                <div className="space-y-2 text-sm text-slate-300">
                  {(traceView?.notes || []).map((note, index) => (
                    <p key={`${note}-${index}`}>{note}</p>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-dark-border bg-dark-card p-5">
            <h3 className="mb-4 text-lg font-semibold">References</h3>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {(result?.metadata?.references || []).map((reference) => (
                <a
                  key={reference.title}
                  href={reference.url}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-lg border border-dark-border/70 bg-dark-bg p-4 text-sm transition-colors hover:border-accent-blue"
                >
                  <div className="font-semibold text-slate-100">{reference.title}</div>
                  <div className="mt-1 break-all text-xs text-slate-400">{reference.url}</div>
                </a>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ScenarioSimulationLab;
