"""Cross-sport calibration of the fleet's championship-% calculators.

For each site (DUNCAN/LOBO/DILLON/GRIFFEY), reads the SHIPPED per-snapshot title
odds stored in <site>/docs/data/seasons/*.json, pairs every (team, snapshot)
odds with whether that team actually won the title that season, and bins by
predicted probability:  "when the model said ~40%, did they win ~40%?"

Reports a reliability table (decile bucket -> actual champion rate), Brier score,
and expected calibration error (ECE), per site and pooled.

NOTE: these are the SHIPPED odds, which are IN-SAMPLE (model fit on all seasons
incl. the one being scored) -> optimistic vs true out-of-sample. DUNCAN has an
out-of-sample LOO benchmark in duncan/title_odds_eval_v3.py to compare against.

Usage: python3 sports-ratings/title_odds_calibration.py   (run from sports/ root)
"""
import json, glob, os, sys

SITES = [("DUNCAN", "duncan", "NBA"), ("LOBO", "lobo", "WNBA"),
         ("DILLON", "dillon", "NFL"), ("GRIFFEY", "griffey", "MLB")]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # sports/


def odds_field(team):
    for k in ("title_odds", "sb_odds"):
        if k in team:
            return k
    return None


def collect(site_dir):
    """Return list of (predicted_odds, is_champion) over all completed seasons,
    plus (n_seasons, champ_found, season_lo, season_hi)."""
    rows = []
    seasons = []
    for f in sorted(glob.glob(os.path.join(ROOT, site_dir, "docs/data/seasons/*.json"))):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        snaps = d.get("snapshots") or []
        if not snaps:
            continue
        of = odds_field(snaps[0]["teams"][0]) if snaps[0].get("teams") else None
        if not of:
            continue
        # champion = team at odds==1.0 in the LAST snapshot; skip incomplete seasons
        last = snaps[-1]["teams"]
        champ = next((t["team"] for t in last if (t.get(of) or 0) >= 0.999), None)
        if champ is None:
            continue  # season not complete (no clinched champ in data)
        seasons.append(int(d["season"]))
        for snap in snaps:
            for t in snap["teams"]:
                p = t.get(of)
                if p is None:
                    continue
                rows.append((float(p), 1 if t["team"] == champ else 0))
    return rows, (len(seasons), min(seasons) if seasons else None, max(seasons) if seasons else None)


def reliability(rows, interior_only=False):
    if interior_only:
        rows = [(p, y) for (p, y) in rows if 0.0 < p < 1.0]
    bins = [(i/10, (i+1)/10) for i in range(10)]
    table = []
    N = len(rows)
    brier = sum((p - y)**2 for p, y in rows) / N if N else 0.0
    ece = 0.0
    for lo, hi in bins:
        if hi == 1.0:
            b = [(p, y) for p, y in rows if lo <= p <= hi]
        else:
            b = [(p, y) for p, y in rows if lo <= p < hi]
        n = len(b)
        if n == 0:
            table.append((lo, hi, None, None, 0)); continue
        actual = sum(y for _, y in b) / n
        meanp = sum(p for p, _ in b) / n
        ece += (n / N) * abs(actual - meanp)
        table.append((lo, hi, meanp, actual, n))
    return table, brier, ece, N


def print_table(label, rows):
    table, brier, ece, N = reliability(rows, interior_only=True)
    print(f"\n  {label}   (interior 0<p<1 only; n={N:,})   Brier={brier:.4f}  ECE={ece:.4f}")
    print(f"    {'bucket':>11}{'pred':>8}{'actual':>8}{'n':>7}   reliability")
    for lo, hi, meanp, actual, n in table:
        if n == 0:
            print(f"    [{lo:.1f},{hi:.1f}){'':>4}{'-':>8}{'-':>8}{0:>7}")
            continue
        bar = "#" * int(round(actual * 30))
        flag = "" if abs(actual - meanp) <= 0.06 else ("  HIGH" if actual < meanp else "  LOW")
        print(f"    [{lo:.1f},{hi:.1f}){'':>4}{meanp:>8.2f}{actual:>8.2f}{n:>7}   {bar}{flag}")


def main():
    pooled = []
    print("="*72)
    print("  FLEET CHAMPIONSHIP-% CALIBRATION  (shipped odds, in-sample)")
    print("="*72)
    for name, sdir, sport in SITES:
        rows, (nseas, lo, hi) = collect(sdir)
        if not rows:
            print(f"\n{name} ({sport}): no data"); continue
        pooled += rows
        print(f"\n{'─'*72}\n{name} ({sport})  -  {nseas} completed seasons {lo}-{hi}")
        print_table(f"{name}", rows)
    print(f"\n{'='*72}\nPOOLED (all four sports)")
    print_table("POOLED", pooled)
    print("\nReading: 'pred' = avg model odds in the bucket, 'actual' = share that won.")
    print("Well-calibrated => pred ~ actual on every row. Flags mark gaps >6pts.")
    print("Caveat: SHIPPED odds are in-sample; compare DUNCAN vs its LOO eval (v3) for the OOS gap.")


if __name__ == "__main__":
    main()
