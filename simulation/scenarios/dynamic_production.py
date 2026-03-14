"""
Simulasi Skenario: Dynamic Production Environment
=================================================
Mensimulasikan lingkungan produksi yang dinamis dan tidak dapat diprediksi
untuk menguji ketahanan (resilience) sistem PSKC.

Fitur Skenario:
1.  **Beban Kerja Berubah (Variable Workload):** Pola traffic berubah
    selama simulasi, dari stabil menjadi 'bursty'.
2.  **Lonjakan Latensi (Latency Spikes):** Secara acak menyuntikkan
    latensi tinggi untuk mensimulasikan kemacetan jaringan atau KMS
    yang kelebihan beban.
3.  **Kegagalan Komponen (Component Failure):** Mensimulasikan KMS
    yang tidak dapat dijangkau untuk sementara waktu, memaksa sistem
    untuk hanya mengandalkan cache.
4.  **Cold Start:** Simulasi dimulai dengan fase 'cold start' di mana
    cache masih kosong dan model ML sedang belajar.
"""

import json
import random
import time

from simulation.engines.latency_engine import LatencyEngine
from simulation.engines.traffic_generator import TrafficGenerator

def simulate_dynamic_request(
    use_pskc: bool,
    iteration: int,
    total_requests: int,
    kms_available: bool = True
) -> dict:
    """
    Mensimulasikan satu request dalam lingkungan produksi yang dinamis.
    """
    # --- Tentukan fase simulasi ---
    is_cold_start = iteration < 20
    is_mid_simulation = total_requests * 0.3 < iteration < total_requests * 0.6
    
    # --- Dapatkan Latency Engine ---
    # Secara default, latensi sangat rendah
    latency_profile = "pskc_cached"
    # Suntikkan lonjakan latensi acak
    if random.random() < 0.05: # 5% kemungkinan lonjakan latensi
        latency_profile = "aws_kms_throttled"
    
    latency_engine = LatencyEngine(profile=latency_profile)

    if not use_pskc:
        # Tanpa PSKC, selalu panggilan penuh ke KMS
        if not kms_available:
            return {"total_ms": 2000, "status": "timeout", "cache_hit": False, "reason": "KMS unavailable"}
        
        base_latency = LatencyEngine(profile="baseline").sample_single()
        spike_latency = latency_engine.sample_single() if latency_profile == "aws_kms_throttled" else 0
        total = base_latency + spike_latency
        return {"total_ms": round(total, 2), "status": "ok", "cache_hit": False, "reason": "No PSKC"}
    
    # --- Dengan PSKC ---
    # Tentukan cache hit probability
    if is_cold_start:
        hit_prob = 0.30 # Akurasi ML rendah di awal
    elif is_mid_simulation:
        hit_prob = 0.95 # Pola stabil, akurasi ML tinggi
    else:
        hit_prob = 0.88 # Pola berubah, akurasi sedikit menurun

    cache_hit = random.random() < hit_prob

    if cache_hit:
        # Latensi cache hit sangat rendah
        total = LatencyEngine(profile="pskc_cached").sample_single()
        return {"total_ms": round(total, 2), "status": "ok", "cache_hit": True, "reason": "Cache Hit"}
    else:
        # Cache miss
        if not kms_available:
            # Jika KMS tidak tersedia saat cache miss, terjadi timeout
            return {"total_ms": 2000, "status": "timeout", "cache_hit": False, "reason": "Cache Miss, KMS unavailable"}
        
        # Latensi cache miss = latensi prefetch + latensi akibat lonjakan (jika ada)
        prefetch_latency = LatencyEngine(profile="pskc_prefetch").sample_single()
        spike_latency = latency_engine.sample_single() if latency_profile == "aws_kms_throttled" else 0
        total = prefetch_latency + spike_latency
        return {"total_ms": round(total, 2), "status": "ok", "cache_hit": False, "reason": "Cache Miss"}


def run_batch(n_requests: int = 2000, use_pskc: bool = True) -> dict:
    """
    Jalankan batch simulasi dinamis.
    """
    results = []
    hits = 0
    timeouts = 0

    # --- Tentukan fase kegagalan komponen ---
    kms_outage_start = n_requests // 2
    kms_outage_end = kms_outage_start + 50 # KMS mati untuk 50 request

    for i in range(n_requests):
        kms_available = not (kms_outage_start <= i < kms_outage_end)
        
        r = simulate_dynamic_request(
            use_pskc=use_pskc,
            iteration=i,
            total_requests=n_requests,
            kms_available=kms_available
        )
        
        results.append(r["total_ms"])
        if r.get("cache_hit"):
            hits += 1
        if r.get("status") == "timeout":
            timeouts += 1

    results.sort()
    
    return {
        "scenario": "dynamic_production",
        "mode": "with_pskc" if use_pskc else "without_pskc",
        "n_requests": n_requests,
        "kms_outage_window": f"{kms_outage_start}-{kms_outage_end}",
        "avg_ms": round(sum(results) / len(results), 2),
        "p50_ms": round(results[int(n_requests * 0.50)], 2),
        "p95_ms": round(results[int(n_requests * 0.95)], 2),
        "p99_ms": round(results[int(n_requests * 0.99)], 2),
        "cache_hit_rate": round(hits / n_requests, 3) if use_pskc else None,
        "timeout_rate": round(timeouts / n_requests, 3),
    }

if __name__ == "__main__":
    print("=== Dynamic Production Simulation ===")
    
    print("\n[WITHOUT PSKC]")
    # Tanpa PSKC, sistem akan sangat tidak stabil
    print(json.dumps(run_batch(use_pskc=False), indent=2))
    
    print("\n[WITH PSKC]")
    # Dengan PSKC, sistem seharusnya lebih tahan terhadap gangguan
    print(json.dumps(run_batch(use_pskc=True), indent=2))
