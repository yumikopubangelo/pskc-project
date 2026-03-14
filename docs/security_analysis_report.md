# Security Analysis Status Report

Tanggal update: 2026-03-10

Dokumen ini merangkum status terbaru dari temuan keamanan historis yang sebelumnya dijelaskan secara lebih panjang pada audit internal 2026-03-08. Fokus dokumen ini adalah "apa statusnya sekarang di kode".

## Ringkasan Eksekutif

Empat temuan utama historis masih relevan sebagai konteks desain. Namun status mitigasinya sekarang berbeda:

| Finding | Severity historis | Status sekarang | Ringkasan |
| --- | --- | --- | --- |
| Nonce reuse pada AES-GCM | Critical | Mostly mitigated | Jalur cache aktif kini memakai nonce acak 96-bit di `FipsCryptographicModule`. |
| IP spoofing via forwarded headers | High | Mitigated in active route helper | `X-Forwarded-For` hanya dipercaya bila koneksi berasal dari trusted proxy. |
| Cache poisoning via ML prefetch | High | Partially mitigated | Ada guard awal di predictor dan prefetch request-path sudah aktif, tetapi IDS detail dan isolasi worker masih parsial. |
| Model registry tanpa integrity check | Critical | Partially mitigated operationally | Checksum verification dan blok `.pkl` saat load sudah ada, tetapi training pipeline masih menghasilkan `.pkl`. |

## 1. Nonce Reuse pada AES-GCM

### Risiko historis

Versi lama mengandalkan nonce manager berbasis counter, yang rawan reuse saat proses restart.

### Status saat ini

Jalur enkripsi cache yang aktif sekarang memakai `FipsCryptographicModule.encrypt_data()` dengan nonce acak 96-bit:

- file: `src/security/fips_module.py`
- mekanisme: `secrets.token_bytes(12)`

### Penilaian

- status: mostly mitigated pada jalur cache yang aktif
- residual risk: masih perlu verifikasi menyeluruh bahwa tidak ada jalur lama yang dipakai diam-diam oleh modul legacy atau test lama

## 2. IP Spoofing lewat `X-Forwarded-For`

### Risiko historis

Versi lama mempercayai header forwarded dari source mana pun.

### Status saat ini

`src/api/routes.py` memakai helper `_extract_client_ip()` yang:

1. membaca IP koneksi langsung terlebih dahulu
2. mengecek apakah source termasuk `TRUSTED_PROXIES`
3. hanya lalu memakai `X-Forwarded-For`

Middleware keamanan di `src/security/security_headers.py` mengikuti pola yang sama.

### Penilaian

- status: mitigated pada helper route aktif
- residual risk: `TRUSTED_PROXIES` default masih kosong, sehingga deployment harus mengisinya sendiri

## 3. Cache Poisoning pada Predictor / Prefetch

### Risiko historis

Penyerang dapat memanipulasi pola akses agar model lebih sering memprediksi key yang salah dan mengusir key valid dari cache.

### Status saat ini

Ada perbaikan awal:

- `src/ml/predictor.py` menambahkan `_is_suspicious_pattern()` untuk mendeteksi rasio key unik yang terlalu rendah
- `src/security/intrusion_detection.py` menyediakan `SecureCacheManager` dan kerangka IDS

Namun implementasi belum selesai:

- beberapa method IDS masih stub
- hardening predictor dan secure cache masih perlu validasi runtime tambahan
- prefetch otomatis sekarang sudah menjadi bagian dari jalur request API, tetapi belum dipisahkan ke worker yang lebih terkontrol

### Penilaian

- status: partially mitigated
- residual risk: integrasi ML-to-cache masih butuh refactor lanjutan sebelum kontrol ini dapat dinilai efektif secara runtime

## 4. Model Integrity dan Unsafe Deserialization

### Risiko historis

Registry lama dapat memuat file model tanpa checksum dan tanpa pembatasan deserialization berbahaya.

### Status saat ini

`src/ml/model_registry.py` sekarang:

- mewajibkan manifest `checksums.json`
- memverifikasi SHA-256 sebelum load
- menolak file `.pkl` saat load
- memakai `torch.load(..., weights_only=True)` untuk `.pt`

Gap yang masih tersisa:

- release governance antar environment masih dasar
- provenance eksternal seperti commit signing atau supply-chain attestation belum ada

### Penilaian

- status: mitigated operationally
- residual risk: approval policy dan provenance eksternal masih perlu dilapisi di atas registry lokal

## Kesimpulan

Dibanding audit historis, perbaikan paling nyata ada pada:

- boundary kriptografi yang lebih jelas
- nonce generation yang lebih aman
- checksum verification untuk artefak model
- parsing IP yang tidak lagi trust-by-default

Area yang masih perlu perhatian sebelum siap untuk deployment lebih serius:

1. menyelesaikan aktivasi self-tests dan memisahkan policy endpoint internal/publik di atas middleware keamanan yang sekarang sudah aktif
2. memperkuat hardening predictor dan secure cache pada flow prefetch yang sekarang sudah aktif
3. menyelaraskan format artefak training dengan registry hardened
4. memvalidasi seluruh request path setelah refactor FIPS-style terakhir

## Dokumen Terkait

- [security_model.md](security_model.md)
- [operations.md](operations.md)
- [development.md](development.md)
