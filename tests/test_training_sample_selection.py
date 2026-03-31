from src.ml.data_loader import DataLoader
from src.ml.trainer import ModelTrainer


def _build_mixed_access_data():
    events = []
    base_ts = 1_700_000_000.0

    for idx in range(80):
        events.append(
            {
                "key_id": "pt:login",
                "service_id": "pt",
                "timestamp": base_ts + idx * 12,
                "cache_hit": 1,
                "latency_ms": 6.0,
                "data_source": "simulation",
                "metadata": {
                    "pattern_type": "realistic",
                    "generated_kind": "realistic_flow",
                    "realism_score_hint": 0.95,
                },
            }
        )

    for idx in range(60):
        events.append(
            {
                "key_id": "mahasiswa:dashboard",
                "service_id": "mahasiswa",
                "timestamp": base_ts + idx * 15,
                "cache_hit": 1,
                "latency_ms": 8.0,
                "data_source": "simulation",
                "metadata": {
                    "pattern_type": "realistic",
                    "generated_kind": "realistic_flow",
                    "realism_score_hint": 0.92,
                },
            }
        )

    for idx in range(140):
        events.append(
            {
                "key_id": f"pt:noise:{idx}:rot:{idx % 9}:session:{idx}",
                "service_id": "pt",
                "timestamp": base_ts + idx,
                "cache_hit": 0,
                "latency_ms": 90.0,
                "data_source": "simulation",
                "metadata": {
                    "pattern_type": "random",
                    "generated_kind": "random_stress",
                    "realism_score_hint": 0.15,
                },
            }
        )

    return sorted(events, key=lambda item: item["timestamp"])


class _FakeCollector:
    def __init__(self, events):
        self._events = list(events)

    def get_stats(self):
        unique_keys = len({item["key_id"] for item in self._events})
        unique_services = len({item["service_id"] for item in self._events})
        return {
            "total_events": len(self._events),
            "unique_keys": unique_keys,
            "unique_services": unique_services,
        }

    def get_access_sequence(self, window_seconds=None, max_events=20000):
        return self._events[-max_events:]


def test_realistic_priority_filters_noisy_high_churn_keys():
    trainer = ModelTrainer(min_samples=10)
    events = _build_mixed_access_data()

    selected, summary = trainer._select_training_events(
        events,
        sample_strategy="realistic_priority",
    )

    selected_keys = {item["key_id"] for item in selected}

    assert summary["applied_strategy"] == "realistic_priority"
    assert summary["selected_events"] < summary["total_events"]
    assert "pt:login" in selected_keys
    assert "mahasiswa:dashboard" in selected_keys
    assert all("noise" not in key for key in selected_keys)


def test_auto_strategy_recommends_realistic_priority_for_mixed_dataset():
    trainer = ModelTrainer(min_samples=10)
    events = _build_mixed_access_data()
    fake_collector = _FakeCollector(events)
    trainer._collector = fake_collector
    trainer._data_loader = DataLoader(fake_collector, trainer._engineer)

    plan = trainer.get_training_plan(
        quality_profile="balanced",
        time_budget_minutes=30,
        sample_strategy="auto",
    )

    assert plan["selection_preview"]["recommended_strategy"] == "realistic_priority"
    assert plan["selection_preview"]["applied_strategy"] == "realistic_priority"
    assert plan["effective_sample_count"] < plan["collector"]["total_events"]
    assert plan["effective_unique_keys"] < plan["collector"]["unique_keys"]
