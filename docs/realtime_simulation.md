# Realtime Simulation

Dokumen ini menjelaskan bagaimana membaca mode realtime simulation di PSKC, terutama untuk memisahkan:

- cache hit biasa vs worker-prefetch yang benar-benar terbukti
- cache miss vs KMS fallback vs KMS failure
- akurasi model offline vs akurasi live di request stream

## Tujuan

Realtime simulation dipakai untuk menguji jalur runtime yang hidup:

- API node virtual dengan `L1` terpisah per node
- Redis sebagai `L2` bersama
- prefetch queue + prefetch worker
- model ML runtime atau shadow model terbaik
- baseline `direct KMS` pada stream request yang sama

Mode ini bukan demo statis. Setiap angka berasal dari request stream yang benar-benar diproses oleh komponen runtime.

## Endpoint Yang Dipakai

- `POST /simulation/live-session/start`
- `GET /simulation/live-session/{session_id}`
- `GET /simulation/live-session/{session_id}/stream`
- `POST /simulation/live-session/{session_id}/stop`

Frontend `Simulation` dan `LiveSimulationDashboard` membaca endpoint yang sama. SSE hanya mengubah cara update data, bukan logika perhitungannya.

## Arti Path Request

Setiap request realtime akan diberi salah satu path berikut:

- `l1_hit`: key sudah ada di cache lokal node API yang melayani request
- `l2_hit`: key tidak ada di L1 node itu, tetapi ada di Redis/shared cache sebelum request diproses
- `late_cache_hit`: key muncul saat request diproses, tetapi tidak terlihat di inspeksi awal. Ini biasanya race kecil antar komponen
- `kms_fetch`: cache miss, lalu request fallback ke KMS dan berhasil mengambil key
- `kms_miss`: cache miss, lalu KMS gagal atau key memang tidak ditemukan
- `blocked`: request ditolak kontrol keamanan

Catatan penting:

- `kms_fetch` tidak otomatis berarti model salah
- `kms_fetch` hanya berarti cache belum hangat saat request masuk
- penyebabnya bisa prediction miss, worker belum selesai, key baru berotasi, atau traffic churn terlalu tinggi

## Cache Origin

Kolom `Cache Origin` di trace menjawab pertanyaan: "key ini ada di cache karena apa?"

- `Worker-prefetched`: ada bukti event completion dari prefetch worker untuk key itu sebelum request masuk
- `Request-cached`: key ada di cache karena request sebelumnya pernah miss, fetch ke KMS, lalu hasilnya disimpan ke cache
- `Warm cache (origin unknown)`: key ditemukan di cache, tetapi origin eksplisitnya tidak tertangkap dalam trace session
- `No`: request tidak menemukan key di cache sebelum diproses

Ini berarti:

- `L2 hit` tidak selalu sama dengan `worker prefetch`
- `L2 hit` bisa terjadi hanya karena request sebelumnya pernah melakukan fallback ke KMS

## Verified Prefetch Hit Rate

`Verified Prefetch Hit Rate` adalah metrik yang sengaja ketat.

Sebuah request baru dihitung sebagai `verified prefetch hit` jika semua syarat ini terpenuhi:

1. request sebelumnya memprediksi key yang benar untuk request berikutnya
2. prefetch worker benar-benar menyelesaikan job untuk key tersebut
3. request berikutnya menemukan key itu sudah hangat di cache

Karena definisinya ketat, angka ini biasanya lebih rendah daripada `cache hit rate`.

## Previous Prediction Top-1 dan Top-10

Kolom `Previous Prediction Top-1` dan `Previous Prediction Top-10` tidak membandingkan request dengan dirinya sendiri.

Yang dibandingkan adalah:

- request `N` memprediksi key untuk request `N+1` pada service stream yang sama
- saat request `N+1` benar-benar datang, simulator mengecek apakah key aktual:
  - sama dengan peringkat 1 prediksi sebelumnya (`Top-1`)
  - masih masuk daftar 10 besar prediksi sebelumnya (`Top-10`)

Karena itu angka live ini jauh lebih keras daripada sekadar membaca metrik validasi model saat training.

## Mengapa Akurasi Model Bisa 100% Tetapi Live Accuracy Rendah

Card status model dan live simulation mengukur hal yang berbeda.

`Model Status` biasanya menunjukkan metrik validasi artefak model aktif:

- berbasis validation split saat training
- bisa memakai sampel yang relatif sedikit
- tidak selalu mewakili churn key pada stream runtime saat ini

`Live Top-1` dan `Live Top-10` mengukur:

- stream request baru
- rotasi key baru
- tekanan KMS nyata di simulator
- interaksi dengan queue dan worker

Jadi kondisi seperti ini valid:

- model status tinggi
- live accuracy lebih rendah

Itu bukan berarti dashboard bohong. Itu berarti workload live lebih keras daripada validation set model.

## Session Learning Overlay

Realtime simulation tidak hanya memakai model registry/runtime.

Ia juga punya overlay pembelajaran per session:

- transition antar key per service
- popularity counter per service

Overlay ini digabung dengan prediksi model untuk meniru kondisi runtime yang belajar pola berulang selama session berjalan.

Artinya:

- model aktif tetap dipakai
- tetapi simulator juga memanfaatkan pola yang baru muncul di session saat ini

## Mengapa Baseline Direct KMS Bisa Lebih Tinggi Saat Load Naik

Baseline `Without PSKC` tidak memakai cache. Setiap request baseline diasumsikan menuju jalur KMS langsung.

Simulator memberi tekanan KMS pada dua lane:

- lane `pskc`: hanya aktif saat jalur PSKC benar-benar miss ke KMS
- lane `direct`: aktif untuk baseline tanpa cache

Saat traffic `heavy_load`, `prime_time`, atau `overload`, lane `direct` akan naik lebih cepat karena semua request baseline memukul KMS. Ini membuat perbandingan lebih realistis daripada baseline yang selalu datar.

## Membaca Tabel Trace

Panduan cepat:

- `Path = L1 hit` dan `Cache Origin = Worker-prefetched`
  berarti worker memanaskan key, lalu request berikutnya benar-benar menikmatinya
- `Path = L2 hit` dan `Cache Origin = Request-cached`
  berarti key ada di Redis karena request sebelumnya miss ke KMS, bukan karena worker
- `Path = KMS fallback`
  berarti request tetap berhasil, tetapi cache belum siap saat request datang
- `Path = KMS failed/not found`
  berarti fallback pun gagal

## Cara Menjalankan Simulasi Yang Lebih Realistis

Untuk melihat `L2 hit`, `worker-prefetched`, dan tekanan KMS yang lebih nyata:

- gunakan `Virtual API Nodes` lebih dari 1
- gunakan `Traffic Profile = heavy_load`, `prime_time`, atau `overload`
- gunakan `Key Realism = mixed` atau `high_churn`
- biarkan session berjalan cukup lama agar transition learning punya data

Kombinasi ini akan membuat:

- L1 tidak terlalu dominan
- Redis/L2 mulai terlihat
- worker prefetch punya kesempatan menunjukkan efeknya
- live accuracy menjadi lebih jujur terhadap churn key

## Batasan Yang Perlu Diketahui

- ini masih simulasi runtime, bukan replay trafik produksi asli
- angka session akan berubah jika profile traffic dan churn key diubah
- `Request-cached` tetap bermanfaat secara latensi, tetapi tidak boleh diklaim sebagai keberhasilan worker prefetch

## Dokumen Terkait

- [simulation_and_ml.md](simulation_and_ml.md)
- [architecture.md](architecture.md)
- [operations.md](operations.md)
