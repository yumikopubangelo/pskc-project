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
}

export const apiClient = new ApiClient();
export default apiClient;
