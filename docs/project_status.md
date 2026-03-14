# Project Status

Dokumen ini adalah daftar status proyek yang fokus pada tiga pertanyaan:

1. apa yang sudah ada tetapi belum selesai
2. apa yang masih kurang untuk membuat sistem lebih utuh
3. apa yang belum dikembangkan sama sekali

Dokumen ini sengaja lebih operasional daripada dokumen arsitektur. Tujuannya agar siapa pun yang masuk ke repository ini bisa cepat melihat gap nyata tanpa harus menyimpulkannya sendiri dari kode.

Jika Anda membutuhkan versi yang lebih rinci per area fitur, dependensi, definisi selesai, dan validation plan, baca [feature_roadmap.md](feature_roadmap.md).

## Cara Membaca

- `Belum selesai`: fitur atau refactor sudah dimulai di kode, tetapi belum tuntas atau belum aman dianggap siap pakai.
- `Masih kurang`: komponen pendukung, pengujian, konfigurasi, atau dokumentasi pelengkap yang dibutuhkan agar sistem lebih lengkap.
- `Belum dikembangkan`: capability yang masuk akal untuk PSKC tetapi saat ini belum benar-benar dibangun.

## 1. Belum Selesai

Bagian ini berisi hal-hal yang sudah tampak di kode, tetapi implementasinya belum lengkap.

| Item | Status saat ini | Dampak | Area kode terkait |
| --- | --- | --- | --- |
| Coverage formal request path backend | jalur `store/access/invalidate/security` sudah tervalidasi dengan test terfokus hit/miss/error dan smoke runtime live via `docker compose`, tetapi belum ada suite integration penuh untuk seluruh topology deploy | core API lebih stabil, tetapi regresi lintas environment dan profile deployment masih perlu coverage tambahan | `src/api/routes.py`, `src/cache/encrypted_store.py`, `src/security/intrusion_detection.py`, `tests/test_api_request_paths.py`, `scripts/smoke_backend_runtime.py` |
| Hardening prefetch runtime dan Redis queue | predictor, worker, shared cache Redis, retry, dan DLQ dasar sudah tersambung, tetapi replay, alerting, dan kontrol operasionalnya masih minim | flow prefetch aktif tetapi belum siap dianggap matang untuk produksi | `src/ml/predictor.py`, `src/api/ml_service.py`, `src/workers/prefetch_worker.py`, `src/cache/redis_cache.py`, `src/prefetch/queue.py` |
| Docker frontend untuk SPA aktual | frontend lokal berjalan via Vite, tetapi service Docker frontend hanya mount static `public/` | UI di container tidak mewakili aplikasi React yang sebenarnya | `frontend/`, `docker-compose.yml` |
| Penyelarasan test suite setelah refactor | banyak test masih mengacu ke modul/interface lama | sulit memakai `pytest` penuh sebagai indikator kesehatan repo | `tests/` |

## 2. Masih Kurang

Bagian ini berisi hal-hal yang dibutuhkan agar sistem lebih lengkap secara engineering dan operasional.

| Item | Yang kurang | Dampak |
| --- | --- | --- |
| Konfigurasi monitoring | `config/prometheus.yml` dan endpoint `/metrics/prometheus` sudah ada | profile `monitoring` sekarang bisa start, tetapi exporter masih memotret state runtime dasar |
| Endpoint observability nyata | endpoint inti seperti `/metrics`, `/metrics/cache-distribution`, `/metrics/latency`, dan `/metrics/accuracy` sudah ada, tetapi datanya masih in-memory dan historinya terbatas | telemetry backend sudah tersedia untuk UI utama, tetapi belum cukup matang untuk observability operasional penuh |
| Integration test dan smoke test formal | sudah ada smoke backend live yang memvalidasi startup, cache hit/miss, audit log, simulation, metrics, dan worker prefetch; tetapi belum ada matrix end-to-end untuk seluruh profile/topology | refactor besar lebih mudah diverifikasi, tetapi coverage deployment masih belum menyeluruh |
| CI untuk lint/test/docs | workflow minimum backend sudah ada untuk focused tests dan Docker smoke | regresi utama lebih mudah tertangkap, tetapi lint/docs gate dan matrix tambahan masih belum ada |
| Deployment notes yang lebih spesifik | belum ada contoh topologi reverse proxy, volume log, trusted proxy config, dan hardening production yang lebih konkret | operator harus banyak menebak sendiri saat deploy |
| Error handling yang lebih ketat di API | beberapa jalur masih berpotensi me-return `500` generik | observability buruk dan perilaku API kurang presisi |
| Sinkronisasi frontend dengan backend aktual | halaman utama frontend sekarang sudah sinkron untuk overview, dashboard, simulation, dan ML pipeline, tetapi masih ada area legacy yang belum disederhanakan | sebagian besar UI utama sudah selaras, namun jejak kode lama masih perlu dibersihkan |
| Lifecycle operasional artefak model | format artefak aman, checksum manifest, signing metadata, provenance, active version, promotion, rollback, dan runtime load sekarang sudah satu jalur | operasi registry model sudah jauh lebih konsisten, walau governance antar environment masih perlu diperdalam |

## 3. Belum Dikembangkan

Bagian ini berisi kemampuan yang relevan untuk visi PSKC, tetapi saat ini belum benar-benar dibangun.

| Capability | Kondisi saat ini | Nilai jika dikembangkan |
| --- | --- | --- |
| Distributed cache runtime yang lebih matang | request path sudah memakai Redis sebagai L2 shared cache, tetapi belum ada topologi multi-node, failover, atau kebijakan eviction operasional yang matang | memungkinkan beberapa service instance berbagi cache dan state dengan cara yang lebih realistis dan tahan gangguan |
| Prefetch orchestration yang lebih matang | worker prefetch Redis sudah punya retry dan DLQ dasar, tetapi belum punya replay tooling, rate control, atau autoscaling | membuat PSKC predictive cache sungguhan yang bisa dioperasikan dengan lebih aman |
| Model deployment pipeline yang aman penuh | training script, registry, secure load, signing metadata, dan release control dasar sekarang sudah aktif; yang belum adalah approval workflow antar environment dan provenance eksternal | menutup gap antara training, registry, dan secure loading dengan kontrol operasional yang lebih matang |
| Endpoint admin/ops khusus | belum ada endpoint nyata untuk cache stats, model stats, audit summaries, atau controls | mempermudah operasi, inspeksi, dan debugging |
| Telemetry historis backend untuk dashboard | dashboard utama sudah membaca backend nyata, tetapi histori metrik masih hidup di memori proses dan mudah hilang saat restart | membuat UI lebih dekat ke alat observability sungguhan |
| Access control yang lebih dalam | ada pondasi security dan ACL di beberapa modul, tetapi belum jadi policy runtime terpadu | meningkatkan isolasi antar service dan kontrol akses sensitif |
| Key lifecycle management lengkap | revoke, rotate, expire, consume sudah tersirat di beberapa area tetapi belum jadi flow utuh | penting untuk sistem manajemen key yang lebih realistis |
| Multi-environment deployment artifacts | belum ada manifest yang rapi untuk staging/production selain Docker Compose demo | mempermudah transisi dari demo ke lingkungan yang lebih serius |

## Prioritas Yang Disarankan

Jika proyek ini ingin dinaikkan dari demo riset menjadi sistem yang lebih rapi, urutan prioritas yang masuk akal adalah:

1. Perluas validasi deployment yang baru ditambahkan ke topology yang lebih realistis: reverse proxy, monitoring profile, dan failure path Redis.
2. Rapikan kontrol keamanan yang tersisa: pemisahan endpoint internal/publik dan hardening policy deployment.
3. Rapikan test suite minimum yang relevan dengan arsitektur baru.
4. Matangkan governance operasional model: approval flow antar environment, provenance eksternal, dan audit release yang lebih formal.
5. Baru setelah itu lanjut ke observability nyata, tuning Redis/worker, dan hardening operasi prefetch.

## Definisi Selesai Yang Praktis

Sebuah item di dokumen ini bisa dianggap selesai jika:

1. implementasinya aktif di jalur runtime yang relevan
2. perilakunya terdokumentasi di `README.md` atau dokumen teknis terkait
3. ada validasi minimal, baik lewat smoke test, integration test, atau test terfokus
4. tidak lagi bertentangan dengan dokumen lain di folder `docs/`

## Dokumen Terkait

- [getting_started.md](getting_started.md)
- [architecture.md](architecture.md)
- [development.md](development.md)
- [operations.md](operations.md)
- [simulation_and_ml.md](simulation_and_ml.md)
