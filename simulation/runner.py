"""
Simulation Runner — PSKC Academic & Government Edition
=======================================================
Entry point untuk menjalankan semua skenario simulasi PSKC
dengan studi kasus sistem autentikasi akademik dan pemerintahan Indonesia.

Skenario:
    1. SIAKAD SSO (PT tunggal) — berbasis JSiI 2023 + MDPI 2025
    2. SEVIMA Siakadcloud (multi-tenant) — berbasis data SEVIMA resmi
    3. PDDikti (skala nasional) — berbasis data Kemdikbudristek 2024
    4. Cold Start — evolusi ML dari warmup ke mature

Usage:
    python simulation/runner.py
    python simulation/runner.py --scenario siakad
    python simulation/runner.py --scenario sevima
    python simulation/runner.py --scenario pddikti --requests 2000
    python simulation/runner.py --scenario all
"""

import json
import argparse

from scenarios.siakad_sso    import run_batch as run_siakad
from scenarios.sevima_cloud  import run_batch as run_sevima
from scenarios.pddikti_auth  import run_batch as run_pddikti
from scenarios.dynamic_production import run_batch as run_dynamic
from engines.cold_start_simulator  import simulate_cold_start


def print_comparison(without: dict, with_pskc: dict, label: str = ""):
    if label:
        print(f"  >> {label}")
    avg_reduction = round((1 - with_pskc["avg_ms"] / without["avg_ms"]) * 100, 1)
    p99_reduction = round((1 - with_pskc["p99_ms"] / without["p99_ms"]) * 100, 1)
    print(f"  Avg latency : {without['avg_ms']}ms → {with_pskc['avg_ms']}ms  ({avg_reduction}% ↓)")
    print(f"  P99 latency : {without['p99_ms']}ms → {with_pskc['p99_ms']}ms  ({p99_reduction}% ↓)")
    if with_pskc.get("cache_hit_rate"):
        print(f"  Cache hit   : {with_pskc['cache_hit_rate'] * 100:.1f}%")
    if with_pskc.get("timeout_rate", 0) > 0:
        print(f"  Timeout rate: {with_pskc['timeout_rate'] * 100:.2f}%")


def run_all(n_requests: int = 1000):
    print("=" * 65)
    print("  PSKC Simulation Report")
    print("  Studi Kasus: Autentikasi Akademik & Pemerintahan Indonesia")
    print("=" * 65)

    # --- SIAKAD SSO ---
    print("\n[SCENARIO 1] SIAKAD SSO — Portal Akademik Perguruan Tinggi")
    print("  Sumber: JSiI Vol.10 No.1 (2023); MDPI App. Sci. 15(22) (2025)")
    for period, label in [
        ("normal"    , "Hari Kuliah Normal"),
        ("krs_online", "KRS Online (Peak Ekstrem)"),
        ("uas"       , "Periode UAS"),
    ]:
        sn_without = run_siakad(n_requests // 3, use_pskc=False, period=period)
        sn_with    = run_siakad(n_requests // 3, use_pskc=True,  period=period)
        print_comparison(sn_without, sn_with, label=label)

    # --- SEVIMA Siakadcloud ---
    print("\n[SCENARIO 2] SEVIMA Siakadcloud — SIAKAD Multi-Tenant")
    print("  Sumber: SEVIMA (2024) — >900 PT Indonesia; MDPI (2025) baseline")
    for rps, tenants, label in [
        (500,  80,  "Normal (500 RPS, 80 tenant aktif)"),
        (4000, 300, "Peak KRS (4000 RPS, 300 tenant)"),
        (9000, 500, "Over-quota (9000 RPS, 500 tenant)"),
    ]:
        sv_without = run_sevima(n_requests // 3, use_pskc=False, rps_load=rps, tenant_count=tenants)
        sv_with    = run_sevima(n_requests // 3, use_pskc=True,  rps_load=rps, tenant_count=tenants)
        print_comparison(sv_without, sv_with, label=label)

    # --- PDDikti ---
    print("\n[SCENARIO 3] PDDikti — Pangkalan Data Pendidikan Tinggi Nasional")
    print("  Sumber: Kemdikbudristek (2024) — >4.900 PT, 9,6 juta mahasiswa")
    for mode, label in [
        ("normal"       , "Akses Normal"),
        ("deadline_week", "Deadline Feeder Semester (Peak)"),
        ("publik_peak"  , "Masa Wisuda (Verifikasi Publik)"),
    ]:
        pd_without = run_pddikti(n_requests // 3, use_pskc=False, mode=mode)
        pd_with    = run_pddikti(n_requests // 3, use_pskc=True,  mode=mode)
        print_comparison(pd_without, pd_with, label=label)

    # --- Cold Start ---
    print("\n[COLD START ANALYSIS]")
    print("  ML model evolution dari 0 request hingga mature")
    timeline = simulate_cold_start(200)
    phases = {"warmup": [], "learning": [], "mature": []}
    for t in timeline:
        if t["phase"] in phases:
            phases[t["phase"]].append(t["latency_ms"])
    for phase, vals in phases.items():
        if vals:
            avg = round(sum(vals) / len(vals), 1)
            print(f"  {phase:10s}: avg {avg}ms  (n={len(vals)} requests)")

    print("\n" + "=" * 65)
    print("  Simulation complete.")
    print("  Referensi lengkap: simulation/references/README.md")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="PSKC Simulation Runner — Academic & Government Edition"
    )
    parser.add_argument(
        "--scenario",
        default="all",
        choices=["all", "siakad", "sevima", "pddikti", "dynamic", "coldstart"],
    )
    parser.add_argument("--requests", type=int, default=1000)
    args = parser.parse_args()

    if args.scenario == "all":
        run_all(args.requests)
    elif args.scenario == "siakad":
        for period in ["normal", "krs_online", "uts", "uas"]:
            r = run_siakad(args.requests, use_pskc=True, period=period)
            print(f"[SIAKAD {period}] {json.dumps(r, indent=2)}")
    elif args.scenario == "sevima":
        for rps, t in [(500, 80), (4000, 300), (9000, 500)]:
            r = run_sevima(args.requests, use_pskc=True, rps_load=rps, tenant_count=t)
            print(f"[SEVIMA RPS={rps}] {json.dumps(r, indent=2)}")
    elif args.scenario == "pddikti":
        for mode in ["normal", "pre_deadline", "deadline_week", "post_deadline"]:
            r = run_pddikti(args.requests, use_pskc=True, mode=mode)
            print(f"[PDDikti {mode}] {json.dumps(r, indent=2)}")
    elif args.scenario == "dynamic":
        r = run_dynamic(args.requests, use_pskc=True)
        print(json.dumps(r, indent=2))
    elif args.scenario == "coldstart":
        timeline = simulate_cold_start(200)
        print(json.dumps(timeline[:10], indent=2))
        print(f"... ({len(timeline)} total entries)")