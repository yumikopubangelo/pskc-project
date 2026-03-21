# Dokumentasi PSKC

Dokumen ini adalah pintu masuk untuk seluruh dokumentasi proyek.

## Mulai Dari Sini

1. [README.md](../README.md) - ringkasan proyek dan status sistem saat ini
2. [getting_started.md](getting_started.md) - setup lokal, Docker, dan smoke test
3. [project_status.md](project_status.md) - backlog status: belum selesai, kurang, dan belum dikembangkan
4. [feature_roadmap.md](feature_roadmap.md) - backlog fitur yang lebih detail, prioritas, dan definisi selesai
5. [architecture.md](architecture.md) - arsitektur runtime dan data flow aktif

## Referensi Teknis

- [api_reference.md](api_reference.md) - endpoint FastAPI yang tersedia saat ini
- [project_status.md](project_status.md) - daftar gap implementasi dan prioritas pengembangan
- [feature_roadmap.md](feature_roadmap.md) - rincian backlog fitur per area, dependensi, dan validation plan
- [security_model.md](security_model.md) - kontrol keamanan aktif, parsial, dan rekomendasi deployment
- [simulation_and_ml.md](simulation_and_ml.md) - engine simulasi, training data, artefak model, dan gap integrasi
- [realtime_simulation.md](realtime_simulation.md) - cara membaca live simulation, cache origin, verified prefetch, dan baseline KMS
- [development.md](development.md) - panduan contributor, frontend, dan status test
- [operations.md](operations.md) - konfigurasi `.env`, Docker Compose, log, dan catatan operasional

## Ringkasan Non-Teknis dan Historis

- [gemini.md](gemini.md) - executive overview untuk stakeholder
- [security_analysis_report.md](security_analysis_report.md) - status terkini dari temuan keamanan historis

## Cara Membaca Dokumentasi Ini

- Jika Anda ingin menjalankan proyek: baca `README.md` lalu `getting_started.md`.
- Jika Anda ingin mengubah backend: baca `architecture.md`, `api_reference.md`, dan `development.md`.
- Jika Anda ingin fokus pada benchmark dan model: baca `simulation_and_ml.md` lalu `realtime_simulation.md`.
- Jika Anda ingin menyiapkan deployment: baca `operations.md` dan `security_model.md`.
