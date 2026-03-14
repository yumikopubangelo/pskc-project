# Model Keamanan PSKC

Dokumen ini menjelaskan kontrol keamanan yang aktif, kontrol yang masih parsial, dan implikasi operasional dari implementasi saat ini.

## Tujuan Keamanan

Aset utama yang dilindungi oleh PSKC adalah material kunci kriptografi yang disimpan sementara di cache lokal untuk mengurangi latensi autentikasi.

Tujuan utama:

1. Menjaga kerahasiaan key saat berada di cache.
2. Menjaga integritas data cache dan audit trail.
3. Mengurangi peluang spoofing pada pemeriksaan IP.
4. Mengurangi risiko model tampering untuk artefak ML.
5. Memberi jalur fail-safe ketika komponen sensitif tidak sehat.

## Kontrol Keamanan yang Aktif Saat Ini

| Kontrol | Status | File utama | Catatan |
| --- | --- | --- | --- |
| AES-256-GCM untuk cache data | aktif | `src/security/fips_module.py` | nonce dibangkitkan acak 96-bit melalui `secrets.token_bytes(12)` |
| HKDF derivation untuk master key | aktif | `src/security/fips_module.py` | master key di-derive dari `CACHE_ENCRYPTION_KEY` |
| FIPS power-on self-tests | aktif by default | `src/security/fips_self_tests.py`, `src/api/routes.py` | startup sekarang menjalankan KAT/fungsi dasar dan fail-fast jika boundary kriptografi rusak |
| Tamper-evident audit log | aktif secara desain | `src/security/tamper_evident_logger.py` | memakai hash chain dan signature berbasis boundary crypto |
| Trusted proxy aware IP extraction | aktif di route helper | `src/api/routes.py` | `X-Forwarded-For` tidak dipercaya dari sembarang source |
| Model checksum verification | aktif di registry | `src/ml/model_registry.py` | `checksums.json` wajib untuk load model |
| Model metadata signing dan provenance | aktif di registry | `src/ml/model_registry.py` | versi model disign, stage/provenance dilacak, dan lifecycle disimpan persisten |
| Blok `.pkl` saat load | aktif | `src/ml/model_registry.py` | registry menolak unsafe deserialization |

## Kontrol yang Masih Parsial

| Kontrol | Status | File utama | Dampak |
| --- | --- | --- | --- |
| HTTP security headers middleware | aktif by default | `src/security/security_headers.py`, `src/api/routes.py` | HSTS, CSP, request-size limit, host validation, dan path traversal guard sekarang aktif pada app FastAPI |
| Sliding window rate limiter | aktif by default | `src/security/security_headers.py`, `src/api/routes.py` | rate limiting sekarang enforced di middleware level dan dapat di-tuning via `HTTP_RATE_LIMIT_*` |
| IDS behavior detail | aktif dasar | `src/security/intrusion_detection.py` | reputation gate, rate check, nonce reuse guard, cache-poisoning heuristics, dan alert buffer sudah aktif pada jalur runtime utama |
| Predictive prefetch hardening | parsial | `src/ml/predictor.py` | background prefetch request-path sudah aktif, tetapi IDS detail dan isolasi worker masih belum penuh |

## Batas Kepatuhan FIPS

PSKC memakai istilah "FIPS-style" atau "FIPS boundary" karena arsitekturnya sudah mengisolasi operasi kriptografi ke satu wrapper khusus. Namun:

- backend yang dipakai masih library `cryptography` umum, bukan modul yang tersertifikasi FIPS 140-2 atau FIPS 140-3
- self-test KAT sekarang aktif saat startup, tetapi backend kriptografi yang dipakai tetap belum tersertifikasi FIPS
- deployment belum mengandalkan HSM atau FIPS provider tersertifikasi

Kesimpulan: arsitektur menuju kepatuhan sudah ada, tetapi sistem ini belum dapat diklaim sebagai FIPS compliant.

## Threat Model Ringkas

| Threat | Risiko utama | Status mitigasi saat ini |
| --- | --- | --- |
| Nonce reuse pada AES-GCM | kebocoran ciphertext dan tag forgery | sebagian besar tertangani pada jalur cache baru karena nonce full-random |
| IP spoofing via `X-Forwarded-For` | bypass akses berbasis IP | tertangani pada helper route selama `TRUSTED_PROXIES` dikonfigurasi benar |
| Cache poisoning melalui pola akses | degradasi performa dan eviction key valid | parsial, ada guard di predictor dan IDS serta flow prefetch aktif, tetapi kontrol detailnya belum penuh |
| Model tampering / unsafe load | remote code execution | checksum, signature metadata, provenance, dan blok `.pkl` saat load sudah diterapkan |
| Audit log tampering | hilangnya jejak forensik | hash chain dan signature sudah ada di logger |

## Implikasi Deployment

Jika ingin menjalankan PSKC di lingkungan yang lebih serius, minimal lakukan:

1. Isi `CACHE_ENCRYPTION_KEY` dengan secret acak yang kuat.
2. Konfigurasikan `TRUSTED_PROXIES` sesuai topologi proxy/load balancer Anda.
3. Tinjau `HTTP_SECURITY_*` dan `HTTP_RATE_LIMIT_*` agar sesuai kebutuhan deployment Anda.
4. Pastikan direktori log persisten dan dapat ditulis oleh proses aplikasi.
5. Jalankan smoke test deployment setelah perubahan config/proxy/Redis; jalur request inti sudah tervalidasi di test terfokus, tetapi topologi deploy tetap perlu diverifikasi di environment aktual.
6. Gunakan artefak model yang bisa diverifikasi checksum, signature, dan tidak memakai `.pkl` untuk load.

## Catatan Khusus Tentang Audit Log

Logger audit menulis ke file `pskc_audit.log` di direktori `/app/logs`. Untuk container deployment, direktori itu sebaiknya di-mount ke volume persisten. Untuk local development, perhatikan bahwa path absolut tersebut mungkin perlu disesuaikan jika tidak ingin log ditulis ke root filesystem lokal.

## Referensi Tambahan

- [security_analysis_report.md](security_analysis_report.md)
- [operations.md](operations.md)
- [architecture.md](architecture.md)
