import threading
import time

from omnivoice.services.job_manager import StudioJobManager, wait_for_terminal


def test_jobs_run_fifo_with_single_active_worker(tmp_path):
    manager = StudioJobManager(tmp_path)
    lock = threading.Lock()
    active = 0
    max_active = 0
    order = []

    def handler(ctx):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            order.append(ctx.payload["name"])
        time.sleep(0.04)
        with lock:
            active -= 1
        return {"name": ctx.payload["name"]}

    manager.register("gpu", handler)
    manager.start()
    first = manager.submit("gpu", {"name": "A"})
    second = manager.submit("gpu", {"name": "B"})

    assert wait_for_terminal(manager, first.id).status == "completed"
    assert wait_for_terminal(manager, second.id).status == "completed"
    manager.shutdown()

    assert order == ["A", "B"]
    assert max_active == 1


def test_idempotency_key_returns_same_job(tmp_path):
    manager = StudioJobManager(tmp_path)
    manager.register("noop", lambda ctx: {"ok": True})

    first = manager.submit("noop", {"x": 1}, idempotency_key="same-command")
    second = manager.submit("noop", {"x": 999}, idempotency_key="same-command")

    assert first.id == second.id
    assert second.payload == {"x": 1}


def test_queued_job_can_be_cancelled_before_worker_starts(tmp_path):
    calls = []
    manager = StudioJobManager(tmp_path)
    manager.register("gpu", lambda ctx: calls.append(ctx.payload) or {})
    job = manager.submit("gpu", {"name": "never"})

    cancelled = manager.request_cancel(job.id)
    assert cancelled.status == "cancelled"

    manager.start()
    time.sleep(0.08)
    manager.shutdown()
    assert calls == []


def test_running_job_cancels_at_cooperative_checkpoint(tmp_path):
    entered = threading.Event()
    manager = StudioJobManager(tmp_path)

    def handler(ctx):
        entered.set()
        for index in range(100):
            ctx.emit(f"step {index}", progress=index / 100)
            time.sleep(0.005)
            ctx.checkpoint()
        return {}

    manager.register("gpu", handler)
    manager.start()
    job = manager.submit("gpu", {})
    assert entered.wait(timeout=1.0)
    manager.request_cancel(job.id)

    finished = wait_for_terminal(manager, job.id, timeout=2.0)
    manager.shutdown()
    assert finished.status == "cancelled"
    assert any(event.event == "cancel_requested" for event in finished.events)
    assert finished.events[-1].event == "cancelled"


def test_running_job_is_recovered_to_queue_after_restart(tmp_path):
    first_manager = StudioJobManager(tmp_path)
    first_manager.register("gpu", lambda ctx: {})
    job = first_manager.submit("gpu", {"project": "A"})

    manifest = first_manager.store.load()
    stored = first_manager.store.find(manifest, job.id)
    stored.status = "running"
    stored.started_at = "yesterday"
    first_manager.store.save(manifest)

    calls = []
    second_manager = StudioJobManager(tmp_path)
    second_manager.register("gpu", lambda ctx: calls.append(ctx.payload["project"]) or {})
    second_manager.start()

    finished = wait_for_terminal(second_manager, job.id)
    second_manager.shutdown()
    assert finished.status == "completed"
    assert calls == ["A"]
    assert any("Recovered" in event.message for event in finished.events) is False
    # Recovery message is stored on the job before it starts; completion replaces
    # the current message while the durable status transition still allows retry.


def test_events_after_returns_only_newer_events(tmp_path):
    manager = StudioJobManager(tmp_path)

    def handler(ctx):
        ctx.emit("quarter", progress=0.25)
        ctx.emit("half", progress=0.5)
        return {"done": True}

    manager.register("gpu", handler)
    manager.start()
    job = manager.submit("gpu", {})
    finished = wait_for_terminal(manager, job.id)
    manager.shutdown()

    assert finished.result == {"done": True}
    newer = manager.events_after(job.id, seq=2)
    assert all(event.seq > 2 for event in newer)
    assert newer[-1].event == "completed"


def test_wait_for_events_wakes_when_new_event_is_emitted(tmp_path):
    manager = StudioJobManager(tmp_path)
    manager.register("noop", lambda ctx: {})
    job = manager.submit("noop", {})
    baseline = job.events[-1].seq

    def emit_later():
        time.sleep(0.05)
        manager.emit(
            job.id,
            event="test.progress",
            message="new event",
            progress=0.5,
        )

    thread = threading.Thread(target=emit_later)
    thread.start()
    started = time.monotonic()
    events, snapshot = manager.wait_for_events(job.id, baseline, timeout=1.0)
    elapsed = time.monotonic() - started
    thread.join(timeout=1.0)

    assert elapsed < 0.5
    assert [event.event for event in events] == ["test.progress"]
    assert snapshot.status == "queued"


def test_wait_for_events_returns_immediately_for_terminal_job(tmp_path):
    manager = StudioJobManager(tmp_path)
    manager.register("noop", lambda ctx: {"ok": True})
    manager.start()
    job = manager.submit("noop", {})
    finished = wait_for_terminal(manager, job.id)
    last_seq = finished.events[-1].seq

    started = time.monotonic()
    events, snapshot = manager.wait_for_events(job.id, last_seq, timeout=1.0)
    elapsed = time.monotonic() - started
    manager.shutdown()

    assert events == []
    assert snapshot.status == "completed"
    assert elapsed < 0.2
