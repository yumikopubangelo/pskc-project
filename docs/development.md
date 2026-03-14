# Development Guide

Dokumen ini membantu contributor memahami struktur proyek, workflow lokal, dan batasan current state codebase.

## Struktur Kode

| Area | Folder | Catatan |
| --- | --- | --- |
| API backend | `src/api` | FastAPI app dan schema request/response |
| Auth integration | `src/auth` | fetcher dan verifier key |
| Cache | `src/cache` | local cache, policy manager, encrypted store |
| Security | `src/security` | crypto boundary, audit log, IDS, headers middleware |
| ML | `src/ml` | collector, feature engineering, model, registry, predictor |
| Simulasi | `simulation` | skenario benchmark dan engine pendukung |
| Scripts | `scripts` | seed data, benchmark, training data, training model |
| Frontend | `frontend` | React/Vite demo UI |
| Tests | `tests` | gabungan test lama dan test pasca refactor |

## Workflow Lokal yang Disarankan

### Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn src.api.routes:app --reload
```

### Frontend

```powershell
Set-Location frontend
npm install
npm run dev
```

### Simulasi dan benchmark

```powershell
python simulation/runner.py --scenario all
python scripts/benchmark.py --all
```

## Area yang Sedang Berubah

Repository ini sedang berada di fase transisi setelah refactor keamanan. Kontributor perlu tahu area berikut paling sensitif:

1. `src/api/routes.py` sekarang menjadi pusat wiring dependency dan sumber kebenaran runtime.
2. `src/cache/encrypted_store.py` dan `src/security/intrusion_detection.py` sudah beralih ke dependency injection.
3. sebagian modul ML dan test masih mengacu ke helper global lama yang sudah dihapus.
4. beberapa dokumen lama pernah mengasumsikan lebih banyak endpoint API daripada yang benar-benar tersedia sekarang.

## Frontend: Demo vs Integrasi Nyata

Frontend bersifat presentational/demo-heavy.

Yang benar saat ini:

- overview, dashboard, simulation, dan ML pipeline sudah membaca data backend nyata
- node graph masih mempertahankan animasi konseptual, tetapi status runtime-nya dibaca dari backend
- halaman simulasi browser sekarang menjalankan engine simulasi Python lewat endpoint backend, bukan generator lokal di browser
- file `frontend/src/utils/apiClient.js` masih memuat beberapa endpoint yang belum semuanya dipakai UI
- default frontend dev mode sekarang `auto`, sehingga UI mencoba backend lokal lebih dulu
- `VITE_API_MODE=mock` sekarang diperlakukan seperti `auto`, sehingga frontend tetap diarahkan ke backend nyata
- gunakan `VITE_API_MODE=live` jika sedang menguji integrasi penuh dengan FastAPI lokal tanpa fallback

Artinya perubahan frontend perlu dilakukan dengan asumsi bahwa UI belum menjadi client resmi dari semua fitur backend.

## Status Test Suite

Test suite saat ini perlu dibaca dengan hati-hati.

### Yang perlu diketahui

- beberapa file test masih mengimpor modul lama seperti `audit_logger`, `SecureKeyHandler`, atau helper global yang telah dihapus
- refactor boundary FIPS-style mengubah banyak interface tetapi test belum seluruhnya diperbarui
- jangan mengasumsikan `pytest` penuh akan hijau tanpa pekerjaan sinkronisasi tambahan

### Saran menjalankan test

Mulai dari test yang sesuai area yang sedang Anda ubah, lalu evaluasi kegagalan satu per satu. Jika sedang mengerjakan dokumentasi atau frontend, test suite penuh belum tentu relevan.

## Style dan Konvensi Praktis

- gunakan `README.md` dan folder `docs/` sebagai sumber kebenaran narasi teknis
- jika mengubah perilaku endpoint, update `docs/api_reference.md`
- jika mengubah wiring runtime atau dependency graph, update `docs/architecture.md`
- jika mengubah flow simulasi, model, atau benchmark, update `docs/simulation_and_ml.md`
- jika mengubah docker, env vars, atau deployment behavior, update `docs/operations.md`

## Area Dokumentasi Yang Wajib Dijaga Sinkron

| Perubahan kode | Dokumen yang harus ikut diupdate |
| --- | --- |
| endpoint baru atau response berubah | `README.md`, `docs/api_reference.md` |
| startup/lifespan/dependency wiring berubah | `docs/architecture.md`, `docs/operations.md` |
| perubahan security controls | `docs/security_model.md`, `docs/security_analysis_report.md` |
| perubahan pipeline ML/simulasi | `docs/simulation_and_ml.md` |
| perubahan frontend run flow | `README.md`, `docs/getting_started.md`, `docs/development.md` |
