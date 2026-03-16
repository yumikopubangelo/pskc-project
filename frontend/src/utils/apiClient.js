// API Client for PSKC Backend Integration

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

class ApiClient {
  constructor(baseURL = API_BASE_URL) {
    this.baseURL = baseURL;
    this.defaultHeaders = {
      'Content-Type': 'application/json',
    };
  }

  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const config = {
      ...options,
      headers: {
        ...this.defaultHeaders,
        ...options.headers,
      },
    };

    try {
      const response = await fetch(url, config);
      
      if (!response.ok) {
        const errorBody = await response.text();
        console.error(`HTTP error! status: ${response.status}`, errorBody);
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      // Handle cases with no content
      if (response.status === 204) {
        return null;
      }

      return await response.json();
    } catch (error) {
      console.error('API Error:', error);
      throw error;
    }
  }

  // Health check
  async getHealth() {
    return this.request('/health');
  }

  // Metrics
  async getMetrics() {
    return this.request('/metrics');
  }

  // Cache operations
  async getCacheStats() {
    return this.request('/cache/stats');
  }

  async getCacheKeys() {
    return this.request('/cache/keys');
  }

  async invalidateKey(key) {
    return this.request(`/cache/invalidate/${key}`, {
      method: 'POST',
    });
  }

  // ML Operations
  async getPredictions() {
    return this.request('/ml/predictions');
  }

  async getModelStatus() {
    return this.request('/ml/status');
  }

  async triggerRetraining() {
    return this.request('/ml/retrain', {
      method: 'POST',
    });
  }

  // Simulation
  async getSimulationScenarios() {
    return this.request('/simulation/scenarios');
  }

  async runSimulation(params) {
    return this.request('/simulation/run', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  }

  async getSimulationResults(id) {
    return this.request(`/simulation/results/${id}`);
  }

  // Live System Test - Tests real ML, cache, and prefetch
  async runLiveTest(numRequests = 50, seedData = true, scenario = 'test', trafficType = 'normal') {
    return this.request(`/simulation/live-test?num_requests=${numRequests}&seed_data=${seedData}&scenario=${scenario}&traffic_type=${trafficType}`, {
      method: 'POST',
    });
  }

  async getLiveTestStatus() {
    return this.request('/simulation/live-test');
  }

  // Security
  async getSecurityAudit() {
    return this.request('/security/audit');
  }

  async getIntrusionLogs() {
    return this.request('/security/intrusions');
  }

  // Chart Data
  async getLatencyChartData() {
    return this.request('/metrics/latency');
  }

  async getCacheDistributionData() {
    return this.request('/metrics/cache-distribution');
  }

  async getAccuracyChartData() {
    return this.request('/metrics/accuracy');
  }

  // Keys
  async getKey(keyId) {
    return this.request(`/keys/${keyId}`);
  }

  async rotateKey(keyId) {
    return this.request(`/keys/${keyId}/rotate`, {
      method: 'POST',
    });
  }

  // ML Pipeline Builder
  async runPipeline(pipeline) {
    return this.request('/ml/pipeline/run', {
      method: 'POST',
      body: JSON.stringify(pipeline),
    });
  }

  async getPipelineStatus(pipelineId) {
    return this.request(`/ml/pipeline/status/${pipelineId}`);
  }

  async getPipelineMetrics(pipelineId) {
    return this.request(`/ml/pipeline/metrics/${pipelineId}`);
  }

  // ============================================================
  // Admin Endpoints
  // ============================================================

  // Admin Auth
  async getAdminAuthStatus() {
    return this.request('/admin/auth/status');
  }

  async getAdminAuditLog(params = {}) {
    const query = new URLSearchParams(params).toString();
    return this.request(`/admin/auth/audit?${query}`);
  }

  // Cache Admin
  async getAdminCacheSummary() {
    return this.request('/admin/cache/summary');
  }

  async invalidateCacheByPrefix(prefix, serviceId = null) {
    const params = new URLSearchParams({ prefix });
    if (serviceId) params.append('service_id', serviceId);
    return this.request(`/admin/cache/invalidate?${params}`, {
      method: 'POST',
    });
  }

  async inspectCacheKeyTtl(keyId, serviceId = 'default') {
    return this.request(`/admin/cache/ttl/${keyId}?service_id=${serviceId}`);
  }

  async getCacheWarmupStatus() {
    return this.request('/admin/cache/warmup');
  }

  async triggerCacheWarmup(serviceId = null) {
    const params = serviceId ? `?service_id=${serviceId}` : '';
    return this.request(`/admin/cache/warmup${params}`, {
      method: 'POST',
    });
  }

  // Model Admin
  async getModelVersionsByStage() {
    return this.request('/admin/model/versions');
  }

  async getModelVersionHistory(modelName) {
    return this.request(`/admin/model/history/${modelName}`);
  }

  async compareModelVersions(modelName, version1, version2) {
    return this.request(`/admin/model/compare?model_name=${modelName}&version1=${version1}&version2=${version2}`);
  }

  async exportModelLifecycle(modelName) {
    return this.request(`/admin/model/export/${modelName}`);
  }

  // Security Admin
  async getSecuritySummary() {
    return this.request('/admin/security/summary');
  }

  async getBlockedIps() {
    return this.request('/admin/security/blocked-ips');
  }

  async getIpReputation() {
    return this.request('/admin/security/reputation');
  }

  async unblockIp(ipAddress) {
    return this.request(`/admin/security/unblock?ip_address=${ipAddress}`, {
      method: 'POST',
    });
  }

  async getAuditRecoveryHistory() {
    return this.request('/admin/security/audit-recovery');
  }

  // Prefetch Admin
  async getPrefetchDlq(limit = 20) {
    return this.request(`/prefetch/dlq?limit=${limit}`);
  }

  async replayPrefetchDlq(jobId = null, limit = 10) {
    const params = new URLSearchParams({ limit: limit.toString() });
    if (jobId) params.append('job_id', jobId);
    return this.request(`/prefetch/dlq/replay?${params}`, {
      method: 'POST',
    });
  }

  async getPrefetchRateLimitStats() {
    return this.request('/prefetch/rate-limit');
  }

  async getReplayHistory(limit = 20) {
    return this.request(`/prefetch/replay-history?limit=${limit}`);
  }

  // ML Drift Status
  async getDriftAnalysis() {
    return this.request('/ml/drift');
  }

  // Key Lifecycle
  async getKeyLifecycle(keyId) {
    return this.request(`/keys/lifecycle/${keyId}`);
  }

  async getKeyLifecycleList(status = null, keyType = null) {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (keyType) params.append('key_type', keyType);
    return this.request(`/keys/lifecycle?${params}`);
  }

  async getKeyLifecycleEvents(keyId, limit = 100) {
    return this.request(`/keys/lifecycle/${keyId}/events?limit=${limit}`);
  }

  async getKeyLifecycleStats() {
    return this.request('/keys/lifecycle/stats');
  }
}

export const apiClient = new ApiClient();
export default apiClient;
