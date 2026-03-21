# Prefetch Worker Architecture

Dokumen ini menjelaskan arsitektur, algoritma, dan operational details dari prefetch worker yang mengisi cache secara proaktif.

## Ikhtisar

Prefetch worker adalah komponen yang memprediksi akses kunci mana yang akan datang dan mengisinya ke cache sebelum client memintanya. Ini mengurangi cache miss rate dan latency puncak.

```
┌──────────────────────────────────────────────────────────────┐
│                    REQUEST FLOW OUTLINE                      │
└──────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│ Client requests kunci (e.g., /keys/access)    │
└────────────────────────────────────────────────┘
                    │
        ┌───────────┴────────────┐
        │ Cache (L1+L2)          │
        │ - HIT: return plaintext│
        │ - MISS: fallback to KMS│
        └───────────┬────────────┘
                    │
        ┌───────────▼────────────────┐
        │ Schedule Prefetch Job      │
        │ (Redis queue)              │
        │ - Current key accessed     │
        │ - Current context          │
        │ - Time spent in cache      │
        └───────────┬────────────────┘
                    │
                    ▼
    ┌──────────────────────────────────────┐
    │   PREFETCH WORKER (runs separately)  │
    │                                      │
    │ 1. Dequeue job from Redis            │
    │ 2. Run ML predictor                  │
    │    → Predict next N keys (e.g., 10) │
    │ 3. Fetch predicted keys from KMS     │
    │ 4. Store to L1 + L2 cache            │
    │ 5. Ack job, loop                     │
    └──────────────────────────────────────┘
```

## Komponen Utama

### 1. Prefetch Worker Process

**File**: `src/workers/prefetch_worker.py`

**Tanggung Jawab**:
- Consume job dari Redis queue secara konstan
- Menjalankan ML predictor untuk setiap job
- Fetch kunci yang diprediksi dari upstream KMS
- Store ke cache (L1 + L2)
- Handle errors dan retry logic

**Deployment**:
```bash
# Run sebagai separate process/service
python -m src.workers.prefetch_worker

# Atau dalam Docker:
# See docker-compose.yml, service: prefetch-worker
```

### 2. Prefetch Queue (Redis)

**Storage**: Redis list dengan key `pskc:prefetch:jobs`

**Job Format**:
```json
{
  "job_id": "uuid-xxxxx",
  "service_id": "api-prod",
  "timestamp": 1710956700.12,
  "accessed_key_id": "user_123:key_456",
  "context": {
    "access_type": "read",
    "cache_hit": true,
    "latency_ms": 2.5,
    "client_ip": "10.0.1.5"
  },
  "metadata": {
    "scheduled_at": "2024-03-20T12:45:00Z",
    "priority": "high"
  }
}
```

**Queue Characteristics**:
- **FIFO ordering**: First job queued = first job processed
- **Blocking pop**: Worker blocks saat queue kosong (configurable timeout)
- **No persistence** (redis-default): Job hilang jika worker crash (acceptable trade-off)
- **Max queue size**: Tidak ada hard limit, tapi monitor untuk backlog

### 3. ML Predictor Integration

**Component**: `src/ml/predictor.py` → `KeyPredictor.predict()`

**Workflow**:
```python
# Worker saat processing job:
access_data = data_collector.get_access_sequence(
    window_seconds=300,  # Last 5 minutes
    max_events=1000
)

# Run ensemble predictor
predicted_keys, confidences = predictor.predict_top_n(
    service_id=job['service_id'],
    n=10,  # Predict top 10 likely next keys
    min_confidence=0.75
)

# Example output:
# [
#   ("user_123:key_789", 0.92),   # High confidence
#   ("user_123:key_101", 0.85),   # Medium-high confidence
#   ("user_123:key_202", 0.72),   # Low confidence (filter out)
# ]
```

**Confidence Threshold**:
- Default: 0.75 (only prefetch if >= 75% predicted probability)
- Only fetch keys dengan confidence >= threshold
- Configurable via `ML_PREDICTION_THRESHOLD`

---

## Worker Lifecycle

### Initialization

```
1. Parse configuration dari environment:
   - REDIS_HOST, REDIS_PORT, REDIS_PASSWORD
   - ML_MODEL_NAME, ML_MODEL_PATH
   - PREFETCH_QUEUE_KEY (default: "pskc:prefetch:jobs")
   - PREFETCH_WORKER_BLOCK_TIMEOUT (default: 5 seconds)
   - LOG_LEVEL
   
2. Connect to Redis
   - Test connection dengan PING
   - Verify queue exists (or create if needed)
   - Set up blocking pop operation
   
3. Load ML model dari registry
   - Load active model version dari disk/registry
   - Run model inference test (predict dummy data)
   - Verify model is_trained=True
   
4. Initialize data collector & feature engineer
   - These are same instances as API servers (via shared Redis)
   - Start consuming access events from data collector
   
5. Enter main loop
   - BLPOP dari Redis queue dengan timeout
   - Process jobs sequentially
   - Log job status dan metrics
```

### Main Loop Processing

```python
while True:
    # Block sampai job available (timeout saat idle)
    job = redis_client.blpop(
        PREFETCH_QUEUE_KEY,
        timeout=PREFETCH_WORKER_BLOCK_TIMEOUT
    )
    
    if job is None:
        # Timeout: no job, continue waiting
        continue
    
    try:
        # Parse job JSON
        job_data = json.loads(job[1])  # job[0] is queue name
        
        # Run prediction
        predicted_keys = predictor.predict_top_n(
            service_id=job_data['service_id'],
            n=10
        )
        
        # Fetch predicted keys dari KMS/origin
        for key_id in predicted_keys:
            if cache.exists(key_id):
                continue  # Already cached, skip
            
            key_material = key_fetcher.fetch_key(key_id)
            cache.set(key_id, key_material)  # Store to L1+L2
        
        # Mark job as processed
        log_prefetch_success(job_data['job_id'])
        
    except Exception as e:
        # Handle errors
        log_prefetch_error(job_data['job_id'], error=str(e))
        # Continue processing next job (don't block on failure)
```

### Shutdown Handling

```
Saat worker terminating (SIGTERM/SIGINT):
  1. Finish processing current job
  2. Flush any pending metrics/logs
  3. Close Redis connection gracefully
  4. Exit with code 0 (success)
  
Timeout: 30 seconds untuk graceful shutdown
```

---

## Job Scheduling

### Saat Job Dijadwalkan (dari API Server)

```python
# File: src/api/routes.py, endpoint /keys/access

# Setelah sukses return key kepada client:
prefetch_job = {
    "job_id": str(uuid.uuid4()),
    "service_id": settings.app_name or "api-prod",
    "timestamp": time.time(),
    "accessed_key_id": key_id,
    "context": {
        "access_type": "read",
        "cache_hit": was_cache_hit,  # True jika dari L1/L2
        "latency_ms": elapsed_ms,
        "client_ip": client_ip
    }
}

redis_client.rpush(
    settings.prefetch_queue_key,  # "pskc:prefetch:jobs"
    json.dumps(prefetch_job)
)
```

### Job Timing

- **Timing**: Scheduled immediately после returning response (async, non-blocking)
- **Frequency**: One job per client request (could be 1000s per second pada peak)
- **Queue size**: Monitor to detect backlog atau worker slowdown

---

## Performance & Scaling

### Throughput

| Scenario | Jobs/sec | Pred Accuracy | Cache Fill Time |
|----------|----------|---------------|-----------------|
| Low traffic (10 req/s) | 10 | 85% | 1-2 mins |
| Medium (100 req/s) | 100 | 85% | 30-60 secs |
| High (1000 req/s) | 1000 | 80% | 10-30 secs |

### Latency Breakdown (per job)

```
Job processing time:
├─ Dequeue from Redis: <1ms
├─ ML prediction: 100-150ms (ensemble model)
├─ Fetch 10 keys from KMS: 500-1000ms (parallel batch)
├─ Cache write (L1+L2): 50-100ms (for all 10 keys)
└─ Total: ~650-1200ms per 10-key job

Worker throughput:
  If 1 job takes 1 second and returns 10 keys:
    → 1 job/sec = covering 10 key accesses/sec
    → At 1000 req/sec traffic, worker can cover ~100 of them
    → Need 10 workers to cover 1000 req/sec baseline
```

### Scaling Strategies

1. **Single Worker (development)**
   - Works fine for <100 req/sec
   - Simple deployment, no job distribution needed

2. **Multiple Workers (production)**
   ```
   ┌─ Redis queue (shared)
   │
   ├─ Worker 1 ───┐
   ├─ Worker 2    ├─→ All read from same queue
   ├─ Worker 3    │
   └─ Worker N ───┘
   
   Benefits:
   - Parallel job processing
   - Fault tolerance (if one worker dies)
   - auto-scale based on queue depth
   ```

3. **Worker Pools**
   ```
   Kind: StatefulSet (Kubernetes)
   Replicas: 3-10 (based on queue depth)
   Resources: 
     - CPU: 1-2 cores per worker
     - Memory: 500MB-1GB per worker
   Auto-scaling trigger:
     - Scale up if queue_depth > 1000
     - Scale down if queue_depth < 100
   ```

### Resource Usage

```
Single Worker Process:
├─ Memory: ~200-300MB
│  ├─ Python runtime: 100MB
│  ├─ Redis client: 20MB
│  ├─ ML model (loaded): 50-100MB
│  └─ Working buffers: 30-50MB
│
└─ CPU: 
   ├─ Idle (waiting): <1%
   ├─ ML prediction: 20-40% (1-2 cores for 100-150ms)
   ├─ KMS fetch: <5% (network-bound)
   └─ Peak (all 10 keys parallel): 40-60%
```

---

## Error Handling & Resilience

### Failure Scenarios

| Scenario | Behavior | Result |
|----------|----------|--------|
| Job JSON corrupt | Parse fails → log error → skip job | Job lost, continue |
| Model inference error | Catch exception → log → false prediction | Miss predicted key (suboptimal but safe) |
| KMS fetch timeout | Retry 3x dengan backoff → skip key | Predicted key not prefetched |
| Redis write fails | Log warning → continue | Cache miss on next request |
| Worker crash | Systemd/K8s restart | Resume from next queued job |
| Queue full | RPUSH blocks briefly | Job scheduling slightly delayed |

### Retry Logic

```python
# For KMS fetch during prefetch:
max_retries = 3
for attempt in range(max_retries):
    try:
        key_material = key_fetcher.fetch_key(key_id)
        cache.set(key_id, key_material)
        break
    except Exception as e:
        if attempt < max_retries - 1:
            wait_seconds = 2 ** attempt  # Exponential backoff
            logger.warning(f"Retry {attempt+1}: {e}, waiting {wait_seconds}s")
            time.sleep(wait_seconds)
        else:
            logger.error(f"Failed to prefetch {key_id} after {max_retries} attempts")
            # Give up on this key, continue
```

---

## Monitoring & Observability

### Key Metrics to Track

```python
from prometheus_client import Counter, Histogram, Gauge

# Job processing metrics
prefetch_jobs_processed = Counter(
    'prefetch_jobs_total',
    'Total prefetch jobs processed',
    ['status']  # 'success', 'error', 'skipped'
)

prefetch_keys_prefetched = Counter(
    'prefetch_keys_total',
    'Total keys prefetched'
)

prefetch_queue_depth = Gauge(
    'prefetch_queue_depth',
    'Current prefetch queue depth'
)

prefetch_job_duration = Histogram(
    'prefetch_job_duration_seconds',
    'Time to process one prefetch job'
)

prefetch_cache_hitrate = Gauge(
    'prefetch_cache_hitrate',
    'Percentage of next requests finding prefetched keys'
)
```

### Example Dashboard (Prometheus/Grafana)

```
Panel 1: Queue Depth Over Time
  Query: prefetch_queue_depth
  Alert: If > 5000 jobs for 5 mins → scale workers

Panel 2: Job Processing Rate
  Query: rate(prefetch_jobs_total[5m])
  Target: 100-200 jobs/min

Panel 3: Prefetch Effectiveness
  Query: prefetch_cache_hitrate
  Target: > 70% (keys were actually used)

Panel 4: Error Rate
  Query: rate(prefetch_jobs_total{status="error"}[5m])
  Alert: If > 1% of jobs fail → investigate
```

### Logging

```
Log Levels:
  DEBUG: Every job dequeued, predictions made
    "Dequeued job [xxx]: predicted keys=10, confidence=[0.92, 0.85, ...]"
  
  INFO: Summary per batch
    "Processed 100 jobs, prefetched 850 keys, avg duration 1.2s"
  
  WARNING: Retry attempts, partial failures
    "Failed to fetch user_123:key_789 after 3 retries, skipped"
  
  ERROR: Critical failures
    "Redis connection lost, retrying in 30s"
    "ML model inference failed: {exception}"
```

---

## Configuration

### Environment Variables

```env
# Prefetch-specific
PREFETCH_QUEUE_KEY=pskc:prefetch:jobs          # Redis queue name
PREFETCH_WORKER_BLOCK_TIMEOUT=5                # Timeout saat dequeue blocks (seconds)
PREFETCH_MAX_RETRIES=3                         # Retries untuk KMS fetch
PREFETCH_RETRY_BACKOFF_SECONDS=5               # Initial backoff (exponential)

# Shared config (also used by prefetch)
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=pskc_redis_secret
REDIS_FAILURE_BACKOFF_SECONDS=30

# ML config
ML_MODEL_NAME=pskc_model
ML_PREDICTION_THRESHOLD=0.75                   # Min confidence to prefetch

# Logging
LOG_LEVEL=info
```

### Runtime Configuration (docker-compose.yml)

```yaml
services:
  prefetch-worker:
    image: pskc:latest
    entrypoint: python -m src.workers.prefetch_worker
    environment:
      REDIS_HOST: redis
      REDIS_PASSWORD: pskc_redis_secret
      LOG_LEVEL: info
    depends_on:
      - redis
    deploy:
      replicas: 3              # Run 3 instances for HA
      resources:
        limits:
          cpus: '2'            # 2 CPU cores max
          memory: 1G           # 1GB memory max
        reservations:
          cpus: '1'
          memory: 500M
```

---

## Operational Runbook

### Starting the Worker

```bash
# Development
cd /path/to/pskc
python -m src.workers.prefetch_worker

# Production (Docker)
docker-compose -f docker-compose.production.yml up prefetch-worker

# Kubernetes
kubectl apply -f k8s/prefetch-worker.yaml
kubectl logs -f deployment/prefetch-worker
```

### Monitoring Queue Health

```bash
# Check queue depth
redis-cli LLEN pskc:prefetch:jobs

# Monitor real-time
redis-cli --stat  # Shows LLEN change rate

# If queue growing (backlog):
# 1. Check worker logs for errors
redis-cli LINDEX pskc:prefetch:jobs 0

# 2. Scale up workers (add more instances)
# 3. Check Redis performance (CPU, memory)
redis-cli INFO stats | grep total_commands_processed
```

### Debugging a Slow Prefetch

```bash
# Get a sample job from queue
redis-cli LRANGE pskc:prefetch:jobs -1 -1

# Simulate what worker does
python -c "
import json
job = json.loads(b'<paste job JSON from redis>')
print(f'Job: {job}')
print(f'Service: {job[\"service_id\"]}')
print(f'Time: {job[\"timestamp\"]}')
"

# Test ML prediction manually
python -c "
from src.ml.predictor import KeyPredictor
predictor = KeyPredictor()
predictor.load_active_model()
predictions = predictor.predict(service_id='api-prod', n=10)
print(predictions)
"

# Check if KMS is slow
time curl http://kms-endpoint/keys/user_123:key_456
```

### Graceful Shutdown

```bash
# Send SIGTERM to worker (will finish current job + exit)
kill -TERM <worker_pid>

# In Kubernetes
kubectl delete pod prefetch-worker-xxxxx

# Monitor
kubectl wait --for=condition=Ready pod/prefetch-worker-newpod

# Verify no job loss (should resume from where stopped)
redis-cli LLEN pskc:prefetch:jobs  # Should see queued jobs
```

---

## Common Issues & Solutions

### Issue 1: Queue Growing Unbounded

**Symptom**: `LLEN pskc:prefetch:jobs` returns 10,000+

**Causes**:
- Worker crashed or slow
- ML model inference taking too long
- KMS timing out

**Solution**:
```bash
# Check worker status
docker logs prefetch-worker | tail -100

# If worker fine, check ML
time python -c "predictor.predict(..."  # Should be <200ms

# If ML slow, profile
py-spy record -o prefetch.prof -- python -m src.workers.prefetch_worker

# If KMS slow, check network
curl -w "@curl-format.txt" -o /dev/null http://kms-endpoint/health
```

### Issue 2: Cache Hit Rate Low (< 50%)

**Symptom**: Prefetched keys not actually used

**Causes**:
- ML model accuracy low
- Traffic pattern changed
- Prediction confidence threshold too low

**Solution**:
```bash
# Check prediction accuracy
monitoring: prefetch_cache_hitrate

# If < 50%, retrain ML model with new data
# Check threshold
grep ML_PREDICTION_THRESHOLD .env

# Try increasing threshold (only prefetch high-confidence)
ML_PREDICTION_THRESHOLD=0.85
```

### Issue 3: Worker Memory Leak

**Symptom**: Memory usage grows over time, worker becomes OOM

**Causes**:
- Data collector events accumulating
- Redis connection buffers not freed
- Model state growing

**Solution**:
```bash
# Monitor memory
kubectl top pod prefetch-worker-xxxxx

# Check data collector stats
python -c "collector.get_stats()" | grep memory

# Add memory limits in docker-compose
  deploy:
    resources:
      limits:
        memory: 1G

# Restart worker periodically (K8s restartPolicy)
restart: always
```

---

## Best Practices

1. **Run Multiple Workers**: At least 2-3 for redundancy and throughput
2. **Set Queue Depth Alert**: Alert if queue > 10,000 jobs for 5 mins
3. **Monitor Accuracy**: Track cache hit rate, aim for >70%
4. **Log Everything**: Prefetch provides visibility into next-access patterns
5. **Test Predictions**: Run prefetch tests before production rollout
6. **Graceful Degradation**: If prefetch fails, API still works (from KMS fetch)
7. **Version ML Model**: New predictions might have different accuracy

---

## Related Components

- **PrefetchQueue**: Redis list, managed by prefetch code
- **KeyPredictor**: `src/ml/predictor.py` - Makes predictions
- **EnsembleModel**: `src/ml/model.py` - LSTM+RF+Markov ensemble
- **DataCollector**: `src/ml/data_collector.py` - Access history for prediction
- **SecureCacheManager**: `src/security/intrusion_detection.py` - Stores fetched keys
