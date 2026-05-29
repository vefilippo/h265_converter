import os
import re
import requests
import datetime as dt
from pathlib import Path
from typing import List, Set, Tuple, Optional

from transcoder.config import settings
from transcoder.history import _parse_iso_z


class SonarrClient:
    def __init__(
        self,
        url: str = settings.SONARR_URL,
        api_key: str = settings.SONARR_API_KEY,
    ):
        self.url = url
        self.headers = {"X-Api-Key": api_key}

    def get_recent_series_ids(
        self,
        since: Optional[dt.datetime] = None,
        page_size: int = 150,
        max_pages: int = 10,
    ) -> Tuple[Set[int], Optional[dt.datetime]]:
        """
        Return (distinct_series_ids, newest_timestamp_seen).

        • If *since* is None, no filtering: every history entry counts as "new".
        • Stops paging as soon as we reach a record older than *since*.
        """
        series_ids: Set[int] = set()
        newest: Optional[dt.datetime] = None
        
        for page in range(1, max_pages + 1):
            try:
                resp = requests.get(
                    f"{self.url}/api/v3/history",
                    headers=self.headers,
                    params={
                        "page": page,
                        "pageSize": page_size,
                        "sortDirection": "descending",
                        "includeSeries": "false",
                        "includeEpisode": "false",
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                records: List[dict] = resp.json().get("records", [])
                if not records:
                    break
            except Exception as exc:
                print(f"🔴 Could not fetch Sonarr history (page {page}): {exc}")
                break

            for rec in records:
                ts = _parse_iso_z(rec["date"])
                if newest is None or ts > newest:
                    newest = ts
                if since is None or ts > since:
                    sid = rec.get("seriesId")
                    if sid:
                        series_ids.add(sid)

            # If we've paged past the watermark, stop.
            if since and _parse_iso_z(records[-1]["date"]) <= since:
                break

        return series_ids, newest

    def get_all_series(self) -> List[dict]:
        """Fetch all series from Sonarr."""
        resp = requests.get(f"{self.url}/api/v3/series", headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def get_episodes(self, series_id: int) -> List[dict]:
        """Fetch all episodes for a given series ID."""
        resp = requests.get(
            f"{self.url}/api/v3/episode",
            headers=self.headers,
            params={"seriesId": series_id},
        )
        resp.raise_for_status()
        return resp.json()

    def get_episode_file(self, episode_file_id: int) -> Optional[dict]:
        """Fetch episode file details using episodeFileId."""
        resp = requests.get(
            f"{self.url}/api/v3/episodefile/{episode_file_id}",
            headers=self.headers,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def extract_languages(episode_file: dict) -> str:
        """Extract and format language names from episode file metadata."""
        langs = episode_file.get("languages", [])
        if langs:
            return "-".join(l["name"] for l in langs).upper()
        return "UNKNOWN"

    @staticmethod
    def extract_resolution(episode_file: dict) -> int:
        """Extract resolution (e.g. 1080) from episode file metadata."""
        quality = episode_file.get("quality", {}).get("quality", {})
        return int(quality.get("resolution", 0))

    @staticmethod
    def extract_quality(episode_file: dict) -> str:
        """Extract quality name (e.g. 'HDTV-1080p') from metadata."""
        quality = episode_file.get("quality", {}).get("quality", {})
        return quality.get("name", "Unknown Quality")

    @staticmethod
    def is_h265_encoded(episode_file: dict) -> bool:
        """Check if the episode file has x265 encoding based on customFormats."""
        for fmt in episode_file.get("customFormats", []):
            if fmt.get("name", "").lower() == "x265":
                return True
        return False

    @staticmethod
    def sanitize_series_name(series_name: str) -> str:
        """Remove invalid characters so the series name is filesystem‑safe."""
        return re.sub(r"[^a-zA-Z0-9 \-]", "", series_name)

    def manual_import_one(self, full_path_host: str) -> None:
        """
        Queue a ManualImport for exactly one file in Sonarr.

        1️⃣ GET  /api/v3/manualimport?folder=…
        2️⃣ POST /api/v3/command {"name":"ManualImport", …}
        """
        # Adjust host path → Docker path if needed
        sonarr_path = full_path_host
        if settings.DOCKER_MAPPING:
            host_root, docker_root = settings.DOCKER_MAPPING
            sonarr_path = sonarr_path.replace(host_root, docker_root)
        sonarr_path = sonarr_path.replace("\\", "/")

        print(f"→ Manual‑import path: {sonarr_path}")

        try:
            folder = os.path.dirname(sonarr_path)
            # 1️⃣ List import candidates
            r1 = requests.get(
                f"{self.url}/api/v3/manualimport",
                headers=self.headers,
                params={"folder": folder, "filterExistingFiles": "true"},
                timeout=30,
            )
            r1.raise_for_status()

            candidates = [
                c for c in r1.json()
                if os.path.normcase(c["path"]) == os.path.normcase(sonarr_path)
                   and not c.get("rejections")
            ]
            if not candidates:
                print(f"🔸 Sonarr did not recognise {sonarr_path}")
                return

            info = candidates[0]
            payload = {
                "name": "ManualImport",
                "importMode": "Move",
                "files": [{
                    "path": info["path"],
                    "seriesId": info["series"]["id"],
                    "episodeIds": [e["id"] for e in info["episodes"]],
                    "quality": info.get("quality"),
                    "languages": info.get("languages"),
                    "releaseGroup": info.get("releaseGroup"),
                    "indexerFlags": info.get("indexerFlags"),
                }]
            }

            # 2️⃣ Queue the import
            r2 = requests.post(
                f"{self.url}/api/v3/command",
                headers={**self.headers, "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            r2.raise_for_status()
            print(f"🟢 Manual‑Import queued for {info['path']}")

        except Exception as exc:
            print(f"🔴 Manual‑Import failed for {full_path_host}: {exc}")
