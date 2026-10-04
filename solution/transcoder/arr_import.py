"""Helpers shared by the Sonarr and Radarr clients for getting a transcoded
file re-imported in place of the original."""
import os


class ImportNotQueued(RuntimeError):
    """Sonarr/Radarr did not accept the uploaded file for import."""


def _revision_tokens(revision: dict | None) -> list[str]:
    # Tokens chosen so BOTH parsers read back the same revision (verified
    # against live Radarr/Sonarr /api/v3/parse): "v3" only works in Sonarr,
    # while "REPACK<n>" means version n+1 in both. Without the tokens the
    # output parses as v1 and is rejected as a downgrade of a Proper source.
    rev = revision or {}
    version = int(rev.get("version") or 1)
    tokens = ["REAL"] * int(rev.get("real") or 0)
    if version == 2:
        tokens.append("REPACK" if rev.get("isRepack") else "Proper")
    elif version >= 3:
        tokens.append(f"REPACK{version - 1}")
    return tokens


def release_quality(quality: dict | None) -> str:
    """Render a Sonarr/Radarr quality object as the filename quality string,
    e.g. ``{"quality": {"name": "Bluray-1080p"}, "revision": {"version": 2}}``
    -> ``"Bluray-1080p Proper"``."""
    q = quality or {}
    name = (q.get("quality") or {}).get("name") or "Unknown Quality"
    return " ".join([name, *_revision_tokens(q.get("revision"))])


def pick_candidate(candidates: list[dict], path: str, app: str) -> dict:
    """Return the manual-import candidate for ``path``; raise ImportNotQueued
    carrying the app's own rejection reasons when it will not import it."""
    target = os.path.normcase(path)
    matches = [c for c in candidates if os.path.normcase(c.get("path", "")) == target]
    if not matches:
        raise ImportNotQueued(f"{app} did not find {path} in its import folder")
    for c in matches:
        if not c.get("rejections"):
            return c
    reasons = "; ".join(
        r.get("reason", "unknown") for c in matches for r in c.get("rejections") or []
    )
    raise ImportNotQueued(f"{app} rejected {path}: {reasons}")
