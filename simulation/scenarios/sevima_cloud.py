"""
Simulasi Skenario: SEVIMA Siakadcloud — Platform SIAKAD Multi-Tenant
=====================================================================
Mensimulasikan beban kerja autentikasi pada platform SIAKAD multi-tenant
seperti SEVIMA Siakadcloud yang melayani ratusan perguruan tinggi sekaligus.

Pada platform cloud multi-tenant, autentikasi jauh lebih kompleks karena:
1. Setiap PT memiliki tenant dan kunci enkripsi yang terpisah
2. Peak KRS dari ribuan PT bisa overlap → total RPS sangat tinggi
3. KMS harus melayani key rotation dari semua tenant secara bersamaan
4. Rate limit per tenant harus dikelola agar satu PT tidak mempengaruhi lainnya

Referensi:
    SEVIMA. (2024). SEVIMA Siakadcloud — Platform SIAKAD No. 1 Indonesia.
    https://sevima.com/siakadcloud
    — Platform melayani >900 perguruan tinggi di Indonesia

    SEVIMA. (2024). Manfaat Single Sign On (SSO) Bagi Tim IT, Admin dan
    Civitas Akademik. https://sevima.com/manfaat-single-sign-on-sso-bagi-tim-it-admin-dan-civitas-akademik
    — SSO terintegrasi: SIAKAD, Edlink (LMS), portal akademik dalam satu login

    Salmuasih & Setiawan (2023). JSiI Vol.10 No.1.
    — 60% PT belum menerapkan SSO secara efektif; banyak yang masih multi-credential

    MDPI (2025). Authentication Challenges in Microservice Architectures.
    Applied Sciences, 15(22), 12088.
    — Rate limiting dan quota management sebagai tantangan utama

Parameter Kunci:
    - Tenant aktif       : >900 perguruan tinggi
    - Peak aggregate RPS : ~5.000–12.000 req/s (saat KRS serentak antar PT)
    - Per-tenant quota   : ~50–200 req/s (tergantung paket langganan)
    - KMS timeout default: 3.000ms (lebih toleran dari AWS karena on-premise-style)
    - Rekomendasi cache TTL: 15 menit – 4 jam (disesuaikan periode akademik)
"""

import json
import math
import random
from pathlib import Path

PARAMS_PATH = Path(__file__).parent.parent / "parameters" / "sevima_params.json"
with open(PARAMS_PATH) as f:
    PARAMS = json.load(f)

# Konstanta platform
PLATFORM_TIMEOUT_MS      = 3000   # timeout hard limit multi-tenant KMS
PLATFORM_QUOTA_PER_TENANT = 150   # default req/s per tenant
PLATFORM_MAX_AGGREGATE   = 12000  # max aggregate RPS semua tenant


def lognormal_latency(mu: float, sigma: float) -> float:
    return math.exp(random.gauss(mu, sigma))


def simulate_sevima_request(use_pskc: bool, rps_load: int = 500, tenant_count: int = 100) -> dict:
    """
    Simulasikan satu request autentikasi di platform SIAKAD multi-tenant.

    Pada platform multi-tenant, setiap request harus:
    1. Identifikasi tenant (PT mana)
    2. Load kunci enkripsi spesifik tenant dari KMS
    3. Validasi JWT
    4. Return token ke service

    Args:
        use_pskc    : Apakah PSKC aktif
        rps_load    : Total RPS aggregate saat ini
        tenant_count: Jumlah tenant aktif yang sedang request bersamaan

    Returns:
        dict dengan latency_ms, cache_hit, throttled, dll.
    """
    p = PARAMS

    # Hitung tekanan load relatif terhadap kapasitas
    load_ratio  = rps_load / PLATFORM_MAX_AGGREGATE  # 0.0 – 1.0+
    per_tenant  = rps_load / max(tenant_count, 1)
    throttled   = per_tenant > PLATFORM_QUOTA_PER_TENANT

    if use_pskc:
        # PSKC menyimpan kunci per-tenant → drastis kurangi beban KMS
        base_hit_rate = p["simulation_use"]["cache_hit_rate"]

        # Load tinggi = lebih banyak miss (eviction tekanan memori)
        hit_rate = base_hit_rate - (load_ratio * 0.08)
        hit_rate = max(0.55, min(0.95, hit_rate))

        cache_hit = random.random() < hit_rate

        if cache_hit:
            mu    = p["simulation_use"]["log_mu_cached"]
            sigma = p["simulation_use"]["log_sigma_cached"]
        else:
            mu    = p["simulation_use"]["log_mu_miss"]
            sigma = p["simulation_use"]["log_sigma_miss"]

        if load_ratio > 0.7:
            mu += 0.12  # queue pressure saat high load

        latency_ms = lognormal_latency(mu, sigma)

        return {
            "latency_ms"  : round(latency_ms, 2),
            "cache_hit"   : cache_hit,
            "source"      : "pskc_cache" if cache_hit else "kms_fallback",
            "throttled"   : False,
            "rps_load"    : rps_load,
            "load_ratio"  : round(load_ratio, 3),
        }

    else:
        # Tanpa PSKC: setiap tenant request langsung ke shared KMS
        mu    = p["simulation_use"]["log_mu_no_cache"]
        sigma = p["simulation_use"]["log_sigma_no_cache"]

        if load_ratio > 0.5:
            mu    += 0.3 * load_ratio
            sigma += 0.06

        # Throttling: request yang over-quota mendapat penalti latensi
        timed_out = False
        if throttled:
            if random.random() < 0.07:
                latency_ms = PLATFORM_TIMEOUT_MS * random.uniform(1.0, 1.2)
                timed_out  = True
            else:
                mu    += 0.4
                sigma += 0.1
                latency_ms = lognormal_latency(mu, sigma)
        else:
            latency_ms = lognormal_latency(mu, sigma)

        return {
            "latency_ms"  : round(latency_ms, 2),
            "cache_hit"   : False,
            "source"      : "kms_direct",
            "throttled"   : throttled,
            "timed_out"   : timed_out,
            "rps_load"    : rps_load,
            "load_ratio"  : round(load_ratio, 3),
        }


def run_batch(
    n_requests   : int  = 1000,
    use_pskc     : bool = True,
    rps_load     : int  = 500,
    tenant_count : int  = 100,
) -> dict:
    """
    Jalankan batch dan kembalikan statistik agregat.
    """
    results = [
        simulate_sevima_request(use_pskc, rps_load=rps_load, tenant_count=tenant_count)
        for _ in range(n_requests)
    ]

    latencies  = sorted(r["latency_ms"] for r in results)
    cache_hits = sum(1 for r in results if r.get("cache_hit"))
    timeouts   = sum(1 for r in results if r.get("timed_out"))
    throttled  = sum(1 for r in results if r.get("throttled"))
    n          = len(latencies)

    return {
        "avg_ms"         : round(sum(latencies) / n, 1),
        "p95_ms"         : round(latencies[int(n * 0.95)], 1),
        "p99_ms"         : round(latencies[int(n * 0.99)], 1),
        "cache_hit_rate" : round(cache_hits / n, 3),
        "timeout_rate"   : round(timeouts / n, 4),
        "throttle_rate"  : round(throttled / n, 4),
        "rps_load"       : rps_load,
        "use_pskc"       : use_pskc,
        "n_requests"     : n,
    }
