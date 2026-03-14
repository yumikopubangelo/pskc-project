import React, { useState, useCallback } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar } from 'recharts';

// Mock data - replace with actual API data
const initialCacheData = [
  { name: 'T=0', hits: 0, misses: 0 },
];

const initialPrefetchData = [
  { name: 'T=0', prefetched: 0, used: 0 },
];

const initialMlPredictions = [];

const Simulation = () => {
  const [isSimulating, setIsSimulating] = useState(false);
  const [simulationStatus, setSimulationStatus] = useState('Not Started');
  const [cacheData, setCacheData] = useState(initialCacheData);
  const [prefetchData, setPrefetchData] = useState(initialPrefetchData);
  const [mlPredictions, setMlPredictions] = useState(initialMlPredictions);
  const [time, setTime] = useState(1);

  const handleStartSimulation = useCallback(() => {
    setIsSimulating(true);
    setSimulationStatus('Running');
    // Reset data
    setTime(1);
    setCacheData(initialCacheData);
    setPrefetchData(initialPrefetchData);
    setMlPredictions(initialMlPredictions);

    // Mock simulation progression
    const interval = setInterval(() => {
      setTime(prevTime => {
        const newTime = prevTime + 1;
        if (newTime > 20) {
          clearInterval(interval);
          setIsSimulating(false);
          setSimulationStatus('Finished');
          return prevTime;
        }

        // Mock cache data
        setCacheData(prevData => {
            const lastData = prevData[prevData.length - 1];
            const newHits = lastData.hits + Math.round(Math.random() * 5);
            const newMisses = lastData.misses + Math.round(Math.random() * 2);
            return [...prevData, { name: `T=${newTime}`, hits: newHits, misses: newMisses }];
        });

        // Mock prefetch data
        setPrefetchData(prevData => {
            const lastData = prevData[prevData.length - 1];
            const newPrefetched = lastData.prefetched + Math.round(Math.random() * 10);
            const newUsed = lastData.used + Math.round(Math.random() * 5);
            return [...prevData, { name: `T=${newTime}`, prefetched: newPrefetched, used: newUsed }];
        });

        // Mock ML predictions
        setMlPredictions(prevPredictions => [
          { time: `T=${newTime}`, prediction: `user_${Math.round(Math.random() * 100)}`, probability: Math.random().toFixed(2) },
          ...prevPredictions,
        ].slice(0, 10));

        return newTime;
      });
    }, 1000);
  }, []);

  return (
    <div className="container mx-auto p-4 text-white">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold">Simulation</h1>
        <div className="flex items-center gap-4">
          <span>Status: <span className={`font-semibold ${isSimulating ? 'text-green-400' : 'text-yellow-400'}`}>{simulationStatus}</span></span>
          <button
            onClick={handleStartSimulation}
            disabled={isSimulating}
            className="bg-accent-blue hover:bg-accent-blue/80 text-white font-bold py-2 px-4 rounded disabled:bg-gray-600"
          >
            {isSimulating ? 'Simulating...' : 'Start Simulation'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Cache Visualization */}
        <div className="bg-dark-card p-4 rounded-lg border border-dark-border">
          <h2 className="text-xl font-semibold mb-2">Cache Performance</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={cacheData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#444" />
              <XAxis dataKey="name" stroke="#888" />
              <YAxis stroke="#888" />
              <Tooltip contentStyle={{ backgroundColor: '#222', border: '1px solid #444' }} />
              <Legend />
              <Line type="monotone" dataKey="hits" stroke="#82ca9d" activeDot={{ r: 8 }} />
              <Line type="monotone" dataKey="misses" stroke="#ca8282" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Prefetch Worker Visualization */}
        <div className="bg-dark-card p-4 rounded-lg border border-dark-border">
          <h2 className="text-xl font-semibold mb-2">Prefetch Worker Activity</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={prefetchData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#444" />
              <XAxis dataKey="name" stroke="#888" />
              <YAxis stroke="#888" />
              <Tooltip contentStyle={{ backgroundColor: '#222', border: '1px solid #444' }} />
              <Legend />
              <Bar dataKey="prefetched" fill="#8884d8" />
              <Bar dataKey="used" fill="#82ca9d" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ML Predictions Log */}
      <div className="bg-dark-card p-4 rounded-lg mt-4 border border-dark-border">
        <h2 className="text-xl font-semibold mb-2">ML Predictions</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left text-gray-400">
            <thead className="text-xs text-gray-300 uppercase bg-dark-bg">
              <tr>
                <th scope="col" className="py-3 px-6">Time</th>
                <th scope="col" className="py-3 px-6">Prediction</th>
                <th scope="col" className="py-3 px-6">Probability</th>
              </tr>
            </thead>
            <tbody>
              {mlPredictions.map((p, i) => (
                <tr key={i} className="border-b border-dark-border">
                  <td className="py-4 px-6">{p.time}</td>
                  <td className="py-4 px-6">{p.prediction}</td>
                  <td className="py-4 px-6">{p.probability}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default Simulation;
