from src.api.simulation_service import list_simulation_scenarios, run_simulation_job


def test_list_simulation_scenarios_exposes_frontend_views():
    payload = list_simulation_scenarios()

    assert payload["default_scenario"] == "siakad"
    assert any(view["id"] == "scenario_lab" for view in payload["available_views"])
    assert any(view["id"] == "realtime" for view in payload["available_views"])


def test_run_simulation_job_returns_integrated_simulation_payload():
    result = run_simulation_job(
        scenario_id="siakad",
        profile_id="normal",
        request_count=80,
        seed=1234,
    )

    assert result["status"] == "completed"
    assert result["request_count"] == 80
    assert "integrated_simulation" in result

    integrated = result["integrated_simulation"]
    assert integrated["source"] == "simulation_folder"
    assert "cache_flow" in integrated
    assert "detailed_trace" in integrated

    cache_flow = integrated["cache_flow"]
    assert cache_flow["with_pskc"]["total_requests"] == 80
    assert cache_flow["without_pskc"]["total_requests"] == 80
    assert isinstance(cache_flow["with_pskc"]["path_breakdown"], list)
    assert isinstance(cache_flow["path_comparison"], list)

    trace_view = integrated["detailed_trace"]
    assert trace_view["service_id"] == "portal_nilai"
    assert len(trace_view["trace_preview"]) >= 12
    assert all("cache_layer" in row for row in trace_view["trace_preview"])


def test_run_simulation_job_supports_dynamic_profile_trace_notes():
    result = run_simulation_job(
        scenario_id="dynamic",
        profile_id="resilience",
        request_count=60,
        seed=99,
    )

    trace_view = result["integrated_simulation"]["detailed_trace"]

    assert trace_view["profile_id"] == "resilience"
    assert any("churn produksi" in note for note in trace_view["notes"])
