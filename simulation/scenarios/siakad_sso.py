"""
Simulasi Skenario: SIAKAD SSO — Portal Akademik Perguruan Tinggi
================================================================
Mensimulasikan beban kerja autentikasi pada Sistem Informasi Akademik (SIAKAD)
dengan arsitektur Single Sign-On (SSO) berbasis CAS/OAuth 2.0.

Studi kasus ini memodelkan pola akses kunci kriptografi di lingkungan perguruan
tinggi Indonesia, yang memiliki karakteristik unik: lonjakan traffic sangat
tinggi pada periode akademik tertentu (KRS, UTS, UAS) namun sangat rendah
di luar jam kuliah.

Referensi:
    Salmuasih & Setiawan, M. A. (2023). Evaluasi Penerapan Single Sign-On
    SAML dan OAuth 2.0: Studi pada Perguruan Tinggi Yogyakarta.
    JSiI (Jurnal Sistem Informasi), 10(1), 41–49.
    https://doi.org/10.30656/jsii.v10i1.6186

    Rezaldy, M., Asror, I., & Sardi, I. L. (2017). Desain dan Analisis
    Arsitektur Microservices Pada Sistem Informasi Akademik Perguruan Tinggi
    Dengan Pendekatan ATAM (Studi Kasus: iGracias Universitas Telkom).
    Vol. 4, No. 2.

    MDPI. (2025). Authentication Challenges and Solutions in Microservice
    Architectures. Applied Sciences, 15(22), 12088.
    https://doi.org/10.3390/app152212088

    MDPI. (2025). Authentication Latency Benchmark in Microservices.
    Baseline: avg 197ms, P95 270ms, P99 320ms (500 sample logins).

Parameter Kunci (berbasis referensi):
    - Pengguna aktif     : ~15.000 – 40.000 (tergantung ukuran PT)
    - Peak concurrent    : 800–2.000 user (periode KRS/UTS/UAS)
    - Layanan terintegrasi: SIAKAD, e-learning (LMS), perpustakaan, portal nilai
    - Auth latency tanpa cache: avg 197ms, P99 ~280ms (baseline MDPI 2025)
    - Auth latency dengan cache: avg 18–25ms (estimasi CAS in-memory)
    - TTL token JWT      : 1–8 jam (common practice OAuth 2.0 PT)
    - Pola traffic       : bursty saat jam kuliah, spike ekstrem saat KRS online
"""

import json
import random
import math
import time
from pathlib import Path

# Load parameter dari file referensi
PARAMS_PATH = Path(__file__).parent.parent / "parameters" / "siakad_params.json"
with open(PARAMS_PATH) as f:
    PARAMS = json.load(f)


def lognormal_latency(mu: float, sigma: float) -> float:
    """
    Generate latency menggunakan log-normal distribution.
    Network/service latency di production mengikuti distribusi ini.
    Referensi: Spotify ELS benchmark blog (2015) — log-normal untuk microservices.
    """
    return math.exp(random.gauss(mu, sigma))


def get_academic_period_multiplier(period: str) -> float:
    """
    Mengembalikan multiplier traffic berdasarkan periode akademik.
    SIAKAD memiliki pola traffic yang sangat seasonal dan predictable.

    Returns:
        float: Multiplier terhadap baseline traffic normal
    """
    period_map = {
        "normal"    : 1.0,   # hari kuliah biasa
        "krs_online": 6.5,   # Kartu Rencana Studi — lonjakan ekstrem, semua mhs login bersamaan
        "uts"       : 3.2,   # Ujian Tengah Semester — akses portal nilai & jadwal
        "uas"       : 3.5,   # Ujian Akhir Semester — lebih tinggi dari UTS
        "liburan"   : 0.15,  # semester break, minimal activity
        "wisuda"    : 2.1,   # periode pengumuman kelulusan
    }
    return period_map.get(period, 1.0)


def get_service_type() -> str:
    """
    Pilih service yang diakses berdasarkan distribusi probabilistik.
    Mayoritas akses ke portal nilai dan e-learning (LMS).
    Berbasis analisis pola umum SIAKAD perguruan tinggi Indonesia.
    """
    services = {
        "portal_nilai"  : 0.35,  # cek nilai, transkrip
        "lms_elearning" : 0.28,  # akses materi kuliah, tugas, kuis
        "krs_pengisian" : 0.15,  # isi KRS, lihat jadwal
        "perpustakaan"  : 0.10,  # akses e-library terintegrasi
        "keuangan"      : 0.07,  # cek tagihan, pembayaran
        "admin_akademik": 0.05,  # input nilai (dosen), admin
    }
    r = random.random()
    cumulative = 0.0
    for service, prob in services.items():
        cumulative += prob
        if r <= cumulative:
            return service
    return "portal_nilai"


def simulate_request(use_pskc: bool, period: str = "normal", cache_warm: bool = True) -> dict:
    """
    Simulasikan satu request autentikasi ke sistem SIAKAD SSO.

    Alur autentikasi SIAKAD:
    1. User request ke service (mis. LMS)
    2. Service redirect ke CAS/OAuth server
    3. CAS server validasi JWT → butuh kunci kriptografi dari KMS
    4. Jika PSKC aktif: kunci sudah di-cache → latensi rendah
    5. Jika tidak: harus fetch ke KMS/LDAP → latensi baseline MDPI

    Args:
        use_pskc  : Apakah PSKC aktif (predictive key caching)
        period    : Periode akademik (normal/krs_online/uts/uas/liburan/wisuda)
        cache_warm: Apakah cache sudah warm (model ML sudah mature)

    Returns:
        dict dengan latency_ms, cache_hit, service, period, dll.
    """
    p        = PARAMS
    service  = get_service_type()
    multi    = get_academic_period_multiplier(period)

    if use_pskc:
        # PSKC: kunci sudah di-cache via predictive pre-fetching
        # Cache hit rate lebih tinggi di periode berulang (KRS sama setiap semester)
        base_hit_rate = p["simulation_use"]["cache_hit_rate"]

        # Periode berulang meningkatkan prediktabilitas ML
        if period in ("krs_online", "uts", "uas"):
            hit_rate = min(0.95, base_hit_rate + 0.08)  # pola seasonal → lebih predictable
        elif period == "liburan":
            hit_rate = base_hit_rate - 0.15  # cold start setelah break panjang
        else:
            hit_rate = base_hit_rate

        # Kurangi hit rate jika cache belum warm (cold start awal semester)
        if not cache_warm:
            hit_rate = max(0.1, hit_rate - 0.45)

        cache_hit = random.random() < hit_rate

        if cache_hit:
            # Cache hit: latency sangat rendah (in-memory AES-256 decrypt)
            mu    = p["simulation_use"]["log_mu_cached"]
            sigma = p["simulation_use"]["log_sigma_cached"]
        else:
            # Cache miss: fallback ke KMS/LDAP
            mu    = p["simulation_use"]["log_mu_miss"]
            sigma = p["simulation_use"]["log_sigma_miss"]

        # Tambahkan beban saat peak (contention pada shared resources)
        if multi > 3.0:
            mu += 0.15  # ~16% tambahan latensi saat peak

        latency_ms = lognormal_latency(mu, sigma)
        return {
            "latency_ms" : round(latency_ms, 2),
            "cache_hit"  : cache_hit,
            "source"     : "pskc_cache" if cache_hit else "kms_fallback",
            "service"    : service,
            "period"     : period,
            "traffic_mul": multi,
        }

    else:
        # Tanpa PSKC: setiap request harus validasi ke KMS/LDAP
        # Baseline dari MDPI 2025: avg 197ms, P99 ~280ms untuk microservices auth
        mu    = p["simulation_use"]["log_mu_no_cache"]
        sigma = p["simulation_use"]["log_sigma_no_cache"]

        # Tambahan latensi saat peak period (queue di CAS server)
        if multi > 3.0:
            mu    += 0.25  # ~28% tambahan saat KRS/UAS — server contention
            sigma += 0.05

        latency_ms = lognormal_latency(mu, sigma)

        # Simulasi timeout sesekali saat over-load (KRS online)
        timed_out = False
        if multi > 5.0 and random.random() < 0.04:
            latency_ms = p["system"]["request_timeout_ms"] * random.uniform(1.0, 1.3)
            timed_out  = True

        return {
            "latency_ms" : round(latency_ms, 2),
            "cache_hit"  : False,
            "source"     : "kms_direct",
            "service"    : service,
            "period"     : period,
            "traffic_mul": multi,
            "timed_out"  : timed_out,
        }


def run_batch(
    n_requests : int = 1000,
    use_pskc   : bool = True,
    period     : str  = "normal",
    cache_warm : bool = True,
) -> dict:
    """
    Jalankan batch simulasi dan kembalikan statistik agregat.

    Returns:
        dict: avg_ms, p95_ms, p99_ms, cache_hit_rate, timeout_rate, period
    """
    results = [
        simulate_request(use_pskc, period=period, cache_warm=cache_warm)
        for _ in range(n_requests)
    ]

    latencies   = sorted(r["latency_ms"] for r in results)
    cache_hits  = sum(1 for r in results if r.get("cache_hit"))
    timeouts    = sum(1 for r in results if r.get("timed_out"))
    n           = len(latencies)

    return {
        "avg_ms"          : round(sum(latencies) / n, 1),
        "p95_ms"          : round(latencies[int(n * 0.95)], 1),
        "p99_ms"          : round(latencies[int(n * 0.99)], 1),
        "cache_hit_rate"  : round(cache_hits / n, 3),
        "timeout_rate"    : round(timeouts / n, 4),
        "period"          : period,
        "use_pskc"        : use_pskc,
        "n_requests"      : n,
    }
