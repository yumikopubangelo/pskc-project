"""
Simulasi Skenario: PDDikti — Portal Data Dikti Nasional
========================================================
Mensimulasikan beban kerja autentikasi pada Portal Data Pendidikan Tinggi
(PDDikti) milik Kemdikbudristek yang menjadi tulang punggung data akademik
nasional Indonesia.

PDDikti adalah gateway data resmi seluruh perguruan tinggi Indonesia:
- Seluruh PT wajib melaporkan data mahasiswa, dosen, dan lulusan
- Data diakses oleh PT, Kemendikbud, BPS, dan publik
- Autentikasi dilakukan via akun PTK (Pangkalan Tenaga Kependidikan)
- Spike terjadi saat deadline pelaporan semester (Feeder deadline)

Referensi:
    Kemdikbudristek. (2024). PDDikti — Pangkalan Data Pendidikan Tinggi.
    https://pddikti.kemdikbud.go.id
    — Data resmi: >4.900 PT terdaftar, >9,6 juta mahasiswa aktif (2024)

    Kemdikbudristek. (2024). Feeder PDDikti — Panduan Pelaporan Data.
    https://feeder.kemdikbud.go.id
    — Deadline pelaporan 2x/tahun; semua PT operator login bersamaan menjelang deadline

    MDPI. (2025). Authentication Challenges and Solutions in Microservice
    Architectures. Applied Sciences, 15(22), 12088.
    — Baseline autentikasi microservices: avg 197ms, P99 320ms

    Salmuasih & Setiawan. (2023). JSiI Vol.10 No.1.
    — Konteks SSO perguruan tinggi Indonesia

Parameter Kunci:
    - PT terdaftar       : >4.900 PT aktif (2024)
    - Mahasiswa aktif    : >9,6 juta (potensi concurrent akses data)
    - Operator Feeder    : 1–3 operator per PT → ~5.000–15.000 operator aktif
    - Peak deadline      : 2x per tahun (Januari & Juli)
    - Auth latency tanpa cache: avg 197ms baseline (MDPI 2025)
    - Pola traffic       : spike besar 1–2 minggu sebelum deadline Feeder
"""

import json
import math
import random
from pathlib import Path

PARAMS_PATH = Path(__file__).parent.parent / "parameters" / "pddikti_params.json"
with open(PARAMS_PATH) as f:
    PARAMS = json.load(f)

# Konstanta PDDikti
TOTAL_PT_TERDAFTAR    = 4900
MAHASISWA_AKTIF       = 9_600_000
FEEDER_DEADLINE_DAYS  = 14  # 2 minggu menjelang deadline = peak periode


def lognormal_latency(mu: float, sigma: float) -> float:
    return math.exp(random.gauss(mu, sigma))


def get_pddikti_traffic_pattern(mode: str) -> float:
    """
    Multiplier traffic berdasarkan periode pelaporan PDDikti.

    PDDikti memiliki dua kategori pengguna:
    1. Operator PT (akses Feeder, lapor data) — sangat seasonal
    2. Publik/mahasiswa (cek data, verifikasi ijazah) — lebih merata

    Args:
        mode: 'normal' / 'pre_deadline' / 'deadline_week' / 'post_deadline' / 'publik_peak'
    """
    patterns = {
        "normal"        : 1.0,
        "pre_deadline"  : 3.8,   # 2 minggu sebelum deadline: operator mulai aktif
        "deadline_week" : 7.2,   # minggu terakhir: semua operator panik → sangat tinggi
        "post_deadline" : 0.4,   # setelah deadline: turun drastis
        "publik_peak"   : 2.1,   # masa wisuda & penerimaan mhs baru → verifikasi data
        "maintenance"   : 0.05,  # jadwal maintenance malam
    }
    return patterns.get(mode, 1.0)


def get_user_type() -> str:
    """
    Distribusi tipe pengguna PDDikti.
    Mayoritas akses untuk verifikasi data dan cek status mahasiswa.
    """
    types = {
        "operator_feeder"  : 0.28,  # operator PT lapor data semester
        "verifikasi_publik": 0.32,  # masyarakat cek data mahasiswa/lulusan
        "admin_pt"         : 0.18,  # admin PT akses dashboard
        "dosen_validator"  : 0.12,  # dosen validasi data akademik
        "kemendikbud_staff": 0.06,  # staf kementerian akses analitik
        "bps_integration"  : 0.04,  # integrasi API BPS/lembaga pemerintah
    }
    r = random.random()
    cumulative = 0.0
    for t, prob in types.items():
        cumulative += prob
        if r <= cumulative:
            return t
    return "verifikasi_publik"


def simulate_pddikti_request(use_pskc: bool, mode: str = "normal") -> dict:
    """
    Simulasikan satu request autentikasi ke sistem PDDikti.

    Flow autentikasi PDDikti:
    1. Operator/publik login ke portal
    2. Auth gateway validasi kredensial via KMS
    3. Generate session token terenkripsi
    4. Akses data PT yang relevan

    Args:
        use_pskc: Apakah PSKC aktif
        mode    : Mode traffic (normal/pre_deadline/deadline_week/dll)

    Returns:
        dict dengan latency_ms, user_type, mode, dll.
    """
    p         = PARAMS
    user_type = get_user_type()
    multi     = get_pddikti_traffic_pattern(mode)

    if use_pskc:
        base_hit_rate = p["simulation_use"]["cache_hit_rate"]

        # Operator Feeder punya pola akses sangat predictable (data PT tertentu)
        # → ML model mudah memprediksi kunci mana yang akan dibutuhkan
        if user_type == "operator_feeder":
            hit_rate = min(0.94, base_hit_rate + 0.10)
        elif user_type in ("admin_pt", "dosen_validator"):
            hit_rate = min(0.90, base_hit_rate + 0.06)
        else:
            hit_rate = base_hit_rate

        # Deadline week: lebih banyak request baru dari PT yang jarang akses
        if mode == "deadline_week":
            hit_rate = max(0.55, hit_rate - 0.12)

        cache_hit = random.random() < hit_rate

        if cache_hit:
            mu    = p["simulation_use"]["log_mu_cached"]
            sigma = p["simulation_use"]["log_sigma_cached"]
        else:
            mu    = p["simulation_use"]["log_mu_miss"]
            sigma = p["simulation_use"]["log_sigma_miss"]

        if multi > 4.0:
            mu += 0.18

        latency_ms = lognormal_latency(mu, sigma)

        return {
            "latency_ms" : round(latency_ms, 2),
            "cache_hit"  : cache_hit,
            "source"     : "pskc_cache" if cache_hit else "kms_fallback",
            "user_type"  : user_type,
            "mode"       : mode,
            "traffic_mul": multi,
        }

    else:
        # Tanpa PSKC: baseline MDPI 197ms avg
        mu    = p["simulation_use"]["log_mu_no_cache"]
        sigma = p["simulation_use"]["log_sigma_no_cache"]

        # Deadline week: sangat tinggi → server kewalahan
        if multi > 5.0:
            mu    += 0.35
            sigma += 0.08

        latency_ms = lognormal_latency(mu, sigma)

        # Sesekali gagal saat deadline peak (server overload)
        timed_out = False
        if multi > 6.0 and random.random() < 0.05:
            latency_ms = p["system"]["request_timeout_ms"] * random.uniform(1.0, 1.4)
            timed_out  = True

        return {
            "latency_ms" : round(latency_ms, 2),
            "cache_hit"  : False,
            "source"     : "kms_direct",
            "user_type"  : user_type,
            "mode"       : mode,
            "traffic_mul": multi,
            "timed_out"  : timed_out,
        }


def run_batch(
    n_requests : int  = 1000,
    use_pskc   : bool = True,
    mode       : str  = "normal",
) -> dict:
    """
    Jalankan batch simulasi dan kembalikan statistik agregat.
    """
    results = [
        simulate_pddikti_request(use_pskc, mode=mode)
        for _ in range(n_requests)
    ]

    latencies  = sorted(r["latency_ms"] for r in results)
    cache_hits = sum(1 for r in results if r.get("cache_hit"))
    timeouts   = sum(1 for r in results if r.get("timed_out"))
    n          = len(latencies)

    return {
        "avg_ms"        : round(sum(latencies) / n, 1),
        "p95_ms"        : round(latencies[int(n * 0.95)], 1),
        "p99_ms"        : round(latencies[int(n * 0.99)], 1),
        "cache_hit_rate": round(cache_hits / n, 3),
        "timeout_rate"  : round(timeouts / n, 4),
        "mode"          : mode,
        "use_pskc"      : use_pskc,
        "n_requests"    : n,
    }
