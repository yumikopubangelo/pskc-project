import React, { useState, useCallback, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar, PieChart, Pie, Cell } from 'recharts';
import apiClient from '../utils/apiClient';

// Color palette
const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8'];

const Simulation = () => {
  const [isSimulating, setIsSimulating] = useState(false);
  const [simulationStatus, setSimulationStatus] = useState('Not Started');
  const [liveTestResult, setLiveTestResult] = useState(null);
  const [error, setError] = useState(null);
  
  // Configuration state
  const [selectedScenario, setSelectedScenario] = useState('test');
  const [selectedTrafficType, setSelectedTrafficType] = useState('normal');
  const [numRequests, setNumRequests] = useState(50);
  const [seedData, setSeedData] = useState(true);
  
  // Scenario and traffic type options
  const scenarios = [
    { value: 'test', label: 'Test (Default)' },
    { value: 'siakad', label: 'SIAKAD (Academic)' },
    { value: 'sevima', label: 'SEVIMA (Cloud Learning)' },
    { value: 'pddikti', label: 'PDDikti (Higher Education)' },
    { value: 'dynamic', label: 'Dynamic Production' },
  ];
  
  const trafficTypes = [
    { value: 'normal', label: 'Normal (80% hit rate)' },
    { value: 'heavy_load', label: 'Heavy Load (60% hit rate)' },
    { value: 'prime_time', label: 'Prime Time (50% hit rate)' },
    { value: 'degraded', label: 'Degraded (30% hit rate)' },
  ];
  
  // Cache visualization data
  const [cacheData, setCacheData] = useState([]);
  // Prefetch visualization data
  const [prefetchData, setPrefetchData] = useState([]);
  // ML predictions
  const [mlPredictions, setMlPredictions] = useState([]);
  // Latency data
  const [latencyData, setLatencyData] = useState([]);
  // Overall results
  const [testSummary, setTestSummary] = useState(null);

  // Fetch initial system status
  const fetchSystemStatus = useCallback(async () => {
    try {
      const status = await apiClient.getLiveTestStatus();
      return status;
    } catch (err) {
      console.error('Failed to fetch system status:', err);
      return null;
    }
  }, []);

  // Run live system test
  const handleStartSimulation = useCallback(async () => {
    setIsSimulating(true);
    setSimulationStatus('Running');
    setError(null);
    setLiveTestResult(null);
    setCacheData([]);
    setPrefetchData([]);
    setMlPredictions([]);
    setLatencyData([]);
    setTestSummary(null);

    try {
      // Call the backend live-test API with scenario and traffic type
      const result = await apiClient.runLiveTest(numRequests, seedData, selectedScenario, selectedTrafficType);
      setLiveTestResult(result);
      
      // Process the results for visualization
      if (result.steps) {
        // Extract data from each step
        const cacheStep = result.steps.find(s => s.step === 'cache_test');
        const prefetchStep = result.steps.find(s => s.step === 'prefetch_test');
        const mlStep = result.steps.find(s => s.step === 'ml_predictions');
        const latencyStep = result.steps.find(s => s.step === 'latency_test');
        const seedingStep = result.steps.find(s => s.step === 'data_seeding');

        // Build cache visualization data
        if (cacheStep) {
          setCacheData([
            { name: 'Hits', value: cacheStep.cache_hits, color: '#00C49F' },
            { name: 'Misses', value: cacheStep.cache_misses, color: '#FF8042' },
          ]);
        }

        // Build prefetch visualization data
        if (prefetchStep) {
          setPrefetchData([
            { name: 'Before', jobs: prefetchStep.queue_before },
            { name: 'After', jobs: prefetchStep.queue_after },
            { name: 'Enqueued', jobs: prefetchStep.jobs_enqueued },
          ]);
        }

        // Build ML predictions list
        if (mlStep && mlStep.predictions) {
          setMlPredictions(mlStep.predictions.map((p, i) => ({
            key: i,
            keyId: p.key_id,
            confidence: (p.confidence * 100).toFixed(1),
          })));
        }

        // Build latency visualization data
        if (latencyStep) {
          setLatencyData([
            { name: 'Average', latency: latencyStep.avg_latency_ms, color: '#0088FE' },
            { name: 'P50', latency: latencyStep.p50_ms, color: '#00C49F' },
            { name: 'P99', latency: latencyStep.p99_ms, color: '#FFBB28' },
            { name: 'Min', latency: latencyStep.min_ms, color: '#8884d8' },
            { name: 'Max', latency: latencyStep.max_ms, color: '#FF8042' },
          ]);
        }

        // Build test summary
        const summary = {
          overallSuccess: result.overall_success,
          stepsCompleted: result.steps.filter(s => s.success).length,
          totalSteps: result.steps.length,
          dataSeeding: seedingStep?.success ? '✓' : '✗',
          mlPredictions: mlStep?.success ? '✓' : '✗',
          cacheTest: cacheStep?.success ? '✓' : '✗',
          prefetchTest: prefetchStep?.success ? '✓' : '✗',
          latencyTest: latencyStep?.success ? '✓' : '✗',
        };
        setTestSummary(summary);
      }

      setSimulationStatus('Finished');
    } catch (err) {
      console.error('Live test failed:', err);
      setError(err.message || 'Failed to run live test');
      setSimulationStatus('Failed');
    } finally {
      setIsSimulating(false);
    }
  }, [numRequests, seedData, selectedScenario, selectedTrafficType]);

  // Load system status on mount
  useEffect(() => {
    fetchSystemStatus();
  }, [fetchSystemStatus]);

  return (
    <div className="container mx-auto p-4 text-white">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold">Live System Test</h1>
          <p className="text-gray-400 text-sm mt-1">
            Test your ML predictions, pre-caching, and prefetch-worker
          </p>
        </div>
        <div className="flex items-center gap-4">
          <span>
            Status:{' '}
            <span
              className={`font-semibold ${
                simulationStatus === 'Finished'
                  ? 'text-green-400'
                  : simulationStatus === 'Running'
                  ? 'text-blue-400'
                  : simulationStatus === 'Failed'
                  ? 'text-red-400'
                  : 'text-yellow-400'
              }`}
            >
              {simulationStatus}
            </span>
          </span>
          <button
            onClick={handleStartSimulation}
            disabled={isSimulating}
            className="bg-accent-blue hover:bg-accent-blue/80 text-white font-bold py-2 px-4 rounded disabled:bg-gray-600 disabled:cursor-not-allowed transition-colors"
          >
            {isSimulating ? 'Testing...' : 'Run Live Test'}
          </button>
        </div>
      </div>

      {/* Configuration Panel */}
      <div className="bg-dark-card rounded-lg p-4 mb-6 border border-dark-border">
        <h2 className="text-lg font-semibold mb-4">Test Configuration</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Scenario Selection */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">Scenario</label>
            <select
              value={selectedScenario}
              onChange={(e) => setSelectedScenario(e.target.value)}
              className="w-full bg-dark-bg border border-dark-border rounded px-3 py-2 text-white focus:outline-none focus:border-accent-blue"
            >
              {scenarios.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>
          
          {/* Traffic Type Selection */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">Traffic Type</label>
            <select
              value={selectedTrafficType}
              onChange={(e) => setSelectedTrafficType(e.target.value)}
              className="w-full bg-dark-bg border border-dark-border rounded px-3 py-2 text-white focus:outline-none focus:border-accent-blue"
            >
              {trafficTypes.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          
          {/* Number of Requests */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">Requests</label>
            <input
              type="number"
              min="10"
              max="200"
              value={numRequests}
              onChange={(e) => {
                const val = e.target.value;
                if (val === '') {
                  setNumRequests(50);
                } else {
                  const parsed = parseInt(val, 10);
                  if (!isNaN(parsed)) {
                    setNumRequests(Math.min(200, Math.max(10, parsed)));
                  }
                }
              }}
              className="w-full bg-dark-bg border border-dark-border rounded px-3 py-2 text-white focus:outline-none focus:border-accent-blue"
            />
          </div>
          
          {/* Seed Data Toggle */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">Options</label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={seedData}
                onChange={(e) => setSeedData(e.target.checked)}
                className="w-4 h-4 accent-accent-blue"
              />
              <span className="text-sm">Seed Training Data</span>
            </label>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-600 rounded-lg p-4 mb-4">
          <p className="text-red-400">Error: {error}</p>
        </div>
      )}

      {/* Test Summary */}
      {testSummary && (
        <div className="bg-dark-card rounded-lg p-4 mb-6 border border-dark-border">
          <h2 className="text-xl font-semibold mb-4">Test Summary</h2>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className={`p-3 rounded-lg ${testSummary.overallSuccess ? 'bg-green-900/30' : 'bg-red-900/30'}`}>
              <p className="text-sm text-gray-400">Overall</p>
              <p className={`text-2xl font-bold ${testSummary.overallSuccess ? 'text-green-400' : 'text-red-400'}`}>
                {testSummary.overallSuccess ? 'PASS' : 'FAIL'}
              </p>
            </div>
            <div className="p-3 rounded-lg bg-dark-bg">
              <p className="text-sm text-gray-400">Data Seeding</p>
              <p className={`text-2xl font-bold ${testSummary.dataSeeding === '✓' ? 'text-green-400' : 'text-red-400'}`}>
                {testSummary.dataSeeding}
              </p>
            </div>
            <div className="p-3 rounded-lg bg-dark-bg">
              <p className="text-sm text-gray-400">ML Predictions</p>
              <p className={`text-2xl font-bold ${testSummary.mlPredictions === '✓' ? 'text-green-400' : 'text-red-400'}`}>
                {testSummary.mlPredictions}
              </p>
            </div>
            <div className="p-3 rounded-lg bg-dark-bg">
              <p className="text-sm text-gray-400">Cache Test</p>
              <p className={`text-2xl font-bold ${testSummary.cacheTest === '✓' ? 'text-green-400' : 'text-red-400'}`}>
                {testSummary.cacheTest}
              </p>
            </div>
            <div className="p-3 rounded-lg bg-dark-bg">
              <p className="text-sm text-gray-400">Prefetch Test</p>
              <p className={`text-2xl font-bold ${testSummary.prefetchTest === '✓' ? 'text-green-400' : 'text-red-400'}`}>
                {testSummary.prefetchTest}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {/* Cache Performance */}
        <div className="bg-dark-card p-4 rounded-lg border border-dark-border">
          <h2 className="text-xl font-semibold mb-2">Cache Performance</h2>
          {cacheData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={cacheData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="value"
                  label={({ name, value }) => `${name}: ${value}`}
                >
                  {cacheData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ backgroundColor: '#222', border: '1px solid #444' }} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-64 flex items-center justify-center text-gray-500">
              Run test to see cache results
            </div>
          )}
          {liveTestResult?.steps?.find(s => s.step === 'cache_test') && (
            <div className="mt-4 text-sm">
              <p>Hit Rate: <span className="text-green-400 font-semibold">
                {liveTestResult.steps.find(s => s.step === 'cache_test').hit_rate}%
              </span></p>
              <p>Redis Available: <span className={liveTestResult.steps.find(s => s.step === 'cache_test').redis_available ? 'text-green-400' : 'text-gray-400'}>
                {liveTestResult.steps.find(s => s.step === 'cache_test').redis_available ? 'Yes' : 'No'}
              </span></p>
            </div>
          )}
        </div>

        {/* Latency Performance */}
        <div className="bg-dark-card p-4 rounded-lg border border-dark-border">
          <h2 className="text-xl font-semibold mb-2">Latency Performance</h2>
          {latencyData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={latencyData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#444" />
                <XAxis dataKey="name" stroke="#888" />
                <YAxis stroke="#888" />
                <Tooltip contentStyle={{ backgroundColor: '#222', border: '1px solid #444' }} />
                <Bar dataKey="latency" fill="#0088FE" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-64 flex items-center justify-center text-gray-500">
              Run test to see latency results
            </div>
          )}
          {liveTestResult?.steps?.find(s => s.step === 'latency_test') && (
            <div className="mt-4 text-sm grid grid-cols-2 gap-2">
              <p>Average: <span className="text-blue-400">{liveTestResult.steps.find(s => s.step === 'latency_test').avg_latency_ms}ms</span></p>
              <p>P50: <span className="text-green-400">{liveTestResult.steps.find(s => s.step === 'latency_test').p50_ms}ms</span></p>
              <p>P99: <span className="text-yellow-400">{liveTestResult.steps.find(s => s.step === 'latency_test').p99_ms}ms</span></p>
              <p>Min: <span className="text-gray-400">{liveTestResult.steps.find(s => s.step === 'latency_test').min_ms}ms</span></p>
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {/* Prefetch Worker Activity */}
        <div className="bg-dark-card p-4 rounded-lg border border-dark-border">
          <h2 className="text-xl font-semibold mb-2">Prefetch Worker Activity</h2>
          {prefetchData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={prefetchData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#444" />
                <XAxis dataKey="name" stroke="#888" />
                <YAxis stroke="#888" />
                <Tooltip contentStyle={{ backgroundColor: '#222', border: '1px solid #444' }} />
                <Bar dataKey="jobs" fill="#8884d8" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-64 flex items-center justify-center text-gray-500">
              Run test to see prefetch results
            </div>
          )}
          {liveTestResult?.steps?.find(s => s.step === 'prefetch_test') && (
            <div className="mt-4 text-sm">
              <p>Queue Before: <span className="text-gray-400">{liveTestResult.steps.find(s => s.step === 'prefetch_test').queue_before}</span></p>
              <p>Queue After: <span className="text-gray-400">{liveTestResult.steps.find(s => s.step === 'prefetch_test').queue_after}</span></p>
              <p>Jobs Enqueued: <span className="text-purple-400">{liveTestResult.steps.find(s => s.step === 'prefetch_test').jobs_enqueued}</span></p>
            </div>
          )}
        </div>

        {/* ML Predictions */}
        <div className="bg-dark-card p-4 rounded-lg border border-dark-border">
          <h2 className="text-xl font-semibold mb-2">ML Predictions</h2>
          {mlPredictions.length > 0 ? (
            <div className="overflow-y-auto max-h-64">
              <table className="w-full text-sm">
                <thead className="text-xs text-gray-300 uppercase bg-dark-bg sticky top-0">
                  <tr>
                    <th className="py-2 px-3 text-left">Key ID</th>
                    <th className="py-2 px-3 text-right">Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {mlPredictions.map((pred) => (
                    <tr key={pred.key} className="border-b border-dark-border">
                      <td className="py-2 px-3 font-mono text-blue-300">{pred.keyId}</td>
                      <td className="py-2 px-3 text-right">
                        <span className={`font-semibold ${
                          pred.confidence > 70 ? 'text-green-400' :
                          pred.confidence > 40 ? 'text-yellow-400' : 'text-red-400'
                        }`}>
                          {pred.confidence}%
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-gray-500">
              Run test to see ML predictions
            </div>
          )}
          {liveTestResult?.steps?.find(s => s.step === 'ml_predictions') && (
            <div className="mt-4 text-sm">
              <p>Predictions Count: <span className="text-blue-400">{liveTestResult.steps.find(s => s.step === 'ml_predictions').predictions_count}</span></p>
            </div>
          )}
        </div>
      </div>

      {/* Test Details */}
      {liveTestResult && (
        <div className="bg-dark-card p-4 rounded-lg border border-dark-border">
          <h2 className="text-xl font-semibold mb-2">Test Details</h2>
          <div className="text-sm text-gray-400">
            <p>Test ID: <span className="text-gray-300 font-mono">{liveTestResult.test_id}</span></p>
            <p>Started: <span className="text-gray-300">{new Date(liveTestResult.started_at).toLocaleString()}</span></p>
            <p>Completed: <span className="text-gray-300">{new Date(liveTestResult.completed_at).toLocaleString()}</span></p>
            <p>Requests: <span className="text-gray-300">{liveTestResult.num_requests}</span></p>
            <p>Scenario: <span className="text-blue-400">{liveTestResult.scenario || 'test'}</span></p>
            <p>Traffic Type: <span className="text-purple-400">{liveTestResult.traffic_type || 'normal'}</span></p>
          </div>
          
          <h3 className="font-semibold mt-4 mb-2">Step Results:</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {liveTestResult.steps?.map((step, idx) => (
              <div key={idx} className={`p-2 rounded border ${
                step.success ? 'border-green-600 bg-green-900/20' : 'border-red-600 bg-red-900/20'
              }`}>
                <p className="font-semibold">{step.step}</p>
                <p className={step.success ? 'text-green-400' : 'text-red-400'}>
                  {step.success ? 'Success' : 'Failed'}
                </p>
                {step.error && (
                  <p className="text-red-400 text-xs mt-1">{step.error}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default Simulation;
