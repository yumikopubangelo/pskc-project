# PSKC Dashboard Visualization Updates
# ============================================================
"""
Panduan untuk update dashboard dengan metrics baru dari enhancement.
File ini berisi specific implementation untuk setiap chart.
"""

# ============================================================
# 1. Per-Key Accuracy Breakdown Chart
# ============================================================

ACCURACY_BREAKDOWN_CHART = """
HTML/JavaScript Implementation untuk Per-Key Accuracy:

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<div id="per-key-accuracy-container" style="width: 100%; height: 400px;">
    <canvas id="perKeyAccuracyChart"></canvas>
</div>

<script>
async function updatePerKeyAccuracyChart() {
    try {
        // Fetch data dari new endpoint
        const response = await fetch('/api/metrics/enhanced/per-key?model_name=cache_predictor');
        const data = await response.json();
        
        const keys = data.metrics.map(m => m.key);
        const accuracies = data.metrics.map(m => m.accuracy * 100);
        const confidences = data.metrics.map(m => m.avg_confidence * 100);
        
        // Create chart
        const ctx = document.getElementById('perKeyAccuracyChart').getContext('2d');
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: keys,
                datasets: [
                    {
                        label: 'Accuracy (%)',
                        data: accuracies,
                        backgroundColor: 'rgba(75, 192, 192, 0.8)',
                        borderColor: 'rgba(75, 192, 192, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'Avg Confidence (%)',
                        data: confidences,
                        backgroundColor: 'rgba(201, 203, 207, 0.8)',
                        borderColor: 'rgba(201, 203, 207, 1)',
                        borderWidth: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Per-Key Prediction Accuracy'
                    },
                    legend: {
                        display: true,
                        position: 'top'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        ticks: {
                            callback: function(value) {
                                return value + '%';
                            }
                        }
                    }
                }
            }
        });
        
        console.log('✅ Per-Key Accuracy Chart Updated');
    } catch (error) {
        console.error('Error updating accuracy chart:', error);
    }
}

// Update setiap 30 detik
setInterval(updatePerKeyAccuracyChart, 30000);
updatePerKeyAccuracyChart(); // Initial load
</script>
"""


# ============================================================
# 2. Per-Key Drift Score Tracking Chart
# ============================================================

DRIFT_TRACKING_CHART = """
HTML/JavaScript untuk Per-Key Drift Score:

<div id="per-key-drift-container" style="width: 100%; height: 400px;">
    <canvas id="perKeyDriftChart"></canvas>
</div>

<script>
async function updatePerKeyDriftChart() {
    try {
        // Fetch drift data
        const response = await fetch('/api/metrics/enhanced/drift?model_name=cache_predictor&time_range=24h');
        const data = response.json();
        
        const keys = data.drift_metrics.map(m => m.key);
        const driftScores = data.drift_metrics.map(m => m.drift_score);
        const driftLevels = data.drift_metrics.map(m => m.drift_level);
        
        // Color code by drift level
        const colors = driftLevels.map(level => {
            switch(level) {
                case 'critical': return 'rgba(255, 0, 0, 0.8)';      // Red
                case 'warning': return 'rgba(255, 165, 0, 0.8)';    // Orange
                case 'normal': return 'rgba(0, 128, 0, 0.8)';       // Green
                default: return 'rgba(128, 128, 128, 0.8)';         // Gray
            }
        });
        
        const ctx = document.getElementById('perKeyDriftChart').getContext('2d');
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: keys,
                datasets: [{
                    label: 'Drift Score (0-1)',
                    data: driftScores,
                    backgroundColor: colors,
                    borderColor: colors.map(c => c.replace('0.8', '1')),
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Model Drift Score per Key (24h)'
                    },
                    legend: { display: false }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 1,
                        ticks: {
                            callback: function(value) {
                                return value.toFixed(2);
                            }
                        }
                    }
                }
            }
        });
        
        // Show alerts for critical drift
        const criticalDrifts = data.drift_metrics.filter(m => m.drift_level === 'critical');
        if (criticalDrifts.length > 0) {
            console.warn('⚠️ CRITICAL DRIFT DETECTED:', criticalDrifts.map(m => m.key));
        }
    } catch (error) {
        console.error('Error updating drift chart:', error);
    }
}

setInterval(updatePerKeyDriftChart, 60000); // Update every minute
updatePerKeyDriftChart();
</script>
"""


# ============================================================
# 3. Model Version Comparison Panel
# ============================================================

MODEL_VERSION_COMPARISON = """
HTML/JavaScript untuk Model Version Comparison:

<div id="model-comparison-container">
    <div style="margin-bottom: 20px;">
        <label for="version-select">Compare Versions:</label>
        <select id="version-select">
            <option value="">Select comparison type...</option>
            <option value="latest_vs_current">Latest vs Current</option>
            <option value="custom">Custom Versions</option>
        </select>
    </div>
    
    <div id="comparison-table-container">
        <table id="versionComparisonTable" style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr style="background-color: #f0f0f0;">
                    <th style="border: 1px solid #ddd; padding: 8px;">Metric</th>
                    <th style="border: 1px solid #ddd; padding: 8px;">Current Version</th>
                    <th style="border: 1px solid #ddd; padding: 8px;">Latest Version</th>
                    <th style="border: 1px solid #ddd; padding: 8px;">Change (%)</th>
                </tr>
            </thead>
            <tbody id="comparisonTableBody">
            </tbody>
        </table>
    </div>
</div>

<script>
async function updateModelComparison() {
    try {
        // Fetch current version
        const currentRes = await fetch('/api/models/current?model_name=cache_predictor');
        const current = await currentRes.json();
        
        // Fetch latest version
        const latestRes = await fetch('/api/models/versions?model_name=cache_predictor&limit=1');
        const latest = await latestRes.json();
        
        const metrics = [
            { name: 'Overall Accuracy', key: 'overall_accuracy' },
            { name: 'Avg Drift Score', key: 'avg_drift_score' },
            { name: 'Avg Latency (ms)', key: 'avg_latency_ms' },
            { name: 'Cache Hit Rate', key: 'cache_hit_rate' },
            { name: 'Prediction Confidence', key: 'avg_confidence' }
        ];
        
        const tbody = document.getElementById('comparisonTableBody');
        tbody.innerHTML = '';
        
        for (const metric of metrics) {
            const currentValue = current.metrics?.[metric.key] ?? 'N/A';
            const latestValue = latest.versions[0].metrics?.[metric.key] ?? 'N/A';
            
            let changePercent = 'N/A';
            let changeStyle = '';
            
            if (typeof currentValue === 'number' && typeof latestValue === 'number') {
                const change = ((latestValue - currentValue) / currentValue) * 100;
                changePercent = change.toFixed(2);
                changeStyle = change > 0 ? 'color: green; font-weight: bold;' : 'color: red; font-weight: bold;';
            }
            
            const row = document.createElement('tr');
            row.innerHTML = `
                <td style="border: 1px solid #ddd; padding: 8px;">${metric.name}</td>
                <td style="border: 1px solid #ddd; padding: 8px;">${typeof currentValue === 'number' ? currentValue.toFixed(4) : currentValue}</td>
                <td style="border: 1px solid #ddd; padding: 8px;">${typeof latestValue === 'number' ? latestValue.toFixed(4) : latestValue}</td>
                <td style="border: 1px solid #ddd; padding: 8px; ${changeStyle}">${changePercent}%</td>
            `;
            tbody.appendChild(row);
        }
        
        console.log('✅ Model Comparison Updated');
    } catch (error) {
        console.error('Error updating model comparison:', error);
    }
}

document.getElementById('version-select').addEventListener('change', updateModelComparison);
updateModelComparison(); // Initial load
</script>
"""


# ============================================================
# 4. Latency Breakdown Pie Chart
# ============================================================

LATENCY_BREAKDOWN_CHART = """
HTML/JavaScript untuk Latency Breakdown:

<div id="latency-breakdown-container" style="width: 100%; max-width: 500px; height: 400px;">
    <canvas id="latencyBreakdownChart"></canvas>
</div>

<script>
async function updateLatencyBreakdownChart() {
    try {
        // Fetch latency breakdown from metrics
        const response = await fetch('/api/metrics/enhanced/latency-breakdown?model_name=cache_predictor');
        const data = await response.json();
        
        const ctx = document.getElementById('latencyBreakdownChart').getContext('2d');
        new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: [
                    'Redis Lookup',
                    'Model Inference',
                    'Data Validation',
                    'Network',
                    'Other'
                ],
                datasets: [{
                    data: [
                        data.latency_breakdown.redis_ms,
                        data.latency_breakdown.inference_ms,
                        data.latency_breakdown.validation_ms,
                        data.latency_breakdown.network_ms,
                        data.latency_breakdown.other_ms
                    ],
                    backgroundColor: [
                        'rgba(255, 99, 132, 0.8)',
                        'rgba(54, 162, 235, 0.8)',
                        'rgba(255, 206, 86, 0.8)',
                        'rgba(75, 192, 192, 0.8)',
                        'rgba(153, 102, 255, 0.8)'
                    ],
                    borderColor: [
                        'rgba(255, 99, 132, 1)',
                        'rgba(54, 162, 235, 1)',
                        'rgba(255, 206, 86, 1)',
                        'rgba(75, 192, 192, 1)',
                        'rgba(153, 102, 255, 1)'
                    ],
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Latency Breakdown (ms)'
                    },
                    legend: {
                        display: true,
                        position: 'right'
                    }
                }
            }
        });
    } catch (error) {
        console.error('Error updating latency chart:', error);
    }
}

setInterval(updateLatencyBreakdownChart, 30000);
updateLatencyBreakdownChart();
</script>
"""


# ============================================================
# 5. Benchmark / Speedup Factor Visualization
# ============================================================

BENCHMARK_SPEEDUP_CHART = """
HTML/JavaScript untuk Benchmark & Speedup:

<div id="benchmark-container" style="margin: 20px 0;">
    <h3>Speedup Factor (PSKC vs Baseline)</h3>
    <div id="speedup-metrics" style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px;">
        <div id="speedup-card" style="padding: 15px; background: #e8f5e9; border-radius: 8px;">
            <div style="font-size: 24px; font-weight: bold; color: #2e7d32;">2.3x</div>
            <div style="color: #558b2f;">Average Speedup</div>
        </div>
        <div id="hitrate-card" style="padding: 15px; background: #e3f2fd; border-radius: 8px;">
            <div style="font-size: 24px; font-weight: bold; color: #1565c0;">87.4%</div>
            <div style="color: #0d47a1;">Cache Hit Rate</div>
        </div>
        <div id="accuracy-card" style="padding: 15px; background: #fff3e0; border-radius: 8px;">
            <div style="font-size: 24px; font-weight: bold; color: #e65100;">92.6%</div>
            <div style="color: #bf360c;">Overall Accuracy</div>
        </div>
    </div>
    
    <div id="speedup-trend-container" style="width: 100%; height: 300px; margin-top: 20px;">
        <canvas id="speedupTrendChart"></canvas>
    </div>
</div>

<script>
async function updateBenchmarkMetrics() {
    try {
        // Fetch benchmark data
        const response = await fetch('/api/metrics/enhanced/benchmark?model_name=cache_predictor&time_range=7d');
        const data = await response.json();
        
        // Update card values
        document.querySelector('#speedup-card div:first-child').textContent = 
            data.speedup_factor.toFixed(1) + 'x';
        document.querySelector('#hitrate-card div:first-child').textContent = 
            (data.cache_hit_rate * 100).toFixed(1) + '%';
        document.querySelector('#accuracy-card div:first-child').textContent = 
            (data.overall_accuracy * 100).toFixed(1) + '%';
        
        // Create speedup trend chart
        const ctx = document.getElementById('speedupTrendChart').getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.speedup_trend.timestamps,
                datasets: [{
                    label: 'Speedup Factor',
                    data: data.speedup_trend.values,
                    borderColor: 'rgba(75, 192, 192, 1)',
                    backgroundColor: 'rgba(75, 192, 192, 0.1)',
                    tension: 0.1,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Speedup Factor Trend (7 days)'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Speedup Factor (x)'
                        }
                    }
                }
            }
        });
        
        console.log('✅ Benchmark Metrics Updated');
    } catch (error) {
        console.error('Error updating benchmark:', error);
    }
}

setInterval(updateBenchmarkMetrics, 60000);
updateBenchmarkMetrics();
</script>
"""


# ============================================================
# 6. Prediction Confidence Display
# ============================================================

CONFIDENCE_METRIC_DISPLAY = """
HTML/JavaScript untuk Prediction Confidence:

<div id="confidence-container" style="padding: 20px;">
    <h3>Prediction Confidence Distribution</h3>
    
    <div id="confidence-stats" style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; margin-bottom: 20px;">
        <div style="padding: 10px; background: #f5f5f5; border-radius: 5px;">
            <strong>Average Confidence:</strong>
            <span id="avg-confidence" style="float: right; font-weight: bold;">92.5%</span>
        </div>
        <div style="padding: 10px; background: #f5f5f5; border-radius: 5px;">
            <strong>Min Confidence:</strong>
            <span id="min-confidence" style="float: right; font-weight: bold;">65.3%</span>
        </div>
        <div style="padding: 10px; background: #f5f5f5; border-radius: 5px;">
            <strong>Max Confidence:</strong>
            <span id="max-confidence" style="float: right; font-weight: bold;">99.8%</span>
        </div>
        <div style="padding: 10px; background: #f5f5f5; border-radius: 5px;">
            <strong>High Confidence (>90%):</strong>
            <span id="high-confidence-pct" style="float: right; font-weight: bold;">78.4%</span>
        </div>
    </div>
    
    <div id="confidence-histogram" style="width: 100%; height: 300px;">
        <canvas id="confidenceHistogram"></canvas>
    </div>
</div>

<script>
async function updateConfidenceMetrics() {
    try {
        // Fetch confidence data
        const response = await fetch('/api/metrics/enhanced/confidence-distribution?model_name=cache_predictor');
        const data = await response.json();
        
        // Update stats
        document.getElementById('avg-confidence').textContent = 
            (data.avg_confidence * 100).toFixed(1) + '%';
        document.getElementById('min-confidence').textContent = 
            (data.min_confidence * 100).toFixed(1) + '%';
        document.getElementById('max-confidence').textContent = 
            (data.max_confidence * 100).toFixed(1) + '%';
        document.getElementById('high-confidence-pct').textContent = 
            (data.high_confidence_percentage).toFixed(1) + '%';
        
        // Create histogram
        const ctx = document.getElementById('confidenceHistogram').getContext('2d');
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: ['0-10%', '10-20%', '20-30%', '30-40%', '40-50%', 
                         '50-60%', '60-70%', '70-80%', '80-90%', '90-100%'],
                datasets: [{
                    label: 'Number of Predictions',
                    data: data.confidence_histogram,
                    backgroundColor: 'rgba(75, 192, 192, 0.8)',
                    borderColor: 'rgba(75, 192, 192, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Confidence Score Distribution'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Count'
                        }
                    }
                }
            }
        });
    } catch (error) {
        console.error('Error updating confidence metrics:', error);
    }
}

setInterval(updateConfidenceMetrics, 30000);
updateConfidenceMetrics();
</script>
"""


# ============================================================
# 7. Accuracy Trend Time-Series
# ============================================================

ACCURACY_TREND_CHART = """
HTML/JavaScript untuk Accuracy Trend:

<div id="accuracy-trend-container" style="width: 100%; height: 400px;">
    <canvas id="accuracyTrendChart"></canvas>
</div>

<script>
async function updateAccuracyTrendChart() {
    try {
        // Fetch accuracy trend data
        const response = await fetch('/api/metrics/enhanced/accuracy-trend?model_name=cache_predictor&time_range=7d');
        const data = await response.json();
        
        const ctx = document.getElementById('accuracyTrendChart').getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.timestamps,
                datasets: [
                    {
                        label: 'Overall Accuracy',
                        data: data.overall_accuracy,
                        borderColor: 'rgba(75, 192, 192, 1)',
                        backgroundColor: 'rgba(75, 192, 192, 0.1)',
                        tension: 0.3,
                        fill: true
                    },
                    {
                        label: 'Short-term EWMA',
                        data: data.ewma_short,
                        borderColor: 'rgba(255, 99, 132, 1)',
                        backgroundColor: 'rgba(255, 99, 132, 0.1)',
                        tension: 0.3,
                        fill: false
                    },
                    {
                        label: 'Long-term EWMA',
                        data: data.ewma_long,
                        borderColor: 'rgba(54, 162, 235, 1)',
                        backgroundColor: 'rgba(54, 162, 235, 0.1)',
                        tension: 0.3,
                        fill: false
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Accuracy Trend (7 days)'
                    },
                    legend: {
                        display: true,
                        position: 'top'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 1,
                        ticks: {
                            callback: function(value) {
                                return (value * 100).toFixed(0) + '%';
                            }
                        }
                    }
                }
            }
        });
        
        console.log('✅ Accuracy Trend Chart Updated');
    } catch (error) {
        console.error('Error updating accuracy trend:', error);
    }
}

setInterval(updateAccuracyTrendChart, 60000);
updateAccuracyTrendChart();
</script>
"""


# ============================================================
# 8. Drift Summary Gauge
# ============================================================

DRIFT_SUMMARY_GAUGE = """
HTML/JavaScript untuk Drift Summary Gauge:

<div id="drift-gauge-container" style="text-align: center; padding: 20px;">
    <h3>Overall Model Drift Status</h3>
    
    <div id="gauge-wrapper" style="position: relative; width: 300px; height: 150px; margin: auto;">
        <canvas id="driftGaugeChart" style="width: 100%; height: 100%;"></canvas>
    </div>
    
    <div id="drift-details" style="margin-top: 20px; padding: 15px; background: #f9f9f9; border-radius: 8px;">
        <div id="drift-status" style="font-size: 18px; font-weight: bold; margin-bottom: 10px;"></div>
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px;">
            <div>
                <strong>Critical Keys:</strong>
                <span id="critical-keys-count" style="display: block; font-weight: bold;">0</span>
            </div>
            <div>
                <strong>Warning Keys:</strong>
                <span id="warning-keys-count" style="display: block; font-weight: bold;">0</span>
            </div>
            <div>
                <strong>Last Detected:</strong>
                <span id="last-drift-time" style="display: block; font-weight: bold;">--</span>
            </div>
            <div>
                <strong>Trend:</strong>
                <span id="drift-trend" style="display: block; font-weight: bold;">--</span>
            </div>
        </div>
    </div>
</div>

<script>
async function updateDriftGauge() {
    try {
        // Fetch drift summary
        const response = await fetch('/api/metrics/enhanced/drift-summary?model_name=cache_predictor');
        const data = await response.json();
        
        // Create gauge chart
        const ctx = document.getElementById('driftGaugeChart').getContext('2d');
        new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['Drift Score', 'Remaining Capacity'],
                datasets: [{
                    data: [data.overall_drift_score * 100, (1 - data.overall_drift_score) * 100],
                    backgroundColor: [
                        data.overall_drift_score > 0.5 ? 'rgba(255, 0, 0, 0.7)' : 
                        data.overall_drift_score > 0.3 ? 'rgba(255, 165, 0, 0.7)' : 
                        'rgba(0, 128, 0, 0.7)',
                        'rgba(200, 200, 200, 0.3)'
                    ],
                    borderColor: ['transparent', 'transparent'],
                    circumference: 180,
                    rotation: 270
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                }
            }
        });
        
        // Update status
        const statusElement = document.getElementById('drift-status');
        if (data.overall_drift_score > 0.5) {
            statusElement.innerHTML = '🔴 CRITICAL - Retraining Recommended';
            statusElement.style.color = '#d32f2f';
        } else if (data.overall_drift_score > 0.3) {
            statusElement.innerHTML = '🟠 WARNING - Monitor Closely';
            statusElement.style.color = '#f57c00';
        } else {
            statusElement.innerHTML = '🟢 NORMAL - All Systems OK';
            statusElement.style.color = '#388e3c';
        }
        
        // Update details
        document.getElementById('critical-keys-count').textContent = data.critical_keys_count;
        document.getElementById('warning-keys-count').textContent = data.warning_keys_count;
        document.getElementById('last-drift-time').textContent = data.last_detected_time || '--';
        document.getElementById('drift-trend').textContent = data.drift_trend || '--';
        
    } catch (error) {
        console.error('Error updating drift gauge:', error);
    }
}

setInterval(updateDriftGauge, 60000);
updateDriftGauge();
</script>
"""


# ============================================================
# Implementation Guide
# ============================================================

DASHBOARD_IMPLEMENTATION_GUIDE = """
## Dashboard Visualization Integration Guide

### Overview
Semua 8 chart dan visualisasi di atas perlu diintegrasikan ke frontend dashboard.
Mereka menggunakan Chart.js untuk rendering dan fetch dari new API endpoints.

### API Endpoints Required

Pastikan endpoints berikut tersedia:
1. `/api/metrics/enhanced/per-key` - Per-key accuracy metrics
2. `/api/metrics/enhanced/drift` - Per-key drift scores
3. `/api/models/current` - Current model version
4. `/api/models/versions` - List all versions
5. `/api/metrics/enhanced/latency-breakdown` - Latency breakdown
6. `/api/metrics/enhanced/benchmark` - Benchmark metrics
7. `/api/metrics/enhanced/confidence-distribution` - Confidence stats
8. `/api/metrics/enhanced/accuracy-trend` - Accuracy trend
9. `/api/metrics/enhanced/drift-summary` - Drift summary

### Integration Steps

1. **Add Chart.js Library**
   ```html
   <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
   ```

2. **Create Dashboard Page Structure**
   ```html
   <div id="dashboard-container">
       <!-- Add containers from above -->
   </div>
   ```

3. **Include JavaScript Code**
   - Copy-paste code dari each section above
   - Atau modularize menjadi separate .js files

4. **Add CSS Styling** (opsional)
   ```css
   .metric-card {
       padding: 15px;
       background: #f5f5f5;
       border-radius: 8px;
       box-shadow: 0 2px 4px rgba(0,0,0,0.1);
   }
   ```

5. **Setup Auto-refresh**
   - Charts di-update setiap 30-60 detik
   - Atau setup WebSocket untuk real-time updates

### Testing Checklist

- [ ] All endpoints return valid data
- [ ] Charts render without errors
- [ ] Auto-refresh works correctly
- [ ] Responsive on mobile
- [ ] Performance acceptable with many data points
- [ ] Error handling for failed requests
- [ ] Time range filters work if applicable

### Performance Optimization Tips

1. **Limit Data Points**: Use downsampling untuk large datasets
2. **Lazy Load**: Load charts only when visible
3. **Cache**: Store recent API responses locally
4. **Compress**: Use API pagination/limits
5. **Monitor**: Track rendering performance with DevTools

### Customization Options

- Adjust update intervals (currently 30-60s)
- Modify color schemes per brand
- Add filters (time range, key, version)
- Add export/download functionality
- Add tooltips and annotations
"""


if __name__ == "__main__":
    print("Dashboard Visualization Update Guide")
    print("=" * 50)
    print("\n8 Charts to implement:")
    print("1. Per-Key Accuracy Breakdown")
    print("2. Per-Key Drift Score Tracking")
    print("3. Model Version Comparison")
    print("4. Latency Breakdown Pie")
    print("5. Benchmark/Speedup Factor")
    print("6. Prediction Confidence Display")
    print("7. Accuracy Trend Time-Series")
    print("8. Drift Summary Gauge")
    print("\n" + DASHBOARD_IMPLEMENTATION_GUIDE)
