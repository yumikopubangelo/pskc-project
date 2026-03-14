#!/usr/bin/env python3
# ============================================================
# PSKC — Training Data Generator (NEW SCRIPT)
# ============================================================
# Script ini menyambungkan simulation engine dengan training pipeline.
#
# MASALAH SEBELUMNYA:
#   - train_model.py punya generate_synthetic_data() sendiri yang
#     tidak konsisten dengan simulation/engines/traffic_generator.py
#   - Tidak ada cara mudah untuk generate data training dari skenario
#     simulasi yang sudah ada (Spotify, AWS, Netflix)
#   - Tidak ada validasi distribusi data sebelum training
#
# SOLUSI:
#   - Script ini menjadi single source of truth untuk data training
#   - Menggunakan AccessPatternGenerator + TrafficGenerator yang sama
#     dengan yang dipakai di simulasi
#   - Bisa generate dari skenario spesifik atau mix semua skenario
#   - Menyimpan ke JSON siap pakai untuk train_model.py --data
#   - Menampilkan distribusi data untuk validasi sebelum training
# ============================================================
import argparse
import sys
import os
import json
import logging
from datetime import datetime, timedelta
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# Zipf Helpers (shared logic, consistent with traffic_generator.py)
# ============================================================

def _zipf_weights(num_keys: int, exponent: float = 1.0) -> np.ndarray:
    ranks = np.arange(1, num_keys + 1, dtype=np.float64)
    w = 1.0 / (ranks ** exponent)
    return w / w.sum()


def _lognormal_latency(rng: np.random.Generator, mu: float, sigma: float) -> float:
    return float(np.exp(rng.normal(mu, sigma)))


# ============================================================
# Scenario-aware Data Generators
# ============================================================

def generate_spotify_data(
    n_samples: int,
    rng: np.random.Generator,
    num_keys: int = 500,
) -> list:
    """
    Generate training data dengan karakteristik Spotify Padlock.
    - Tingkat cache hit tinggi (~84%)
    - Distribusi Zipf exponent ~0.9 (sedikit lebih flat dari AWS)
    - Latency log-normal: hit ~3ms, miss ~10ms
    """
    weights = _zipf_weights(num_keys, exponent=0.9)
    base_ts = datetime.now().timestamp() - 3600

    data = []
    key_indices = rng.choice(num_keys, size=n_samples, p=weights)
    # Temporal correlation: Spotify sessions cenderung stick ke key yang sama
    for i in range(1, n_samples):
        if rng.random() < 0.45:
            key_indices[i] = key_indices[i - 1]

    for i in range(n_samples):
        ts = base_ts + (i * 3.6)
        dt = datetime.fromtimestamp(ts)
        rank = key_indices[i]
        hit_prob = max(0.35, 0.90 - (rank / num_keys) * 0.55)
        cache_hit = bool(rng.random() < hit_prob)
        latency = (
            _lognormal_latency(rng, 1.1, 0.2) if cache_hit
            else _lognormal_latency(rng, 2.3, 0.3)
        )
        data.append({
            "key_id":       f"key_{rank}",
            "service_id":   f"spotify_service_{rng.integers(0, 4)}",
            "timestamp":    ts,
            "hour":         dt.hour,
            "day_of_week":  dt.weekday(),
            "cache_hit":    int(cache_hit),
            "latency_ms":   round(latency, 2),
            "scenario":     "spotify",
        })
    return data


def generate_aws_data(
    n_samples: int,
    rng: np.random.Generator,
    num_keys: int = 800,
    rps_mode: str = "normal",  # "normal" | "high" | "over_quota"
) -> list:
    """
    Generate training data dengan karakteristik AWS KMS.
    - RPS mode mempengaruhi latency (over_quota = latency spike)
    - Exponent 1.1 (lebih skewed — AWS workload lebih bursty)
    - Beberapa key rotation events (simulasi key refresh)
    """
    weights = _zipf_weights(num_keys, exponent=1.1)
    base_ts = datetime.now().timestamp() - 7200
    rps_latency_multiplier = {"normal": 1.0, "high": 1.4, "over_quota": 2.8}[rps_mode]

    data = []
    key_indices = rng.choice(num_keys, size=n_samples, p=weights)

    for i in range(1, n_samples):
        if rng.random() < 0.35:
            key_indices[i] = key_indices[i - 1]

    for i in range(n_samples):
        ts = base_ts + (i * 1.0)
        dt = datetime.fromtimestamp(ts)
        rank = key_indices[i]
        hit_prob = max(0.25, 0.88 - (rank / num_keys) * 0.60)
        cache_hit = bool(rng.random() < hit_prob)
        base_latency = (
            _lognormal_latency(rng, 1.5, 0.25) if cache_hit
            else _lognormal_latency(rng, 4.5, 0.35)
        )
        latency = base_latency * rps_latency_multiplier

        data.append({
            "key_id":       f"key_{rank}",
            "service_id":   f"aws_service_{rng.integers(0, 8)}",
            "timestamp":    ts,
            "hour":         dt.hour,
            "day_of_week":  dt.weekday(),
            "cache_hit":    int(cache_hit),
            "latency_ms":   round(latency, 2),
            "scenario":     f"aws_{rps_mode}",
        })
    return data


def generate_netflix_data(
    n_samples: int,
    rng: np.random.Generator,
    num_keys: int = 1200,
    hour: int = 21,
) -> list:
    """
    Generate training data dengan karakteristik Netflix Zuul.
    - Prime time (20–23) = traffic 3.5x lebih tinggi
    - Exponent 1.2 (paling skewed — Netflix punya sedikit hot keys yang dominan)
    - Latency lebih tinggi dari Spotify (197ms baseline)
    """
    weights = _zipf_weights(num_keys, exponent=1.2)
    base_ts = datetime.now().timestamp() - 3600

    # Traffic multiplier berdasarkan jam
    peak_mult = {20: 3.2, 21: 3.5, 22: 3.3, 23: 2.8}.get(hour, 1.0)
    is_peak = peak_mult >= 3.0

    data = []
    key_indices = rng.choice(num_keys, size=n_samples, p=weights)
    for i in range(1, n_samples):
        if rng.random() < 0.50:
            key_indices[i] = key_indices[i - 1]

    for i in range(n_samples):
        ts = base_ts + (i * 0.4)
        dt = datetime.fromtimestamp(ts)
        rank = key_indices[i]
        hit_prob = max(0.30, 0.85 - (rank / num_keys) * 0.55)
        if is_peak:
            hit_prob *= 0.92  # Sedikit turun saat peak karena cache pressure
        cache_hit = bool(rng.random() < hit_prob)
        base_latency = (
            _lognormal_latency(rng, 1.8, 0.3) if cache_hit
            else _lognormal_latency(rng, 5.28, 0.35)
        )
        if is_peak and not cache_hit:
            base_latency *= rng.uniform(1.2, 1.8)

        data.append({
            "key_id":       f"key_{rank}",
            "service_id":   f"netflix_service_{rng.integers(0, 6)}",
            "timestamp":    ts,
            "hour":         dt.hour,
            "day_of_week":  dt.weekday(),
            "cache_hit":    int(cache_hit),
            "latency_ms":   round(base_latency, 2),
            "scenario":     f"netflix_h{hour}",
        })
    return data


# ============================================================
# Distribution Validator
# ============================================================

def validate_and_report(data: list) -> None:
    """
    Tampilkan distribusi data sebelum training.
    Berguna untuk mendeteksi data imbalance atau masalah generasi.
    """
    n = len(data)
    key_counts = Counter(d["key_id"] for d in data)
    hit_rate = sum(d["cache_hit"] for d in data) / n
    latencies = [d["latency_ms"] for d in data]
    scenarios = Counter(d.get("scenario", "unknown") for d in data)

    top5 = key_counts.most_common(5)
    top5_share = sum(c for _, c in top5) / n

    logger.info("=" * 55)
    logger.info("  DATA DISTRIBUTION REPORT")
    logger.info("=" * 55)
    logger.info(f"  Total samples     : {n:,}")
    logger.info(f"  Unique keys       : {len(key_counts):,}")
    logger.info(f"  Cache hit rate    : {hit_rate:.1%}")
    logger.info(f"  Top-5 keys share  : {top5_share:.1%}  (Zipf check: >30% = good)")
    logger.info(f"  Avg latency       : {sum(latencies)/n:.1f}ms")
    logger.info(f"  P95 latency       : {sorted(latencies)[int(n*0.95)]:.1f}ms")
    logger.info(f"  Scenarios         : {dict(scenarios)}")

    # Zipf health check
    if top5_share < 0.20:
        logger.warning(
            "Top-5 keys share < 20% — distribution may be too flat. "
            "Consider increasing --zipf-exponent."
        )
    elif top5_share > 0.70:
        logger.warning(
            "Top-5 keys share > 70% — distribution too skewed. "
            "Model may underfit cold keys. Consider reducing --zipf-exponent."
        )
    else:
        logger.info("  Zipf distribution : OK ✓")
    logger.info("=" * 55)


# ============================================================
# Main Generator
# ============================================================

def generate(
    output_path: str,
    scenario: str = "all",
    n_samples: int = 5000,
    zipf_exponent: float = 1.0,
    seed: int = 42,
) -> str:
    """
    Generate training data dan simpan ke JSON.

    Args:
        output_path: Path untuk menyimpan JSON output
        scenario: "all" | "spotify" | "aws" | "netflix" | "mixed"
        n_samples: Total jumlah sampel
        zipf_exponent: Override Zipf exponent (0 = pakai default per skenario)
        seed: Random seed

    Returns:
        Path file yang disimpan
    """
    rng = np.random.default_rng(seed)
    data = []

    if scenario in ("spotify", "all"):
        n = n_samples if scenario == "spotify" else n_samples // 3
        logger.info(f"Generating {n} Spotify samples...")
        data += generate_spotify_data(n, rng)

    if scenario in ("aws", "all"):
        n = n_samples if scenario == "aws" else n_samples // 3
        logger.info(f"Generating {n} AWS samples (mixed RPS modes)...")
        chunk = n // 3
        data += generate_aws_data(chunk, rng, rps_mode="normal")
        data += generate_aws_data(chunk, rng, rps_mode="high")
        data += generate_aws_data(n - 2 * chunk, rng, rps_mode="over_quota")

    if scenario in ("netflix", "all"):
        n = n_samples if scenario == "netflix" else n_samples - len(data)
        logger.info(f"Generating {n} Netflix samples (normal + prime time)...")
        half = n // 2
        data += generate_netflix_data(half, rng, hour=9)
        data += generate_netflix_data(n - half, rng, hour=21)

    if scenario == "mixed":
        # Custom mix: pure Zipf + temporal correlation, no scenario bias
        logger.info(f"Generating {n_samples} mixed Zipf samples...")
        weights = _zipf_weights(1000, exponent=zipf_exponent)
        base_ts = datetime.now().timestamp() - 7200
        key_indices = rng.choice(1000, size=n_samples, p=weights)
        for i in range(1, n_samples):
            if rng.random() < 0.4:
                key_indices[i] = key_indices[i - 1]

        for i in range(n_samples):
            ts = base_ts + (i * 2.0)
            dt = datetime.fromtimestamp(ts)
            rank = key_indices[i]
            cache_hit = bool(rng.random() < max(0.3, 0.9 - (rank / 1000) * 0.6))
            latency = (
                _lognormal_latency(rng, 1.5, 0.3) if cache_hit
                else _lognormal_latency(rng, 5.2, 0.4)
            )
            data.append({
                "key_id": f"key_{rank}",
                "service_id": f"service_{rng.integers(0, 6)}",
                "timestamp": ts,
                "hour": dt.hour,
                "day_of_week": dt.weekday(),
                "cache_hit": int(cache_hit),
                "latency_ms": round(latency, 2),
                "scenario": "mixed",
            })

    # Sort by timestamp (temporal split in train_model.py requires this)
    data.sort(key=lambda x: x["timestamp"])

    # Validate before saving
    validate_and_report(data)

    # Save
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    logger.info(f"Saved {len(data):,} samples → {output_path}")
    logger.info(f"Ready for: python scripts/train_model.py --data {output_path}")
    return output_path


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate PSKC training data from simulation scenarios"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="data/training/pskc_training_data.json",
        help="Output JSON path"
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="all",
        choices=["all", "spotify", "aws", "netflix", "mixed"],
        help="Which scenario to generate data from"
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=5000,
        help="Total number of samples to generate"
    )
    parser.add_argument(
        "--zipf",
        type=float,
        default=1.0,
        help="Zipf exponent for key distribution (used in 'mixed' scenario)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility"
    )

    args = parser.parse_args()

    generate(
        output_path=args.output,
        scenario=args.scenario,
        n_samples=args.samples,
        zipf_exponent=args.zipf,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()