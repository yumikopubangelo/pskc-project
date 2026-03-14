"""
Cold Start Simulator (IMPROVED)
================================
Mensimulasikan fase cold start PSKC ketika tidak ada data historis.
Menampilkan evolusi akurasi ML dari nol hingga mature.

Strategi:
    Phase 1 (0–20 req)  : Rule-based heuristics, akurasi ~55%
    Phase 2 (20–60 req) : Online learning aktif, akurasi naik ke ~78%
    Phase 3 (60+ req)   : Model mature, akurasi stabil ~91%

IMPROVEMENTS vs sebelumnya:
    - get_ml_accuracy() sebelumnya deterministik (smooth curve) — tidak realistis.
      Di dunia nyata akurasi naik-turun karena:
        * Distribusi request berubah (traffic spike, shift pola)
        * Online learning sesekali "salah arah" sebelum konvergen
        * Noise dari data imbalance di awal
    - Ditambahkan simulate_traffic_spike() untuk melihat ketahanan model
    - Ditambahkan parameter seed untuk reproducibility
    - Return value menyertakan accuracy_theoretical untuk perbandingan
      vs accuracy_actual yang mengandung noise
"""

import math
import random
import numpy as np
from typing import Optional


# ============================================================
# Accuracy Model with Realistic Noise
# ============================================================

def get_ml_accuracy_theoretical(n_requests_seen: int) -> float:
    """
    Model akurasi teoritis (smooth sigmoid curve).
    Ini adalah ekspektasi akurasi, bukan nilai aktual.
    """
    if n_requests_seen < 20:
        return 0.45 + (n_requests_seen / 20) * 0.15      # 45% → 60%
    elif n_requests_seen < 60:
        progress = (n_requests_seen - 20) / 40
        return 0.60 + progress * 0.22                     # 60% → 82%
    else:
        extra = min((n_requests_seen - 60) / 200, 1.0)
        return 0.82 + extra * 0.097                       # 82% → 91.7%


def get_ml_accuracy(
    n_requests_seen: int,
    rng: Optional[np.random.Generator] = None,
    noise_scale: float = 1.0,
) -> float:
    """
    Modelkan akurasi ML sebagai fungsi dari jumlah request yang telah diproses,
    dengan noise realistis yang mencerminkan fluktuasi di dunia nyata.

    BEFORE: return nilai deterministik — akurasi selalu naik smooth.
    AFTER:  noise ditambahkan per-fase dengan skala yang berbeda:
            - Phase 1 (warmup): noise tinggi — model masih sangat tidak stabil
            - Phase 2 (learning): noise sedang — online learning kadang undershoot
            - Phase 3 (mature): noise rendah — model stabil tapi masih berfluktuasi

    Args:
        n_requests_seen: Jumlah request yang sudah diproses model
        rng: numpy random generator (untuk reproducibility)
        noise_scale: Multiplier untuk noise (1.0 = default, 0 = no noise / theoretical)

    Returns:
        Akurasi antara 0.0 dan 1.0
    """
    if rng is None:
        rng = np.random.default_rng()

    theoretical = get_ml_accuracy_theoretical(n_requests_seen)

    # Noise level per fase — lebih tinggi di awal, lebih rendah di mature
    if n_requests_seen < 20:
        # Warmup: sangat tidak stabil, bisa drop signifikan
        noise_std = 0.08 * noise_scale
        # Occasional sharp drops (model "confused" by new pattern)
        if rng.random() < 0.15:
            noise_std *= 2.5
    elif n_requests_seen < 60:
        # Learning: lebih stabil, tapi sesekali masih fluktuasi
        noise_std = 0.04 * noise_scale
        if rng.random() < 0.08:
            noise_std *= 1.8
    else:
        # Mature: minor fluktuasi dari distribusi shift
        noise_std = 0.015 * noise_scale

    noise = rng.normal(0, noise_std)
    accuracy = theoretical + noise

    # Clamp ke range valid [0.1, 0.99]
    return float(np.clip(accuracy, 0.10, 0.99))


# ============================================================
# Main Simulation
# ============================================================

def simulate_cold_start(
    total_requests: int = 200,
    seed: int = 42,
    noise_scale: float = 1.0,
) -> list:
    """
    Simulasikan seluruh lifecycle dari cold start hingga mature.

    Args:
        total_requests: Jumlah total request yang disimulasikan
        seed: Random seed untuk reproducibility
        noise_scale: Kontrol intensitas noise (0 = smooth/theoretical, 1 = realistic)

    Returns:
        List of dicts dengan metrik per request, termasuk:
        - accuracy_theoretical: Nilai smooth curve (ekspektasi)
        - ml_accuracy: Nilai aktual dengan noise (realistis)
    """
    rng = np.random.default_rng(seed)
    timeline = []
    cumulative_hits = 0

    for i in range(total_requests):
        theoretical = get_ml_accuracy_theoretical(i)
        actual_accuracy = get_ml_accuracy(i, rng=rng, noise_scale=noise_scale)

        cache_hit = rng.random() < actual_accuracy

        if cache_hit:
            cumulative_hits += 1
            latency = math.exp(rng.normal(1.5, 0.3))   # ~4.5ms
        else:
            latency = math.exp(rng.normal(5.2, 0.4))   # ~180ms fallback

        phase = (
            "warmup"   if i < 20 else
            "learning" if i < 60 else
            "mature"
        )

        timeline.append({
            "request_n":           i + 1,
            "phase":               phase,
            "accuracy_theoretical": round(theoretical, 3),
            "ml_accuracy":         round(actual_accuracy, 3),
            "cache_hit":           bool(cache_hit),
            "latency_ms":          round(latency, 2),
            "rolling_hit_rate":    round(cumulative_hits / (i + 1), 3),
        })

    return timeline


# ============================================================
# Traffic Spike Scenario (NEW)
# ============================================================

def simulate_traffic_spike(
    total_requests: int = 300,
    spike_start: int = 80,
    spike_duration: int = 40,
    spike_novelty: float = 0.7,
    seed: int = 42,
) -> list:
    """
    Simulasikan cold start + sudden traffic spike setelah model mature.

    Ini mensimulasikan skenario nyata seperti:
    - Viral event yang mengubah pola akses secara tiba-tiba
    - Deployment fitur baru yang memunculkan key access pattern baru
    - Serangan DDoS yang mengacak distribusi request

    Args:
        total_requests: Total request yang disimulasikan
        spike_start: Request ke-N saat spike dimulai
        spike_duration: Durasi spike dalam jumlah request
        spike_novelty: Seberapa beda pola spike dari normal (0–1).
                       0 = spike biasa (volume naik), 1 = pola sama sekali baru
        seed: Random seed

    Returns:
        List of dicts per request dengan field tambahan:
        - is_spike: apakah request ini bagian dari spike
        - effective_accuracy: akurasi yang diperhitungkan efek spike
    """
    rng = np.random.default_rng(seed)
    timeline = []
    cumulative_hits = 0

    for i in range(total_requests):
        spike_start_i = spike_start
        spike_end_i = spike_start + spike_duration
        is_spike = spike_start_i <= i < spike_end_i

        theoretical = get_ml_accuracy_theoretical(i)
        actual_accuracy = get_ml_accuracy(i, rng=rng, noise_scale=1.0)

        if is_spike:
            # Spike introduces novel keys model hasn't seen —
            # penalti akurasi proporsional dengan novelty
            spike_penalty = spike_novelty * 0.35
            # Efek spike berkurang seiring model mulai adapt (online learning)
            adapt_progress = (i - spike_start_i) / max(spike_duration, 1)
            current_penalty = spike_penalty * (1.0 - adapt_progress * 0.6)
            actual_accuracy = max(0.10, actual_accuracy - current_penalty)

        cache_hit = rng.random() < actual_accuracy

        if cache_hit:
            cumulative_hits += 1
            latency = math.exp(rng.normal(1.5, 0.3))
        else:
            latency = math.exp(rng.normal(5.2, 0.4))

        phase = (
            "warmup"   if i < 20   else
            "learning" if i < 60   else
            "spike"    if is_spike else
            "recovery" if i >= spike_end_i and i < spike_end_i + 30 else
            "mature"
        )

        timeline.append({
            "request_n":            i + 1,
            "phase":                phase,
            "accuracy_theoretical": round(theoretical, 3),
            "ml_accuracy":          round(actual_accuracy, 3),
            "cache_hit":            bool(cache_hit),
            "latency_ms":           round(latency, 2),
            "rolling_hit_rate":     round(cumulative_hits / (i + 1), 3),
            "is_spike":             is_spike,
        })

    return timeline


# ============================================================
# Summary Helper
# ============================================================

def summarize_timeline(timeline: list) -> dict:
    """Ringkasan statistik per fase dari timeline."""
    from collections import defaultdict

    phases = defaultdict(list)
    for t in timeline:
        phases[t["phase"]].append(t)

    summary = {}
    for phase, events in phases.items():
        latencies = [e["latency_ms"] for e in events]
        accuracies = [e["ml_accuracy"] for e in events]
        hit_rates = [e["rolling_hit_rate"] for e in events]
        summary[phase] = {
            "n_requests":    len(events),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
            "avg_accuracy":  round(sum(accuracies) / len(accuracies), 3),
            "final_hit_rate": round(hit_rates[-1], 3),
        }
    return summary