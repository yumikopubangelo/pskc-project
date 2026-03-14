import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '../utils/apiClient';

export function useMetrics(pollInterval = 5000) {
  const [metrics, setMetrics] = useState({
    cacheHitRate: 0,
    avgLatency: 0,
    mlAccuracy: 0,
    mispredictionRate: 0,
    totalRequests: 0,
    activeNodes: 0,
    keysCached: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchMetrics = useCallback(async () => {
    try {
      const data = await apiClient.getMetrics();
      setMetrics(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, pollInterval);
    return () => clearInterval(interval);
  }, [fetchMetrics, pollInterval]);

  return { metrics, loading, error, refetch: fetchMetrics };
}

export function useCacheStats(pollInterval = 5000) {
  const [stats, setStats] = useState({
    hits: 0,
    misses: 0,
    size: 0,
    maxSize: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchStats = useCallback(async () => {
    try {
      const data = await apiClient.getCacheStats();
      setStats(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStats, pollInterval]);

  return { stats, loading, error, refetch: fetchStats };
}

export function useModelStatus() {
  const [status, setStatus] = useState({
    accuracy: 0,
    lastTrained: null,
    status: 'loading',
    predictionsPerMin: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await apiClient.getModelStatus();
      setStatus(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  return { status, loading, error, refetch: fetchStatus };
}

export default useMetrics;
