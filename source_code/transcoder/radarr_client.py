import os
import re
import requests
import datetime as dt
from pathlib import Path
from typing import List, Set, Tuple, Optional

from transcoder.config import settings
from transcoder.history import _parse_iso_z


class RadarrClient:
    def __init__(
        self,
        url: str = settings.RADARR_URL,
        api_key: str = settings.RADARR_API_KEY,
    ):
        self.url = url
        self.headers = {"X-Api-Key": api_key}

    def get_all_movies(self) -> List[dict]:
        url = f"{self.url}/api/v3/movie"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def filter_non_h265_movies(self, movies) -> List[dict]:
        non_h265 = []
        for movie in movies:
            movie_file = movie.get('movieFile')  # this is a dict, not a list
            if not movie_file:
                continue
            media_info = movie_file.get('mediaInfo', {})
            video_codec = media_info.get('videoCodec', '').lower()
            if all(x not in video_codec for x in ['h265', 'hevc', 'x265']):
                languages = self.extract_languages(movie_file)
                non_h265.append({
                    "title": movie["title"],
                    "codec": video_codec or "unknown",
                    "path": movie_file.get("path", "unknown"),
                    "resolution": movie_file.get("quality").get("quality").get("resolution"),
                    "quality": movie_file.get("quality").get("quality").get("name"),
                    "languages": languages,
                    "year": movie["year"]
                })
        return non_h265
        
    def extract_languages(self, movie_file)-> List[dict]:
        """Extract and format language names from episode file metadata."""
        if 'languages' in movie_file:
            return "-".join(lang['name'] for lang in movie_file['languages']).upper()
        return "UNKNOWN"

    def manual_import_one(self, full_path_host: str) -> None:
        radarr_path = full_path_host
        if settings.DOCKER_MAPPING:
            host_root, docker_root = settings.DOCKER_MAPPING
            radarr_path = radarr_path.replace(host_root, docker_root)
        radarr_path = radarr_path.replace("\\", "/")

        print(f"→ Manual‑import path: {radarr_path}")

        try:
            folder = os.path.dirname(radarr_path)
            r1 = requests.get(
                f"{self.url}/api/v3/manualimport",
                headers=self.headers,
                params={"folder": folder, "filterExistingFiles": "true"},
                timeout=30,
            )
            r1.raise_for_status()

            candidates = [
                c for c in r1.json()
                if os.path.normcase(c["path"]) == os.path.normcase(radarr_path)
                   and not c.get("rejections")
            ]
            if not candidates:
                print(f"🔸 Radarr did not recognise {radarr_path}")
                return

            info = candidates[0]
            payload = {
                "name": "ManualImport",
                "importMode": "Move",
                "files": [{
                    "path": info["path"],
                    "movieId": info["movie"]["id"],
                    "quality": info.get("quality"),
                    "languages": info.get("languages"),
                    "releaseGroup": info.get("releaseGroup"),
                    "indexerFlags": info.get("indexerFlags"),
                }]
            }

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
