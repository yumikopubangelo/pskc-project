# Simulation and ML

Dokumen ini menjelaskan bagian simulasi dan machine learning di repository PSKC, termasuk apa yang benar-benar bisa dijalankan saat ini dan apa yang masih perlu disatukan.

Jika Anda ingin memahami arti metrik di halaman realtime simulation, baca juga [realtime_simulation.md](realtime_simulation.md).

## Ruang Lingkup

Ada dua dunia yang berbeda tetapi sekarang sudah saling terhubung lewat API:

1. `simulation/` dan `scripts/` di Python untuk benchmark, data generation, dan training
2. halaman simulasi dan ML di frontend yang memanggil endpoint backend nyata

Keduanya tetap punya peran yang berbeda, tetapi frontend tidak lagi memakai dataset demo lokal untuk simulation dan status ML utama.

## Simulasi Backend Python

### Entry point utama

`simulation/runner.py`

Contoh command:

```powershell
python simulation/runner.py --scenario all
python simulation/runner.py --scenario spotify
python simulation/runner.py --scenario amazon --requests 2000
python simulation/runner.py --scenario netflix --requests 2000
python simulation/runner.py --scenario dynamic --requests 2000
python simulation/runner.py --scenario coldstart
```

### Skenario yang tersedia

| Skenario | File | Fokus | Sumber Referensi |
|----------|------|-------|------------------|
| SIAKAD SSO | `simulation/scenarios/siakad_sso.py` | Portal Akademik PT (single tenant), peak KRS/UAS | JSiI Vol.10 No.1 (2023); MDPI App.Sci. 15(22) (2025) |
| SEVIMA Siakadcloud | `simulation/scenarios/sevima_cloud.py` | Multi-tenant cloud, >900 PT Indonesia | Data resmi SEVIMA (2024) |
| PDDikti | `simulation/scenarios/pddikti_auth.py` | Skala nasional, >4.900 PT | Kemdikbudristek (2024) |
| Dynamic production | `simulation/scenarios/dynamic_production.py` | Perubahan beban kerja dan failure pattern campuran | Simulasi berbasis parameter dinamis |
| Cold start | `simulation/engines/cold_start_simulator.py` | Fase warmup, learning, mature dengan EWMA concept drift | Analisis ML lifecycle |

### Sumber parameter

Lihat:

- `simulation/parameters/*.json`
- `simulation/references/README.md`
- `simulation/references/sources.bib`

## Script Pendukung Data dan Benchmark

### 1. Seed data sintetis

```powershell
python scripts/seed_data.py
```

Output default masuk ke `data/raw/`.

### 2. Generate training data dari skenario

```powershell
python scripts/generate_training_data.py --scenario all --samples 5000
```

Output default:

- `data/training/pskc_training_data.json`

Script ini lebih cocok dipakai daripada generator data ad-hoc lama karena distribusinya lebih dekat ke skenario simulasi.

### 3. Training model

```powershell
python scripts/train_model.py --data data/training/pskc_training_data.json
```

Script training melakukan hal berikut:

- load data atau generate synthetic fallback
- split temporal 70/15/15
- ekstraksi fitur dengan `FeatureEngineer`
- train RandomForest dan evaluasi train/val/test
- bungkus hasil training ke `EnsembleModel` yang kompatibel dengan runtime
- simpan artefak aman `.pskc.json` melalui `ModelRegistry`
- update checksum manifest dan active version registry

### 4. Benchmark baseline vs PSKC

```powershell
python scripts/benchmark.py --all
```

### 5. Benchmark Validator (Statistical Validation)

```powershell
python simulation/benchmark_validator.py --runs 10 --seed 42 --scenario spotify
```

**Fitur:**
- Reproducibility dengan seed control
- Validasi statistik formal:
  - Confidence intervals
  - Hypothesis testing (Welch's t-test, Mann-Whitney U)
  - Cohen's d effect size
- CLI untuk custom runs, seeds, dan scenarios

## Modul ML Utama

| Modul | File | Fungsi |
| --- | --- | --- |
| Collector | `src/ml/data_collector.py` | rekam access event dan statistik key |
| Feature engineering | `src/ml/feature_engineering.py` | bangun vector fitur temporal/statistik |
| Model | `src/ml/model.py` | ensemble LSTM + RandomForest + Markov |
| Registry | `src/ml/model_registry.py` | versioning, active model, checksum verification |
| Predictor | `src/ml/predictor.py` | top-N prediction dan prefetch helper |

## Status Integrasi ML Saat Ini

Ini bagian yang paling penting untuk dipahami secara jujur.

### Yang sudah baik

- `DataCollector`, `ModelTrainer`, dan `KeyPredictor` sekarang aktif secara online lewat endpoint backend.
- `EnsembleModel` mendukung kombinasi LSTM, RandomForest, dan Markov Chain.
- `ModelRegistry` sekarang memverifikasi checksum, signature metadata, provenance, dan tetap menolak `.pkl` saat load.
- Request path `/keys/access` sekarang merekam event ke collector ML runtime.
- Endpoint `/ml/status`, `/ml/predictions`, dan `/ml/retrain` sudah membaca runtime ML nyata.
- Runtime trainer sekarang memuat active version dari registry saat startup, dan retraining runtime menyimpan artefak aman baru kembali ke registry yang sama.
- Registry juga sudah punya endpoint operasional untuk summary, lifecycle, promotion stage, dan rollback runtime.

### Yang masih belum matang penuh

1. Request path API sekarang menjadwalkan prefetch ke Redis queue, lalu worker terpisah mengisi shared cache terenkripsi.
2. Retry dengan backoff eksponensial sederhana dan DLQ dasar sudah ada, tetapi replay workflow dan alerting-nya belum matang.
3. Secure model pipeline sekarang sudah konsisten dari training sampai runtime load, tetapi approval/release policy antar environment masih belum formal.
4. Observability historis untuk model lifecycle sudah persisten di registry log dan diekspor ke Prometheus, tetapi telemetry lain masih banyak hidup di memori proses.

## Frontend Simulation vs Backend Simulation

Halaman `frontend/src/pages/Simulation.jsx`:

- memanggil `/simulation/scenarios`, `/simulation/run`, dan `/simulation/results/{id}`
- menjalankan engine simulasi Python di backend
- cocok untuk demo interaktif tanpa kembali ke angka demo lokal

Script Python di `simulation/`:

- menghasilkan angka benchmark berbasis model distribusi dan parameter referensi
- cocok untuk laporan, command line benchmark, dan eksperimen backend

Jangan menyamakan flow simulation API dengan jalur request produksi. Simulation sekarang online di backend, tetapi tetap merupakan runtime benchmark yang terpisah.

## Artefak dan Lokasi Output

| Artefak | Lokasi umum |
| --- | --- |
| raw seed data | `data/raw/` |
| processed training data | `data/training/` |
| model registry | `data/models/registry.json` |
| checksum manifest | `data/models/checksums.json` |
| model artifacts `.pskc.json` | `data/models/` |

## Rekomendasi Lanjutan Untuk Menyatukan Pipeline

Jika ingin membuat PSKC benar-benar prediktif end-to-end, urutan pekerjaan yang masuk akal adalah:

1. tambahkan DLQ replay workflow, alerting, dan metric historis untuk worker prefetch
2. formalkan approval/promotion policy antar environment di luar registry lokal
3. lengkapi observability historis agar training/prediction metrics tidak hanya hidup di memori proses
4. tambahkan release governance model yang lebih operasional, misalnya approval gate dan provenance eksternal
