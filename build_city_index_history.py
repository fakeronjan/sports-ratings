"""
build_city_index_history.py

Build the City Index history JSON for the portal. For each year from
1997 to current, emit snapshot entries at:
  - Each sport's championship date for that calendar year (NBA Finals,
    NFL Super Bowl, MLB World Series, WNBA Finals, NHL Stanley Cup, MLS Cup)
  - December 31 calendar year-end

For each snapshot date, each sport's "current state" is its latest
rating snapshot on or before that date. Teams are emitted with pre-
computed z-scores so the portal can aggregate by metro without
re-running the math per page load.

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

SPORT_FINALE_NAMES = {
    'NBA':  'NBA Finals',
    'NFL':  'NFL Super Bowl',
    'MLB':  'MLB World Series',
    'WNBA': 'WNBA Finals',
    'NHL':  'NHL Stanley Cup',
    'MLS':  'MLS Cup',
}

FROM_YEAR = 1997
TO_YEAR   = 2026  # include current in-progress year


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
                d_obj = date.fromisoformat(ds[:10])
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


def collect_sport_finale_dates(sport_path):
    """For each season file, the max snapshot date. That's that sport's
    end-of-season date (championship/finals/cup)."""
    finales = []
    seasons_dir = os.path.join(sport_path, 'docs', 'data', 'seasons')
    if not os.path.isdir(seasons_dir):
        return []
    for fname in os.listdir(seasons_dir):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(seasons_dir, fname)) as f:
                d = json.load(f)
        except Exception:
            continue
        max_date = None
        for snap in d.get('snapshots', []):
            ds = snap.get('date')
            if not ds:
                continue
            try:
                d_obj = date.fromisoformat(ds[:10])
            except Exception:
                continue
            if max_date is None or d_obj > max_date:
                max_date = d_obj
        if max_date:
            finales.append(max_date)
    return sorted(set(finales))


print("Loading all snapshots per sport...")
all_snaps = {}
finale_dates_by_sport = {}
for sport, repo in REPOS.items():
    all_snaps[sport] = collect_snapshots(repo)
    finale_dates_by_sport[sport] = collect_sport_finale_dates(repo)
    print(f"  {sport}: {len(all_snaps[sport])} snapshots, "
          f"{len(finale_dates_by_sport[sport])} season ends")

# Build the list of key dates (sport finales + year-ends), sorted.
key_dates = []  # list of (date, label, year, kind)
for sport, finales in finale_dates_by_sport.items():
    for fd in finales:
        if fd.year < FROM_YEAR or fd.year > TO_YEAR:
            continue
        key_dates.append((fd, f"{fd.year} {SPORT_FINALE_NAMES[sport]}", fd.year, sport))
for year in range(FROM_YEAR, TO_YEAR + 1):
    # Cap at today's date so we don't emit a 2026-12-31 snapshot from June.
    target = date(year, 12, 31)
    if target > date.today():
        continue
    key_dates.append((target, f"{year} Year-End", year, 'year-end'))
key_dates.sort(key=lambda x: x[0])

print(f"\nKey dates: {len(key_dates)}")

# For each key date, compute snapshot.
result_snapshots = []
for kd, label, year, kind in key_dates:
    entry = {
        'date':            str(kd),
        'label':           label,
        'year':            year,
        'kind':            kind,
        'snapshots_used':  {},
        'teams':           [],
    }
    sport_payloads = []
    for sport, snaps in all_snaps.items():
        found = snapshot_at(snaps, kd)
        if not found:
            continue
        d_obj, snap = found
        entry['snapshots_used'][sport] = str(d_obj)
        teams = [t for t in snap.get('teams', []) if t.get('rating') is not None]
        sport_payloads.append({'label': sport, 'teams': teams})

    # Per-sport z-score.
    for s in sport_payloads:
        ratings = [t['rating'] for t in s['teams']]
        if len(ratings) < 2:
            continue
        mean = sum(ratings) / len(ratings)
        std  = (sum((r - mean) ** 2 for r in ratings) / len(ratings)) ** 0.5
        if std == 0:
            continue
        for t in s['teams']:
            t['_z'] = (t['rating'] - mean) / std

    # Flatten.
    for s in sport_payloads:
        for t in s['teams']:
            if '_z' not in t:
                continue
            name = t.get('display_name') or t.get('team') or t.get('name')
            if not name:
                continue
            entry['teams'].append({
                'sport':  s['label'],
                'team':   name,
                'rating': round(float(t['rating']), 3),
                'zScore': round(float(t['_z']), 4),
            })

    if entry['teams']:
        result_snapshots.append(entry)

out_path = 'docs/data/city_index_history.json'
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, 'w') as f:
    json.dump({'snapshots': result_snapshots}, f, separators=(',', ':'))
print(f"\nWrote {out_path}: {os.path.getsize(out_path):,} bytes, "
      f"{len(result_snapshots)} snapshots")
