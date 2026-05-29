import threading
import time
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from transcoder.db import Base
from transcoder.models import Job, MediaItem
from transcoder.worker_controller import WorkerController
from sqlalchemy import create_engine


def _make_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _add_job(Session):
    s = Session()
    item = MediaItem(source="sonarr", external_id="1", title="A",
                     remote_path="/x.mkv", resolution=1080, eligibility="needs_transcode")
    s.add(item); s.commit()
    job = Job(media_item_id=item.id, state="queued")
    s.add(job); s.commit()
    jid = job.id
    s.close()
    return jid


def test_controller_processes_queued_job():
    Session = _make_factory()
    jid = _add_job(Session)
    processed = []

    def fake_process(session, job, clients, *, cancel_event=None, **io):
        job.state = "done"
        session.commit()
        processed.append(job.id)

    ctrl = WorkerController(Session, clients={}, process=fake_process, idle_timeout=0.1)
    ctrl.start()
    ctrl.wake()
    for _ in range(50):
        if processed:
            break
        time.sleep(0.05)
    ctrl.shutdown()
    assert processed == [jid]
    s = Session()
    assert s.get(Job, jid).state == "done"
    s.close()


def test_controller_cancel_queued_job_is_skipped():
    Session = _make_factory()
    jid = _add_job(Session)
    started = threading.Event()

    def fake_process(session, job, clients, *, cancel_event=None, **io):
        started.set()
        job.state = "done"
        session.commit()

    ctrl = WorkerController(Session, clients={}, process=fake_process, idle_timeout=0.1)
    ctrl.request_cancel(jid)
    ctrl.start()
    ctrl.wake()
    time.sleep(0.3)
    ctrl.shutdown()
    assert started.is_set() is False
    s = Session()
    assert s.get(Job, jid).state == "cancelled"
    s.close()


def test_controller_cancel_running_sets_event():
    Session = _make_factory()
    jid = _add_job(Session)
    entered = threading.Event()
    saw_cancel = {}

    def fake_process(session, job, clients, *, cancel_event=None, **io):
        entered.set()
        for _ in range(100):
            if cancel_event is not None and cancel_event.is_set():
                saw_cancel["set"] = True
                break
            time.sleep(0.02)
        job.state = "cancelled"
        session.commit()

    ctrl = WorkerController(Session, clients={}, process=fake_process, idle_timeout=0.1)
    ctrl.start()
    ctrl.wake()
    assert entered.wait(timeout=2.0)
    ctrl.request_cancel(jid)
    for _ in range(100):
        if saw_cancel.get("set"):
            break
        time.sleep(0.02)
    ctrl.shutdown()
    assert saw_cancel.get("set") is True
