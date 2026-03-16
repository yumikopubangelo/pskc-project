# Deployment Policies — Production Runtime

Dokumen ini berisi kebijakan deployment detail untuk environment production PSKC. Bagian ini melengkapi `docker-compose.production.yml` dan `docs/operations.md`.

## Table of Contents

1. [Runtime Topology](#runtime-topology)
2. [Service Dependencies & Startup Order](#service-dependencies--startup-order)
3. [Resource Limits & Scaling Policies](#resource-limits--scaling-policies)
4. [Rolling Update Strategy](#rolling-update-strategy)
5. [Backup & Recovery](#backup--recovery)
6. [Security Hardening](#security-hardening)
7. [High Availability](#high-availability)
8. [Health Check Policies](#health-check-policies)

---

## Runtime Topology

### Production Architecture

```
                                    [ Internet ]
                                           |
                                    [ Cloud Load Balancer ]
                                    (TLS Termination, WAF)
                                           |
                                    [ Nginx Reverse Proxy ]
                               (Port 443, Rate Limiting)
                                           |
                    +----------------------+----------------------+
                    |                      |                      |
            [ PSKC API Primary ]   [ PSKC API Secondary ]  [ Prefetch Worker ]
                    |                      |                      |
                    +----------------------+----------------------+
                                           |
                                    [ Redis Cluster ]
                               (Primary + Replicas)
                                           |
                    +----------------------+----------------------+
                    |                      |                      |
            [ Prometheus ]           [ Grafana ]           [ AlertManager ]
```

### Network Segmentation

| Service | Network Zone | Purpose |
| --- | --- | --- |
| Cloud Load Balancer | External | Public entry point, TLS termination |
| Nginx | DMZ | Reverse proxy, rate limiting, request routing |
| PSKC API | Application | Core business logic, authentication |
| Prefetch Worker | Application | Background prediction, cache warming |
| Redis | Data | Caching layer, queue management |
| Prometheus/Grafana | Monitoring | Observability (internal only) |

### Port Mapping

| Service | Internal Port | External Port | Protocol |
| --- | --- | --- | --- |
| Nginx | 80, 443 | 443 (HTTPS) | HTTP/HTTPS |
| PSKC API | 8000 | - | HTTP (via Nginx) |
| Redis | 6379 | - | Redis |
| Prometheus | 9090 | - | HTTP |
| Grafana | 3000 | 3001 | HTTP |

---

## Service Dependencies & Startup Order

### Dependency Graph

```
nginx ─────┬────> pskc-api ─────┬────> redis
           │                    │
           │                    └────> prefetch-worker
           │
           └────> prometheus ─────> grafana
```

### Startup Sequence

**Phase 1: Infrastructure (0-30s)**

1. **Redis** - Must start first
   - Wait for: Docker health check (redis-cli ping)
   - Timeout: 30s
   - Failure action: Block dependent services

2. **Prometheus** - Metrics collection
   - Wait for: Redis available
   - Timeout: 30s

**Phase 2: Application Core (30-90s)**

3. **PSKC API** - Main application
   - Wait for: Redis healthy, FIPS self-test passed
   - Health check: `/health/ready`
   - Timeout: 60s
   - Failure action: Restart container

4. **Prefetch Worker** - Background processing
   - Wait for: Redis healthy, API healthy
   - Health check: Internal heartbeat
   - Timeout: 30s

**Phase 3: External Access (90s+)**

5. **Nginx** - Reverse proxy
   - Wait for: API healthy
   - Health check: `/health` endpoint
   - Timeout: 30s

6. **Grafana** - Dashboard
   - Wait for: Prometheus available
   - Timeout: 60s

### Startup Timeout Configuration

```yaml
# docker-compose.production.yml
services:
  redis:
    healthcheck:
      start_period: 10s
      timeout: 10s
      retries: 5
  
  api:
    healthcheck:
      start_period: 60s    # Longer for FIPS tests
      timeout: 10s
      retries: 5
  
  prefetch-worker:
    depends_on:
      api:
        condition: service_healthy
      redis:
        condition: service_healthy
```

---

## Resource Limits & Scaling Policies

### Resource Allocation Matrix

| Service | CPU Request | CPU Limit | Memory Request | Memory Limit | Storage |
| --- | --- | --- | --- | --- | --- |
| nginx | 100m | 500m | 64Mi | 256Mi | - |
| pskc-api | 500m | 2000m | 512Mi | 2Gi | - |
| prefetch-worker | 250m | 1000m | 256Mi | 1Gi | - |
| redis | 250m | 1000m | 512Mi | 2Gi | 10Gi |
| prometheus | 100m | 500m | 256Mi | 1Gi | 50Gi |
| grafana | 50m | 250m | 128Mi | 512Mi | - |

### Scaling Triggers

#### Horizontal Scaling (HPA)

**PSKC API:**
```yaml
# api-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: pskc-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: pskc-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
```

**Prefetch Worker:**
```yaml
# prefetch-worker-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: pskc-prefetch-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: pskc-prefetch-worker
  minReplicas: 1
  maxReplicas: 5
  metrics:
  - type: External
    external:
      metric:
        name: redis_list_length
        selector:
          matchLabels:
            queue: pskc-prefetch-jobs
      target:
        type: AverageValue
        averageValue: "100"
```

#### Vertical Scaling (VPA) for Redis

```yaml
# redis-vpa.yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: pskc-redis-vpa
spec:
  targetRef:
    apiVersion: "apps/v1"
    kind: Deployment
    name: pskc-redis
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
    - containerName: redis
      minAllowed:
        cpu: 250m
        memory: 512Mi
      maxAllowed:
        cpu: 2000m
        memory: 4Gi
      controlledResources: ["cpu", "memory"]
```

### Auto-scaling Rules

| Metric | Threshold | Action | Cooldown |
| --- | --- | --- | --- |
| CPU (API) | > 70% for 2min | Scale up (+1) | 3 min |
| CPU (API) | < 30% for 5min | Scale down (-1) | 5 min |
| Memory (API) | > 80% for 2min | Scale up (+1) | 3 min |
| Request Latency | p99 > 500ms | Scale up (+1) | 2 min |
| Prefetch Queue | > 100 items | Scale worker (+1) | 2 min |
| Cache Hit Rate | < 50% | Trigger retrain | 10 min |

---

## Rolling Update Strategy

### Update Policy

```yaml
# RollingUpdate configuration
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1        # Allow 1 extra pod during update
    maxUnavailable: 0  # No pods unavailable during update
```

### Update Sequence

**Step 1: Pre-update Checks (before each pod)**
1. Verify new image builds successfully
2. Run integration tests
3. Check Prometheus metrics for anomalies
4. Notify on-call team

**Step 2: Update Process**
```
┌─────────────────────────────────────────────────────────────┐
│                    Rolling Update Flow                      │
├─────────────────────────────────────────────────────────────┤
│  1. Deploy new API pod (maxSurge=1)                        │
│     └─> New pod starts, health check passes                 │
│  2. Route 10% traffic to new pod                           │
│     └─> Monitor error rate, latency                        │
│  3. If healthy: Route 50% traffic                         │
│  4. If healthy: Route 100% traffic                        │
│  5. Shutdown old pod                                      │
│  6. Repeat for remaining pods                             │
└─────────────────────────────────────────────────────────────┘
```

### Rollback Procedure

```bash
# Quick rollback to previous version
kubectl rollout undo deployment/pskc-api

# Rollback to specific revision
kubectl rollout undo deployment/pskc-api --to-revision=3

# Check rollback status
kubectl rollout status deployment/pskc-api
```

### Update Windows

| Environment | Update Window | Maintenance Window |
| --- | --- | --- |
| Development | Anytime | None |
| Staging | Mon-Fri, 09:00-17:00 | 30 min |
| Production | Sun-Thu, 02:00-04:00 | 2 hours |

---

## Backup & Recovery

### Backup Schedule

| Data Type | Frequency | Retention | Location |
| --- | --- | --- | --- |
| Redis RDB | Every 15 min | 7 days | S3/GCS bucket |
| Redis AOF | Continuous | 3 days | Local + S3 |
| Model Registry | Daily | 30 days | S3/GCS bucket |
| Prometheus Data | Daily | 15 days | S3/GCS bucket |
| Audit Logs | Daily | 90 days | S3/GCS bucket |
| Grafana Dashboards | On change | Forever | Git |

### Backup Commands

```bash
# Redis backup
redis-cli -a "$REDIS_PASSWORD" BGSAVE
# AOF is automatically written

# Model registry backup
aws s3 sync data/models/ s3://pskc-backup/models/$(date +%Y%m%d)/

# Prometheus backup
curl -s http://localhost:9090/api/v1/admin/tsdb/snapshot > snapshot.tar.gz

# Full backup script
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups/$DATE"

mkdir -p $BACKUP_DIR

# Redis
redis-cli -a "$REDIS_PASSWORD" BGSAVE
sleep 5
cp /var/lib/redis/dump.rdb $BACKUP_DIR/

# Models
cp -r data/models/* $BACKUP_DIR/models/

# Compress
tar -czf pskc-backup-$DATE.tar.gz $BACKUP_DIR/

# Upload
aws s3 cp pskc-backup-$DATE.tar.gz s3://pskc-backups/
```

### Recovery Procedures

**Redis Recovery:**
```bash
# Stop Redis
docker-compose stop redis

# Restore from backup
cp backup/dump.rdb ./redis-data/

# Start Redis
docker-compose start redis

# Verify
redis-cli -a "$REDIS_PASSWORD" INFO | grep role
```

**Model Recovery:**
```bash
# Download from backup
aws s3 cp s3://pskc-backup/models/20240115/ data/models/ --recursive

# Verify checksum
python -c "import json; print(json.load(open('data/models/checksums.json')))"

# Reload model in registry
curl -X POST http://localhost:8000/ml/reload
```

**Full System Recovery:**
```bash
# 1. Restore infrastructure
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secrets.yaml

# 2. Restore Redis
kubectl apply -f k8s/redis-pvc.yaml
docker-compose up -d redis

# 3. Restore data
./scripts/restore-redis.sh
./scripts/restore-models.sh

# 4. Start application
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/prefetch-deployment.yaml

# 5. Verify
./scripts/health-check.sh
```

---

## Security Hardening

### Network Policies

```yaml
# k8s-network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: pskc-network-policy
spec:
  podSelector:
    matchLabels:
      app: pskc-api
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: nginx
    ports:
    - protocol: TCP
      port: 8000
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: redis
    ports:
    - protocol: TCP
      port: 6379
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 53
    - protocol: UDP
      port: 53
```

### Pod Security Standards

```yaml
# api-pss.yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10000
  runAsGroup: 10000
  fsGroup: 10000
  seccompProfile:
    type: RuntimeDefault
  capabilities:
    drop:
    - ALL
```

### Secret Management

| Secret | Storage | Rotation | Access |
| --- | --- | --- | --- |
| SECRET_KEY | HashiCorp Vault / AWS Secrets Manager | 90 days | API service account |
| CACHE_ENCRYPTION_KEY | HashiCorp Vault / AWS Secrets Manager | 90 days | API, Prefetch |
| REDIS_PASSWORD | HashiCorp Vault / AWS Secrets Manager | 30 days | API, Prefetch, Redis |
| ML_MODEL_SIGNING_KEY | HashiCorp Vault / AWS Secrets Manager | 180 days | API only |

### TLS Configuration

```nginx
# Nginx TLS configuration
server {
    listen 443 ssl http2;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    
    # HSTS
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    
    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
}
```

---

## High Availability

### Redis HA Setup

```
┌─────────────────┐     ┌─────────────────┐
│   Redis Master │────>│  Redis Replica1 │
│   (Primary)    │     │   (Read/Backup)  │
└────────┬────────┘     └─────────────────┘
         │
         └───────────> Redis Replica2
                      (Read/Backup)
```

```yaml
# Redis Sentinel configuration
sentinel monitor mymaster redis-master 6379 2
sentinel down-after-milliseconds mymaster 5000
sentinel failover-timeout mymaster 60000
sentinel parallel-syncs mymaster 1
```

### API HA Setup

```yaml
# Multiple replicas with pod anti-affinity
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchLabels:
            app: pskc-api
        topologyKey: kubernetes.io/hostname
```

### Database/Queue HA

| Component | HA Strategy | RTO | RPO |
| --- | --- | --- | --- |
| Redis | Sentinel/Cluster | < 30s | < 1s |
| API | Multi-replica | < 60s | N/A |
| Prefetch Worker | Multi-replica | < 60s | N/A |
| Prometheus | Thanos/Remote | < 5min | < 1h |

---

## Health Check Policies

### Health Check Matrix

| Service | Liveness | Readiness | Startup |
| --- | :---: | :---: | :---: |
| nginx | /health | /health | - |
| pskc-api | /health | /health/ready | /health/startup |
| redis | redis-cli ping | - | - |
| prefetch-worker | internal | internal | - |
| prometheus | /-/healthy | - | - |
| grafana | /api/health | - | - |

### Health Check Thresholds

```yaml
# Kubernetes probe configuration
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30
  timeoutSeconds: 5
  failureThreshold: 3    # Kill after 3 failures

readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3    # Remove from service after 3 failures
  successThreshold: 1

startupProbe:
  httpGet:
    path: /health/startup
    port: 8000
  failureThreshold: 30  # Allow 30 * 10s = 5min startup
  periodSeconds: 10
```

### Dependency Health Timeouts

| Dependency | Timeout | Failure Action |
| --- | --- | :---: |
| Redis connection | 5s | fail_open (serve without cache) |
| Redis command | 2s | fail_open |
| FIPS module | 30s | fail_closed (block startup) |
| Audit logger | 10s | fail_closed (block startup) |
| ML model load | 60s | fail_open (serve without prediction) |
| Prefetch queue | 5s | fail_open |

---

## Quick Reference

### Deployment Checklist

- [ ] Secrets rotated within 90 days
- [ ] TLS certificates valid (> 30 days)
- [ ] Backups verified working
- [ ] Rollback procedure tested
- [ ] Health checks passing
- [ ] Metrics within normal ranges
- [ ] On-call team notified
- [ ] Maintenance window communicated

### Emergency Contacts

| Role | Contact | Escalation Time |
| --- | --- | :---: |
| On-call Engineer | [PAGERDUTY] | 15 min |
| Team Lead | [SLACK] | 30 min |
| Security Team | [SLACK] | 30 min |
| Infrastructure | [SLACK] | 1 hour |

### Useful Commands

```bash
# Check pod status
kubectl get pods -n pskc -o wide

# View logs
kubectl logs -f deployment/pskc-api -n pskc

# Check resource usage
kubectl top pods -n pskc

# Scale deployment
kubectl scale deployment pskc-api --replicas=5 -n pskc

# Port forward for debugging
kubectl port-forward svc/pskc-api 8000:8000 -n pskc

# Execute in container
kubectl exec -it pskc-api-xxx -n pskc -- /bin/sh
```
