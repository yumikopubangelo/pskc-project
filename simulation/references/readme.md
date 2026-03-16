# Simulation References & Parameters

Dokumen ini menjelaskan parameter simulasi PSKC, sumber referensi yang digunakan, dan cara menginterpretasikan hasil simulasi.

Simulasi PSKC menggunakan dua lapisan referensi:

1. **Skenario utama** — berbasis konteks sistem informasi perguruan tinggi Indonesia
2. **Referensi metodologi** — berbasis sistem produksi global untuk validasi model distribusi dan parameter teknis KMS

---

## Struktur Dokumen

- [Skenario Utama (Indonesia)](#skenario-utama-indonesia)
  - [Skenario 1: SIAKAD SSO](#skenario-1-siakad-sso--perguruan-tinggi-tunggal)
  - [Skenario 2: SEVIMA SiakadCloud](#skenario-2-sevima-siakadcloud--multi-tenant)
  - [Skenario 3: PDDikti](#skenario-3-pddikti--skala-nasional)
- [Referensi Metodologi (Global)](#referensi-metodologi-global)
- [Baseline Universal](#baseline-universal)
- [Model Distribusi Latensi](#model-distribusi-latensi)
- [Cara Mengutip Hasil Simulasi](#cara-mengutip-hasil-simulasi)
- [Perubahan dari Versi Sebelumnya](#perubahan-dari-versi-sebelumnya)
- [File Terkait](#file-terkait)

---

## Skenario Utama (Indonesia)

Ketiga skenario berikut merepresentasikan konteks nyata sistem informasi perguruan tinggi Indonesia, di mana latensi autentikasi menjadi bottleneck yang teridentifikasi di literatur lokal.

---

### Skenario 1: SIAKAD SSO — Perguruan Tinggi Tunggal

**File simulasi:** `simulation/scenarios/siakad_sso.py`
**Parameter file:** `simulation/parameters/siakad_params.json`

#### Konteks

Sistem informasi akademik berbasis SSO di perguruan tinggi tunggal adalah kasus yang paling representatif untuk mayoritas institusi pendidikan tinggi Indonesia. Salmuasih dan Setiawan (2023) mendokumentasikan bahwa dari 17 PT di Yogyakarta, banyak yang belum mengoptimasi implementasi SSO berbasis SAML dan OAuth 2.0, menghasilkan overhead validasi yang signifikan. Rezaldy dkk. (2017) mengidentifikasi masalah serupa pada iGracias Universitas Telkom yang mengintegrasikan SIAKAD, LMS (iDea), dan e-library dalam satu SSO.

Traffic sistem ini bersifat sangat seasonal: terjadi spike besar selama periode KRS, registrasi semester, dan ujian.

#### Parameter Simulasi

| Parameter | Nilai | Sumber / Justifikasi |
| --- | --- | --- |
| Baseline avg latency | 197 ms | MDPI Applied Sciences (2025) — 500 successful logins |
| Baseline P95 latency | 270 ms | MDPI Applied Sciences (2025) |
| Baseline P99 latency | 320 ms | MDPI Applied Sciences (2025) |
| Traffic pattern | Bursty seasonal | Periode KRS dan registrasi semester |
| Peak multiplier | 3–5× normal traffic | Estimasi konservatif untuk PT menengah |
| Request count (simulasi default) | 1.000 request | Representatif satu sesi registrasi aktif |
| Distribusi latensi | Log-normal | Spotify Engineering Blog (2015) — prinsip universal |
| Cache TTL range | 5–300 detik | Diderivasi dari AWS KMS recommendation |

#### Karakteristik Khas

- Mayoritas request adalah JWT verification untuk SSO
- Pola akses kunci sangat terprediksi: cluster per periode akademik
- Cold start terjadi di awal semester baru saat pola akses berubah
- PSKC diharapkan paling efektif pada fase mature setelah model selesai warmup

#### Referensi Utama

- Salmuasih & Setiawan (2023) — `salmuasih_setiawan_2023`
- Rezaldy dkk. (2017) — `rezaldy_2017`
- MDPI Applied Sciences (2025) — `mdpi_auth_2025` (baseline latensi)

---

### Skenario 2: SEVIMA SiakadCloud — Multi-Tenant

**File simulasi:** `simulation/scenarios/sevima_multitenancy.py`
**Parameter file:** `simulation/parameters/sevima_params.json`

#### Konteks

SEVIMA SiakadCloud melayani lebih dari 900 perguruan tinggi di Indonesia sejak 2004 dalam model multi-tenant. Setiap tenant (PT) berbagi infrastruktur yang sama, namun autentikasi harus memisahkan konteks per tenant. Ini menghasilkan overhead tambahan di lapisan key management karena kunci kriptografi harus diisolasi antar tenant.

Karakteristik paling kritis dari skenario ini adalah efek *noisy neighbor*: spike traffic dari satu PT dapat memengaruhi latensi autentikasi PT lain jika tidak ada mekanisme isolasi yang efisien.

#### Parameter Simulasi

| Parameter | Nilai | Sumber / Justifikasi |
| --- | --- | --- |
| Baseline avg latency | 220 ms | 197ms + ~23ms overhead tenant isolation (estimasi konservatif) |
| Baseline P95 latency | 310 ms | Lebih tinggi dari skenario tunggal karena noisy neighbor |
| Baseline P99 latency | 380 ms | Ekstrem pada saat concurrent burst multi-tenant |
| Traffic pattern | Concurrent multi-tenant burst | Banyak PT spike bersamaan di periode akademik yang sama |
| Tenant count (simulasi) | 5–10 tenant aktif | Representatif kluster PT skala menengah |
| Request count (simulasi default) | 2.000 request | Lebih tinggi karena beban multi-tenant |
| Overhead tenant isolation | ~23 ms | Estimasi derivatif dari prinsip overhead routing layer tambahan |
| Cache TTL range | 5–300 detik | Diderivasi dari AWS KMS recommendation |

#### Karakteristik Khas

- Kunci kriptografi harus diisolasi per tenant — tidak boleh ada cross-tenant cache hit
- Pola akses antar tenant berkorelasi karena periode akademik nasional yang sama
- Prefetch prediktif PSKC menguntungkan karena pola burst multi-tenant bersifat berulang
- Risiko: pre-fetch yang salah tenant bisa memperburuk tekanan memory

#### Referensi Utama

- SEVIMA SiakadCloud (2024) — `sevima_siakadcloud_2024`
- SEVIMA SSO (2024) — `sevima_sso_2024`
- MDPI Applied Sciences (2025) — `mdpi_auth_2025` (baseline latensi)

---

### Skenario 3: PDDikti — Skala Nasional

**File simulasi:** `simulation/scenarios/pddikti_national.py`
**Parameter file:** `simulation/parameters/pddikti_params.json`

#### Konteks

PDDikti (Pangkalan Data Pendidikan Tinggi) adalah sistem pelaporan nasional yang dikelola Kemdikbudristek. Lebih dari 4.900 PT aktif wajib melaporkan data akademik dua kali setahun, setiap Januari dan Juli. Dengan 9,6 juta mahasiswa aktif dan sekitar 340.000 dosen aktif, volume data yang dilaporkan sangat besar.

Karakteristik paling kritis dari skenario ini adalah *extreme deadline spike*: hampir semua PT melaporkan data dalam 2–3 hari terakhir sebelum batas waktu, menciptakan traffic spike yang sangat terkonsentrasi dalam window waktu yang sempit. Pola ini analog dengan skenario prime time pada platform skala besar, namun dengan tekanan deadline yang membuat traffic-nya lebih ekstrem sekaligus lebih terprediksi.

#### Parameter Simulasi

| Parameter | Nilai | Sumber / Justifikasi |
| --- | --- | --- |
| Baseline avg latency | 250 ms | 197ms + overhead skala nasional (estimasi konservatif) |
| Baseline P95 latency | 350 ms | Volume konkuren sangat tinggi |
| Baseline P99 latency | 400 ms | Ekstrem saat deadline window 72 jam |
| Traffic pattern | Extreme deadline spike | Seluruh PT lapor dalam 2–3 hari terakhir sebelum deadline |
| Peak window | 72 jam sebelum deadline | Observasi umum perilaku pelaporan deadline nasional |
| Concurrent PT (simulasi) | ~4.900 PT | Data resmi PDDikti (2024) |
| Request count (simulasi default) | 5.000 request | Representatif traffic deadline |
| Distribusi latensi | Log-normal dengan heavy tail | Karakteristik sistem yang mengalami overload periodik |
| Cache TTL range | 5–300 detik | Diderivasi dari AWS KMS recommendation |

#### Karakteristik Khas

- Pola akses sangat terprediksi secara temporal: dua kali setahun, selalu menjelang deadline
- Model PSKC dapat di-pre-warm sebelum periode deadline untuk cache hit rate optimal
- Cold start tidak menjadi masalah jika model sudah ditraining dari siklus deadline sebelumnya
- Skenario paling menuntut dari sisi throughput absolut

#### Referensi Utama

- PDDikti Kemdikbudristek (2024) — `pddikti_2024`
- Feeder PDDikti (2024) — `feeder_pddikti_2024`
- MDPI Applied Sciences (2025) — `mdpi_auth_2025` (baseline latensi)

---

## Referensi Metodologi (Global)

Skenario-skenario global berikut tidak menjadi skenario simulasi utama, tetapi digunakan sebagai **referensi metodologi** untuk memvalidasi model distribusi latensi, parameter teknis KMS, dan prinsip-prinsip engineering yang diterapkan di PSKC.

| Referensi | Kontribusi ke PSKC | BibTeX key |
| --- | --- | --- |
| Spotify Engineering (2015) | Model distribusi log-normal untuk latensi mikroservis — dipakai di semua skenario | `spotify_els_2015` |
| Spotify Padlock (2018) | Parameter KMS internal: 1M lookup/s, p99 <5ms cache, <15ms no-cache | `spotify_padlock_2018` |
| AWS KMS Quotas (2024) | Batas throughput: 10.000 req/s symmetric KMS, throttling policy | `aws_kms_quotas_2024` |
| AWS KMS XKS (2024) | Hard timeout 250ms, 1.800 req/s external key store | `aws_kms_xks_2024` |
| AWS KMS Caching FAQ (2024) | Rekomendasi TTL cache: 5 menit hingga 24 jam | `aws_kms_caching_2024` |
| Netflix / VdoCipher (2025) | Skala referensi: 260M subscriber, 14B API calls/hari, Zuul 2 + EVCache | `netflix_tech_2025` |

### Catatan Penggunaan

Referensi metodologi global tidak digunakan untuk mengklaim kemiripan konteks dengan PSKC. Fungsinya adalah:

1. Memvalidasi bahwa model distribusi log-normal adalah pilihan yang tepat untuk memodelkan latensi mikroservis
2. Memberikan batas atas dan batas bawah yang masuk akal untuk parameter KMS
3. Menunjukkan bahwa rekomendasi TTL yang digunakan PSKC konsisten dengan praktik industri

---

## Baseline Universal

Seluruh skenario simulasi PSKC menggunakan baseline latensi dari sumber yang sama untuk memastikan konsistensi perbandingan.

**Sumber baseline:** Aldea, C.L. and Bocu, R. (2025) 'Authentication Challenges and Solutions in Microservice Architectures', Applied Sciences, 15(22088).

| Metrik | Nilai Baseline |
| --- | --- |
| Average latency | 197 ms |
| P95 latency | 270 ms |
| P99 latency | 320 ms |
| Sample size | 500 successful logins |
| Konteks | Arsitektur mikroservis dengan JWT overhead |

### Derivasi Overhead Tambahan

Skenario multi-tenant (SEVIMA) dan skala nasional (PDDikti) menggunakan baseline yang dinaikkan secara konservatif:

- **SEVIMA (+23ms):** estimasi overhead routing dan isolasi tenant di lapisan autentikasi. Nilai ini adalah estimasi bawah yang konservatif dan dapat diperbarui jika data empiris tersedia.
- **PDDikti (+53ms):** estimasi overhead skala nasional akibat konkurensi ekstrem. Derivasi dari prinsip umum degradasi latensi pada sistem yang mendekati kapasitas.

Kedua overhead ini bersifat **asumsi simulasi**, bukan klaim empiris, dan harus diperlakukan demikian dalam interpretasi hasil.

---

## Model Distribusi Latensi

Seluruh simulasi menggunakan distribusi **log-normal** untuk memodelkan latensi per request.

### Justifikasi

Log-normal adalah model yang sudah divalidasi untuk latensi mikroservis oleh Spotify Engineering (2015) dalam studi ELS (Exponential Latency Smoothing). Karakteristiknya:

- Ekor kanan yang lebih panjang dari distribusi normal — mencerminkan occasional slow requests
- Tidak memiliki nilai negatif — secara fisik masuk akal untuk latensi
- Parameter mudah dikalibrasi dari mean dan standard deviation yang diketahui

### Parameter Distribusi per Skenario

| Skenario | Karakteristik distribusi | Catatan |
| --- | --- | --- |
| SIAKAD SSO | Log-normal standar | Traffic normal dengan seasonal burst |
| SEVIMA Multi-Tenant | Log-normal dengan σ lebih tinggi | Noisy neighbor effect menambah variance |
| PDDikti Nasional | Log-normal dengan heavy tail | Extreme concurrent load saat deadline |

Parameter numerik aktual tersimpan di masing-masing file JSON di `simulation/parameters/`.

---

## Cara Mengutip Hasil Simulasi

Ketika melaporkan hasil simulasi PSKC dalam konteks akademis atau teknis, gunakan format berikut:

### Untuk hasil reduksi latensi

> "Simulasi PSKC pada skenario [nama skenario] menunjukkan reduksi latensi rata-rata sebesar [X]% (dari [Y] ms menjadi [Z] ms), berdasarkan parameter yang diderivasi dari [referensi utama]. Baseline latensi mengacu pada El Akhdar dkk. (2025) dengan rata-rata 197ms pada arsitektur mikroservis dengan beban autentikasi JWT."

### Untuk cache hit rate

> "Cache hit rate sebesar [X]% dicapai pada fase mature (setelah [N] request warmup), menggunakan model ensemble LSTM+RandomForest+Markov Chain dengan TTL dinamis [Y]–[Z] detik."

### Untuk cold start analysis

> "Analisis cold start menunjukkan tiga fase: warmup ([N] request, avg [X] ms), learning ([N] request, avg [X] ms), dan mature ([N] request, avg [X] ms), konsisten dengan pola yang diidentifikasi pada sistem caching adaptif."

---

## Perubahan dari Versi Sebelumnya

Versi ini mengganti tiga skenario utama sebelumnya (Spotify Padlock, AWS KMS, Netflix Zuul) dengan tiga skenario berbasis konteks Indonesia. Alasan perubahan:

1. **Relevansi konteks** — skenario Indonesia lebih merepresentasikan target adopsi PSKC di ekosistem pendidikan tinggi Indonesia
2. **Verifiabilitas lokal** — parameter dapat dikonfirmasi dari sumber primer yang dapat diakses (Kemdikbudristek, jurnal nasional)
3. **Kebaruan kontribusi** — tidak ada studi sebelumnya yang menganalisis optimasi latensi autentikasi secara spesifik untuk konteks SIAKAD/PDDikti

Skenario global Spotify/AWS/Netflix tetap dipertahankan sebagai **referensi metodologi** karena kontribusinya pada model distribusi dan parameter teknis KMS tetap valid secara universal.

---

## File Terkait

| File | Keterangan |
| --- | --- |
| `simulation/references/sources.bib` | Seluruh referensi dalam format BibTeX |
| `simulation/parameters/siakad_params.json` | Parameter numerik skenario SIAKAD SSO |
| `simulation/parameters/sevima_params.json` | Parameter numerik skenario SEVIMA SiakadCloud |
| `simulation/parameters/pddikti_params.json` | Parameter numerik skenario PDDikti nasional |
| `simulation/parameters/baseline_params.json` | Baseline universal dari MDPI (2025) |
| `simulation/parameters/methodology_params.json` | Parameter referensi metodologi global |
| `simulation/scenarios/siakad_sso.py` | Engine simulasi skenario SIAKAD SSO |
| `simulation/scenarios/sevima_multitenancy.py` | Engine simulasi skenario SEVIMA |
| `simulation/scenarios/pddikti_national.py` | Engine simulasi skenario PDDikti |
| `simulation/engines/cold_start_simulator.py` | Simulator fase warmup → learning → mature |
| `simulation/runner.py` | Entry point untuk menjalankan semua skenario |
| `scripts/benchmark.py` | Benchmark suite untuk validasi klaim performa |