from transcoder.engine.eligibility import compute_eligibility


def test_eligibility_rules():
    assert compute_eligibility(1080, is_h265=False, excluded=False) == "needs_transcode"
    assert compute_eligibility(2160, is_h265=False, excluded=False) == "needs_transcode"
    assert compute_eligibility(720, is_h265=False, excluded=False) == "below_1080p"
    assert compute_eligibility(1080, is_h265=True, excluded=False) == "already_h265"
    assert compute_eligibility(1080, is_h265=False, excluded=True) == "excluded"
    # excluded wins over everything
    assert compute_eligibility(720, is_h265=True, excluded=True) == "excluded"
