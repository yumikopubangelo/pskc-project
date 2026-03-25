# Realtime Simulation

Dokumen ini menjelaskan bagaimana membaca halaman realtime simulation PSKC dan arti setiap metrik yang tampil.

## Tujuan

Realtime simulation dipakai untuk memvalidasi bahwa angka performa dan akurasi yang tampil di dashboard benar-benar berasal dari jalur request runtime, bukan angka demo statis.

Komponen yang ikut terlibat:

- FastAPI request path
- `LocalCache` virtual per node sebagai L1
- Redis shared cache sebagai L2
- prefetch worker + Redis queue
- predictor / model ML aktif
- baseline direct KMS pada stream request yang sama

## Cara Kerja

Untuk setiap request simulasi:

1. request diarahkan ke salah satu virtual API node
2. sistem mengecek L1 node itu
3. jika L1 miss, sistem mengecek L2 Redis bersama
4. jika L1 dan L2 miss, request fallback ke KMS
5. request berikutnya dinilai terhadap prediksi yang dibuat request sebelumnya
6. predictor menerima feedback outcome, drift diperbarui, dan River online learning dapat beradaptasi tanpa membuat versi model baru

## Arti Path

- `l1_hit`: key sudah tersedia di local cache node yang melayani request
- `l2_hit`: key tidak ada di L1 node saat ini, tetapi tersedia di Redis shared cache
- `late_cache_hit`: key tersedia saat request dieksekusi, tetapi asal tepatnya tidak bisa dipastikan hanya dari probe awal
- `kms_fetch`: key tidak ada di cache, lalu berhasil diambil dari KMS
- `kms_miss`: key tidak ada di cache dan KMS juga gagal / tidak memiliki key itu
- `blocked`: request diblokir oleh security layer

## Prediction Metrics

- `Live Top-1`: seberapa sering request sebelumnya menebak request saat ini tepat di ranking pertama
- `Live Top-10`: seberapa sering request saat ini masih masuk 10 besar tebakan request sebelumnya
- `Verified Prefetch Hit Rate`: hanya dihitung sukses jika worker benar-benar menyelesaikan prefetch untuk key yang lalu benar-benar dipakai request berikutnya
- `Accuracy per key`: akurasi grounded per key, dihitung dari sampel request nyata selama session berjalan

## Cache Origin

Kolom `Cache Origin` di trace tidak sama dengan `Path`.

- `Worker-prefetched`: key sudah dipanaskan oleh worker sebelum request datang
- `Request-cached`: key masuk cache karena request sebelumnya melakukan fallback ke KMS lalu menyimpannya
- `Warm cache (origin unknown)`: key terlihat sudah hangat, tetapi asal tepatnya tidak bisa dipastikan dari event yang tersedia
- `No`: tidak ada bukti cache hangat sebelum request

`L2 hit` tidak otomatis berarti worker berhasil prefetch. Bisa saja itu hasil `request_fetch` dari request sebelumnya.

## Observability & Latency Metrics

Panel observability menampilkan:

- `cache_hit_rate_percent`: persentase request yang selesai lewat cache
- `latency_reduction_percent`: pengurangan latensi PSKC dibanding baseline direct KMS pada stream yang sama
- `cache_efficiency_percent`: skor berbobot dari kontribusi L1, L2, dan late cache hit
- `kms_offload_percent`: berapa banyak request direct KMS yang berhasil dihindari oleh PSKC
- `predictor drift`: drift score runtime predictor
- `River online`: jumlah update incremental online learning
- `latency breakdown`: average dan P95 untuk L1, L2, late cache hit, KMS fallback, KMS miss, dan baseline direct KMS

## Mengapa Akurasi Model Bisa Berbeda dengan Simulasi

Angka di halaman status model dan angka di simulation bisa berbeda karena konteks evaluasinya berbeda.

- status model: biasanya berasal dari validation set saat training
- realtime simulation: berasal dari stream request baru yang sedang berjalan

Jadi model bisa punya validation accuracy tinggi tetapi live accuracy lebih rendah jika:

- key churn tinggi
- pola akses berubah
- basis validasi model terlalu kecil
- worker belum sempat menyelesaikan prefetch

## Tentang Drift dan Online Learning

PSKC sekarang memiliki dua jalur training yang berbeda:

- scheduled / manual training:
  full retrain, membuat versi model persisted baru
- drift-triggered online training:
  memakai River `partial_fit`, tidak membuat versi model baru, dan dipakai untuk adaptasi cepat saat simulation/runtime berubah

Ini penting agar drift detection tidak memblokir simulasi dengan full retrain berat.

## Tentang KMS Baseline

Baseline `Without PSKC` mensimulasikan direct KMS pada stream request yang sama. Latensi KMS tidak konstan:

- saat traffic naik, pressure lane direct KMS ikut naik
- saat overload, direct KMS bisa mengalami spike dan antrian
- PSKC juga tetap bisa terkena KMS fallback jika L1/L2 miss

Karena itu metrik `Saved` di trace bisa positif atau negatif per request. Yang relevan adalah tren agregat, bukan hanya satu sampel.

## Rekomendasi Membaca Dashboard

- lihat `Requests Processed` dan `Accuracy Samples` dulu
- pastikan `Redis shared cache`, `Prefetch worker`, dan `Selected model loaded` bernilai aktif
- cek `Latency Breakdown by Path` untuk memastikan L1, L2, dan KMS fallback memang terukur
- cek `Per-Key Observability` untuk melihat key mana yang konsisten bagus atau buruk
- lihat trace untuk memahami apakah miss datang dari prediction miss, worker belum selesai, atau key churn terlalu cepat
