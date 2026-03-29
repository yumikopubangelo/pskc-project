# PSKC Project

![Docker](https://img.shields.io/badge/Docker-Enabled-blue?logo=docker)
![Python](https://img.shields.io/badge/Python-3.11%2B-brightgreen?logo=python)

---

## 📖 Overview

**PSKC** (Predictive Secure Key‑Cache) is a modular micro‑service platform that provides:
- **Real‑time cache‑hit analytics**
- **Online learning with River**
- **Concept‑drift detection (EWMA, ADWIN, EDDM)**
- **Automatic retraining via a dedicated ML worker**
- **Database Explorero** for administrators to inspect raw SQLite data.

All components communicate through **Redis** and expose a **FastAPI** HTTP API. The frontend is a Vite‑powered React app.

---

## 🏗️ Architecture

```mermaid
flowchart TD
    subgraph DockerCompose[Docker‑Compose]
        direction LR
        API[API Service (FastAPI)] -->|HTTP| Frontend[Frontend (Vite/React)]
        API -->|Redis| Redis[Redis]
        MLWorker[ML Worker] -->|Redis| Redis
        Prefetch[Prefetch Worker] -->|Redis| Redis
    end
    subgraph DB[SQLite DB]
        DBFile[(pskc.db)]
    end
    API -->|SQLAlchemy| DBFile
    classDef service fill:#f9f9f9,stroke:#333,stroke-width:1px;
    class API,MLWorker,Prefetch,Frontend service;
```

---

## 📦 Prerequisites

- **Docker Desktop** (or Docker Engine) >= 24.x
- **Docker‑Compose** (v2) – bundled with Docker Desktop
- **Python 3.11+** (only needed if you want to run services locally without Docker)
- **Node.js 20+** (for frontend development)

---

## ⚙️ Setup & Run (Docker)

1. **Clone the repository**
   ```bash
   git clone https://github.com/your‑org/pskc-project.git
   cd pskc-project
   ```
2. **Create a `.env` file** (copy from `example.env` if present) and adjust any secrets.
3. **Start the stack**
   ```bash
   docker compose up --build -d
   ```
   The following containers will be launched:
   - `pskc-api` – FastAPI backend (exposed on `http://localhost:8000`)
   - `pskc-frontend` – React UI (exposed on `http://localhost:3000`)
   - `pskc-redis` – Redis cache
   - `pskc-ml-worker` – ML worker (auto‑training & drift detection)
   - `pskc-prefetch-worker` – Prefetch job processor
4. **Verify health**
   ```bash
   curl http://localhost:8000/health
   ```
   You should see `{"status":"healthy"}`.

---

## 🛠️ Configuration (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | Application mode (`development`/`production`). |
| `LOG_LEVEL` | `info` | Python logging level. |
| `REDIS_HOST` | `redis` | Hostname of the Redis container. |
| `REDIS_PORT` | `6379` | Redis port. |
| `REDIS_PASSWORD` | `pskc_redis_secret` | Redis password (set in `.env`). |
| `ML_UPDATE_INTERVAL_SECONDS` | `30` | How often the ML worker polls Redis for new events. |
| `ML_SCHEDULED_TRAIN_INTERVAL_SECONDS` | `3600` | Minimum interval between scheduled trainings. |
| `ML_DRIFT_THRESHOLD` | `0.12` | EWMA drop percentage that triggers a drift alert. |
| `ML_ENABLE_RIVER` | `true` | Enable River online learning. |
| `PREFETCH_RATE_LIMIT_RPS` | `10` | Jobs per second the prefetch worker may consume. |
| `PREFETCH_MAX_RETRIES` | `3` | Maximum retry attempts before moving a job to DLQ. |

---

## 📡 API Endpoints

### Core API (`/api`)
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check. |
| `GET` | `/admin/db/tables` | List all SQLite tables with row counts. |
| `GET` | `/admin/db/tables/{table}` | Paginated rows of a specific table (`?page=1&size=100`). |
| `GET` | `/ml/status` | Current ML model status & sample count. |
| `POST` | `/ml/training/train` | Trigger a training run (optional `force` & `reason`). |
| `GET` | `/ml/training/progress` | Real‑time training progress (used by the UI). |

### Prefetch API (`/prefetch` – internal)
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/prefetch/jobs` | Enqueue a prefetch job. |
| `GET` | `/prefetch/stats` | Queue, retry & DLQ statistics. |
| `POST` | `/prefetch/replay` | Replay jobs from DLQ back to the main queue. |

---

## 🎨 Frontend – Database Explorer

The **Database Explorer** lives at `http://localhost:3000/db-explorer`. It provides:
- Table selector dropdown.
- Paginated data grid with smooth glass‑morphic styling.
- Search & column‑sorting (future enhancement).
- Real‑time refresh every 30 seconds.

The UI is built with **React**, **Vite**, and vanilla CSS using a curated dark‑mode palette (HSL‑based gradients, subtle micro‑animations on hover, and Google Font *Inter*).

---

## 🤖 ML Worker & Drift Detection

- **Drift detection** uses EWMA, ADWIN, and EDDM. When a drift is detected, the worker logs a warning and automatically triggers a retraining via the API.
- **River** provides online incremental learning for cache‑hit prediction.
- The worker respects the `ML_UPDATE_INTERVAL_SECONDS` and `ML_SCHEDULED_TRAIN_INTERVAL_SECONDS` settings.

All drift‑related logs are emitted under `src.ml.drift` and can be observed with:
```bash
docker logs pskc-ml-worker -f | grep drift
```

---

## 📂 Prefetch Worker

- Implements a **Redis‑backed rate‑limited queue** (`pskc:prefetch:jobs`).
- Supports automatic retry with exponential back‑off and a dead‑letter queue (DLQ).
- The recent‑queue timeout (`brpop` returning `None`) is now treated as a normal empty‑queue condition, avoiding spurious back‑off warnings.

---

## 🧪 Testing

```bash
# Backend tests (pytest)
cd src
pytest

# Frontend tests (vitest)
cd ../frontend
npm run test
```

---

## 🤝 Contributing

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/awesome‑feature`).
3. Follow the **code‑style** guidelines (black, isort, flake8).
4. Write unit tests for any new logic.
5. Submit a Pull Request.

---

## 📜 License

This project is licensed under the **MIT License**. See `LICENSE` for details.

---

*Happy hacking! 🚀*
