

## 1. SIAKAD SSO — Perguruan Tinggi Indonesia

**Sumber Utama:**

**[1a]** Salmuasih & Setiawan, M. A. (2023). Evaluasi Penerapan Single Sign-On SAML dan OAuth 2.0: Studi pada Perguruan Tinggi Yogyakarta. *JSiI (Jurnal Sistem Informasi)*, 10(1), 41–49.
https://doi.org/10.30656/jsii.v10i1.6186

| Parameter | Nilai | Konteks |
|-----------|-------|---------|
| PT yang disurvei | 17 PT Yogyakarta | 22 responden dari Pusat IT |
| Protokol SSO | SAML + OAuth 2.0 | Mayoritas; beberapa belum efektif |
| PT belum efektif SSO | 7 dari 17 | Ketidaksesuaian protokol dan use case |
| PT klaim riset protokol | 60% | Masih ada gap implementasi |

**[1b]** Rezaldy, M., Asror, I., & Sardi, I. L. (2017). Desain dan Analisis Arsitektur Microservices Pada SIAKAD Perguruan Tinggi: Studi Kasus iGracias Universitas Telkom (ATAM). Vol. 4, No. 2.

| Parameter | Nilai | Konteks |
|-----------|-------|---------|
| Sistem | iGracias Telkom University | SIAKAD + LMS (iDea) + e-library |
| Arsitektur | Microservices + SSO | Integrasi antar service via SSO |
| Layanan terintegrasi | SIAKAD, LMS, perpustakaan | Satu login untuk semua |

**[1c]** MDPI. (2025). Authentication Challenges and Solutions in Microservice Architectures. *Applied Sciences*, 15(22), 12088.
https://doi.org/10.3390/app152212088

| Parameter | Nilai | Konteks |
|-----------|-------|---------|
| Baseline auth latency | avg 197ms | Tanpa caching |
| P95 latency | 270ms | Microservices auth benchmark |
| P99 latency | 320ms | Sample 500 successful logins |

> **Catatan:** Angka 197ms digunakan sebagai **baseline "tanpa PSKC"** di semua skenario (konsisten dengan versi sebelumnya).

---

## 2. SEVIMA Siakadcloud — Platform SIAKAD Multi-Tenant

**Sumber Utama:**

**[2a]** SEVIMA. (2024). *Siakadcloud — Platform SIAKAD No. 1 Indonesia*.
https://sevima.com/siakadcloud
— PT. Sentra Vidya Utama; berkomitmen sejak 2004 dalam administrasi akademik PT Indonesia.

| Parameter | Nilai | Konteks |
|-----------|-------|---------|
| Perguruan tinggi dilayani | >900 PT | Seluruh Indonesia |
| Model deployment | Multi-tenant SaaS cloud | Termasuk SIAKAD, Edlink, portal akademik |
| SSO coverage | Semua modul SEVIMA Platform | 1 login → akses SIAKAD + LMS + keuangan |

**[2b]** SEVIMA. (2024). *Manfaat Single Sign On (SSO) Bagi Tim IT, Admin dan Civitas Akademik*.
https://sevima.com/manfaat-single-sign-on-sso-bagi-tim-it-admin-dan-civitas-akademik

| Parameter | Nilai | Konteks |
|-----------|-------|---------|
| 2FA support | ✓ (OTP) | Verifikasi ganda untuk keamanan |
| MFA support | ✓ | Multi-factor untuk akun sensitif |
| Pengguna | Mahasiswa, dosen, operator, staf | Semua civitas akademik |

---

## 3. PDDikti — Pangkalan Data Pendidikan Tinggi Nasional

**Sumber Utama:**

**[3a]** Kemdikbudristek. (2024). *PDDikti — Pangkalan Data Pendidikan Tinggi*.
https://pddikti.kemdikbud.go.id

| Parameter | Nilai | Konteks |
|-----------|-------|---------|
| PT terdaftar aktif | >4.900 PT | Data 2024 |
| Mahasiswa aktif | >9,6 juta | Seluruh jenjang pendidikan tinggi |
| Dosen aktif | ~340.000 | Seluruh PT Indonesia |

**[3b]** Kemdikbudristek. (2024). *Feeder PDDikti — Panduan Pelaporan Data Semester*.
https://feeder.kemdikbud.go.id

| Parameter | Nilai | Konteks |
|-----------|-------|---------|
| Frekuensi deadline | 2x per tahun | Januari & Juli |
| Operator per PT | 1–3 orang | Estimasi; total ~5.000–15.000 operator |
| Dampak | Semua operator login hampir bersamaan | Spike traffic ekstrem menjelang deadline |

---

## 4. Baseline Auth Latency (Peer-reviewed, digunakan di semua skenario)

**Sumber:** MDPI. (2025). *Authentication Latency Benchmark in Microservices*. Applied Sciences, 15(22), 12088.

| Parameter | Nilai |
|-----------|-------|
| Sample size | 500 successful logins |
| Average latency | **197ms** |
| P95 latency | **270ms** |
| P99 latency | **320ms** |

> Angka ini digunakan sebagai baseline "tanpa PSKC" yang konsisten di semua skenario.

---

## 5. Distribusi Latensi (Log-Normal) — Tetap Dipertahankan

**Sumber:** Spotify Engineering. (2015). *ELS: A Latency-Based Load Balancer*.
https://engineering.atspotify.com/2015/12/els-part-1

> Distribusi latensi jaringan/microservices mengikuti **log-normal distribution** — ini adalah fakta matematis universal yang berlaku di semua skenario, termasuk SIAKAD dan PDDikti. Referensi ini dipertahankan karena berkaitan dengan metodologi simulasi, bukan studi kasusnya.

---

## Perbandingan Skenario

| Skenario | File | Karakteristik Unik |
|----------|------|--------------------|
| SIAKAD SSO | `scenarios/siakad_sso.py` | Traffic seasonal (KRS, UTS, UAS); sangat predictable untuk ML |
| SEVIMA Siakadcloud | `scenarios/sevima_cloud.py` | Multi-tenant; quota per PT; spike overlap antar PT |
| PDDikti | `scenarios/pddikti_auth.py` | Skala nasional; spike ekstrem saat deadline Feeder |
| Cold Start | `engines/cold_start_simulator.py` | Evolusi model ML warmup → mature |

---

## Catatan Metodologi

Parameter angka latensi (197ms avg, P99 320ms) identik dengan versi skenario sebelumnya karena bersumber dari paper yang sama (MDPI 2025). Perubahan di sini adalah **konteks studi kasus** — dari perusahaan teknologi swasta (Spotify, Netflix) ke **institusi akademik dan pemerintahan Indonesia** — bukan perubahan nilai baseline
---

## Cara Mengutip dalam Presentasi

> *"Parameter simulasi ini didasarkan pada data latensi sistem Padlock
> milik Spotify (engineering.atspotify.com, 2018), benchmark autentikasi
> microservices dari jurnal MDPI (2025), dokumentasi resmi AWS KMS, dan
> analisis arsitektur Netflix (VdoCipher, 2025). Distribusi latensi
> menggunakan log-normal model sesuai karakteristik production microservices."*
