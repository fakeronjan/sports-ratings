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

# NHL data starts at 1980 (earliest season ending in calendar year 1980),
# which is the floor for all 4 US major leagues having coverage. NBA, NFL,
# and MLB go further back but we cap at NHL for an "all 4 majors" view.
# WNBA (1997) and MLS (1996) just won't contribute to pre-1996/97 entries.
FROM_YEAR = 1980
TO_YEAR   = 2026  # include current in-progress year


def collect_season_end_snapshots(sport_path):
    """For each COMPLETED season file, return (end_date, end_snapshot) where
    end_snapshot is the final snapshot of that season (the championship
    moment). Skips in-progress seasons (no 'End of playoffs' marker).

    This is what we want for cross-sport rating windows: at any key date we
    use each sport's LAST COMPLETED season-end rating, NOT a mid-season
    snapshot. Mid-season ratings are still fluctuating from in-progress
    games and would pollute the 'cross-sport snapshot at the championship
    moment' semantics."""
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
        snaps = d.get('snapshots', [])
        if not snaps:
            continue
        last = snaps[-1]
        if 'End of playoffs' not in (last.get('label') or ''):
            continue  # in-progress season
        ds = last.get('date')
        if not ds:
            continue
        try:
            d_obj = date.fromisoformat(ds[:10])
        except Exception:
            continue
        out.append((d_obj, last))
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


print("Loading season-end snapshots per sport...")
season_end_snaps = {}  # sport -> [(end_date, end_snapshot), ...] sorted by date
for sport, repo in REPOS.items():
    season_end_snaps[sport] = collect_season_end_snapshots(repo)
    print(f"  {sport}: {len(season_end_snaps[sport])} completed seasons")

# Derived: the per-sport finale-date list (used for building key_dates).
finale_dates_by_sport = {
    sport: [d for d, _ in snaps]
    for sport, snaps in season_end_snaps.items()
}

# Rolling view captured AT THE END OF EACH SPORT'S SEASON.
# Year-End snapshots dropped per user direction 2026-06-06: each sport's
# championship moment is the natural "rating window", and the Year-End was
# a synthetic moment that didn't correspond to any actual sports event.
# Current live snapshot is also dropped from this view - the Current
# Summary tab already shows live ratings via the sport cards.
#
# NBA Finals + NHL Stanley Cup combine into a single "NBA + NHL Finals"
# snapshot at the LATER of the two end dates. They happen within days of
# each other every June; collapsing them keeps the picker tidy and the
# City History chart from showing two redundant adjacent points. By the
# later date, both sports' final ratings are baked in.

# Season-year for labeling. NFL's Super Bowl always plays in Jan / Feb of
# the year AFTER the season starts (1996 season -> SB XXXI on 2024-01-26),
# so for NFL the season year is `date.year - 1`. Every other sport's
# finale happens in the same calendar year as its season.
def season_year_for(sport, dt):
    if sport == 'NFL':
        return dt.year - 1
    return dt.year

# Group finales by SEASON year (not calendar year of the finale date) so
# the NBA+NHL combine pairs the right years and the picker labels read
# correctly. Green Bay 1996 SB win is labeled "1996 NFL Super Bowl"
# (date 1997-01-26) - it WAS the end of the 1996 season.
finales_by_year = {}  # season_year -> {sport: date}
for sport, finales in finale_dates_by_sport.items():
    for fd in finales:
        season_yr = season_year_for(sport, fd)
        if season_yr < FROM_YEAR or season_yr > TO_YEAR:
            continue
        finales_by_year.setdefault(season_yr, {})[sport] = fd

key_dates = []  # list of (date, label, year, kind)
for year in sorted(finales_by_year):
    sports_dates = finales_by_year[year]
    nba_dt = sports_dates.get('NBA')
    nhl_dt = sports_dates.get('NHL')
    if nba_dt and nhl_dt:
        later = max(nba_dt, nhl_dt)
        key_dates.append((later, f"{year} NBA + NHL Finals", year, 'nba+nhl'))
    elif nba_dt:
        key_dates.append((nba_dt, f"{year} NBA Finals", year, 'NBA'))
    elif nhl_dt:
        key_dates.append((nhl_dt, f"{year} NHL Stanley Cup", year, 'NHL'))
    for sport in ('NFL', 'MLB', 'WNBA', 'MLS'):
        if sport in sports_dates:
            fd = sports_dates[sport]
            key_dates.append((fd, f"{year} {SPORT_FINALE_NAMES[sport]}", year, sport))
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
    # Each sport contributes its LAST COMPLETED SEASON-END snapshot as of
    # the key date - NOT a mid-season snapshot. This keeps the cross-sport
    # view clean of in-season progress: at the 2026 NFL Super Bowl moment,
    # NBA shows the 2024-25 season-end (last completed) rather than a
    # mid-2025-26 snapshot. User direction 2026-06-06.
    sport_payloads = []
    for sport, snaps in season_end_snaps.items():
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

    # Flatten. Champion / runner-up status (2 = champion, 1 = runner-up) is
    # preserved so the City History view can mark championship moments with
    # a 👑 / 🥈 emoji on the chart and in the table.
    #
    # Each fleet site uses a slightly different field name for this:
    #   NBA / WNBA / MLB / NHL: finals_status (2 = champ, 1 = RU)
    #   NFL (DILLON):            sb_status    (2 = champ, 1 = RU)
    #   MLS (COBI):              mls_cup_finish (string 'Champion' / 'Runner-Up')
    # Coalesce them into a single finalsStatus int.
    def champ_status(team):
        v = team.get('finals_status')
        if v is None:
            v = team.get('sb_status')
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
        mls = team.get('mls_cup_finish')
        if isinstance(mls, str):
            s = mls.strip().lower()
            if s == 'champion':
                return 2
            if 'runner' in s:
                return 1
        return 0

    for s in sport_payloads:
        for t in s['teams']:
            if '_z' not in t:
                continue
            name = t.get('display_name') or t.get('team') or t.get('name')
            if not name:
                continue
            entry['teams'].append({
                'sport':        s['label'],
                'team':         name,
                'rating':       round(float(t['rating']), 3),
                'zScore':       round(float(t['_z']), 4),
                'finalsStatus': champ_status(t),
            })

    if entry['teams']:
        result_snapshots.append(entry)

out_path = 'docs/data/city_index_history.json'
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, 'w') as f:
    json.dump({'snapshots': result_snapshots}, f, separators=(',', ':'))
print(f"\nWrote {out_path}: {os.path.getsize(out_path):,} bytes, "
      f"{len(result_snapshots)} snapshots")
