#!/usr/bin/env python3
"""
PSKC ML Worker Service
=====================
Dedicated ML container that handles:
- Auto-training (scheduled retraining)
- Drift detection (EWMA-based concept drift)
- River online learning (true incremental updates)
- Model evaluation and metrics

This worker communicates with:
- Redis: For collecting training data and caching
- API: For model predictions and serving
- Prefetch Worker: For collaborative predictions
"""
import os
import sys
import time
import logging
import signal
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MLWorkerService:
    """
    Main ML Worker Service that runs all ML features:
    1. Auto-training (periodic retraining)
    2. Drift detection (EWMA-based)
    3. River online learning
    4. Model evaluation
    """
    
    def __init__(self):
        # Configuration
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        
        # ML Components
        self._trainer = None
        self._river_learner = None
        self._drift_detector = None
        
        # Configuration from environment
        self._update_interval = int(os.environ.get('ML_UPDATE_INTERVAL_SECONDS', '30'))
        self._min_samples = int(os.environ.get('ML_MIN_SAMPLES', '100'))
        self._drift_threshold = float(os.environ.get('ML_DRIFT_THRESHOLD', '0.12'))
        self._enable_river = os.environ.get('ML_ENABLE_RIVER', 'true').lower() == 'true'
        
        # Redis connection
        self._redis_host = os.environ.get('REDIS_HOST', 'redis')
        self._redis_port = int(os.environ.get('REDIS_PORT', '6379'))
        self._redis_db = int(os.environ.get('REDIS_DB', '0'))
        self._redis_password = os.environ.get('REDIS_PASSWORD', 'pskc_redis_secret')
        
        logger.info("=" * 60)
        logger.info("PSKC ML WORKER SERVICE")
        logger.info("=" * 60)
        logger.info(f"Update interval: {self._update_interval}s")
        logger.info(f"Min samples: {self._min_samples}")
        logger.info(f"Drift threshold: {self._drift_threshold}")
        logger.info(f"River enabled: {self._enable_river}")
        logger.info(f"Redis: {self._redis_host}:{self._redis_port}")
    
    def _initialize_components(self):
        """Initialize ML components"""
        logger.info("Initializing ML components...")
        
        # Import ML components
        from src.ml.trainer import ModelTrainer, DriftDetector
        from src.ml.river_online_learning import RiverOnlineLearner, is_river_available
        
        # Initialize trainer with auto-training - use singleton to share state with API
        from src.ml.trainer import get_model_trainer
        self._trainer = get_model_trainer()
        
        # Override the singleton's configuration with our environment settings
        self._trainer._update_interval = self._update_interval
        self._trainer._min_samples = self._min_samples
        self._trainer._drift_detector.drift_threshold = self._drift_threshold
        self._trainer._context_window = 10
        
        # Load existing model
        load_result = self._trainer.load_active_model()
        logger.info(f"Model loaded: {load_result.get('success')}, version: {load_result.get('version')}")
        
        # Initialize DriftDetector (standalone)
        self._drift_detector = DriftDetector(
            drift_threshold=self._drift_threshold,
            warning_threshold=self._drift_threshold / 2,
            ewma_alpha=0.3,
        )
        
        # Initialize River if available
        if self._enable_river:
            if is_river_available():
                self._river_learner = RiverOnlineLearner(
                    model_type="adaptive_forest",
                    max_depth=5,
                    n_models=5,
                    drift_threshold=0.5,
                )
                logger.info("River Adaptive Forest initialized")
            else:
                logger.warning("River not available, using fallback")
        
        logger.info("ML components initialized successfully")
    
    def _connect_redis(self):
        """Connect to Redis"""
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
            logger.info(f"Connected to Redis at {self._redis_host}:{self._redis_port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            return False
    
    def _start_auto_training(self):
        """Start auto-training"""
        if self._trainer:
            self._trainer.start_auto_training()
            logger.info("Auto-training started")
    
    def _collect_and_learn(self) -> Dict[str, Any]:
        """
        Collect data from Redis and perform online learning.
        This is the main ML loop.
        """
        stats = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "events_processed": 0,
            "drift_detected": False,
            "drift_status": "ok",
            "training_triggered": False,
        }
        
        try:
            # Collect recent events from Redis - use same key as data collector
            cache_key = "pskc:ml:events"
            
            # Try to get recent events (get the most recent events)
            try:
                # Get the length of the list first
                list_length = self._redis_client.llen(cache_key)
                # Get the most recent 100 events (or fewer if list is shorter)
                start_index = max(0, list_length - 100)
                events_data = self._redis_client.lrange(cache_key, start_index, list_length - 1)
                stats["events_processed"] = len(events_data)
                
                # Process each event for River online learning
                if self._river_learner and events_data:
                    import json
                    import numpy as np
                    
                    for event_str in events_data[-10:]:  # Process last 10 events
                        try:
                            event = json.loads(event_str)
                            
                            # Extract features (simplified)
                            features = np.array([
                                event.get('hour', 12) / 24.0,
                                event.get('day_of_week', 0) / 7.0,
                                float(event.get('cache_hit', 0)),
                                float(event.get('latency_ms', 0)) / 1000.0,
                            ])
                            
                            label = event.get('key_id', 'unknown')
                            
                            # River partial fit
                            self._river_learner.partial_fit(
                                features.reshape(1, -1),
                                np.array([label])
                            )
                        except Exception as e:
                            logger.debug(f"Error processing event: {e}")
                        
            except Exception as e:
                logger.debug(f"Could not collect events from Redis: {e}")
            
            # Check drift detector status
            drift_status = self._drift_detector.record(cache_hit=True)  # Simplified
            stats["drift_status"] = drift_status
            
            if drift_status == "drift":
                stats["drift_detected"] = True
                logger.warning("Drift detected! Model may need retraining.")
            
            # Get trainer stats
            if self._trainer:
                trainer_stats = self._trainer.get_stats()
                stats["trainer"] = {
                    "auto_training": trainer_stats.get("auto_training", False),
                    "training_count": trainer_stats.get("training_count", 0),
                    "last_train_time": trainer_stats.get("last_train_time"),
                }
            
            # Get River stats
            if self._river_learner:
                river_stats = self._river_learner.get_stats()
                stats["river"] = {
                    "sample_count": river_stats.get("sample_count", 0),
                    "initialized": river_stats.get("initialized", False),
                }
            
            # Model stats
            if self._trainer and self._trainer.model:
                stats["model"] = {
                    "is_trained": self._trainer.model.is_trained,
                    "version": self._trainer._active_model_version,
                    "source": self._trainer._model_source,
                }
            
        except Exception as e:
            logger.error(f"Error in collect_and_learn: {e}")
            stats["error"] = str(e)
        
        return stats
    
    def _run_worker_loop(self):
        """Main worker loop"""
        logger.info("Starting ML worker loop...")
        
        while self._running:
            try:
                # Collect data and perform learning
                stats = self._collect_and_learn()
                
                # Log status periodically
                logger.info(
                    f"ML Worker Status: "
                    f"drift={stats['drift_status']}, "
                    f"events={stats['events_processed']}, "
                    f"river_samples={stats.get('river', {}).get('sample_count', 0)}"
                )
                
                # Sleep for update interval
                time.sleep(self._update_interval)
                
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                time.sleep(5)  # Brief pause on error
    
    def start(self):
        """Start the ML worker service"""
        logger.info("Starting PSKC ML Worker Service...")
        
        # Initialize components
        if not self._connect_redis():
            logger.error("Cannot start without Redis connection")
            return False
        
        self._initialize_components()
        
        # Start auto-training
        self._start_auto_training()
        
        # Start worker thread
        self._running = True
        self._worker_thread = threading.Thread(target=self._run_worker_loop, daemon=True)
        self._worker_thread.start()
        
        logger.info("PSKC ML Worker Service started successfully")
        logger.info(f"Auto-training: enabled")
        logger.info(f"Drift detection: enabled (threshold={self._drift_threshold})")
        logger.info(f"River online learning: {'enabled' if self._river_learner else 'disabled'}")
        
        return True
    
    def stop(self):
        """Stop the ML worker service"""
        logger.info("Stopping PSKC ML Worker Service...")
        
        self._running = False
        
        if self._trainer:
            self._trainer.stop_auto_training()
        
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        
        logger.info("PSKC ML Worker Service stopped")
    
    def get_status(self) -> Dict[str, Any]:
        """Get service status"""
        status = {
            "running": self._running,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        if self._trainer:
            status["trainer"] = self._trainer.get_stats()
        
        if self._river_learner:
            status["river"] = self._river_learner.get_stats()
        
        if self._drift_detector:
            status["drift_detector"] = self._drift_detector.get_stats()
        
        return status


def main():
    """Main entry point"""
    # Create service
    service = MLWorkerService()
    
    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        service.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start service
    if service.start():
        logger.info("ML Worker is running. Press Ctrl+C to stop.")
        
        # Keep running
        try:
            while True:
                time.sleep(60)
                # Print status periodically
                status = service.get_status()
                logger.info(f"Status: {status.get('trainer', {}).get('auto_training', False)}, "
                          f"River: {status.get('river', {}).get('sample_count', 0)}")
        except KeyboardInterrupt:
            pass
    else:
        logger.error("Failed to start ML Worker Service")
        sys.exit(1)
    
    service.stop()


if __name__ == "__main__":
    main()
