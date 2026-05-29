#!/usr/bin/env python3

import argparse
import sys
from typing import Optional, Set
import datetime as dt
import re
import os

from transcoder.logging_setup import init_logging
from transcoder.config import settings
from transcoder.history import (
    load_last_history_date,
    save_last_history_date
)
from transcoder.exclusion import (load_excluded_episodes, save_excluded_episodes, load_excluded_movies, save_excluded_movies)
from transcoder.sonarr_client import SonarrClient
from transcoder.radarr_client import RadarrClient
from transcoder.sftp_client import (upload_file_via_sftp, download_file_via_sftp)
from transcoder.convert import convert_with_handbrake


def handle_sonarr(scope: str, target_title: Optional[str]) -> None:
    print("▶️  Starting Sonarr processing…")
    os.makedirs("./tmp", exist_ok=True)
    excluded_eps = load_excluded_episodes()

    client = SonarrClient(settings.SONARR_URL, settings.SONARR_API_KEY)
    
    watermark = load_last_history_date() if scope == "new" else None
    recent_ids: Set[int] = set()
    newest_seen: Optional[dt.datetime] = None

    if scope == "new":
        recent_ids, newest_seen = client.get_recent_series_ids(watermark)
        if watermark is None:
            print("⏲️  First incremental run – watermark initialized; processing all series this time.")
        elif not recent_ids:
            print("✓ Nothing new since last run.")
            if newest_seen:
                save_last_history_date(newest_seen)
            return

    all_series = client.get_all_series()

    if target_title:
        all_series = [
            s for s in all_series
            if s["title"].lower() == target_title
        ]
    elif scope == "new" and watermark is not None:
        all_series = [s for s in all_series if s["id"] in recent_ids]

    if not all_series:
        print("⚠️  No matching series to process – skipping Sonarr.")
        return

    all_series.sort(key=lambda s: s["title"].lower())
    for series in all_series:
        print(f"🔄 Processing series: {series['title']}")
        #process_series(series, excluded_eps)
        series_id = series['id']
        series_title = series['title']
        episodes = client.get_episodes(series_id)
    
        for episode in episodes:
            if episode.get('hasFile'):
                if (series_title, str(episode['seasonNumber']), str(episode['episodeNumber'])) in excluded_eps:
                    #print(f"Skipping episode: {series_title} S{episode['seasonNumber']:02}E{episode['episodeNumber']:02} as in exclusion list")
                    continue
                episode_file = client.get_episode_file(episode['episodeFileId'])
                if episode_file and 'path' in episode_file:
                    file_path = episode_file['path'].replace("/TVShows/", settings.LOCAL_FOLDER)#.replace("/", "\\")
                
                resolution = client.extract_resolution(episode_file)
                if resolution < 1080:
                    #print(f"Skipping episode: {series_title} S{episode['seasonNumber']:02}E{episode['episodeNumber']:02} for low resolution --> {resolution} < 1080p")
                    continue  # Skip videos with resolution lower than 1080p
                preset = settings.PRESET_4K if resolution > 1080 else settings.PRESET_1080
                if client.is_h265_encoded(episode_file):
                    #print(f"Skipping episode: {series_title} S{episode['seasonNumber']:02}E{episode['episodeNumber']:02} as lready h265")
                    continue
                if file_path and not client.is_h265_encoded(episode_file):
                    languages = client.extract_languages(episode_file)
                    quality = client.extract_quality(episode_file)
                    sanitized_series = re.sub(r'[^a-zA-Z0-9 \-]', '', series_title)
                    new_file_name = f"{sanitized_series} - S{episode['seasonNumber']:02}E{episode['episodeNumber']:02} - h265 - [{languages}] {quality} {settings.RELEASE_TAG}.mkv"
                    print(f"Processing: {series_title} S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}")
                    
                    #download the file
                    tmp_file = os.path.join("./tmp", os.path.basename(file_path))
                    download_file_via_sftp(settings.HOSTNAME, settings.PORT, settings.USERNAME, settings.PASSWORD, file_path, tmp_file)
                    
                    output_file, exclude_flag = convert_with_handbrake(tmp_file, new_file_name, preset)

                    if output_file is None:
                        continue

                    if exclude_flag:
                        print(f"Converted file is larger. Adding to exclusion list.")
                        save_excluded_episodes(series_title, episode['seasonNumber'], episode['episodeNumber'])
                    else:
                        upload_file_via_sftp(settings.HOSTNAME, settings.PORT, settings.USERNAME, settings.PASSWORD, output_file, settings.WATCH_FOLDER + new_file_name)
                        client.manual_import_one(output_file)

                    os.remove(output_file)

    if scope == "new" and newest_seen:
        save_last_history_date(newest_seen)

    print("✓ Sonarr processing complete.")


def handle_radarr(scope: str, target_movie: Optional[str]) -> None:
    print("▶️  Starting Radarr processing…")
    os.makedirs("./tmp", exist_ok=True)

    client = RadarrClient(settings.RADARR_URL, settings.RADARR_API_KEY)

    movies = client.get_all_movies()
    print(f"Total movies found: {len(movies)}")

    print("Filtering movies with codec != h265/hevc...")
    non_h265_list = client.filter_non_h265_movies(movies)

    if target_movie:
        non_h265_list = [e for e in non_h265_list if e["title"].lower() == target_movie]

    excluded = load_excluded_movies()
    print(f"Found {len(non_h265_list)} non-H265 movies")
    for entry in non_h265_list:
        if entry['resolution'] < 1080:
            continue  # Skip videos with resolution lower than 1080p
        
        if entry['title'] in excluded:
            continue  #skip movies excluded
            
        print(f"{entry['title']} | Codec: {entry['codec']} | Path: {entry['path']} | Resolution: {entry['resolution']} | Quality: {entry['quality']} | Languages: {entry['languages']} | Year: {entry['year']}")
        preset = settings.PRESET_4K if entry['resolution'] > 1080 else settings.PRESET_1080
        file_path = entry['path'].replace("/movies/", settings.LOCAL_FOLDER_MOVIES).replace("/", "\\")
        print(file_path)
        
        tmp_file = os.path.join("./tmp", os.path.basename(file_path))
        download_file_via_sftp(settings.HOSTNAME, settings.PORT, settings.USERNAME, settings.PASSWORD, file_path, tmp_file)
        
        sanitized_movie = re.sub(r'[^a-zA-Z0-9 \-]', '', entry['title'])
        new_file_name = f"{sanitized_movie} ({entry['year']}) [h265] [{entry['languages']}] {entry['quality']} {settings.RELEASE_TAG}.mkv"
        
        output_file, exclude_flag = convert_with_handbrake(tmp_file, new_file_name, preset)

        if output_file is None:
            continue

        if exclude_flag:
            print(f"Converted file is larger. Adding to exclusion list.")
            save_excluded_movies(entry['title'])
        else:
            upload_file_via_sftp(settings.HOSTNAME, settings.PORT, settings.USERNAME, settings.PASSWORD, output_file, settings.WATCH_FOLDER + new_file_name)
            client.manual_import_one(output_file)

        os.remove(output_file)

    print("✓ Radarr processing complete.")


def main() -> None:
    init_logging()

    parser = argparse.ArgumentParser(
        description="Transcode Videos From Sonarr/Radarr to H.265"
    )
    parser.add_argument(
        "app",
        choices=["all", "sonarr", "radarr"],
        default="all",
        help="Which app to run: sonarr, radarr, or all (in sequence)."
    )
    parser.add_argument(
        "scope",
        nargs="?",
        choices=["all", "new"],
        default="all",
        help="Content scope: 'all' or 'new' (incremental)."
    )
    parser.add_argument(
        "--show",
        help="Sonarr: only this exact series title (case-insensitive)."
    )
    parser.add_argument(
        "--movie",
        help="Radarr: only this exact movie title (case-insensitive)."
    )
    args = parser.parse_args()

    apps = args.app
    scope = args.scope
    target_tv = args.show.lower() if args.show else None
    target_movie = args.movie.lower() if args.movie else None

    if apps in ("all", "sonarr"):
        handle_sonarr(scope, target_tv)

    if apps in ("all", "radarr"):
        handle_radarr(scope, target_movie)

    if apps not in ("all", "sonarr", "radarr"):
        print(f"❌ Unknown app scope: {apps}")
        sys.exit(1)


if __name__ == "__main__":
    main()
