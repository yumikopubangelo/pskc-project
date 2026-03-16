# Feature Roadmap

Dokumen ini adalah backlog pengembangan yang lebih detail daripada `project_status.md`.

Tujuannya bukan hanya mencatat apa yang masih kurang, tetapi juga:

1. menjelaskan fitur apa yang sebenarnya perlu dibangun
2. menunjukkan kenapa fitur itu penting
3. memetakan area kode yang kemungkinan terdampak
4. memberikan definisi selesai yang cukup konkret untuk eksekusi engineering

## Cara Menggunakan Dokumen Ini

- Gunakan `project_status.md` jika Anda ingin melihat gambaran singkat gap proyek.
- Gunakan dokumen ini jika Anda ingin memecah gap itu menjadi backlog kerja yang bisa dieksekusi.
- Jangan membaca semua bagian sebagai pekerjaan paralel. Banyak item di sini punya dependensi dan harus dikerjakan berurutan.

## Prioritas

| Prioritas | Makna |
| --- | --- |
| `P0` | penting untuk kestabilan, keamanan, atau kemampuan deploy yang masuk akal |
| `P1` | penting untuk operasional sistem setelah fondasi stabil |
| `P2` | penting untuk kematangan produk, observability, dan ergonomi operator |
| `P3` | nilai tambah jangka menengah, tetapi bukan blocker utama |

## Ringkasan Backlog

| Area | Prioritas | Status singkat |
| --- | --- | --- |
| Deployment dan topologi runtime | `P0` | stack sudah hidup, tetapi policy deployment nyata masih kurang rinci |
| Observability historis | `P0` | metrics endpoint sudah ada, tetapi banyak data masih hidup di memori proses |
| Prefetch orchestration yang matang | `P1` | queue, retry, DLQ sudah ada, tetapi replay dan rate control belum matang |
| Concept drift EWMA maturation | `P1` | ada di desain, implementasi belum matang, perlu diselesaikan agar konsisten dengan klaim paper |
| Benchmark validation suite | `P1` | simulasi sudah berjalan, tetapi reproducibility dan validasi statistik formal belum ada |
| Zero-downtime key rotation | `P1` | ✅ Selesai - rotation dengan grace period dan atomicity sudah tersedia |
| Governance model release | `P1` | ✅ Selesai - signing, provenance, promotion, rollback aktif, ensemble LSTM+RF+Markov berjalan |
| Key lifecycle management | `P1` | ✅ Selesai - cache access, secure store, rotate, revoke, expire semua terintegrasi dalam workflow lengkap dengan API endpoints |
| Admin dan ops control plane | `P1` | observability dasar ada, tetapi endpoint kontrol operasional masih minim |
| River online learning integration | `P2` | RF+Markov sudah stabil, River untuk true online learning belum terintegrasi |
| Frontend productization | `P2` | halaman utama sudah online, tetapi masih ada area UI yang menyisakan pola demo-heavy |
| Test matrix dan CI yang lebih lengkap | `P2` | CI backend minimum sudah ada, tetapi belum mencakup topology matrix dan failure path penuh |
| Multi-environment artifacts | `P3` | Docker Compose demo sudah ada, tetapi staging/production manifest belum rapi |

---

## 1. Deployment dan Topologi Runtime

**Prioritas:** `P0`

### Tujuan

Membuat stack PSKC bisa dideploy dengan asumsi yang lebih realistis daripada mode demo lokal.

### Kondisi saat ini

- `api`, `redis`, `prefetch-worker`, `prometheus`, dan `grafana` sudah bisa dijalankan.
- startup backend, smoke test live, dan focused CI minimum sudah ada.
- middleware HTTP security, self-test FIPS-style, audit log, dan Redis queue sudah aktif.
- policy reverse proxy, pemisahan endpoint internal/publik, dan readiness production belum benar-benar dibakukan.

### Fitur yang perlu dikembangkan

1. **Reference deployment dengan reverse proxy**
   - Tambahkan contoh topologi `reverse-proxy -> api -> redis/prefetch-worker`.
   - Dokumentasikan `TRUSTED_PROXIES`, header forwarding, dan HSTS/CSP behavior.
   - Pisahkan contoh dev vs contoh production.

2. **Health vs readiness vs dependency health**
   - `GET /health` saat ini terlalu sederhana.
   - Tambahkan endpoint readiness yang benar-benar memeriksa dependency penting.
   - Tetapkan mana dependency yang fail-open dan mana yang fail-closed.

3. **Pemisahan endpoint publik dan endpoint operasional**
   - Tentukan endpoint mana yang boleh diakses publik.
   - Kelompokkan endpoint ops seperti metrics, audit, lifecycle, dan DLQ inspection.
   - Tambahkan kontrol akses yang konsisten untuk endpoint sensitif.

4. **Policy startup dependency**
   - Saat ini sebagian dependency diprime secara best-effort.
   - Perlu policy eksplisit untuk Redis down, audit log unavailable, atau registry model corrupt.
   - Hasil akhirnya harus terdokumentasi dan terukur.

5. **Production config profile**
   - Saat ini konfigurasi masih lebih dekat ke development.
   - Perlu preset atau contoh production untuk timeout, rate limit, secret handling, dan retention.

### Area kode yang kemungkinan terdampak

- `src/api/routes.py`
- `src/security/security_headers.py`
- `src/runtime/bootstrap.py`
- `config/settings.py`
- `docker-compose.yml`
- `docs/operations.md`

### Definisi selesai

- ada contoh deployment reverse proxy yang jelas
- endpoint readiness terpisah dari health sederhana
- policy akses endpoint sensitif terdokumentasi dan enforced
- startup behavior untuk dependency failure tidak ambigu
- smoke test topology yang lebih realistis tersedia

### Validasi minimum

- integration test untuk proxy header dan host validation
- smoke test Docker dengan proxy nyata
- negative test untuk Redis unavailable saat startup dan runtime

---

## 2. Observability Historis

**Prioritas:** `P0`

### Tujuan

Membuat operator bisa membaca kondisi sistem dari histori, bukan hanya snapshot runtime proses yang sedang hidup.

### Kondisi saat ini

- `/metrics`, `/metrics/prefetch`, `/metrics/prometheus`, audit log, dan lifecycle log sudah ada.
- sebagian metrics frontend masih berasal dari state in-memory proses API.
- lifecycle model sudah persisten, tetapi latency/cache/training telemetry belum terarsip dengan rapi.

### Fitur yang perlu dikembangkan

1. **Persistensi metrics utama**
   - simpan seri waktu penting seperti request count, cache hit rate, latency bucket, dan training outcome
   - pisahkan metrics operasional dengan metrics untuk dashboard demo

2. **Prometheus coverage yang lebih lengkap**
   - tambahkan queue depth history, retry saturation, worker activity, dan registry state yang lebih lengkap
   - tentukan label yang stabil agar tidak menimbulkan cardinality berlebihan

3. **Alerting dasar**
   - Redis unavailable
   - DLQ growth
   - audit recovery event
   - model integrity failure
   - worker stagnation

4. **Dashboard operasional**
   - dashboard utama frontend saat ini masih lebih cocok untuk demo
   - perlu dashboard operator yang fokus ke health, queue, error rate, dan model state

5. **Retention dan cleanup**
   - audit log dan lifecycle log butuh policy rotasi
   - metric snapshot lokal butuh retention atau roll-up strategy

### Area kode yang kemungkinan terdampak

- `src/observability/prometheus_exporter.py`
- `src/api/routes.py`
- `src/prefetch/queue.py`
- `src/workers/prefetch_worker.py`
- `frontend/src/pages/`
- `docs/operations.md`

### Definisi selesai

- metrik inti tidak lagi hilang hanya karena proses API restart
- operator punya sinyal yang cukup untuk membedakan error cache, error queue, error model, dan error security
- ada dashboard atau query operasional yang terdokumentasi

### Validasi minimum

- test endpoint metrics
- smoke test dengan Prometheus aktif
- simulasi DLQ/retry untuk memastikan alert condition benar-benar terlihat

---

## 3. Prefetch Orchestration yang Matang

**Prioritas:** `P1`

### Tujuan

Menjadikan prefetch worker bukan sekadar background task yang hidup, tetapi subsistem yang dapat dioperasikan.

### Kondisi saat ini

- request path sudah enqueue job prefetch ke Redis
- worker sudah konsumsi queue, retry, dan DLQ dasar
- predictor sudah terhubung ke jalur request utama

### Fitur yang perlu dikembangkan

1. **DLQ replay workflow**
   - endpoint atau script untuk requeue item dari DLQ
   - audit trail untuk replay manual
   - guard agar job berbahaya tidak direplay tanpa filter

2. **Rate control dan backpressure**
   - batasi jumlah prefetch per service
   - batasi ukuran queue yang sehat
   - fallback policy saat worker tertinggal terlalu jauh

3. **Concurrency control worker**
   - saat ini worker masih sederhana
   - perlu concurrency policy yang eksplisit agar tidak menyebabkan cache thrashing atau KMS pressure

4. **Failure classification**
   - bedakan fetch failure, secure store failure, queue failure, dan security rejection
   - gunakan klasifikasi itu untuk retry policy yang lebih tepat

5. **Budgeting dan prioritization**
   - jangan semua prediksi diperlakukan sama
   - perlu budget per service, per priority, atau per confidence band

### Area kode yang kemungkinan terdampak

- `src/api/ml_service.py`
- `src/prefetch/queue.py`
- `src/workers/prefetch_worker.py`
- `src/cache/redis_cache.py`
- `src/ml/predictor.py`

### Definisi selesai

- operator bisa melihat job gagal, tahu penyebabnya, dan melakukan replay aman
- worker tidak mem-banjiri cache atau dependency upstream saat load tinggi
- retry policy tidak lagi seragam untuk semua jenis kegagalan

### Validasi minimum

- test replay DLQ
- test retry classification
- load test queue depth vs worker throughput

---

## 4. Concept Drift EWMA Maturation

**Prioritas:** `P1`

> **Catatan konsistensi paper:** Section 2.4 Tinjauan Pustaka mengklaim mekanisme drift detection berbasis EWMA sudah diimplementasikan di PSKC. Item ini memastikan klaim tersebut benar-benar terpenuhi secara fungsional, bukan hanya ada di desain.

### Tujuan

Menyelesaikan implementasi EWMA drift detection agar model prediksi PSKC dapat beradaptasi secara otomatis ketika distribusi pola akses kunci berubah di lingkungan produksi.

### Kondisi saat ini

- konsep drift detection EWMA sudah ada di desain dan sebagian kode
- integrasi ke request path dan model selection belum matang
- tidak ada event drift yang terekam di audit log saat ini

### Fitur yang perlu dikembangkan

1. **EWMA window yang terkonfigurasi**
   - parameter alpha (smoothing factor) dapat dikonfigurasi via `config/settings.py`
   - window size dapat disesuaikan per skenario beban kerja
   - dokumentasikan nilai default yang direkomendasikan

2. **Drift detection aktif di request path**
   - setiap event akses digunakan untuk memperbarui statistik EWMA
   - saat metric EWMA melampaui threshold, drift flag aktif
   - model selection fallback ke versi lebih konservatif saat drift terdeteksi

3. **Tiga status drift sesuai desain**
   - status `stable`: distribusi normal, prediksi penuh aktif
   - status `warning`: sinyal awal perubahan, prediksi diperlambat
   - status `active_drift`: perubahan signifikan, fallback ke hot keys dari collector
   - transisi antar status terekam di audit log

4. **Integrasi dengan model registry**
   - saat drift aktif, catat konteks drift di lifecycle log
   - trigger retraining otomatis jika drift berlangsung lebih dari threshold waktu
   - rollback ke versi model sebelumnya jika akurasi turun drastis pasca-drift

5. **Metrics untuk drift**
   - ekspor status drift saat ini ke Prometheus (`pskc_drift_status`, `pskc_drift_score`)
   - tampilkan di dashboard operator

### Area kode yang kemungkinan terdampak

- `src/ml/model.py`
- `src/ml/predictor.py`
- `src/ml/trainer.py`
- `src/ml/data_collector.py`
- `src/observability/prometheus_exporter.py`
- `config/settings.py`

### Definisi selesai

- EWMA window aktif dan terkonfigurasi
- tiga status drift terimplementasi dan dapat di-observe
- drift event terekam di audit log dan diekspor ke Prometheus
- model fallback beroperasi saat drift aktif
- retraining otomatis dapat di-trigger dari kondisi drift

### Validasi minimum

- unit test untuk transisi status stable → warning → active_drift
- integration test untuk fallback prediksi saat drift aktif
- smoke test dengan distribusi akses yang sengaja diubah drastis
- verifikasi bahwa drift event muncul di audit log dan metrics endpoint

---

## 5. Benchmark Validation Suite

**Prioritas:** `P1`

> **Catatan konsistensi paper:** Paper mengklaim reduksi latensi 86.8% (Spotify), 85.9% (AWS KMS), dan 86.0% (Netflix) berdasarkan simulasi dengan parameter dari sumber primer. Item ini memastikan angka-angka tersebut dapat direproduksi dan diverifikasi secara independen.

### Tujuan

Membuat klaim performa PSKC dapat divalidasi ulang dengan satu command, menggunakan parameter yang terdokumentasi dan metodologi yang transparan.

### Kondisi saat ini

- engine simulasi sudah berjalan untuk tiga skenario utama
- parameter tersimpan di `simulation/parameters/*.json`
- belum ada suite benchmark formal yang menghasilkan laporan statistik terstandarisasi
- referensi MDPI (2025) sebagai basis angka 197ms baseline perlu diverifikasi ulang

### Fitur yang perlu dikembangkan

1. **Benchmark suite yang reproducible**
   - satu command untuk menjalankan seluruh benchmark: `python scripts/benchmark.py --all`
   - setiap run menghasilkan laporan JSON dengan metadata: timestamp, parameter, seed, environment
   - hasil dapat dibandingkan antar run untuk mendeteksi regresi performa

2. **Laporan statistik formal**
   - untuk setiap skenario: mean, median, P95, P99, standard deviation
   - confidence interval untuk klaim reduksi latensi
   - cache hit rate per fase: warmup, learning, mature

3. **Dokumentasi metodologi**
   - jelaskan secara eksplisit bagaimana parameter dari Spotify/AWS/Netflix diterjemahkan ke simulasi
   - tambahkan catatan tentang asumsi dan batasan model distribusi log-normal
   - perbarui `simulation/references/README.md` dengan cara mengutip hasil benchmark

4. **Verifikasi referensi baseline**
   - pastikan referensi MDPI (2025) yang menjadi basis 197ms dapat diakses dan diverifikasi
   - jika tidak dapat diverifikasi, ganti dengan referensi yang dapat dikonfirmasi

5. **Regression gate di CI**
   - tambahkan smoke benchmark ke pipeline CI
   - gagalkan CI jika reduksi latensi turun lebih dari threshold tertentu

### Area kode yang kemungkinan terdampak

- `scripts/benchmark.py`
- `simulation/runner.py`
- `simulation/scenarios/*.py`
- `simulation/parameters/*.json`
- `simulation/references/README.md`
- `.github/workflows/`

### Definisi selesai

- benchmark dapat dijalankan ulang dan menghasilkan hasil yang konsisten
- laporan statistik mencakup mean, P95, P99, dan confidence interval
- metodologi terdokumentasi dengan jelas di `simulation/references/README.md`
- referensi baseline dapat diverifikasi

### Validasi minimum

- jalankan benchmark tiga kali dan verifikasi konsistensi hasil
- bandingkan output dengan angka yang diklaim di paper
- smoke test CI benchmark gate

---

## 6. Zero-Downtime Key Rotation

**Prioritas:** `P1`

> **Catatan konsistensi paper:** Section 2.7 Tinjauan Pustaka menyebutkan "rotasi kunci tanpa downtime" sebagai salah satu fitur pembeda PSKC. Item ini memastikan klaim tersebut terimplementasi secara eksplisit.

### Tujuan

Memastikan rotasi kunci kriptografi dapat dilakukan tanpa menyebabkan cache miss spike, service disruption, atau jendela kerentanan antara kunci lama dan kunci baru.

### Kondisi saat ini

- `src/security/secret_rotation.py` sudah ada
- rotation tersedia secara teknis tetapi tidak memiliki grace period yang terkonfigurasi
- atomicity antara invalidasi kunci lama dan aktivasi kunci baru belum dijamin
- tidak ada audit trail khusus untuk siklus rotasi

### Fitur yang perlu dikembangkan

1. **Grace period yang terkonfigurasi**
   - kunci lama tetap valid selama grace period setelah kunci baru aktif
   - grace period dapat dikonfigurasi per service atau secara global
   - setelah grace period habis, kunci lama dihapus dari semua layer cache secara atomik

2. **Dual-key validation window**
   - selama rotasi, sistem menerima validasi dari kunci lama maupun kunci baru
   - request yang sedang berjalan tidak terganggu oleh rotasi
   - tidak ada window di mana kedua kunci tidak tersedia

3. **Atomik invalidasi lintas layer**
   - invalidasi kunci lama harus terjadi di L1 (LocalCache) dan L2 (Redis) secara konsisten
   - jika invalidasi L2 gagal, L1 tetap valid sampai retry berhasil
   - event invalidasi terekam di audit log dengan timestamp yang tepat

4. **Audit trail rotasi**
   - setiap rotasi menghasilkan chain event: rotation_initiated → new_key_active → old_key_grace → old_key_expired
   - chain event ini terintegrasi dengan tamper-evident audit logger yang sudah ada

5. **Integrasi dengan window of vulnerability mitigation**
   - mengacu pada temuan Ozcelik & Skjellum (2021) tentang window of vulnerability pada CRL
   - pastikan waktu antara keputusan rotasi dan efektivitas rotasi di cache seminimal mungkin

### Area kode yang kemungkinan terdampak

- `src/security/secret_rotation.py`
- `src/security/rotate_encryption_key.py`
- `src/cache/encrypted_store.py`
- `src/cache/local_cache.py`
- `src/cache/redis_cache.py`
- `src/security/tamper_evident_logger.py`
- `src/api/routes.py`
- `config/settings.py`

### Definisi selesai

- rotasi tidak menyebabkan cache miss spike yang terukur
- grace period dapat dikonfigurasi dan berfungsi sesuai spesifikasi
- audit trail mencatat seluruh siklus rotasi dengan timestamp akurat
- tidak ada window di mana kedua kunci tidak tersedia selama rotasi

### Validasi minimum

- test rotasi dengan traffic aktif dan ukur cache miss rate sebelum/selama/sesudah
- test grace period: kunci lama masih valid sebelum grace period habis
- test atomicity: simulasikan Redis failure selama invalidasi dan verifikasi konsistensi
- verifikasi audit trail mencatat semua event rotasi

---

## 7. Governance Model Release

**Prioritas:** `P1`

### Tujuan

Membawa pipeline model dari sekadar "aman dimuat" menjadi "aman dirilis dan dioperasikan".

### Kondisi saat ini

- training script menghasilkan artefak `.pskc.json`
- registry memverifikasi checksum dan signature metadata
- provenance dasar, active version, promote, rollback, dan lifecycle log sudah aktif
- runtime trainer/predictor memuat active version dari registry
- **Ensemble Model (LSTM + RandomForest + Markov Chain) sudah aktif dan berjalan di runtime**
- **LSTM sudah terintegrasi penuh dalam pipeline prediksi**
- Online learning dengan concept drift EWMA ada di desain, tapi masih belum matang penuh (lihat item 4)

### Fitur yang perlu dikembangkan

1. **Approval flow antar stage**
   - promotion saat ini masih bisa dilakukan langsung
   - perlu workflow approval untuk pindah dari `development → staging → production`

2. **Release criteria yang eksplisit**
   - threshold akurasi minimum
   - data volume minimum
   - tidak ada integrity issue
   - bukti evaluasi yang terdokumentasi

3. **External provenance**
   - ikat model ke commit SHA
   - simpan metadata environment training
   - jika memungkinkan, tambahkan attestation atau manifest supply-chain

4. **Registry retention dan cleanup**
   - policy untuk jumlah versi yang disimpan
   - policy untuk versi yang boleh dihapus
   - perlindungan agar active version atau version production tidak terhapus sembarangan

5. **Release playbook**
   - kapan promote
   - kapan rollback
   - bagaimana menilai drift
   - bagaimana menangani signature mismatch

### Area kode yang kemungkinan terdampak

- `scripts/train_model.py`
- `src/ml/model_registry.py`
- `src/ml/trainer.py`
- `src/api/ml_service.py`
- `src/api/routes.py`
- `docs/simulation_and_ml.md`

### Definisi selesai

- setiap perubahan stage model punya jejak approval atau alasan release
- rollback bukan hanya fitur teknis, tetapi juga prosedur operasional yang terdokumentasi
- provenance model cukup untuk melacak asal artefak dan konteks training

### Validasi minimum

- regression test untuk approval gate
- test integritas registry setelah promote/rollback
- smoke test runtime load setelah promotion

---

## 8. Key Lifecycle Management

**Prioritas:** `P1`

### Tujuan

Membuat PSKC terasa seperti sistem manajemen key yang lebih lengkap, bukan hanya secure cache. Mencakup revokasi responsif sesuai temuan tentang window of vulnerability (Ozcelik & Skjellum, 2021).

### Kondisi saat ini

- key bisa disimpan, diakses, dan di-cache dengan jalur yang aman
- IDS, audit, dan cache policy sudah aktif
- endpoint `/keys/invalidate` sudah ada
- revoke, rotate, expire, consume, dan ACL per service belum menjadi workflow utuh
- parameter `ttl` di `/keys/store` belum diteruskan ke secure store

### Fitur yang perlu dikembangkan

1. **Revocation yang responsif**
   - key yang ditarik harus bisa dihapus dari seluruh layer cache (L1 dan L2) secara instan
   - event revocation harus terekam di audit log dengan timestamp akurat
   - meminimalkan window of vulnerability antara keputusan revokasi dan efektivitas di cache

2. **TTL forwarding di `/keys/store`**
   - perbaiki implementasi endpoint agar parameter `ttl` benar-benar diteruskan ke `secure_set()`
   - TTL dinamis dari `CachePolicyManager` tetap berlaku sebagai fallback

3. **Rotation workflow** (lihat juga item 6)
   - versi key lama dan baru
   - graceful transition
   - invalidation policy untuk material lama

4. **Expiration and consume semantics**
   - tidak semua key cocok dengan TTL sederhana
   - beberapa material mungkin one-time use atau bounded use

5. **Service-level authorization**
   - service mana boleh akses key apa
   - audit jika service keluar dari scope

6. **Incident response hooks**
   - purge cepat
   - denylist service
   - emergency mode untuk access throttling

### Area kode yang kemungkinan terdampak

- `src/security/intrusion_detection.py`
- `src/cache/encrypted_store.py`
- `src/api/routes.py`
- `src/auth/`
- `docs/security_model.md`

### Definisi selesai

- lifecycle key punya event dan aturan yang eksplisit
- revoke/rotate tidak bergantung pada intervensi manual di cache
- service authorization bisa dipaksa di jalur request utama
- parameter `ttl` di `/keys/store` berfungsi sesuai schema

### Validasi minimum

- test revoke ke semua layer cache (L1 dan L2)
- test TTL forwarding di `/keys/store`
- test rotation rollout
- test authorization violation dan audit trail

---

## 9. Admin dan Ops Control Plane

**Prioritas:** `P1`

### Tujuan

Memberikan operator kontrol yang cukup tanpa harus masuk langsung ke file system atau Redis.

### Kondisi saat ini

- beberapa endpoint observability sudah tersedia
- audit dan intrusion inspection sudah ada
- belum ada admin API yang rapi untuk control plane operasional

### Fitur yang perlu dikembangkan

1. **Admin endpoints untuk cache**
   - cache summary per service
   - invalidate by prefix
   - inspect TTL
   - warmup status

2. **Admin endpoints untuk model**
   - versi model per stage
   - active version history
   - compare registry entries
   - export lifecycle summary

3. **Admin endpoints untuk security**
   - intrusion summary
   - current blocked IP list
   - reputation view
   - audit recovery history

4. **AuthN/AuthZ untuk control plane**
   - endpoint admin tidak boleh sekadar bergantung pada topologi jaringan
   - perlu auth yang konsisten

### Area kode yang kemungkinan terdampak

- `src/api/routes.py`
- `src/api/schemas.py`
- `src/security/intrusion_detection.py`
- `src/security/tamper_evident_logger.py`
- `docs/api_reference.md`

### Definisi selesai

- operator bisa melakukan inspeksi dan tindakan dasar tanpa akses shell langsung
- endpoint admin dibedakan jelas dari endpoint aplikasi biasa
- access control untuk admin endpoint tidak ambigu

### Validasi minimum

- test authorization admin endpoint
- test destructive-control safeguard
- smoke test cache/model/security admin flows

---

## 10. River Online Learning Integration

**Prioritas:** `P2`

> **Catatan konsistensi paper:** README dan dokumentasi teknis awal menyebut River sebagai komponen online learning. Saat ini RF+Markov sudah stabil. Item ini mengintegrasikan River untuk true incremental learning tanpa mengganggu ensemble yang sudah ada.

### Tujuan

Mengintegrasikan library River agar model PSKC dapat diperbarui secara inkremental per event akses, tanpa memerlukan full retraining yang membutuhkan batch data.

### Kondisi saat ini

- `EnsembleModel` mendukung LSTM + RandomForest + Markov Chain
- retraining saat ini memerlukan batch data yang cukup via `/ml/retrain`
- River belum ada di `requirements.txt` atau pipeline training

### Fitur yang perlu dikembangkan

1. **River model wrapper**
   - bungkus River classifier atau regressor yang kompatibel dengan interface `EnsembleModel`
   - River component menjadi member keempat ensemble, bukan pengganti

2. **Incremental update per event**
   - setiap event akses yang direkam oleh `DataCollector` juga men-trigger River update
   - update River tidak memblokir request path (async atau background)

3. **Kompatibilitas dengan model registry**
   - artefak River dapat disimpan dan dimuat melalui `ModelRegistry` yang sudah ada
   - checksum dan signature berlaku untuk artefak River

4. **Fallback yang aman**
   - jika River update gagal, ensemble tetap berfungsi dengan RF+Markov
   - error River tidak propagate ke request path utama

5. **Kontribusi River ke prediksi ensemble**
   - tentukan bobot kontribusi River vs RF vs Markov dalam ensemble vote
   - bobot dapat dikonfigurasi dan didokumentasikan

### Area kode yang kemungkinan terdampak

- `src/ml/model.py`
- `src/ml/trainer.py`
- `src/ml/data_collector.py`
- `src/ml/model_registry.py`
- `requirements.txt`

### Definisi selesai

- River terintegrasi sebagai komponen ensemble keempat
- update inkremental berjalan tanpa memblokir request path
- artefak River kompatibel dengan model registry yang sudah ada
- fallback ke ensemble tanpa River berjalan dengan benar

### Validasi minimum

- unit test untuk River wrapper
- test incremental update tanpa memblokir latency request
- test fallback saat River update gagal
- smoke test artefak River di model registry

---

## 11. Frontend Productization

**Prioritas:** `P2`

### Tujuan

Mengurangi jejak demo-heavy yang tersisa dan membuat UI lebih cocok sebagai client operasional.

### Kondisi saat ini

- overview, dashboard, simulation, dan ML pipeline sudah membaca backend
- beberapa area UI masih menyisakan pola presentasional atau state demo lama
- frontend Docker masih berupa Vite dev server

### Fitur yang perlu dikembangkan

1. **Pembersihan mode demo**
   - pastikan area UI yang tersisa tidak kembali ke dataset lokal diam-diam
   - audit utilitas fallback yang masih tersisa

2. **Halaman operator**
   - registry model
   - lifecycle model
   - prefetch queue/DLQ
   - audit dan intrusion overview
   - status drift EWMA (terintegrasi dengan item 4)

3. **Error handling frontend**
   - tampilkan perbedaan antara no data, backend down, security denied, dan worker lag

4. **Frontend build production**
   - Docker image production
   - static serving yang benar
   - env strategy yang konsisten

### Area kode yang kemungkinan terdampak

- `frontend/src/pages/`
- `frontend/src/utils/`
- `frontend/vite.config.js`
- `docker-compose.yml`
- `docs/getting_started.md`

### Definisi selesai

- UI utama tidak bergantung pada data demo lokal
- operator bisa melihat state backend penting dari UI termasuk status drift
- container frontend tidak lagi hanya dev server

### Validasi minimum

- build frontend production
- smoke test UI terhadap backend live
- regression test untuk API error states di halaman utama

---

## 12. Test Matrix dan CI yang Lebih Lengkap

**Prioritas:** `P2`

### Tujuan

Membuat perubahan besar di repository ini bisa divalidasi tanpa banyak tebakan manual, termasuk memastikan klaim performa di paper tidak mengalami regresi.

### Kondisi saat ini

- focused backend tests sudah ada
- smoke backend live via Docker sudah ada
- seluruh repo belum bisa dijadikan sinyal hijau tunggal karena masih ada jejak legacy

### Fitur yang perlu dikembangkan

1. **Pisahkan test legacy vs current architecture**
   - tandai mana test yang memang obsolete
   - jangan biarkan `pytest` penuh ambigu selamanya

2. **Topology matrix**
   - local runtime
   - Docker runtime
   - monitoring profile
   - proxy-enabled topology

3. **Failure-path suite**
   - Redis unavailable
   - audit log recovery
   - model integrity failure
   - queue backlog
   - drift detection trigger

4. **Performance and load validation**
   - baseline latency
   - prefetch throughput
   - cache hit behavior
   - benchmark regression gate (terintegrasi dengan item 5)

5. **Docs gate minimum**
   - perubahan endpoint harus memicu review docs terkait
   - perubahan env/deploy harus memicu review operations docs

### Area kode yang kemungkinan terdampak

- `.github/workflows/`
- `tests/`
- `scripts/smoke_backend_runtime.py`
- `docs/`

### Definisi selesai

- ada subset test yang jelas untuk health repo saat ini
- ada smoke matrix minimum untuk topology utama
- kegagalan production-critical punya coverage otomatis
- benchmark regression gate aktif di CI

### Validasi minimum

- workflow CI baru
- test failure-path yang benar-benar dapat dipicu
- dokumentasi matrix test di `docs/development.md`

---

## 13. Multi-Environment Artifacts

**Prioritas:** `P3`

### Tujuan

Mengurangi jarak antara environment demo dan environment yang lebih serius.

### Kondisi saat ini

- Docker Compose dev/demo sudah ada
- belum ada manifest yang benar-benar dirancang untuk staging/production

### Fitur yang perlu dikembangkan

1. **Compose override atau manifest per environment**
   - dev
   - staging
   - production-like

2. **Secret handling yang lebih matang**
   - jangan hanya mengandalkan `.env`
   - dokumentasikan integrasi ke secret manager atau injection environment yang lebih aman

3. **Storage dan retention policy**
   - log
   - model registry
   - audit backup
   - metrics

### Definisi selesai

- environment demo tidak lagi diperlakukan seolah sama dengan staging/production
- operator punya contoh manifest yang masuk akal untuk lebih dari satu environment

---

## Urutan Implementasi yang Masuk Akal

Jika hanya satu tim kecil yang mengerjakan repo ini, urutan yang paling pragmatis adalah:

1. deployment dan topologi runtime
2. observability historis
3. concept drift EWMA maturation ← **kritis untuk konsistensi paper**
4. benchmark validation suite ← **kritis untuk validasi klaim performa**
5. zero-downtime key rotation ← **kritis untuk konsistensi paper**
6. prefetch orchestration yang matang
7. key lifecycle management
8. governance model release yang lebih formal
9. admin dan ops control plane
10. river online learning integration
11. frontend productization
12. test matrix dan CI yang lebih lengkap
13. multi-environment artifacts

Item 3, 4, dan 5 dinaikkan prioritasnya dalam urutan ini karena ketiganya berkaitan langsung dengan klaim yang dibuat di paper akademis PSKC. Konsistensi antara implementasi dan narasi paper adalah hal yang tidak bisa ditunda.

---

## Matriks Konsistensi Paper vs Roadmap

Tabel ini merangkum klaim utama di paper PSKC dan status coverage-nya di roadmap ini.

| Klaim di Paper | Item Roadmap | Status |
| --- | --- | --- |
| Ensemble LSTM+RF+Markov aktif | Item 7 (Governance) | ✅ Sudah aktif di runtime |
| Concept drift EWMA terimplementasi | Item 4 (EWMA Maturation) | 🔄 Dalam pengembangan |
| Rotasi kunci tanpa downtime | Item 6 (Zero-Downtime Rotation) | 🔄 Dalam pengembangan |
| Reduksi latensi 86% terverifikasi | Item 5 (Benchmark Validation) | 🔄 Dalam pengembangan |
| AES-256-GCM cache enkripsi | Item 1 (Deployment) | ✅ Aktif |
| Prefetch prediktif aktif | Item 3 (Prefetch Orchestration) | ✅ Aktif, maturasi ongoing |
| Tamper-evident audit HMAC chain | Item 9 (Admin Control Plane) | ✅ Aktif |
| Window of vulnerability mitigation | Item 8 (Key Lifecycle) | 🔄 Dalam pengembangan |
| Online learning inkremental (River) | Item 10 (River Integration) | 🔄 Planned |
| TTL dinamis berbasis pola akses | Item 8 (Key Lifecycle) | 🔄 Perbaikan TTL forwarding |

---

## Template Breakdown Pekerjaan

Jika sebuah item di dokumen ini mau dipecah menjadi issue atau task implementasi, format minimalnya sebaiknya seperti ini:

| Field | Isi |
| --- | --- |
| tujuan | capability yang ingin dicapai |
| scope | file atau subsistem yang boleh berubah |
| non-goal | hal yang sengaja tidak dikerjakan dulu |
| risiko | regresi atau risiko security/ops |
| validasi | test, smoke, atau metric yang harus lulus |
| dokumentasi | file docs yang wajib ikut diperbarui |

---

## Dokumen Terkait

- [project_status.md](project_status.md)
- [architecture.md](architecture.md)
- [api_reference.md](api_reference.md)
- [security_model.md](security_model.md)
- [simulation_and_ml.md](simulation_and_ml.md)
- [operations.md](operations.md)
- [development.md](development.md)