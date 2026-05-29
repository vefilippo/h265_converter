def compute_eligibility(resolution: int, is_h265: bool, excluded: bool) -> str:
    if excluded:
        return "excluded"
    if is_h265:
        return "already_h265"
    if resolution < 1080:
        return "below_1080p"
    return "needs_transcode"
