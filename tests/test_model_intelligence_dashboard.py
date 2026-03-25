from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api import routes_models
from src.database.models import (
    Base,
    KeyPrediction,
    ModelMetric,
    ModelVersion,
    PerKeyMetric,
    PredictionLog,
    TrainingMetadata,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_model_intelligence_dashboard_returns_versions_training_metrics_and_logs(db_session, monkeypatch):
    created_at = datetime.utcnow()
    version = ModelVersion(
        model_name="pskc_model",
        version_number="1",
        status="production",
        created_at=created_at,
        metrics_json={
            "runtime_version": "v1",
            "accepted": True,
            "reason": "manual",
            "decision_reason": "meaningful_accuracy_improvement",
        },
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)

    db_session.add_all(
        [
            ModelMetric(version_id=version.version_id, metric_name="accuracy", metric_value=0.82, recorded_at=created_at),
            ModelMetric(version_id=version.version_id, metric_name="top_10_accuracy", metric_value=0.97, recorded_at=created_at),
            TrainingMetadata(
                version_id=version.version_id,
                training_start_time=created_at - timedelta(seconds=42),
                training_end_time=created_at,
                samples_count=640,
                accuracy_before=0.71,
                accuracy_after=0.82,
            ),
            KeyPrediction(
                version_id=version.version_id,
                key="svc:key-1",
                predicted_value="svc:key-1",
                actual_value="svc:key-1",
                is_correct=True,
                confidence=0.91,
                timestamp=created_at,
            ),
            PerKeyMetric(
                version_id=version.version_id,
                key="svc:key-1",
                accuracy=0.82,
                drift_score=0.18,
                cache_hit_rate=0.76,
                hit_rate=0.76,
                total_predictions=11,
                error_count=2,
                avg_confidence=0.88,
                timestamp=created_at,
            ),
            PredictionLog(
                version_id=version.version_id,
                key="svc:key-1",
                predicted_value="svc:key-1",
                actual_value="svc:key-1",
                confidence=0.91,
                is_correct=True,
                latency_ms=12.4,
                timestamp=created_at,
            ),
        ]
    )
    db_session.commit()

    fake_predictor = SimpleNamespace(
        get_prediction_stats=lambda: {
            "river_online": {
                "initialized": True,
                "model_type": "adaptive_forest",
                "learn_count": 7,
                "sample_count": 125,
                "recent_predictions_count": 15,
                "last_online_learning_result": {"success": True, "sample_count": 18},
            },
            "ensemble": {
                "drift_score": 0.12,
                "outcome_count": 33,
            },
        }
    )
    fake_trainer = SimpleNamespace(
        get_stats=lambda: {
            "drift_stats": {"drift_count": 2, "warning_count": 1},
            "online_learning_count": 3,
            "last_online_learning": "2026-03-26T00:00:00+00:00",
        }
    )

    monkeypatch.setattr("src.ml.predictor.get_key_predictor", lambda: fake_predictor)
    monkeypatch.setattr("src.ml.trainer.get_model_trainer", lambda: fake_trainer)

    payload = await routes_models.model_intelligence_dashboard(db=db_session)

    assert payload["summary"]["total_versions"] == 1
    assert payload["summary"]["active_version"]["version_id"] == version.version_id
    assert payload["versions"][0]["metrics"]["accuracy"] == pytest.approx(0.82)
    assert payload["training_history"][0]["samples_count"] == 640
    assert payload["river_online"]["initialized"] is True
    assert payload["training_paths"]["online_training"]["online_learning_count"] == 3
    assert payload["drift_status"]["predictor"]["drift_score"] == pytest.approx(0.12)
    assert payload["recent_prediction_logs"][0]["key"] == "svc:key-1"
