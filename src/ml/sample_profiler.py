# ============================================================
# PSKC — Sample Profiler Module
# Extract, compare, and persist statistical fingerprints
# of training datasets.
# ============================================================
import math
import logging
import numpy as np
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class SampleProfiler:
    """
    Extracts a statistical 'fingerprint' from a training dataset
    and compares it against live traffic patterns.

    The fingerprint is compact (JSON-serializable) and captures:
      - Temporal distribution  (24-hour histogram)
      - Key frequency          (top-50 keys)
      - Service distribution   (proportional)
      - Cache-hit rate
      - Latency percentiles
      - RF feature statistics  (mean & std per column)
    """

    # ----------------------------------------------------------------
    # Extract
    # ----------------------------------------------------------------

    @staticmethod
    def extract_profile(
        access_data: List[Dict[str, Any]],
        X_rf: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Build a statistical profile from training ``access_data``.

        Parameters
        ----------
        access_data : list[dict]
            The list of event dicts produced by ``DataCollector.get_access_sequence()``.
            Expected keys: ``key_id``, ``service_id``, ``timestamp``,
            ``cache_hit``, ``latency_ms``, ``hour``.
        X_rf : np.ndarray, optional
            The RF feature matrix (n_samples × n_features) used for training.
            If provided, per-feature mean/std are included in the profile.

        Returns
        -------
        dict
            A JSON-serializable profile dictionary.
        """
        if not access_data:
            return {"total_samples": 0, "unique_keys": 0, "unique_services": 0}

        total = len(access_data)

        # --- Key frequency (top 50) ----------------------------------
        key_counts = Counter(e.get("key_id", "?") for e in access_data)
        top_keys = dict(key_counts.most_common(50))

        # --- Service distribution (proportional) ---------------------
        svc_counts = Counter(e.get("service_id", "?") for e in access_data)
        svc_dist = {
            svc: round(cnt / total, 4) for svc, cnt in svc_counts.most_common(30)
        }

        # --- Temporal histogram (24 hours) ---------------------------
        hour_hist: Dict[str, int] = defaultdict(int)
        for e in access_data:
            h = e.get("hour")
            if h is None:
                try:
                    h = datetime.fromtimestamp(e.get("timestamp", 0)).hour
                except Exception:
                    h = 0
            hour_hist[str(h)] += 1

        # --- Cache-hit rate ------------------------------------------
        cache_hits = sum(1 for e in access_data if e.get("cache_hit"))
        cache_hit_rate = round(cache_hits / total, 4) if total else 0.0

        # --- Latency -------------------------------------------------
        latencies = [float(e.get("latency_ms", 0)) for e in access_data if e.get("latency_ms") is not None]
        if latencies:
            avg_latency = round(float(np.mean(latencies)), 2)
            p95_latency = round(float(np.percentile(latencies, 95)), 2)
        else:
            avg_latency = 0.0
            p95_latency = 0.0

        # --- RF feature stats ----------------------------------------
        feature_stats: Optional[Dict[str, Dict[str, float]]] = None
        if X_rf is not None and len(X_rf) > 0:
            feature_stats = {}
            for col_idx in range(X_rf.shape[1]):
                col = X_rf[:, col_idx]
                feature_stats[f"feat_{col_idx}"] = {
                    "mean": round(float(np.mean(col)), 6),
                    "std": round(float(np.std(col)), 6),
                }

        profile = {
            "total_samples": total,
            "unique_keys": len(key_counts),
            "unique_services": len(svc_counts),
            "temporal_profile": dict(hour_hist),
            "key_frequency_profile": top_keys,
            "service_distribution": svc_dist,
            "cache_hit_rate": cache_hit_rate,
            "avg_latency_ms": avg_latency,
            "latency_p95_ms": p95_latency,
            "feature_stats": feature_stats,
        }
        logger.info(
            "Extracted training sample profile: %d samples, %d keys, %d services",
            total, len(key_counts), len(svc_counts),
        )
        return profile

    # ----------------------------------------------------------------
    # Compare
    # ----------------------------------------------------------------

    @staticmethod
    def compare_profiles(
        baseline: Dict[str, Any],
        live: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Compare a stored training-baseline profile against a live traffic
        pattern and return a divergence report.

        Returns
        -------
        dict
            ``divergence_score`` (0-1, higher = more different),
            ``temporal_divergence``, ``key_overlap``, etc.
        """
        result: Dict[str, Any] = {
            "divergence_score": 0.0,
            "temporal_divergence": 0.0,
            "key_overlap_ratio": 1.0,
            "cache_hit_rate_delta": 0.0,
            "details": {},
        }

        if not baseline or not live:
            return result

        scores = []

        # 1. Temporal divergence (Jensen-Shannon on 24-hour histograms)
        base_temporal = baseline.get("temporal_profile", {})
        live_temporal = live.get("temporal_profile", {})
        if base_temporal and live_temporal:
            td = SampleProfiler._js_divergence_hists(base_temporal, live_temporal)
            result["temporal_divergence"] = round(td, 4)
            scores.append(td)

        # 2. Key overlap (Jaccard index on top-50 keys)
        base_keys = set(baseline.get("key_frequency_profile", {}).keys())
        live_keys = set(live.get("key_frequency_profile", {}).keys())
        if base_keys or live_keys:
            union = base_keys | live_keys
            intersection = base_keys & live_keys
            jaccard = len(intersection) / len(union) if union else 1.0
            result["key_overlap_ratio"] = round(jaccard, 4)
            # Convert to divergence (0 = same, 1 = fully different)
            scores.append(1.0 - jaccard)

        # 3. Cache-hit rate delta
        base_chr = float(baseline.get("cache_hit_rate", 0) or 0)
        live_chr = float(live.get("cache_hit_rate", 0) or 0)
        delta = abs(live_chr - base_chr)
        result["cache_hit_rate_delta"] = round(delta, 4)
        scores.append(min(delta / 0.3, 1.0))  # 30% swing = max divergence

        # 4. Service distribution divergence
        base_svc = baseline.get("service_distribution", {})
        live_svc = live.get("service_distribution", {})
        if base_svc and live_svc:
            sd = SampleProfiler._js_divergence_hists(base_svc, live_svc)
            result["details"]["service_divergence"] = round(sd, 4)
            scores.append(sd)

        # Overall divergence (average of component scores)
        if scores:
            result["divergence_score"] = round(sum(scores) / len(scores), 4)

        return result

    # ----------------------------------------------------------------
    # Persist / Load
    # ----------------------------------------------------------------

    @staticmethod
    def save_profile(
        version_id: int,
        profile: Dict[str, Any],
        db_session,
    ) -> bool:
        """Persist a ``TrainingSampleProfile`` row linked to *version_id*."""
        try:
            from src.database.models import TrainingSampleProfile

            row = TrainingSampleProfile(
                version_id=version_id,
                total_samples=profile.get("total_samples", 0),
                unique_keys=profile.get("unique_keys", 0),
                unique_services=profile.get("unique_services", 0),
                temporal_profile=profile.get("temporal_profile"),
                key_frequency_profile=profile.get("key_frequency_profile"),
                service_distribution=profile.get("service_distribution"),
                cache_hit_rate=profile.get("cache_hit_rate"),
                avg_latency_ms=profile.get("avg_latency_ms"),
                latency_p95_ms=profile.get("latency_p95_ms"),
                feature_stats=profile.get("feature_stats"),
            )
            db_session.add(row)
            db_session.commit()
            logger.info("Saved training sample profile for version_id=%d", version_id)
            return True
        except Exception as exc:
            db_session.rollback()
            logger.error("Failed to save training sample profile: %s", exc)
            return False

    @staticmethod
    def load_latest_profile(
        model_name: str,
        db_session,
    ) -> Optional[Dict[str, Any]]:
        """Load the most recent profile for the active production model."""
        try:
            from src.database.models import TrainingSampleProfile, ModelVersion

            row = (
                db_session.query(TrainingSampleProfile)
                .join(ModelVersion, ModelVersion.version_id == TrainingSampleProfile.version_id)
                .filter(ModelVersion.model_name == model_name)
                .order_by(TrainingSampleProfile.created_at.desc())
                .first()
            )
            if row is None:
                return None

            return {
                "version_id": row.version_id,
                "total_samples": row.total_samples,
                "unique_keys": row.unique_keys,
                "unique_services": row.unique_services,
                "temporal_profile": row.temporal_profile,
                "key_frequency_profile": row.key_frequency_profile,
                "service_distribution": row.service_distribution,
                "cache_hit_rate": row.cache_hit_rate,
                "avg_latency_ms": row.avg_latency_ms,
                "latency_p95_ms": row.latency_p95_ms,
                "feature_stats": row.feature_stats,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        except Exception as exc:
            logger.error("Failed to load latest training sample profile: %s", exc)
            return None

    # ----------------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------------

    @staticmethod
    def _js_divergence_hists(
        hist_a: Dict[str, Any],
        hist_b: Dict[str, Any],
    ) -> float:
        """
        Jensen-Shannon divergence between two (possibly sparse) histograms.
        Returns a value in [0, 1].
        """
        all_keys = set(hist_a.keys()) | set(hist_b.keys())
        if not all_keys:
            return 0.0

        # Normalize to probability distributions
        sum_a = sum(float(v) for v in hist_a.values()) or 1.0
        sum_b = sum(float(v) for v in hist_b.values()) or 1.0

        p = {k: float(hist_a.get(k, 0)) / sum_a for k in all_keys}
        q = {k: float(hist_b.get(k, 0)) / sum_b for k in all_keys}

        # M = (P + Q) / 2
        m = {k: (p[k] + q[k]) / 2.0 for k in all_keys}

        def _kl(dist, ref):
            total = 0.0
            for k in all_keys:
                if dist[k] > 0 and ref[k] > 0:
                    total += dist[k] * math.log(dist[k] / ref[k])
            return total

        js = (_kl(p, m) + _kl(q, m)) / 2.0
        # Clamp to [0, 1] — theoretical max of JS is ln(2) ≈ 0.693
        return min(js / math.log(2), 1.0)
