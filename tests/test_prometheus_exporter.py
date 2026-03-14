from fastapi.testclient import TestClient

from src.api.routes import app


def test_prometheus_metrics_endpoint_exposes_text_format():
    with TestClient(app) as client:
        response = client.get("/metrics/prometheus")

    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    assert "pskc_requests_total" in response.text
    assert "pskc_prefetch_queue_length" in response.text
    assert "pskc_ml_model_loaded" in response.text
    assert "pskc_ml_registry_signed_versions" in response.text
    assert "pskc_ml_lifecycle_events_total" in response.text
