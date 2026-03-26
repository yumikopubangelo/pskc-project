# Feature Roadmap PSKC

Dokumen ini menjelaskan fitur yang **masih perlu dikembangkan** dari kondisi repo saat ini. Pasangannya adalah [comprehensive_features.md](comprehensive_features.md), yang menjelaskan apa saja yang sudah aktif.

Tujuan dokumen ini bukan membuat daftar ide sebanyak mungkin, tetapi membuat backlog yang bisa langsung dipakai untuk implementasi.

## Cara Memakai Dokumen Ini

Setiap item di bawah punya 5 bagian:

1. **Kenapa penting**  
   Masalah apa yang sedang ditutup.
2. **Yang sudah ada**  
   Fondasi yang sudah tersedia di repo sekarang.
3. **Yang perlu dibangun**  
   Pekerjaan implementasi yang benar-benar harus dilakukan.
4. **File utama**  
   Area kode yang paling mungkin disentuh.
5. **Definition of done**  
   Kapan item itu boleh dianggap selesai.

Skala prioritas:

- `P0`: penting untuk stabilitas atau kejujuran sistem sekarang
- `P1`: penting untuk operasi dan maturity berikutnya
- `P2`: peningkatan produk / DX / analisis
- `P3`: ekspansi jangka menengah

## Prioritas Singkat

Kalau Anda hanya ingin tahu "habis ini saya harus bikin apa", mulai dari urutan ini:

1. `P0` rapikan migration discipline database dan schema upgrades
2. `P0` stabilkan validation dan deployment profile
3. `P0` matangkan observability historis dan operator metrics
4. `P1` matangkan prefetch ops: replay, backpressure, budgeting
5. `P1` tingkatkan akurasi model dengan data/feature/evaluation yang lebih kuat
6. `P1` rapikan governance release model lintas environment

## Roadmap

### 1. Schema Migration Discipline

**Prioritas:** `P0`

**Kenapa penting**  
Repo sekarang sudah punya auto-repair ringan untuk beberapa kolom SQLite lama, tetapi itu hanya jaring pengaman. Begitu tabel observability atau model intelligence terus bertambah, tanpa migration discipline yang jelas dashboard bisa rusak pada database existing.

**Yang sudah ada**

- default SQLite path lintas platform
- startup compatibility repair untuk additive columns penting
- ORM model untuk version, training, prediction, dan per-key metrics

**Yang perlu dibangun**

- migration workflow yang benar-benar versioned
- direktori migration yang konsisten untuk local/dev/prod
- smoke test upgrade database existing
- dokumentasi kapan pakai auto-repair ringan vs migration resmi

**File utama**

- `src/database/connection.py`
- `src/database/models.py`
- `config/settings.py`
- `docs/operations.md`

**Definition of done**

- upgrade schema database existing tidak butuh reset manual
- perubahan tabel observability dan model intelligence punya migration story yang jelas
- CI punya smoke test upgrade database lama ke schema terbaru

---

### 2. Production Deployment Profile

**Prioritas:** `P0`

**Kenapa penting**  
Backend sudah hidup, tetapi policy deployment production belum tegas: reverse proxy, trusted proxy, public/internal endpoint boundary, dan profile config per environment masih belum final.

**Yang sudah ada**

- FastAPI modular di `src/api/`
- HTTP security middleware aktif
- env settings cukup lengkap
- Docker Compose dasar sudah ada

**Yang perlu dibangun**

- profile config terpisah untuk `development`, `staging`, `production`
- dokumentasi reverse proxy yang benar untuk forwarded headers
- pemisahan endpoint publik vs internal yang benar-benar enforceable
- contoh compose / deployment untuk production-like mode

**File utama**

- `config/settings.py`
- `src/security/security_headers.py`
- `src/api/routes.py`
- `docker-compose.yml`
- `docs/operations.md`

**Definition of done**

- ada mode config production yang jelas
- `TRUSTED_PROXIES` dan internal/public endpoint policy terdokumentasi
- smoke test production-like topology bisa dijalankan

---

### 3. Historical Observability Backend

**Prioritas:** `P0`

**Kenapa penting**  
Dashboard sekarang sudah jujur untuk snapshot runtime, tetapi banyak metrik masih belum persisten. Akibatnya analisis tren harian, incident review, dan alerting jangka menengah masih lemah.

**Yang sudah ada**

- `/metrics/prometheus`
- Model Intelligence dashboard
- realtime simulation observability
- database tables untuk model/version/training/prediction

**Yang perlu dibangun**

- penyimpanan historis untuk latency, hit rate, drift, queue depth, DLQ growth
- retention dan roll-up strategy
- endpoint query historis untuk dashboard operator
- alertable metrics untuk Redis down, worker idle, DLQ naik, drift spike

**File utama**

- `src/observability/`
- `src/api/routes_dashboard.py`
- `src/api/routes_observability.py`
- `src/prefetch/queue.py`
- `docs/operations.md`

**Definition of done**

- operator bisa melihat tren historis, bukan hanya snapshot
- queue depth, retry, DLQ, latency, drift, dan cache hit punya data history
- retention policy jelas

---

### 4. Prefetch Ops Maturity

**Prioritas:** `P1`

**Kenapa penting**  
Worker prefetch sudah ada, tetapi operasi production belum matang tanpa replay DLQ, backpressure, prioritization, dan rate control.

**Yang sudah ada**

- Redis queue
- worker terpisah
- retry dasar
- DLQ dasar
- bukti worker di realtime simulation

**Yang perlu dibangun**

- replay endpoint / admin workflow untuk DLQ
- rate control per service
- backpressure saat Redis atau worker tertinggal
- budgeting prefetch berdasarkan confidence dan latency benefit
- queue metrics yang lebih rinci

**File utama**

- `src/prefetch/queue.py`
- `src/workers/prefetch_worker.py`
- `src/api/route_prefetch.py`
- `src/api/live_simulation_service.py`

**Definition of done**

- operator bisa replay job dari DLQ
- worker tidak overload diam-diam saat traffic naik
- prefetch cost bisa dibatasi dengan policy yang jelas

---

### 5. ML Accuracy Improvement Program

**Prioritas:** `P1`

**Kenapa penting**  
Pipeline ML sudah online, tetapi akurasi live masih sangat bergantung pada pola data. Saat churn tinggi atau validasi terlalu kecil, angka di dashboard bisa terlihat bagus tetapi tidak cukup kuat secara statistik.

**Yang sudah ada**

- full training path + online learning path
- full-training planner dengan quality profile dan time budget
- secure registry
- active model status
- realtime simulation dengan grounded accuracy
- per-key accuracy di simulation

**Yang perlu dibangun**

- evaluasi berbasis dataset replay atau access logs nyata
- calibration loop untuk quality profile vs hardware budget
- feature engineering yang lebih kaya untuk service/key affinity
- acceptance criteria model yang memperhitungkan `top-10` dan sample basis
- tuning workflow untuk threshold prediction dan prefetch policy
- per-key false positive / false negative analysis

**File utama**

- `src/ml/trainer.py`
- `src/ml/predictor.py`
- `src/ml/model.py`
- `src/api/ml_service.py`
- `src/api/live_simulation_service.py`

**Definition of done**

- ada workflow tuning yang repeatable
- operator tahu profile training mana yang cocok untuk hardware dan traffic yang berbeda
- model acceptance tidak lagi hanya "accuracy tinggi", tetapi juga sample basis kuat
- ada evaluasi replay nyata atau semi-nyata yang bisa diulang

---

### 6. Model Governance Across Environments

**Prioritas:** `P1`

**Kenapa penting**  
Registry lokal sudah aman, tetapi governance rilis model lintas environment belum formal. Ini penting kalau model nanti melewati proses review, approval, dan promotion yang lebih ketat.

**Yang sudah ada**

- signing metadata
- provenance dasar
- promote / rollback
- lifecycle logging

**Yang perlu dibangun**

- approval flow antar environment
- release checklist model
- integrasi provenance eksternal seperti commit SHA atau build metadata
- policy siapa yang boleh promote ke production

**File utama**

- `src/ml/model_registry.py`
- `src/api/ml_service.py`
- `src/api/route_ml.py`
- `docs/operations.md`

**Definition of done**

- promotion punya policy dan audit trail yang jelas
- model release punya approval state, bukan hanya tombol promote

---

### 7. Operator Dashboard

**Prioritas:** `P1`

**Kenapa penting**  
Frontend saat ini sudah kuat untuk demo teknis, tetapi operator view untuk penggunaan harian belum benar-benar lengkap.

**Yang sudah ada**

- Dashboard
- Realtime Simulation
- Model Intelligence
- ML Training

**Yang perlu dibangun**

- halaman operator khusus untuk queue, DLQ, Redis health, drift, active model, last training, audit summary
- error handling yang lebih spesifik per komponen
- historical comparison view untuk PSKC vs baseline

**File utama**

- `frontend/src/pages/`
- `frontend/src/components/`
- `src/api/routes_dashboard.py`
- `src/api/routes_observability.py`

**Definition of done**

- operator tidak perlu membuka banyak halaman untuk diagnosis runtime
- queue, drift, model, Redis, dan audit summary terlihat dalam satu alur kerja

---

### 7. Simulation with Real Traffic Replay

**Prioritas:** `P1`

**Kenapa penting**  
Simulation sekarang sudah jauh lebih jujur, tetapi masih synthetic session generator. Untuk pembuktian yang lebih kuat, sistem butuh mode replay dari log akses nyata.

**Yang sudah ada**

- realtime simulation
- grounded accuracy
- L1/L2/KMS trace
- baseline direct KMS

**Yang perlu dibangun**

- input replay dari access logs / captured events
- mapping antara request stream nyata dan simulation session
- privacy-safe sanitization untuk log replay
- hasil replay dibandingkan dengan synthetic benchmark

**File utama**

- `src/api/live_simulation_service.py`
- `src/ml/data_collector.py`
- `scripts/`
- `docs/realtime_simulation.md`

**Definition of done**

- user bisa menjalankan simulation dengan dataset replay nyata
- akurasi live dan prefetch benefit bisa dibuktikan dari trafik real

---

### 8. Security and Admin Hardening

**Prioritas:** `P1`

**Kenapa penting**  
Hardening dasar sudah aktif, tetapi akses admin dan operasi sensitif masih perlu dibatasi lebih rapi untuk deployment nyata.

**Yang sudah ada**

- HTTP security middleware
- rate limiter
- audit log
- IDS

**Yang perlu dibangun**

- auth admin yang konsisten untuk endpoint sensitif
- role separation untuk promote/rollback/replay/admin cache actions
- incident mode atau emergency controls
- key/service scoped policy yang lebih granular

**File utama**

- `src/security/`
- `src/api/route_admin_pipeline.py`
- `src/api/route_security_lifecycle.py`
- `frontend/src/pages/SecurityTesting.jsx`

**Definition of done**

- endpoint sensitif tidak lagi hanya bergantung pada network policy
- ada boundary admin yang jelas dan terdokumentasi

---

### 9. Test Suite Modernization

**Prioritas:** `P1`

**Kenapa penting**  
Repo masih punya campuran test untuk route monolith lama dan arsitektur modular baru. Ini bikin sinyal CI tidak selalu bersih.

**Yang sudah ada**

- focused backend tests untuk trainer, predictor, model intelligence, live simulation, settings
- smoke runtime script

**Yang perlu dibangun**

- refactor suite legacy agar patch point dan path sesuai arsitektur modular
- tambah Docker smoke tests yang bisa masuk CI
- matrix minimal untuk local, Docker, dan monitoring profile

**File utama**

- `tests/`
- `.github/workflows/`
- `scripts/smoke_backend_runtime.py`

**Definition of done**

- test suite inti konsisten dengan arsitektur yang sekarang
- CI tidak bergantung pada test legacy yang sudah out-of-date

---

### 10. Productization and Packaging

**Prioritas:** `P2`

**Kenapa penting**  
Sistem sudah kuat secara teknis, tetapi packaging untuk onboarding tim atau stakeholder masih bisa dipermudah.

**Yang sudah ada**

- README
- docs index
- frontend aktif

**Yang perlu dibangun**

- tutorial end-to-end yang lebih singkat
- sample datasets / seed modes yang konsisten
- operator quickstart dan runbook insiden
- dokumentasi "what to build next" per role: backend, ML, frontend, ops

**File utama**

- `README.md`
- `docs/`
- `scripts/`

**Definition of done**

- orang baru bisa memahami sistem, menjalankan stack, dan memilih next task tanpa membaca seluruh repo

## Saran Praktis Memilih Task Berikutnya

Kalau Anda ingin memilih task berikut dengan cepat:

- Pilih **Production Deployment Profile** jika fokus Anda stabilitas deploy
- Pilih **Historical Observability Backend** jika fokus Anda operasi harian
- Pilih **Prefetch Ops Maturity** jika fokus Anda performa runtime
- Pilih **ML Accuracy Improvement Program** jika fokus Anda kualitas prediksi
- Pilih **Test Suite Modernization** jika fokus Anda CI dan regression safety

## Template Saat Menambah Item Baru

Kalau nanti Anda menambah item ke roadmap ini, pakai format berikut:

```md
### Nama Item

**Prioritas:** `P1`

**Kenapa penting**
...

**Yang sudah ada**
...

**Yang perlu dibangun**
...

**File utama**
...

**Definition of done**
...
```
