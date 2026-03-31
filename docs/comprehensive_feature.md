# Comprehensive Feature PSKC

Dokumen ini menjelaskan proyek PSKC secara lebih komprehensif: apa yang sedang dibangun, komponen apa saja yang sudah aktif, bagaimana alur sistem bekerja, data apa yang dihasilkan, dan batasannya saat ini.

PSKC adalah singkatan dari **Predictive Secure Key Caching**.

## 1. Inti Proyek

PSKC adalah sistem untuk menurunkan latensi akses kunci dengan cara memprediksi key yang kemungkinan akan diminta berikutnya, lalu memanaskan cache sebelum request benar-benar datang.

Masalah yang ingin diselesaikan:

- akses langsung ke KMS mahal dari sisi latensi
- pada traffic tinggi, pola key sering tidak acak murni
- banyak request bisa berhenti lebih cepat di cache jika sistem tahu key mana yang perlu disiapkan lebih dulu

Karena itu, PSKC menggabungkan:

- cache aman berlapis
- machine learning
- prefetch worker
- fallback KMS
- observability dan simulation untuk pembuktian

## 2. Prinsip Arsitektur

PSKC dibangun dengan beberapa prinsip:

- request path utama harus tetap sederhana dan tahan gagal
- prediksi tidak boleh memblokir request utama
- prefetch harus dijalankan oleh worker terpisah
- model lifecycle harus punya registry dan metadata aman
- angka yang tampil di dashboard harus bisa dijelaskan asalnya

Ini sebabnya repo tidak hanya punya model ML, tetapi juga Redis cache, queue, worker, simulation, audit log, metrics, dan database metadata.

## 3. Komponen Utama Sistem

### 3.1 API Backend

Backend utama adalah FastAPI di `src/api`.

Tugas utamanya:

- menerima request store/access key
- melayani status cache, ML, simulation, dan security
- mencatat event untuk jalur ML
- menyiapkan queue prefetch
- menyajikan data untuk dashboard frontend

File utama:

- [src/api/routes.py](d:/pskc-project/src/api/routes.py)
- [src/api/route_keys.py](d:/pskc-project/src/api/route_keys.py)
- [src/api/route_training.py](d:/pskc-project/src/api/route_training.py)
- [src/api/routes_models.py](d:/pskc-project/src/api/routes_models.py)
- [src/api/live_simulation_service.py](d:/pskc-project/src/api/live_simulation_service.py)
- [src/api/ml_service.py](d:/pskc-project/src/api/ml_service.py)

### 3.2 Cache Layer

PSKC punya dua lapis cache:

- `L1`: local cache per proses API
- `L2`: Redis shared cache antar proses / container

Peran keduanya:

- `L1` menangani hit tercepat
- `L2` memungkinkan key hangat dibagi antar node API
- jika dua lapis ini miss, sistem fallback ke KMS

File utama:

- [src/cache/local_cache.py](d:/pskc-project/src/cache/local_cache.py)
- [src/cache/redis_cache.py](d:/pskc-project/src/cache/redis_cache.py)
- [src/cache/encrypted_store.py](d:/pskc-project/src/cache/encrypted_store.py)

### 3.3 Prefetch Worker

Prefetch worker adalah komponen yang mengambil hasil prediksi dan memanaskan cache sebelum request berikutnya datang.

Yang sudah ada:

- Redis-backed queue
- retry dasar
- dead-letter queue dasar
- worker terpisah
- integrasi ke simulation proof

Yang perlu dipahami:

- worker terpisah paling realistis memanaskan `L2`
- request berikutnya yang mengenai `L2` akan mempromosikan key itu ke `L1`
- karena itu `L2 hit` tidak otomatis berarti worker selalu sukses; bisa juga key masuk cache karena request sebelumnya melakukan fetch dan menyimpannya

File utama:

- [src/prefetch/queue.py](d:/pskc-project/src/prefetch/queue.py)
- [src/workers/prefetch_worker.py](d:/pskc-project/src/workers/prefetch_worker.py)

### 3.4 ML Runtime

ML runtime PSKC terdiri dari beberapa bagian:

- collector data akses
- feature engineering
- trainer
- predictor
- online learner
- secure model registry

Tujuannya bukan hanya menghasilkan model, tetapi memastikan model:

- bisa dilatih
- bisa dievaluasi
- bisa dipromosikan
- bisa di-load kembali secara aman
- bisa dipantau dari dashboard

File utama:

- [src/ml/data_collector.py](d:/pskc-project/src/ml/data_collector.py)
- [src/ml/feature_engineering.py](d:/pskc-project/src/ml/feature_engineering.py)
- [src/ml/trainer.py](d:/pskc-project/src/ml/trainer.py)
- [src/ml/predictor.py](d:/pskc-project/src/ml/predictor.py)
- [src/ml/river_online_learning.py](d:/pskc-project/src/ml/river_online_learning.py)
- [src/ml/model_registry.py](d:/pskc-project/src/ml/model_registry.py)
- [src/ml/incremental_model.py](d:/pskc-project/src/ml/incremental_model.py)

### 3.5 Model Intelligence

Model Intelligence adalah permukaan observability untuk lifecycle model.

Fungsi utamanya:

- melihat semua versi model
- melihat history training
- melihat metrics per versi
- melihat drift status
- melihat River online learning stats
- melihat prediction logs

Ini penting karena tanpa halaman ini, angka model mudah terlihat seperti angka demo. Dengan halaman ini, operator bisa melacak apa yang sebenarnya terjadi pada model aktif dan candidate model.

File utama:

- [src/api/routes_models.py](d:/pskc-project/src/api/routes_models.py)
- [frontend/src/pages/ModelIntelligence.jsx](d:/pskc-project/frontend/src/pages/ModelIntelligence.jsx)

### 3.6 Realtime Simulation

Realtime simulation adalah komponen pembuktian.

Tujuannya:

- menunjukkan bahwa angka di dashboard berasal dari jalur request yang benar-benar disimulasikan
- memperlihatkan alur `L1`, `L2`, `KMS fetch`, dan baseline `direct KMS`
- menunjukkan apakah worker, Redis, dan model benar-benar aktif
- menunjukkan akurasi grounded terhadap request stream yang sedang berjalan

Simulation bukan sekadar grafik acak. Ia menyimpan trace dan bukti komponen yang dipakai selama session berjalan.

File utama:

- [src/api/live_simulation_service.py](d:/pskc-project/src/api/live_simulation_service.py)
- [frontend/src/components/LiveSimulationDashboard.jsx](d:/pskc-project/frontend/src/components/LiveSimulationDashboard.jsx)
- [frontend/src/pages/Simulation.jsx](d:/pskc-project/frontend/src/pages/Simulation.jsx)
- [docs/realtime_simulation.md](d:/pskc-project/docs/realtime_simulation.md)

## 4. Jalur Request yang Ingin Dibangun

Alur ideal PSKC:

1. request datang ke API
2. API cek `L1`
3. jika miss, API cek `L2`
4. jika tetap miss, API fallback ke KMS
5. API merekam event akses
6. predictor menghitung kandidat key berikutnya
7. job prefetch dikirim ke queue Redis
8. worker memanaskan cache untuk kandidat itu
9. request berikutnya punya peluang lebih tinggi untuk kena `L1` atau `L2`

Kalau prediksi salah, sistem tidak boleh rusak. Yang terjadi hanya:

- prefetch tidak membantu
- request berikutnya fallback ke jalur biasa
- outcome itu direkam untuk evaluasi model

## 5. Jalur Training yang Sudah Dipisah

PSKC sekarang punya dua jalur training.

### 5.1 Full Training

Dipakai untuk:

- retrain terjadwal
- retrain manual
- pembuatan versi model persisted baru

Karakteristik:

- lebih berat
- menulis metadata training
- bisa menghasilkan versi baru di registry
- bisa ditolak jika kualitasnya tidak cukup baik

### 5.2 Online Training

Dipakai untuk:

- drift-triggered adaptation
- update ringan saat pola berubah

Karakteristik:

- tidak memblokir runtime seperti full retrain
- tidak membuat versi model persisted baru
- dipakai untuk adaptasi cepat

Pemisahan ini penting karena drift detection tidak seharusnya selalu menyalakan full retrain yang mahal dan mengganggu simulation.

## 6. Secure Model Pipeline

Model pipeline PSKC sekarang diarahkan agar aman dan bisa diaudit.

Yang sudah ada:

- secure artifact `.pskc.json`
- checksum
- signature
- provenance
- active version
- promote / rollback
- lifecycle event

Yang dimaksud secure di sini bukan hanya "model bisa disimpan", tetapi:

- format artefak dibatasi
- registry memverifikasi integritas sebelum load
- metadata versi model tidak dibiarkan liar
- provenance tersimpan agar asal model bisa ditelusuri

## 7. Security Layer

PSKC punya lapisan keamanan terpisah dari logika cache/ML.

Yang sudah ada:

- HTTP security middleware
- rate limiting
- request body guard
- sensitive path protection
- tamper-evident audit log
- FIPS-style startup self-tests
- IDS / anomaly checks dasar

Ini penting karena PSKC menyentuh jalur key dan cache. Sistem seperti ini harus menjaga bukan hanya latency, tetapi juga trust boundary.

File utama:

- [src/security/security_headers.py](d:/pskc-project/src/security/security_headers.py)
- [src/security/tamper_evident_logger.py](d:/pskc-project/src/security/tamper_evident_logger.py)
- [src/security/fips_self_tests.py](d:/pskc-project/src/security/fips_self_tests.py)
- [src/security/intrusion_detection.py](d:/pskc-project/src/security/intrusion_detection.py)

## 8. Persistence dan Data yang Digunakan

PSKC memakai beberapa jenis persistence:

- `SQLite`: metadata model, metrics, prediction logs, training history
- `Redis`: L2 cache, prefetch queue, runtime state tertentu
- `data/models`: artifact model dan registry metadata
- `logs`: audit dan log operasional

Konsekuensinya:

- sistem bisa menjelaskan status model aktif
- history training bisa dianalisis ulang
- prediction log bisa dipakai debugging
- simulation dan dashboard bisa mengambil data nyata, bukan angka hardcoded

## 9. Frontend Surface

Frontend saat ini bukan hanya landing page, tetapi operator console sederhana.

Halaman penting:

- `Dashboard`
- `Simulation`
- `ML Training`
- `Model Intelligence`
- `Security Testing`

Peran tiap halaman:

- `Dashboard`: ringkasan cepat status runtime
- `Simulation`: pembuktian dan trace realtime
- `ML Training`: kontrol full training, planner, budget, dan hasil training
- `Model Intelligence`: observability model lifecycle
- `Security Testing`: validasi keamanan

## 10. Observability

PSKC mencoba menampilkan angka yang bisa dipertanggungjawabkan.

Contoh metrik yang sudah dipakai:

- model accuracy
- top-10 accuracy
- per-key accuracy
- drift score
- cache hit rate
- latency reduction
- cache efficiency
- KMS offload
- queue / worker proof

Metrik ini penting karena tanpa pemisahan yang jelas, dashboard mudah menampilkan angka yang tampak bagus tetapi tidak punya dasar.

## 11. Apa yang Sudah Kuat Saat Ini

Area yang relatif sudah kuat:

- backend runtime
- secure cache path
- prefetch worker dasar
- secure model registry
- realtime simulation sebagai alat pembuktian
- model intelligence untuk lifecycle model

## 12. Apa yang Masih Perlu Dimatangkan

Walaupun banyak bagian sudah hidup, ada area yang masih perlu terus dikembangkan:

- profil deployment production yang lebih ketat
- observability historis yang lebih kaya
- governance antar environment
- worker operations yang lebih matang
- benchmark validation yang lebih formal
- beberapa area tuning ML agar akurasi lebih stabil pada stream baru

Backlog itu ada di:

- [feature_roadmap.md](feature_roadmap.md)

## 13. Cara Membaca Proyek Ini

Kalau Anda baru masuk ke repo ini, jalur baca yang paling masuk akal:

1. baca [../README.md](../README.md)
2. baca [realtime_simulation.md](realtime_simulation.md)
3. baca [feature_roadmap.md](feature_roadmap.md)
4. baru masuk ke `src/api`, `src/ml`, dan `frontend/src/pages`

## 14. Ringkasan Akhir

Kalau proyek ini diringkas dalam satu ide:

PSKC adalah sistem **Predictive Secure Key Caching** yang mencoba membuat request key lebih cepat dengan prediksi ML dan prefetch, sambil tetap menjaga keamanan, observability, dan pembuktian yang jujur melalui simulation realtime dan model intelligence.
