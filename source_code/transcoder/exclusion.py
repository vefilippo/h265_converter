import os
from transcoder.config import settings
import csv

def load_excluded_episodes():
    """Load episodes that should be excluded from future runs."""
    excluded = set()
    if os.path.exists(settings.EPISODE_EXCLUSION_CSV):
        with open(settings.EPISODE_EXCLUSION_CSV, mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            for row in reader:
                excluded.add(tuple(row))
    return excluded

def save_excluded_episodes(series, season, episode):
    """Save an episode to the exclusion list."""
    with open(settings.EPISODE_EXCLUSION_CSV, mode='a', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([series, season, episode])

def load_excluded_movies():
    excluded = set()
    if os.path.exists(settings.MOVIE_EXCLUSION_CSV):
        with open(settings.MOVIE_EXCLUSION_CSV, mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            for row in reader:
                excluded.add(row[0])  # Just title
    return excluded

def save_excluded_movies(title):
    with open(settings.MOVIE_EXCLUSION_CSV, mode='a', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([title])