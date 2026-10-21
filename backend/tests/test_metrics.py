"""运行指标与 LLM / 编译计时器的测试（不涉及 token 或费用）。"""

from __future__ import annotations

from app.services.metrics import MetricsRegistry, compile_job, llm_call


def test_render_empty_registry():
    assert MetricsRegistry().render() == ""


def test_counter_type_emitted_once_for_multiple_label_sets():
    registry = MetricsRegistry()
    registry.inc("kiwi_demo_total", {"kind": "a"})
    registry.inc("kiwi_demo_total", {"kind": "b"}, amount=2)
    text = registry.render()
    assert text.count("# TYPE kiwi_demo_total counter") == 1
    assert 'kiwi_demo_total{kind="a"} 1' in text
    assert 'kiwi_demo_total{kind="b"} 2' in text


def test_histogram_buckets_sum_and_count():
    registry = MetricsRegistry()
    registry.observe("kiwi_demo_duration_seconds", 0.03)
    registry.observe("kiwi_demo_duration_seconds", 0.4)
    text = registry.render()
    assert text.count("# TYPE kiwi_demo_duration_seconds histogram") == 1
    assert 'kiwi_demo_duration_seconds_bucket{le="0.025"} 0' in text
    assert 'kiwi_demo_duration_seconds_bucket{le="0.05"} 1' in text
    assert 'kiwi_demo_duration_seconds_bucket{le="0.5"} 2' in text
    assert 'kiwi_demo_duration_seconds_bucket{le="+Inf"} 2' in text
    assert "kiwi_demo_duration_seconds_count 2" in text
    assert "kiwi_demo_duration_seconds_sum" in text


def test_snapshot_aggregates_labels():
    registry = MetricsRegistry()
    registry.inc("kiwi_demo_total", {"kind": "a"})
    registry.inc("kiwi_demo_total", {"kind": "b"})
    registry.observe("kiwi_demo_duration_seconds", 1.0)
    snap = registry.snapshot()
    assert snap["counters"]["kiwi_demo_total"] == 2
    assert snap["histograms"]["kiwi_demo_duration_seconds"]["count"] == 1


async def test_llm_call_records_success_and_failure():
    from app.services.metrics import metrics

    before = metrics.snapshot()["counters"].get("kiwi_llm_requests_total", 0)
    async with llm_call("test-model"):
        pass
    try:
        async with llm_call("test-model"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    after = metrics.snapshot()["counters"].get("kiwi_llm_requests_total", 0)
    assert after - before == 2


async def test_compile_job_records_outcome():
    from app.services.metrics import metrics

    before = metrics.snapshot()["counters"].get("kiwi_compile_total", 0)
    async with compile_job():
        pass
    after = metrics.snapshot()["counters"].get("kiwi_compile_total", 0)
    assert after - before == 1
