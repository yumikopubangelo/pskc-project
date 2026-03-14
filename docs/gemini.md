# Executive Overview

Dokumen ini ditujukan untuk stakeholder, reviewer, atau anggota tim baru yang membutuhkan gambaran cepat tanpa masuk terlalu dalam ke detail kode.

## Apa Itu PSKC

PSKC adalah konsep secure key caching yang mencoba menurunkan latensi autentikasi di sistem mikroservis dengan tiga ide utama:

1. kunci yang sering dipakai disimpan lokal untuk sementara
2. penyimpanan lokal itu tetap dienkripsi
3. pola akses dapat dipelajari untuk memprediksi key yang perlu dipanaskan lebih awal

## Apa Yang Sudah Ada di Repository Ini

Repository saat ini sudah memiliki:

- backend FastAPI untuk health check dan operasi dasar cache key
- secure cache in-memory dengan boundary kriptografi khusus
- tamper-evident audit logging
- engine simulasi untuk skenario Spotify, AWS, Netflix, dynamic environment, dan cold start
- dashboard React/Vite untuk demo visual dan presentasi
- script untuk generate data, benchmark, dan training model

## Apa Yang Belum Selesai Sepenuhnya

Repository ini belum merupakan platform produksi penuh. Beberapa komponen masih berupa tahap transisi:

- predictive prefetch belum terhubung penuh ke jalur request API
- middleware keamanan HTTP dan rate limiter sekarang sudah aktif secara default, tetapi policy `TRUSTED_PROXIES` dan blokir path sensitif masih perlu disetel sesuai deployment
- self-test FIPS sekarang aktif saat startup, tetapi kebijakan trusted proxy dan endpoint sensitif tetap perlu disetel sesuai deployment
- frontend Docker belum mewakili SPA React yang dipakai saat development lokal
- test suite masih membawa jejak modul lama dan perlu dirapikan

## Nilai Utama Proyek

PSKC berguna sebagai:

- referensi arsitektur untuk secure caching key material
- artefak presentasi untuk menjelaskan bagaimana ML bisa membantu cache warm-up
- playground teknis untuk membandingkan baseline latency vs cache-assisted latency
- basis eksperimen untuk merapikan pipeline keamanan dan registry model

## Hasil yang Ditonjolkan

Simulasi dan frontend demo menonjolkan dampak berikut:

- rata-rata latensi dapat turun tajam saat cache hit rate tinggi
- skenario prime time atau quota pressure lebih terlindungi bila key sudah tersedia lokal
- cold start menunjukkan bahwa akurasi model dan manfaat cache tidak muncul instan sejak request pertama

## Untuk Pembaca Lanjutan

- untuk setup dan menjalankan proyek: [getting_started.md](getting_started.md)
- untuk arsitektur teknis: [architecture.md](architecture.md)
- untuk simulasi dan ML: [simulation_and_ml.md](simulation_and_ml.md)
- untuk status keamanan: [security_model.md](security_model.md)
