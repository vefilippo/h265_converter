import logging
from transcoder.log_buffer import RingBufferHandler


def test_buffer_captures_and_cursors():
    h = RingBufferHandler(capacity=3)
    log = logging.getLogger("test.ring")
    log.handlers = [h]
    log.setLevel(logging.INFO)
    log.propagate = False
    log.info("one"); log.warning("two"); log.error("three")

    lines = h.after(0)
    assert [l["message"] for l in lines] == ["one", "two", "three"]
    assert [l["level"] for l in lines] == ["INFO", "WARNING", "ERROR"]
    assert lines[0]["seq"] == 1 and lines[-1]["seq"] == 3
    assert "ts" in lines[0]

    assert [l["message"] for l in h.after(2)] == ["three"]

    log.info("four")
    msgs = [l["message"] for l in h.after(0)]
    assert msgs == ["two", "three", "four"]
    assert h.after(0)[-1]["seq"] == 4
