#!/usr/bin/env python3
"""
Baja Boyz WC 2026 — automated score sync.

Fetches each team's FIFA World Cup schedule from ESPN, computes group-stage
points (3 win / 1 draw) and the furthest round reached, then PATCHes the
results into Firebase at drafts/BAJAWC26/scores. Mirrors the in-app
"Sync from ESPN" button so it runs even when nobody has the app open.

No secrets required: the Realtime DB allows writes to drafts/BAJAWC26.
"""
import json
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

FIREBASE = "https://baja-boyz-wc-2026-challenge-default-rtdb.firebaseio.com"
SCORES_URL = f"{FIREBASE}/drafts/BAJAWC26/scores.json"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/teams/{}/schedule"

# app team id -> ESPN fifa.world team id
TEAMS = {
    "MEX": 203, "RSA": 467, "KOR": 451, "CZE": 450, "CAN": 206, "BIH": 452,
    "QAT": 4398, "SUI": 475, "BRA": 205, "MAR": 2869, "HAI": 2654, "SCO": 580,
    "USA": 660, "PAR": 210, "AUS": 628, "TUR": 465, "GER": 481, "CUW": 11678,
    "CIV": 4789, "ECU": 209, "NED": 449, "JPN": 627, "SWE": 466, "TUN": 659,
    "BEL": 459, "EGY": 2620, "IRN": 469, "NZL": 2666, "ESP": 164, "CPV": 2597,
    "KSA": 655, "URU": 212, "FRA": 478, "SEN": 654, "IRQ": 4375, "NOR": 464,
    "ARG": 202, "ALG": 624, "AUT": 474, "JOR": 2917, "POR": 482, "COD": 2850,
    "UZB": 2570, "COL": 208, "ENG": 448, "CRO": 477, "GHA": 4469, "PAN": 2659,
}

ROUND_NAME_TO_ROUND = {
    "group stage": "Eliminated (Group Stage)",
    "round of 32": "Round of 32",
    "round of 16": "Round of 16",
    "quarterfinals": "Quarterfinal", "quarterfinal": "Quarterfinal",
    "semifinals": "Semifinal", "semifinal": "Semifinal",
    "third place": "3rd Place", "third-place": "3rd Place", "3rd place": "3rd Place",
    "3rd-place match": "3rd Place", "3rd place match": "3rd Place",
    "final": "Runner-up",  # upgraded to Champion if they won
}
ROUND_ORDER = {
    "Eliminated (Group Stage)": 0, "Round of 32": 1, "Round of 16": 2,
    "Quarterfinal": 3, "Semifinal": 4, "3rd Place": 5, "Runner-up": 6, "Champion": 7,
}
# Knockout matches tag the round on season.slug (seasonType is null there).
SLUG_TO_ROUND = {
    "round-of-32": "Round of 32", "round-of-16": "Round of 16",
    "quarterfinals": "Quarterfinal", "semifinals": "Semifinal",
    "third-place": "3rd Place", "3rd-place-match": "3rd Place",
    "final": "Runner-up",
}


def round_of(event):
    # Try season.slug (knockouts) first, then seasonType.name (group stage).
    slug = (event.get("season") or {}).get("slug")
    if slug in SLUG_TO_ROUND:
        return SLUG_TO_ROUND[slug]
    name = ((event.get("seasonType") or {}).get("name", "") or "").lower()
    return ROUND_NAME_TO_ROUND.get(name)


def fetch(item):
    tid, eid = item
    try:
        with urllib.request.urlopen(ESPN.format(eid), timeout=25) as r:
            data = json.load(r)
        return tid, eid, data.get("events", [])
    except Exception as e:
        print(f"  ! fetch failed {tid} ({eid}): {e}", file=sys.stderr)
        return tid, eid, None


def score_val(c):
    s = c.get("score") or {}
    if isinstance(s, dict):
        return int(float(s.get("value", s.get("displayValue", 0)) or 0))
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def compute(tid, eid, events):
    eid = str(eid)
    completed = [
        e for e in events
        if (e.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("completed")
            or e.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("state") == "post")
    ]
    if not completed:
        return None

    group_points = 0
    for e in completed:
        if round_of(e) != "Eliminated (Group Stage)":
            continue
        comps = e.get("competitions", [{}])[0].get("competitors", [])
        us = next((c for c in comps if str(c.get("team", {}).get("id")) == eid), None)
        them = next((c for c in comps if str(c.get("team", {}).get("id")) != eid), None)
        if not us:
            continue
        ours, theirs = score_val(us), score_val(them) if them else 0
        if ours > theirs:
            group_points += 3
        elif ours == theirs:
            group_points += 1

    round_reached = "Eliminated (Group Stage)"
    deepest = None
    for e in completed:
        r = round_of(e)
        if not r or r == "Eliminated (Group Stage)":
            continue
        if r == "3rd Place":
            # Bronze playoff counts only for the winner; the loser finishes 4th
            # and stays at the Semifinal tier.
            comps = e.get("competitions", [{}])[0].get("competitors", [])
            us = next((c for c in comps if str(c.get("team", {}).get("id")) == eid), None)
            if not (us and (us.get("winner") or (us.get("score") or {}).get("winner"))):
                continue
        if deepest is None or ROUND_ORDER[r] > ROUND_ORDER[deepest]:
            deepest = r
    if deepest:
        round_reached = deepest
        final = next((e for e in completed if round_of(e) == "Runner-up"), None)
        if final:
            comps = final.get("competitions", [{}])[0].get("competitors", [])
            us = next((c for c in comps if str(c.get("team", {}).get("id")) == eid), None)
            if us and (us.get("winner") or (us.get("score") or {}).get("winner")):
                round_reached = "Champion"

    return {"groupPoints": group_points, "roundReached": round_reached}


def main():
    with ThreadPoolExecutor(max_workers=12) as ex:
        fetched = list(ex.map(fetch, TEAMS.items()))

    new_scores = {}
    for tid, eid, events in fetched:
        if events is None:
            continue
        result = compute(tid, eid, events)
        if result is not None:
            new_scores[tid] = result

    if not new_scores:
        print("No completed matches found — nothing to sync.")
        return

    body = json.dumps(new_scores).encode()
    req = urllib.request.Request(
        SCORES_URL, data=body, method="PATCH",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        print(f"Firebase write failed: HTTP {e.code} {e.read().decode()}", file=sys.stderr)
        sys.exit(1)

    print(f"Synced {len(new_scores)} team(s) to Firebase (HTTP {status}):")
    for tid, s in sorted(new_scores.items()):
        print(f"  {tid}: {s['groupPoints']} pts · {s['roundReached']}")


if __name__ == "__main__":
    main()
