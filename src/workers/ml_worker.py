#!/usr/bin/env python3
"""
PSKC ML Worker Service
======================
Dedicated ML container yang menangani:
- Drift detection (EWMA-based concept drift dari event Redis)
- River online learning (incremental update per event)
- Auto-training terjadwal → memanggil API endpoint /ml/training/train
  sehingga progress tracker + WebSocket di frontend ikut aktif

Komunikasi:
- Redis  : baca events (pskc:ml:events) langsung
- API    : panggil POST /ml/training/train untuk training
           sehingga semua progress tracking + model persistence
           terpusat di API container
"""
import os
import sys
import time
import json
import logging
import signal
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MLWorkerService:
    """
    ML Worker yang terhubung ke pipeline training via API HTTP.

    Arsitektur:
      [Redis events] → drift detection + River (lokal worker)
                    → jika drift / jadwal → POST /ml/training/train (API)
                    → API jalankan training + update WebSocket progress
    """

    def __init__(self):
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Konfigurasi dari environment
        self._update_interval        = int(os.environ.get('ML_UPDATE_INTERVAL_SECONDS', '30'))
        # Scheduled training interval is separate — much longer than the drift-check loop.
        # Default: 1 hour. Drift detection can still trigger sooner.
        self._scheduled_train_interval = int(os.environ.get('ML_SCHEDULED_TRAIN_INTERVAL_SECONDS', '3600'))
        self._min_samples       = int(os.environ.get('ML_MIN_SAMPLES', '100'))
        self._drift_threshold   = float(os.environ.get('ML_DRIFT_THRESHOLD', '0.12'))
        self._enable_river      = os.environ.get('ML_ENABLE_RIVER', 'true').lower() == 'true'

        # URL API — sudah diset di docker-compose: http://api:8000
        self._api_url = os.environ.get('API_URL', 'http://api:8000').rstrip('/')

        # Redis
        self._redis_host     = os.environ.get('REDIS_HOST', 'redis')
        self._redis_port     = int(os.environ.get('REDIS_PORT', '6379'))
        self._redis_db       = int(os.environ.get('REDIS_DB', '0'))
        self._redis_password = os.environ.get('REDIS_PASSWORD', 'pskc_redis_secret')
        self._redis_client   = None

        # State internal
        self._river_learner      = None
        self._drift_detector     = None
        self._traffic_tracker    = None
        self._last_train_time    = 0.0          # epoch saat terakhir kita trigger training
        self._last_event_offset  = 0            # offset Redis agar tidak re-proses event lama
        self._consecutive_errors = 0
        self._training_ongoing   = False         # flag untuk track progress training terjadwal
        self._pattern_divergence_threshold = float(
            os.environ.get('ML_PATTERN_DIVERGENCE_THRESHOLD', '0.35')
        )

        logger.info("=" * 60)
        logger.info("PSKC ML WORKER SERVICE  (API-integrated mode)")
        logger.info("=" * 60)
        logger.info(f"API URL         : {self._api_url}")
        logger.info(f"Update interval : {self._update_interval}s")
        logger.info(f"Min samples     : {self._min_samples}")
        logger.info(f"Drift threshold : {self._drift_threshold}")
        logger.info(f"River enabled   : {self._enable_river}")
        logger.info(f"Redis           : {self._redis_host}:{self._redis_port}")

    # ------------------------------------------------------------------
    # Inisialisasi
    # ------------------------------------------------------------------

    def _connect_redis(self) -> bool:
        try:
            import redis
            self._redis_client = redis.Redis(
                host=self._redis_host,
                port=self._redis_port,
                db=self._redis_db,
                password=self._redis_password,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            self._redis_client.ping()
            
            # Set initial offset to avoid re-processing historical data
            try:
                self._last_event_offset = self._redis_client.llen("pskc:ml:events")
            except Exception:
                self._last_event_offset = 0
                
            logger.info(f"Connected to Redis at {self._redis_host}:{self._redis_port} - Starting Event Offset: {self._last_event_offset}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            return False

    def _initialize_local_components(self):
        """Inisialisasi komponen lokal (drift detector + River + traffic tracker)."""
        from src.ml.trainer import DriftDetector  # noqa: F401 (ModelTrainer not needed here)
        from src.ml.river_online_learning import RiverOnlineLearner, is_river_available
        from src.ml.traffic_pattern_tracker import TrafficPatternTracker

        self._drift_detector = DriftDetector(
            drift_threshold=self._drift_threshold,
            warning_threshold=self._drift_threshold / 2,
            ewma_alpha=0.3,
        )
        logger.info("Drift detector initialized")

        # Traffic pattern tracker (uses the same Redis connection)
        self._traffic_tracker = TrafficPatternTracker(
            redis_client=self._redis_client,
            ttl_seconds=3600,
        )
        logger.info("Traffic pattern tracker initialized")

        if self._enable_river:
            if is_river_available():
                self._river_learner = RiverOnlineLearner(
                    model_type="adaptive_forest",
                    max_depth=5,
                    n_models=5,
                    drift_threshold=0.5,
                )
                logger.info("River SRPClassifier initialized")
            else:
                logger.warning("River not available — skipping River online learning")

    # ------------------------------------------------------------------
    # Komunikasi ke API
    # ------------------------------------------------------------------

    def _api_post(self, path: str, params: dict = None, timeout: int = 30) -> Optional[Dict]:
        """POST ke API container, return JSON response atau None saat error."""
        try:
            import httpx
            url = f"{self._api_url}{path}"
            resp = httpx.post(url, params=params, timeout=timeout)
            if resp.status_code in (200, 202):
                return resp.json()
            logger.warning(f"API POST {path} returned {resp.status_code}: {resp.text[:200]}")
            return None
        except Exception as e:
            logger.error(f"API POST {path} failed: {e}")
            return None

    def _api_get(self, path: str, timeout: int = 10) -> Optional[Dict]:
        """GET ke API container, return JSON response atau None saat error."""
        try:
            import httpx
            url = f"{self._api_url}{path}"
            resp = httpx.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            logger.debug(f"API GET {path} failed: {e}")
            return None

    def _wait_for_api(self, max_wait: int = 120) -> bool:
        """Tunggu sampai API container siap menerima request."""
        logger.info(f"Waiting for API at {self._api_url} ...")
        deadline = time.time() + max_wait
        while time.time() < deadline:
            result = self._api_get("/health")
            if result and result.get("status") in ("healthy", "ok", "ready"):
                logger.info("API is ready")
                return True
            time.sleep(5)
        logger.error("API did not become ready in time")
        return False

    # ------------------------------------------------------------------
    # Trigger training lewat API
    # ------------------------------------------------------------------

    def _trigger_training(self, reason: str = "scheduled") -> bool:
        """
        Minta API untuk menjalankan training.
        Return True jika API menerima request (200 atau 202).
        """
        logger.info(f"Triggering training via API (reason={reason})...")
        result = self._api_post(
            "/ml/training/train",
            params={"force": "true", "reason": reason},
            timeout=600,   # training bisa lama
        )
        if result is not None:
            status = result.get("status") or ("success" if result.get("success") else "unknown")
            logger.info(f"Training API response: {status}")
            self._last_train_time = time.time()
            if reason == "scheduled":
                self._training_ongoing = True
                logger.info("Scheduled training progress tracking started")
            return True
        return False

    # ------------------------------------------------------------------
    # Baca & proses event dari Redis
    # ------------------------------------------------------------------

    def _fetch_new_events(self) -> list:
        """Ambil event baru dari Redis sejak offset terakhir."""
        if not self._redis_client:
            return []
        try:
            cache_key = "pskc:ml:events"
            total_len = self._redis_client.llen(cache_key)
            if total_len <= self._last_event_offset:
                return []

            # Ambil hanya event baru (max 5000 sekaligus)
            end_idx   = total_len - 1
            start_idx = max(self._last_event_offset, total_len - 5000)
            raw       = self._redis_client.lrange(cache_key, start_idx, end_idx)
            self._last_event_offset = total_len

            events = []
            for item in raw:
                try:
                    events.append(json.loads(item))
                except Exception:
                    pass
            return events
        except Exception as e:
            logger.debug(f"Redis fetch error: {e}")
            return []

    def _process_events(self, events: list) -> Dict[str, Any]:
        """
        Proses event baru:
        - Feed ke River online learning
        - Feed ke drift detector
        """
        import numpy as np

        river_updates = 0
        drift_signals = []

        for event in events:
            cache_hit  = bool(event.get('cache_hit', False))
            latency_ms = float(event.get('latency_ms', 0))  # used by River features

            # Drift detector — signature: record(cache_hit: bool) -> str
            try:
                signal = self._drift_detector.record(cache_hit=cache_hit)
                drift_signals.append(signal)
            except Exception:
                pass

            # Traffic pattern tracker — feed every event
            if self._traffic_tracker:
                try:
                    self._traffic_tracker.record_event(event)
                except Exception:
                    pass

            # River online learning
            if self._river_learner:
                try:
                    ts = float(event.get('timestamp', time.time()))
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    features = np.array([
                        dt.hour / 24.0,
                        dt.weekday() / 7.0,
                        float(cache_hit),
                        min(latency_ms / 1000.0, 10.0),
                    ])
                    label = event.get('key_id', 'unknown')
                    self._river_learner.partial_fit(features.reshape(1, -1), np.array([label]))
                    river_updates += 1
                except Exception as e:
                    logger.debug(f"River update error: {e}")

        # Spike detection — capture events if spike
        spike_detected = False
        if self._traffic_tracker:
            try:
                spike_detected = self._traffic_tracker.detect_spike()
                if spike_detected:
                    self._traffic_tracker.capture_spike_events(events)
            except Exception:
                pass

        drift_detected = "drift" in drift_signals
        return {
            "new_events": len(events),
            "river_updates": river_updates,
            "drift_detected": drift_detected,
            "drift_signals": list(set(drift_signals)),
            "spike_detected": spike_detected,
        }

    # ------------------------------------------------------------------
    # Loop utama
    # ------------------------------------------------------------------

    def _collect_and_decide(self) -> Dict[str, Any]:
        """Satu siklus: ambil event baru, proses, putuskan apakah perlu training."""
        stats: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "new_events": 0,
            "drift_detected": False,
            "training_triggered": False,
            "river_samples": 0,
        }

        # 1. Ambil event baru dari Redis
        new_events = self._fetch_new_events()
        stats["new_events"] = len(new_events)

        # 2. Proses event (River + drift)
        if new_events:
            proc = self._process_events(new_events)
            stats.update(proc)

        # River sample count
        if self._river_learner:
            stats["river_samples"] = self._river_learner.get_stats().get("sample_count", 0)

        # 3. Jika training sedang berlangsung, track progress
        if self._training_ongoing:
            progress = self._api_get("/ml/training/progress")
            if progress:
                phase = progress.get("current_phase", "unknown")
                pct = progress.get("progress_percent", 0)
                msg = progress.get("latest_update", {}).get("message", "")
                logger.info(f"Scheduled training progress: {phase} - {pct:.1f}% - {msg}")
                if phase in ("completed", "failed"):
                    self._training_ongoing = False
                    logger.info(f"Scheduled training finished: {phase}")
            else:
                logger.debug("Could not fetch training progress")

        # 4. Pattern divergence check
        if self._traffic_tracker and not stats.get("drift_detected"):
            try:
                pattern_comparison = self._check_pattern_divergence()
                if pattern_comparison:
                    stats["pattern_comparison"] = pattern_comparison
                    if pattern_comparison.get("divergence_score", 0) > self._pattern_divergence_threshold:
                        logger.warning(
                            "Pattern divergence detected (%.2f > %.2f) — triggering retraining",
                            pattern_comparison["divergence_score"],
                            self._pattern_divergence_threshold,
                        )
                        ok = self._trigger_training(reason="pattern_divergence")
                        stats["training_triggered"] = ok
            except Exception as e:
                logger.debug(f"Pattern divergence check failed: {e}")

        # 5. Putuskan apakah perlu training via API
        time_since_train = time.time() - self._last_train_time
        scheduled_due    = time_since_train >= self._scheduled_train_interval

        if stats.get("drift_detected"):
            logger.warning("Drift detected — triggering retraining via API")
            ok = self._trigger_training(reason="drift_detected")
            stats["training_triggered"] = ok

        elif not stats.get("training_triggered") and scheduled_due:
            # Cek dulu apakah API punya cukup data
            ml_status = self._api_get("/ml/status")
            if ml_status:
                # /ml/status returns sample_count at top level
                event_count = int(ml_status.get("sample_count", 0) or 0)
                stats["api_event_count"] = event_count  # Log for debugging

                if event_count >= self._min_samples:
                    logger.info(f"Scheduled training TRIGGERED — {event_count} events available (>= {self._min_samples} required)")
                    ok = self._trigger_training(reason="scheduled")
                    stats["training_triggered"] = ok
                else:
                    logger.info(f"Scheduled training SKIPPED — only {event_count}/{self._min_samples} events (need {self._min_samples - event_count} more)")
                    # Reset timer agar tidak spam check tiap 30s kalau data belum cukup
                    self._last_train_time = time.time()
            else:
                logger.warning("Could not reach API to check event count")
                self._last_train_time = time.time()

        return stats

    def _check_pattern_divergence(self) -> Optional[Dict[str, Any]]:
        """
        Load the latest training baseline profile from the API and
        compare it to the live traffic pattern captured in Redis.

        Returns the comparison result dict, or None if baseline is
        not available.
        """
        if not self._traffic_tracker:
            return None

        live_pattern = self._traffic_tracker.get_live_pattern()
        if not live_pattern or live_pattern.get("total_samples", 0) < 50:
            # Not enough live data to compare
            return None

        # Fetch baseline from API
        baseline = self._api_get("/ml/pattern/baseline")
        if not baseline or not baseline.get("total_samples"):
            return None

        from src.ml.sample_profiler import SampleProfiler
        comparison = SampleProfiler.compare_profiles(baseline, live_pattern)
        comparison["baseline_samples"] = baseline.get("total_samples", 0)
        comparison["live_samples"] = live_pattern.get("total_samples", 0)

        if comparison.get("divergence_score", 0) > 0.1:
            logger.info(
                "Pattern comparison: divergence=%.3f, temporal=%.3f, key_overlap=%.3f",
                comparison.get("divergence_score", 0),
                comparison.get("temporal_divergence", 0),
                comparison.get("key_overlap_ratio", 0),
            )

        return comparison

    def _run_worker_loop(self):
        logger.info("ML worker loop started")
        while self._running:
            try:
                stats = self._collect_and_decide()
                logger.info(
                    f"ML Worker: new_events={stats['new_events']}, "
                    f"drift={stats.get('drift_detected', False)}, "
                    f"river_samples={stats['river_samples']}, "
                    f"training_triggered={stats['training_triggered']}"
                )
                self._consecutive_errors = 0
            except Exception as e:
                self._consecutive_errors += 1
                logger.error(f"Worker loop error (#{self._consecutive_errors}): {e}")
                time.sleep(min(60, 5 * self._consecutive_errors))
                continue

            time.sleep(self._update_interval)

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    def start(self) -> bool:
        logger.info("Starting PSKC ML Worker Service...")

        if not self._connect_redis():
            logger.error("Cannot start without Redis connection")
            return False

        if not self._wait_for_api():
            logger.warning("API not ready — will retry during worker loop")

        self._initialize_local_components()

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._run_worker_loop, daemon=True
        )
        self._worker_thread.start()

        logger.info("PSKC ML Worker started")
        logger.info(f"  Drift detection  : enabled (threshold={self._drift_threshold})")
        logger.info(f"  River learning   : {'enabled' if self._river_learner else 'disabled'}")
        logger.info(f"  Auto-training    : via API {self._api_url}/ml/training/train")
        logger.info(f"  Train interval   : every {self._update_interval}s (if data sufficient)")
        return True

    def stop(self):
        logger.info("Stopping PSKC ML Worker Service...")
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=10)
        logger.info("PSKC ML Worker stopped")

    def get_status(self) -> Dict[str, Any]:
        status: Dict[str, Any] = {
            "running": self._running,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "api_url": self._api_url,
            "last_train_time": self._last_train_time,
            "training_ongoing": self._training_ongoing,
        }
        if self._river_learner:
            status["river"] = self._river_learner.get_stats()
        if self._drift_detector:
            status["drift_detector"] = self._drift_detector.get_stats()
        return status


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main():
    service = MLWorkerService()

    def _shutdown(signum, *_):
        logger.info(f"Signal {signum} received — shutting down")
        service.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    if not service.start():
        logger.error("Failed to start ML Worker Service")
        sys.exit(1)

    logger.info("ML Worker is running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
            s = service.get_status()
            logger.info(
                f"Status: running={s['running']}, "
                f"river_samples={s.get('river', {}).get('sample_count', 0)}, "
                f"drift_ok={s.get('drift_detector', {}).get('status', 'unknown')}, "
                f"training_ongoing={s.get('training_ongoing', False)}"
            )
    except KeyboardInterrupt:
        pass

    service.stop()


if __name__ == "__main__":
    main()
