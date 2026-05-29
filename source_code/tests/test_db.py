def test_make_engine_and_base_exist():
    from transcoder.db import Base, make_engine
    engine = make_engine("sqlite:///:memory:")
    assert engine is not None
    assert hasattr(Base, "metadata")
