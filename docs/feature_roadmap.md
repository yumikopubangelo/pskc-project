# Feature Roadmap PSKC

Backlog pengembangan fitur yang **belum dikerjakan atau belum selesai**.
Untuk fitur yang sudah selesai, lihat [`comprehensive_features.md`](comprehensive_features.md).

---

## Cara Menggunakan Dokumen Ini

- Setiap item menjelaskan **apa yang perlu dibangun**, **mengapa penting**, **file yang terdampak**, dan **definisi selesai**.
- Item memiliki dependensi — jangan dikerjakan paralel sembarangan.
- Prioritas: `P0` = blocker deploy, `P1` = operasional, `P2` = maturitas produk, `P3` = jangka menengah.

---

## Ringkasan Backlog

| Area | Item | Prioritas | Status |
|------|------|-----------|--------|
| **Runtime** | Deployment & topologi reverse proxy | P0 | Belum ada |
| **Runtime** | Production config profile | P0 | Belum ada |
| **Runtime** | Startup dependency policy | P0 | Belum ada |
| **ML — Model** | LSTM input sekuensial (bukan tabular) | P0 | Bug arsitektur |
| **ML — Model** | River tersambung ke `predict_top_n()` | P0 | Terputus |
| **ML — Model** | Adaptive ensemble weights (Markov dinamis) | P1 | Statis 20% |
| **ML — Model** | Stratified train/val split | P1 | Belum ada |
| **ML — Feature** | Fitur N-gram sequence-aware | P1 | Belum ada |
| **ML — Feature** | Fitur kontekstual service embedding | P1 | Belum ada |
| **ML — Feature** | Graph-based features dari Markov matrix | P2 | Belum ada |
| **ML — Feature** | Perbaikan temporal encoding | P2 | Partial |
| **ML — Training** | HPO dengan Optuna | P2 | Belum ada |
| **ML — Training** | Class imbalance handling yang lebih baik | P1 | Partial |
| **ML — Training** | LSTM attention mechanism | P2 | Belum ada |
| **ML — Drift** | Drift characterization (tipe drift) | P1 | Belum ada |
| **ML — Drift** | Drift aktif di request path (runtime integration) | P1 | Belum terhubung |
| **ML — Drift** | Cold-start handling untuk key baru | P1 | Belum ada |
| **ML — Online** | Feedback loop ke River dari event aktual | P1 | Belum ada |
| **ML — Eval** | Per-key accuracy tracking | P2 | Belum ada |
| **ML — Eval** | Prediction confidence estimation | P2 | Belum ada |
| **ML — Eval** | Automated model health check | P2 | Belum ada |
| **ML — Governance** | Approval flow antar stage | P1 | Belum ada |
| **ML — Governance** | Release criteria yang eksplisit | P1 | Belum ada |
| **ML — Governance** | External provenance (commit SHA) | P2 | Belum ada |
| **Data Pipeline** | Validasi kualitas data training | P1 | Partial |
| **Data Pipeline** | Long-term time-series metrics storage | P2 | Belum ada |
| **Security** | Fine-grained ACL per key_id / service_id | P1 | Belum ada |
| **Security** | Token-based auth (bukan hanya API key hardcoded) | P1 | Belum ada |
| **Security** | Multi-tenant key isolation | P2 | Belum ada |
| **Security** | Incident response hooks (emergency mode) | P1 | Belum ada |
| **Auth** | AdminAuthManager terintegrasi ke endpoint guard | P1 | Partial |
| **Observability** | Alert rules (Redis down, DLQ growth, drift, dll.) | P1 | Belum ada |
| **Observability** | Dashboard operator (health, queue, model state) | P2 | Belum ada |
| **Observability** | SLA tracking dashboard | P2 | Belum ada |
| **Observability** | Metrics retention policy + roll-up strategy | P2 | Belum ada |
| **Prefetch** | DLQ replay workflow yang aman | P1 | Partial |
| **Prefetch** | Rate control dan backpressure per service | P1 | Belum ada |
| **Prefetch** | Budgeting dan prioritization per confidence band | P2 | Belum ada |
| **Benchmark** | Dokumentasi metodologi simulasi formal | P1 | Belum ada |
| **Benchmark** | UI integration untuk visualisasi benchmark | P2 | Belum ada |
| **Benchmark** | Confidence interval dan statistical validation | P2 | Belum ada |
| **Benchmark** | Regression gate di CI | P2 | Belum ada |
| **Frontend** | Halaman operator (drift, DLQ, registry, lifecycle) | P1 | Partial |
| **Frontend** | Error handling yang membedakan jenis error | P2 | Partial |
| **Frontend** | Simulasi visualization di dashboard | P2 | Belum ada |
| **Testing** | Integration test untuk core request paths | P1 | Belum ada |
| **Testing** | Topology matrix test (local, Docker, proxy) | P2 | Belum ada |
| **Testing** | Failure-path suite (Redis down, drift trigger, dll.) | P2 | Belum ada |
| **Deploy** | Multi-environment manifest (staging, production) | P3 | Belum ada |
| **Deploy** | Secret management (bukan hanya `.env`) | P2 | Belum ada |

---

## Area 1 — Machine Learning: Model

### ML-1.1 Perbaiki LSTM agar Menerima Input Sekuensial

**Prioritas:** `P0`

**Masalah:**
LSTM saat ini menerima tensor tabular `(batch, 30_features)` — identik dengan input Random Forest. Kemampuan temporal LSTM tidak dimanfaatkan sama sekali, sehingga LSTM hanya berfungsi sebagai RF kedua yang lebih lambat.

**Yang perlu dikerjakan:**
- Ubah input LSTM menjadi `(batch, sequence_length=10, features=30)` menggunakan `context_window` yang sudah di-extract di `trainer.py`
- Tambahkan/refactor layer `LSTM → Dropout → Dense → Softmax` untuk prediksi key
- Update training loop di `trainer.py` agar melempar data sekuensial ke LSTM, bukan tabular flatten
- Naikkan bobot LSTM di ensemble (dari ~0% efektif ke 25–30%)
- Pastikan model lama tetap bisa di-load (backward compatibility via version check)

**File terdampak:**
- [`src/ml/incremental_model.py`](src/ml/incremental_model.py)
- [`src/ml/trainer.py`](src/ml/trainer.py)

**Definisi selesai:**
- LSTM menerima input 3D, bukan 2D
- Accuracy LSTM lebih tinggi dari RF pada pola temporal dalam test
- Training pipeline tidak rusak untuk data non-sekuensial

**Potensi gain:** +15–30% accuracy pada pola temporal

---

### ML-1.2 Sambungkan River ke Jalur Prediksi Utama

**Prioritas:** `P0`

**Masalah:**
`RiverOnlineLearner` diimplementasikan dan dilatih, tetapi tidak dipanggil di `predict_top_n()`. Semua kerja online learning diabaikan saat prediksi.

**Yang perlu dikerjakan:**
- Ikutkan River sebagai komponen ke-4 di `EnsembleModel.predict_top_n()`
- Bobot awal River: 15%, adaptif berdasarkan akurasi
- Feedback loop: setiap key yang benar-benar diakses di-`partial_fit` ke River secara async via `ml_worker`
- Fallback aman: jika River error, ensemble tetap berjalan tanpa River

**File terdampak:**
- [`src/ml/river_online_learning.py`](src/ml/river_online_learning.py)
- [`src/ml/incremental_model.py`](src/ml/incremental_model.py)
- [`src/workers/ml_worker.py`](src/workers/ml_worker.py)

**Definisi selesai:**
- River ikut berkontribusi dalam prediksi akhir `predict_top_n()`
- `partial_fit` dipanggil async setiap ada akses key aktual
- Error River tidak propagate ke request path

**Potensi gain:** +5–10% accuracy pada pola terkini

---

### ML-1.3 Adaptive Ensemble Weights (Markov Dinamis)

**Prioritas:** `P1`

**Masalah:**
Bobot Markov terkunci statis di 20% tidak peduli performanya. Jika Markov buruk, dia tetap dapat 20%.

**Yang perlu dikerjakan:**
- Extend `EnsembleWeightTracker` untuk tracking sliding-window accuracy Markov dan River
- Update bobot Markov dan River setiap N prediksi (default N=500) dengan normalisasi softmax
- Jika akurasi model < threshold minimum → kurangi bobot otomatis
- Log weight change ke observability layer

**File terdampak:**
- [`src/ml/incremental_model.py`](src/ml/incremental_model.py)

**Definisi selesai:**
- Semua 4 model (RF, LSTM, Markov, River) memiliki bobot dinamis
- Weight history bisa di-query via API

**Potensi gain:** +5–10% accuracy

---

### ML-1.4 Stratified Train/Val Split

**Prioritas:** `P1`

**Masalah:**
Split temporal murni 70/30 tidak menjaga distribusi kelas — key yang jarang bisa absen dari val set sehingga metrik validasi menipu.

**Yang perlu dikerjakan:**
- Implementasi stratified split yang mempertahankan proporsi per key di train dan val
- Warning jika ada key dengan < 10 sample di training set
- Naikkan `min_samples` dari 100 ke 300–500

**File terdampak:**
- [`src/ml/trainer.py`](src/ml/trainer.py)

**Definisi selesai:**
- Val set selalu merepresentasikan semua key yang ada di train set
- Warning tersedia di log jika key under-represented

**Potensi gain:** +3–5% accuracy (terutama key jarang)

---

## Area 2 — Machine Learning: Feature Engineering

### ML-2.1 Fitur Sequence-Aware (N-gram)

**Prioritas:** `P1`

**Masalah:**
Fitur saat ini tidak menangkap urutan akses secara eksplisit. Bigram dan trigram patterns diabaikan.

**Yang perlu dikerjakan:**
- Bigram frequency: `P(key_b | key_a)` untuk top-50 key pairs
- Trigram entropy: ketidakpastian dari 3 akses terakhir
- Autocorrelation inter-arrival (deteksi pola periodik)
- Position-in-cycle: posisi event dalam pola berulang yang terdeteksi

**File terdampak:**
- [`src/ml/data_collector.py`](src/ml/data_collector.py)
- [`src/ml/trainer.py`](src/ml/trainer.py)

**Potensi gain:** +5–10% accuracy

---

### ML-2.2 Fitur Kontekstual Service Embedding

**Prioritas:** `P1`

**Masalah:**
Service hanya dihitung agregat. Identitas service tidak direpresentasikan secara eksplisit.

**Yang perlu dikerjakan:**
- `service_id` embedding: one-hot top-N service, bucket sisanya sebagai "other"
- `time_since_service_last_access`: detik sejak service ini terakhir akses key ini
- `service_key_affinity_score`: frekuensi service ini akses key tertentu

**Potensi gain:** +3–5% accuracy

---

### ML-2.3 Graph-Based Features dari Markov Transition Matrix

**Prioritas:** `P2`

**Masalah:**
Markov menyimpan transition matrix tetapi informasinya tidak dimanfaatkan sebagai fitur untuk RF/LSTM.

**Yang perlu dikerjakan:**
- `in_degree`: jumlah key yang mengarah ke key ini
- `out_degree`: jumlah key yang biasanya diakses setelah key ini
- `pagerank_score`: "kepentingan" key dalam access graph
- `key_community_id`: cluster ID dari community detection

**File terdampak:**
- [`src/ml/pattern_analyzer.py`](src/ml/pattern_analyzer.py)

**Potensi gain:** +4–6% accuracy

---

### ML-2.4 Perbaiki Temporal Encoding

**Prioritas:** `P2`

**Masalah:**
Encoding jam/hari hanya sin/cos dasar. Tidak ada pola transisi jam atau konteks minggu.

**Yang perlu dikerjakan:**
- `hour_transition_frequency`: frekuensi historis akses saat jam berganti
- `day_of_month` cyclical, `week_of_year` cyclical
- `is_business_hour`: boolean
- `minutes_from_hour_boundary`: posisi dalam jam berjalan

**Potensi gain:** +2–3% accuracy

---

## Area 3 — Machine Learning: Training & Model Improvements

### ML-3.1 Hyperparameter Optimization dengan Optuna

**Prioritas:** `P2`

**Masalah:**
RF menggunakan 100 trees dan depth tetap — belum tentu optimal untuk distribusi data yang berubah-ubah.

**Yang perlu dikerjakan:**
- Integrasikan Optuna (budget: max 10 menit per training run)
- Parameter yang di-tune: `n_estimators`, `max_depth`, `min_samples_split`, `feature_selection_k`, LSTM hidden size
- Simpan best params ke config, dipakai pada scheduled training berikutnya
- Hanya jalan saat scheduled training, tidak saat drift-triggered training

**File baru:** [`src/ml/hpo_optuna.py`](src/ml/hpo_optuna.py)

**Potensi gain:** +3–5% accuracy

---

### ML-3.2 Perbaiki Class Imbalance Handling

**Prioritas:** `P1`

**Masalah:**
Balancing ke median class size bisa menipu metrik validasi dan menyebabkan overfit pada key jarang.

**Yang perlu dikerjakan:**
- Ganti ke `class_weight='balanced'` di RF (weighted loss, bukan oversampling)
- Hanya oversample class dengan sample < 10% dari mean
- Stratified sampling di `DataBalancer`

**File terdampak:**
- [`src/ml/model_improvements.py`](src/ml/model_improvements.py)

**Potensi gain:** +3–5% accuracy (metrik lebih jujur)

---

### ML-3.3 Attention Mechanism pada LSTM

**Prioritas:** `P2` *(dependensi: ML-1.1 harus selesai dulu)*

**Yang perlu dikerjakan:**
- Self-attention layer setelah LSTM output untuk meningkatkan kemampuan menangkap dependensi jangka panjang
- Attention weights bisa divisualisasikan untuk debugging
- Multi-head attention opsional jika ukuran model memungkinkan

**Potensi gain:** +3–5% accuracy pada pola temporal kompleks

---

## Area 4 — Machine Learning: Drift & Online Learning

### ML-4.1 Drift Characterization (Klasifikasi Tipe Drift)

**Prioritas:** `P1`

**Masalah:**
Drift hanya terdeteksi ya/tidak. Tidak ada klasifikasi tipe sehingga strategi respons tidak bisa dibedakan.

**Tipe drift yang perlu dibedakan:**

| Tipe | Karakteristik | Respons |
|------|--------------|---------|
| Gradual | Penurunan perlahan selama beberapa jam | Adjust learning rate |
| Sudden | Perubahan mendadak dalam satu window | Retrain segera dengan data terbaru |
| Recurring | Pola musiman/periodik | Gunakan seasonal model historis |
| Emerging keys | Key baru muncul yang tidak ada di training | Cold-start handling khusus |

**File terdampak:**
- [`src/ml/pattern_analyzer.py`](src/ml/pattern_analyzer.py)
- [`src/ml/auto_retrainer.py`](src/ml/auto_retrainer.py)

---

### ML-4.2 Drift Detection Aktif di Request Path

**Prioritas:** `P1`

**Masalah:**
`DriftDetector` sudah diimplementasikan di `trainer.py` tetapi tidak dipanggil di request path `/keys/access`. Drift hanya terdeteksi saat training cycle, bukan saat runtime.

**Yang perlu dikerjakan:**
- Update statistik EWMA setiap event akses (non-blocking, via background queue)
- Saat drift flag aktif, ubah behavior prediksi ke mode konservatif (fallback ke hot keys)
- Tiga status drift terimplementasi di runtime: `stable` → `warning` → `active_drift`
- Transisi antar status terekam di audit log
- Ekspor status drift ke Prometheus: `pskc_drift_status`, `pskc_drift_score`

**File terdampak:**
- [`src/ml/predictor.py`](src/ml/predictor.py)
- [`src/ml/trainer.py`](src/ml/trainer.py)
- [`src/observability/prometheus_exporter.py`](src/observability/prometheus_exporter.py)
- [`config/settings.py`](config/settings.py)

**Definisi selesai:**
- Drift event terekam di audit log saat status berubah
- Model fallback beroperasi saat `active_drift`
- Status drift tampil di `/ml/drift` endpoint dan Prometheus

---

### ML-4.3 Cold-Start Handling untuk Key Baru

**Prioritas:** `P1`

**Masalah:**
Key baru tidak punya history — akurasi sangat rendah sampai 50–100 event terkumpul. Tidak ada fallback bermakna.

**Yang perlu dikerjakan:**
- Deteksi otomatis key baru (belum ada di training data)
- Similarity-based fallback: cari key paling mirip secara fitur (cosine distance)
- Pinjam distribusi prediksi dari key serupa selama cold-start phase
- Tambahkan flag `is_cold_start: true` di response prediksi
- River model sebagai learner utama untuk key baru (belajar lebih cepat dari RF)

**Potensi gain:** +5–8% accuracy pada key baru

---

### ML-4.4 Feedback Loop ke River dari Event Aktual

**Prioritas:** `P1`

**Masalah:**
River tidak pernah mendapat konfirmasi prediksi yang benar — tidak belajar dari kesalahan di production.

**Yang perlu dikerjakan:**
- Cache prediksi terakhir per session/request
- Saat key berikutnya diakses, bandingkan dengan prediksi sebelumnya
- Panggil `river_model.partial_fit(X_prev, y_actual)` secara async via `ml_worker`
- Rate limiting untuk partial_fit agar tidak membebani worker

**File terdampak:**
- [`src/ml/river_online_learning.py`](src/ml/river_online_learning.py)
- [`src/workers/ml_worker.py`](src/workers/ml_worker.py)

---

## Area 5 — Machine Learning: Evaluasi & Observabilitas

### ML-5.1 Per-Key Accuracy Tracking

**Prioritas:** `P2`

**Masalah:**
Hanya ada global top-1 dan top-10 accuracy. Tidak diketahui key mana yang prediksinya buruk.

**Yang perlu dikerjakan:**
- Confusion matrix ringkas (top-50 key) per training run
- Tracking per-key accuracy: hot keys (>1000 akses), medium, cold
- Expose via endpoint `GET /ml/metrics/per-key`

**File baru/terdampak:** [`src/ml/evaluation.py`](src/ml/evaluation.py)

---

### ML-5.2 Prediction Confidence Estimation

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Hitung ensemble variance: jika RF, LSTM, Markov sepakat → confidence tinggi
- Temperature scaling untuk kalibrasi probabilitas
- Expose `confidence_score` di response prediksi
- Abstention threshold: jika confidence < X, tambahkan flag `low_confidence`

---

### ML-5.3 Automated Model Health Check

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Cek rutin setiap 1 jam: bandingkan prediksi vs actual dari event yang masuk ke `data_collector`
- Jika online accuracy drop > 10% → trigger drift check segera
- Alert ke log dan Prometheus jika model health buruk

---

## Area 6 — Machine Learning: Governance & Deployment Safety

### ML-6.1 Approval Flow Antar Stage

**Prioritas:** `P1`

**Masalah:**
Promotion model bisa dilakukan langsung tanpa approval. Tidak ada gate antara `development → staging → production`.

**Yang perlu dikerjakan:**
- Workflow approval: promotion perlu dikonfirmasi dengan alasan dan authorizer
- Release criteria yang eksplisit: threshold accuracy minimum, volume data minimum, tidak ada integrity issue
- Log approval trail sebagai bagian dari lifecycle event

**File terdampak:**
- [`src/ml/model_registry.py`](src/ml/model_registry.py)
- [`src/api/route_ml.py`](src/api/route_ml.py)

---

### ML-6.2 External Provenance (Commit SHA & Environment)

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Ikat artefak model ke git commit SHA saat training
- Simpan metadata environment training (Python version, package versions)
- Tambahkan ke model signature/manifest

**File terdampak:**
- [`src/ml/trainer.py`](src/ml/trainer.py)
- [`src/ml/model_registry.py`](src/ml/model_registry.py)

---

### ML-6.3 Registry Retention & Cleanup Policy

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Policy: jumlah maksimum versi yang disimpan per model
- Perlindungan: versi active/production tidak boleh dihapus sembarangan
- Script cleanup otomatis dengan dry-run mode

---

## Area 7 — Data Pipeline

### DP-1 Validasi Kualitas Data Training

**Prioritas:** `P1`

**Masalah:**
Validasi data hanya di level event individual. Tidak ada validasi kualitas dataset sebelum training dimulai.

**Yang perlu dikerjakan:**
- Cek distribusi label sebelum training: warning jika satu key dominasi >50%
- Cek coverage: minimal X unique key ada di dataset
- Cek temporal coverage: data mencakup distribusi jam/hari yang cukup
- Reject training jika data quality score < threshold

**File terdampak:**
- [`src/ml/trainer.py`](src/ml/trainer.py)
- [`src/ml/data_collector.py`](src/ml/data_collector.py)

---

### DP-2 Long-Term Time-Series Metrics Storage

**Prioritas:** `P2`

**Masalah:**
Metrics hanya disimpan di Redis dengan retensi 24 jam. Tidak ada cara melihat tren minggu atau bulan lalu.

**Yang perlu dikerjakan:**
- Pilihan: Prometheus remote write, InfluxDB, atau TimescaleDB
- Metrics agregasi/roll-up untuk historical analysis (hourly → daily → weekly)
- Dashboard multi-week trend di frontend
- Retention policy yang terdokumentasi

**File terdampak:**
- [`src/observability/metrics_persistence.py`](src/observability/metrics_persistence.py)
- [`src/observability/prometheus_exporter.py`](src/observability/prometheus_exporter.py)

---

## Area 8 — Security & Auth

### SEC-1 Fine-Grained ACL per key_id / service_id

**Prioritas:** `P1`

**Masalah:**
Access control saat ini berbasis role global. Tidak ada ACL yang menyatakan "service X boleh akses key Y".

**Yang perlu dikerjakan:**
- ACL rule: `(service_id, key_id_prefix) → allowed/denied`
- Enforcement di `SecureCacheManager.secure_get()` dan `secure_set()`
- Audit log jika service mencoba akses di luar scope
- Admin endpoint untuk manage ACL rules

**File terdampak:**
- [`src/security/access_control.py`](src/security/access_control.py)
- [`src/cache/encrypted_store.py`](src/cache/encrypted_store.py)
- [`src/api/route_admin_pipeline.py`](src/api/route_admin_pipeline.py)

---

### SEC-2 Token-Based Auth yang Proper

**Prioritas:** `P1`

**Masalah:**
Auth admin saat ini menggunakan hardcoded API key untuk dev. Tidak ada token lifecycle (expiry, revocation, rotation).

**Yang perlu dikerjakan:**
- Token-based auth: JWT atau opaque token dengan expiry
- Token revocation list
- Token rotation tanpa downtime
- Integration test untuk expired/revoked token

**File terdampak:**
- [`src/api/admin_control_plane.py`](src/api/admin_control_plane.py)
- [`src/security/access_control.py`](src/security/access_control.py)

---

### SEC-3 AdminAuthManager Terintegrasi ke Semua Endpoint Guard

**Prioritas:** `P1`

**Masalah:**
`AdminAuthManager` sudah ada di `admin_control_plane.py` tetapi tidak semua endpoint sensitif menggunakannya secara konsisten.

**Yang perlu dikerjakan:**
- Audit semua endpoint yang butuh auth
- Terapkan `AdminAuthManager` dependency di semua endpoint sensitif secara konsisten
- Test: request tanpa token ke endpoint sensitif harus 401/403

---

### SEC-4 Multi-Tenant Key Isolation

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Namespace key per tenant di cache (prefix strategy)
- Isolasi enkripsi: tenant berbeda tidak bisa dekripsi key milik tenant lain
- Metrics per-tenant

---

### SEC-5 Incident Response Hooks (Emergency Mode)

**Prioritas:** `P1`

**Yang perlu dikerjakan:**
- `POST /admin/security/emergency-purge` — purge semua key dari cache satu service
- `POST /admin/security/denylist-service` — blokir service dari akses
- Emergency mode: throttle semua akses ke rate sangat rendah
- Semua operasi ini terekam di audit log dengan justifikasi

**File terdampak:**
- [`src/api/admin_control_plane.py`](src/api/admin_control_plane.py)
- [`src/security/intrusion_detection.py`](src/security/intrusion_detection.py)

---

## Area 9 — Observability

### OBS-1 Alert Rules

**Prioritas:** `P1`

**Masalah:**
Tidak ada alert rule. Operator tidak tahu ada masalah kecuali aktif memantau.

**Alert yang perlu diimplementasikan:**

| Kondisi | Severity | Channel |
|---------|---------|---------|
| Redis unavailable > 30 detik | Critical | Log + Prometheus alert |
| DLQ size > threshold | Warning | Log + Prometheus |
| Worker stagnation (no heartbeat > 60s) | Critical | Log + Prometheus |
| Model integrity failure saat load | Critical | Log + audit |
| Drift status = `active_drift` | Warning | Log + Prometheus |
| Audit log recovery event | Warning | Log |
| Cache hit rate drop > 20% | Warning | Prometheus |

**File terdampak:**
- [`src/observability/prometheus_exporter.py`](src/observability/prometheus_exporter.py)
- [`src/prefetch/queue.py`](src/prefetch/queue.py)
- [`src/workers/prefetch_worker.py`](src/workers/prefetch_worker.py)

---

### OBS-2 Dashboard Operator

**Prioritas:** `P2`

**Masalah:**
Dashboard frontend saat ini demo-focused. Tidak ada operator view yang fokus ke health sistem.

**Yang perlu dikerjakan:**
- Panel: status Redis, worker heartbeat, DLQ depth, request rate
- Panel: model state (stage, version, last accuracy, drift status)
- Panel: cache hit rate trend, latency histogram
- Panel: security — blocked IPs, IDS alert rate
- Gunakan data dari Prometheus/MetricsPersistence

**File terdampak:**
- [`frontend/src/pages/`](frontend/src/pages/)
- [`frontend/src/utils/apiClient.js`](frontend/src/utils/apiClient.js)

---

### OBS-3 Metrics Retention & Roll-up Strategy

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Audit log: rotation policy (max size, age-based cleanup)
- Model lifecycle log: tetap tersimpan (tidak di-rotate)
- Metric snapshot: roll-up hourly → daily dengan aggregation
- Konfigurasi retention via env var, bukan hardcode

---

## Area 10 — Prefetch Orchestration

### PF-1 DLQ Replay Workflow yang Aman

**Prioritas:** `P1`

**Masalah:**
Endpoint `/prefetch/replay` ada tetapi tidak memiliki safety guard. Job berbahaya bisa di-replay tanpa filter.

**Yang perlu dikerjakan:**
- Filter replay: hanya item dengan `failure_reason` yang diizinkan
- Audit trail untuk setiap replay manual
- Dry-run mode: tampilkan apa yang akan di-replay tanpa eksekusi
- Rate limit untuk replay (tidak boleh flood worker)

**File terdampak:**
- [`src/prefetch/queue.py`](src/prefetch/queue.py)
- [`src/api/route_prefetch.py`](src/api/route_prefetch.py)

---

### PF-2 Rate Control dan Backpressure per Service

**Prioritas:** `P1`

**Masalah:**
Tidak ada batasan prefetch per service. Satu service bisa menguras kapasitas worker.

**Yang perlu dikerjakan:**
- Token bucket per service ID untuk enqueue prefetch job
- Max queue depth per service (configurable)
- Backpressure: jika worker tertinggal terlalu jauh, drop low-confidence jobs
- Metrics: queue depth per service di Prometheus

**File terdampak:**
- [`src/prefetch/queue.py`](src/prefetch/queue.py)
- [`src/api/ml_service.py`](src/api/ml_service.py)

---

### PF-3 Budgeting dan Prioritization per Confidence Band

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Kategorikan prefetch job: high confidence (>80%), medium (50–80%), low (<50%)
- Budget: X% kapasitas worker untuk high, Y% untuk medium, Z% untuk low
- Low confidence jobs dibuang saat queue penuh
- Metrics per confidence band

---

## Area 11 — Runtime & Deployment

### RT-1 Reference Deployment dengan Reverse Proxy

**Prioritas:** `P0`

**Masalah:**
Stack Docker berjalan tapi tidak ada panduan deployment realistis dengan reverse proxy.

**Yang perlu dikerjakan:**
- Contoh topologi `nginx/traefik → api → redis/prefetch-worker`
- Dokumentasikan `TRUSTED_PROXIES`, header forwarding, HSTS/CSP behavior
- Pisahkan contoh dev vs production
- README untuk deployment yang tidak ambigu

**File terdampak:**
- [`docker-compose.yml`](docker-compose.yml)
- [`docs/operations.md`](docs/operations.md)

---

### RT-2 Production Config Profile

**Prioritas:** `P0`

**Masalah:**
Konfigurasi saat ini lebih dekat ke development (timeout longgar, rate limit permisif, debug mode).

**Yang perlu dikerjakan:**
- Preset production untuk: timeout, rate limit, secret handling, log level, retention
- Dokumentasi nilai yang direkomendasikan per variabel
- Env validation saat startup: panic jika env production tapi `APP_ENV=development`

**File terdampak:**
- [`config/settings.py`](config/settings.py)
- [`docker-compose.yml`](docker-compose.yml)

---

### RT-3 Startup Dependency Policy

**Prioritas:** `P0`

**Masalah:**
Policy saat startup tidak jelas — mana yang fail-open, mana yang fail-closed.

**Yang perlu dikerjakan:**
- Dokumentasikan policy per dependency:
  - Redis: fail-closed (API tidak bisa jalan tanpa Redis)
  - Audit log: fail-open (tetap jalan tapi alert)
  - Model registry: fail-open (jalan tanpa ML, prediksi dinonaktifkan)
  - FIPS self-test: fail-closed (tidak bisa jalan jika KAT gagal)
- Readiness endpoint `GET /ready` harus benar-benar cek semua dependency
- Test startup dengan setiap dependency dimatikan satu per satu

**File terdampak:**
- [`src/runtime/bootstrap.py`](src/runtime/bootstrap.py)
- [`src/api/route_health.py`](src/api/route_health.py)

---

### RT-4 Multi-Environment Manifests

**Prioritas:** `P3`

**Yang perlu dikerjakan:**
- `docker-compose.override.yml` untuk dev (volume mounts, debug ports)
- `docker-compose.staging.yml` dengan resource limits
- `docker-compose.production.yml` template (tanpa hardcoded secrets)
- Dokumentasi cara switch antar environment

---

### RT-5 Secret Management yang Lebih Aman

**Prioritas:** `P2`

**Masalah:**
Secrets hanya via `.env` file. Tidak ada integrasi ke secret manager.

**Yang perlu dikerjakan:**
- Dokumentasikan cara integrasi ke Docker secrets, Vault, atau AWS Secrets Manager
- Minimal: contoh docker-compose yang menggunakan Docker secrets (bukan env var plain)
- Validasi: pastikan secrets tidak ter-log atau ter-expose di health endpoint

---

## Area 12 — Benchmark Validation

### BM-1 Dokumentasi Metodologi Formal

**Prioritas:** `P1`

**Masalah:**
Simulasi menghasilkan angka bagus tapi metodologi tidak terdokumentasi secara formal. Tidak jelas bagaimana parameter diterjemahkan ke simulasi.

**Yang perlu dikerjakan:**
- Jelaskan secara eksplisit bagaimana parameter (latency distribution, cache sizes, Pareto ratio) dipilih
- Catatan asumsi dan batasan model log-normal
- Perbarui `simulation/references/README.md` dengan cara mengutip hasil

---

### BM-2 Confidence Interval dan Statistical Validation

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Jalankan simulasi N kali (N=30) dan hitung confidence interval 95%
- Significance testing untuk klaim latency improvement
- Dokumentasikan sample size dan distribusi asumsi

---

### BM-3 Regression Gate di CI

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Tambahkan smoke benchmark ke pipeline CI
- Gagalkan CI jika latency improvement turun > 10% dari baseline
- Perbarui `.github/workflows/` dengan benchmark validation step

---

### BM-4 UI Integration Benchmark Visualization

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Halaman simulasi di frontend: pilih skenario, jalankan, lihat hasil
- Comparison chart PSKC vs baseline yang interaktif
- Simpan historical comparison results

---

## Area 13 — Frontend

### FE-1 Halaman Operator

**Prioritas:** `P1`

**Masalah:**
Tidak ada halaman yang khusus untuk operator memonitor state sistem.

**Yang perlu dikerjakan:**
- Halaman Model Registry: list versions, promote/rollback UI
- Halaman ML Lifecycle: history training, accuracy trend
- Halaman Prefetch: queue depth, DLQ items, replay UI
- Halaman Audit: recent events, intrusion alerts
- Status drift EWMA: current state, history

**File terdampak:**
- [`frontend/src/pages/`](frontend/src/pages/)
- [`frontend/src/utils/apiClient.js`](frontend/src/utils/apiClient.js)

---

### FE-2 Error Handling yang Membedakan Jenis Error

**Prioritas:** `P2`

**Masalah:**
Saat ini error dari backend tidak dibedakan di UI — semua terlihat sama.
****
**Yang perlu dikerjakan:**
- Bedakan di UI: `no data`, `backend down`, `security denied`, `worker lag`, `model not ready`
- Tampilkan status yang jelas dengan aksi yang bisa dilakukan user
- Retry logic dengan exponential backoff di API client

---

### FE-3 Simulasi Visualization di Dashboard

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Integrasi hasil simulasi ke frontend dashboard
- Chart: latency comparison, cache hit rate, KMS reduction
- Tombol "Run Simulation" dari UI dengan progress indicator

---

## Area 14 — Testing & CI

### TEST-1 Integration Test Core Request Paths

**Prioritas:** `P1`

**Masalah:**
Belum ada integration test yang menguji alur lengkap dari request masuk sampai response keluar.

**Yang perlu dikerjakan:**
- Test `/keys/access`: cache miss → KMS fetch → cache store → response
- Test `/keys/access`: cache hit L1 → langsung response
- Test `/keys/access` dengan Redis down (fail-open behavior)
- Test `/ml/retrain` → training selesai → model tersimpan

---

### TEST-2 Topology Matrix Test

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Test di local runtime (tanpa Docker)
- Test di Docker runtime (semua container)
- Test dengan monitoring profile (Prometheus + Grafana aktif)
- Test dengan proxy di depan API

---

### TEST-3 Failure-Path Suite

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Redis unavailable saat startup
- Redis unavailable saat runtime (setelah startup sukses)
- Audit log tidak bisa ditulis
- Model integrity failure saat load
- DLQ backlog (worker tidak bisa consume)
- Drift detection trigger (sengaja inject distribusi berbeda)

---

### TEST-4 Benchmark Regression Gate

**Prioritas:** `P2`

**Yang perlu dikerjakan:**
- Baseline latency test (P50, P95, P99)
- Prefetch throughput test
- Cache hit rate minimal: harus ≥ X% setelah warmup
- Gagal CI jika hasil di bawah threshold

---

## Urutan Implementasi yang Direkomendasikan

Urutan berdasarkan dependensi dan impact tertinggi untuk tim kecil:

**Blok 1 — Runtime & Security Foundation (P0)**
1. RT-1: Reference deployment dengan reverse proxy
2. RT-2: Production config profile
3. RT-3: Startup dependency policy
4. SEC-3: AdminAuthManager konsisten di semua endpoint

**Blok 2 — ML Critical Fixes (P0–P1)**
5. ML-1.1: LSTM input sekuensial ← bug arsitektur terbesar
6. ML-1.2: River tersambung ke predict_top_n ← online learning terbuang sia-sia
7. ML-4.2: Drift detection aktif di request path ← konsistensi paper
8. ML-4.3: Cold-start handling
9. ML-1.3: Adaptive ensemble weights
10. ML-1.4: Stratified train/val split

**Blok 3 — Operasional (P1)**
11. OBS-1: Alert rules
12. PF-1: DLQ replay aman
13. PF-2: Rate control prefetch per service
14. SEC-1: Fine-grained ACL
15. SEC-5: Incident response hooks
16. ML-6.1: Approval flow model
17. TEST-1: Integration test core paths

**Blok 4 — Feature Engineering ML (P1–P2)**
18. ML-2.1: Fitur N-gram
19. ML-2.2: Fitur service embedding
20. ML-3.2: Class imbalance perbaikan
21. ML-4.1: Drift characterization
22. ML-4.4: Feedback loop River

**Blok 5 — Maturitas Produk (P2)**
23. ML-5.1–5.3: Evaluasi per-key, confidence, health check
24. DP-2: Long-term metrics storage
25. OBS-2: Dashboard operator
26. FE-1: Halaman operator
27. BM-1–3: Dokumentasi dan validasi benchmark
28. TEST-2–4: Topology matrix dan failure tests

**Blok 6 — Advanced (P2–P3)**
29. ML-2.3: Graph-based features
30. ML-3.1: HPO Optuna
31. ML-3.3: LSTM attention
32. RT-4: Multi-environment manifests
33. SEC-4: Multi-tenant isolation

---

## Matriks Konsistensi Paper vs Roadmap

| Klaim di Paper | Item Roadmap | Status |
|----------------|-------------|--------|
| Ensemble LSTM+RF+Markov aktif | ML-1.1, ML-1.3 | ⚠️ LSTM tidak benar-benar temporal |
| Online learning (River) aktif | ML-1.2, ML-4.4 | ⚠️ Terhubung tapi tidak di jalur prediksi |
| Concept drift EWMA terimplementasi | ML-4.2 | ⚠️ Ada di kode, belum aktif di runtime |
| Rotasi kunci tanpa downtime | Selesai | ✅ Aktif |
| Reduksi latensi 86% terverifikasi | BM-1, BM-2 | ⚠️ Simulasi 61.6%, metodologi belum formal |
| AES-256-GCM cache enkripsi | Selesai | ✅ Aktif |
| Prefetch prediktif aktif | PF-1, PF-2 | ✅ Aktif, maturasi ongoing |
| Tamper-evident audit HMAC chain | Selesai | ✅ Aktif |
| TTL dinamis berbasis pola akses | Selesai | ✅ Aktif |

---

## Dokumen Terkait

- [comprehensive_features.md](comprehensive_features.md) — Inventaris fitur yang sudah selesai
- [project_status.md](project_status.md) — Ringkasan status proyek
- [architecture.md](architecture.md) — Arsitektur detail
- [security_model.md](security_model.md) — Model keamanan
- [simulation_and_ml.md](simulation_and_ml.md) — Detail ML dan simulasi
- [operations.md](operations.md) — Panduan operasional
