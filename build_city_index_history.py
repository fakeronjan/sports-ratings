"""
build_city_index_history.py

For each Dec 31 from 1997 to 2025, find the rating snapshot closest to
(but on or before) Dec 31 in each sport (NBA, WNBA, NFL, MLB, NHL, MLS).
Emit team-level rating + per-sport z-score for each year. Metro
aggregation and Stouffer combined-z is done in the portal so the
TEAM_TO_METRO mapping stays a single source of truth.

Output: docs/data/city_index_history.json
"""
import json
import os
from datetime import date

REPOS = {
    'NBA':  '../NBA',
    'WNBA': '../WNBA',
    'NFL':  '../NFL',
    'MLB':  '../MLB',
    'NHL':  '../NHL',
    'MLS':  '../soccer us-mex',
}

FROM_YEAR = 1997
TO_YEAR   = 2025  # 2026 is in-progress; portal already shows live current


def collect_snapshots(sport_path):
    """All snapshots across all seasons for a sport, with date parsed.
    Returns sorted list of (date, snap_dict)."""
    out = []
    seasons_dir = os.path.join(sport_path, 'docs', 'data', 'seasons')
    if not os.path.isdir(seasons_dir):
        return out
    for fname in os.listdir(seasons_dir):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(seasons_dir, fname)) as f:
                d = json.load(f)
        except Exception:
            continue
        for snap in d.get('snapshots', []):
            ds = snap.get('date')
            if not ds:
                continue
            try:
                yyyy, mm, dd = ds[:10].split('-')
                d_obj = date(int(yyyy), int(mm), int(dd))
            except Exception:
                continue
            out.append((d_obj, snap))
    out.sort(key=lambda x: x[0])
    return out


def snapshot_at(snaps, target):
    """Latest snapshot on or before target. Returns (date, snap) or None."""
    found = None
    for d_obj, snap in snaps:
        if d_obj <= target:
            found = (d_obj, snap)
        else:
            break
    return found


print("Loading all snapshots per sport...")
all_snaps = {}
for sport, repo in REPOS.items():
    snaps = collect_snapshots(repo)
    all_snaps[sport] = snaps
    print(f"  {sport}: {len(snaps)} snapshots")


history = {}
for year in range(FROM_YEAR, TO_YEAR + 1):
    target = date(year, 12, 31)
    year_entry = {'snapshots_used': {}, 'teams': []}
    sport_payloads = []
    for sport, snaps in all_snaps.items():
        found = snapshot_at(snaps, target)
        if not found:
            continue
        d_obj, snap = found
        year_entry['snapshots_used'][sport] = str(d_obj)
        # Filter to teams that have a rating
        teams = [t for t in snap.get('teams', []) if t.get('rating') is not None]
        sport_payloads.append({'label': sport, 'teams': teams})

    # Per-sport z-score
    for s in sport_payloads:
        ratings = [t['rating'] for t in s['teams']]
        if len(ratings) < 2:
            continue
        mean = sum(ratings) / len(ratings)
        var  = sum((r - mean) ** 2 for r in ratings) / len(ratings)
        std  = var ** 0.5
        if std == 0:
            continue
        for t in s['teams']:
            t['zScore'] = (t['rating'] - mean) / std

    # Flatten to team-level entries
    for s in sport_payloads:
        for t in s['teams']:
            if 'zScore' not in t:
                continue
            name = t.get('display_name') or t.get('team') or t.get('name')
            if not name:
                continue
            year_entry['teams'].append({
                'sport':  s['label'],
                'team':   name,
                'rating': round(float(t['rating']), 3),
                'zScore': round(float(t['zScore']), 4),
            })

    history[str(year)] = year_entry
    used = year_entry['snapshots_used']
    print(f"  {year}: {len(year_entry['teams']):3d} teams across {len(used)} sports ({', '.join(f'{k}:{v}' for k, v in used.items())})")


out_path = 'docs/data/city_index_history.json'
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, 'w') as f:
    json.dump(history, f, separators=(',', ':'))
print(f"\nWrote {out_path}: {os.path.getsize(out_path):,} bytes")
