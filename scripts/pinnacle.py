# Public Pinnacle player-prop prices -> pinprops.json (two-sided over/under lines, pregame only).
# Pinnacle is the sharpest public book, so its no-vig price is the best single anchor for "true %".
# Same shape as bovprops.json so the site can merge it the same way. Public prices only, no account.
import json, re, sys, time, datetime, urllib.request

KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"  # public guest key the pinnacle.com website itself sends
LEAGUES = {"NFL": 889, "NCAAF": 880, "NBA": 487, "NHL": 1456, "MLB": 246, "WNBA": 578, "NCAAM": 493}
MKT = {  # description tail -> site prop type
    "Total Receptions": "REC", "Total Receiving Yards": "REC YDS", "Total Rushing Yards": "RUSH YDS",
    "Total Rush Attempts": "CAR", "Total Pass Completions": "CMP", "Total Pass Attempts": "ATT",
    "Total Passing Yards": "PASS YDS", "Total Interceptions": "INT", "Total Touchdown Passes": "PASS TD",
    "Total Touchdowns": "ANY TD",
    "Total Points": "PTS", "Total Rebounds": "REB", "Total Assists": "AST", "Total Threes Made": "3PM",
    "Total Pts & Rebs & Asts": "PRA", "Total Steals": "STL", "Total Blocks": "BLK",
    "Total Goals": "G", "Total Shots On Goal": "SOG", "Total Saves": "SV",
    "Total Bases": "TB", "Total Home Runs": "HR", "Total Strikeouts": "K", "Total Hits Allowed": "H ALW",
    "Total Earned Runs": "ER", "Total Pitching Outs": "OUTS", "Total Hits": "H",
}
TAILS = sorted(MKT, key=len, reverse=True)


def get(path):
    u = "https://guest.api.arcadia.pinnacle.com/0.1/" + path
    for tr in range(3):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"x-api-key": KEY, "User-Agent": "Mozilla/5.0 crosscheck/1.0", "Accept": "application/json"}), timeout=30))
        except Exception as e:
            if tr == 2:
                print(path, "failed", e); return []
            time.sleep(2 + 3 * tr)


def ms(iso):
    try: return int(datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception: return None


out = {"pulled": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "src": "pinnacle", "lg": {}}
now = time.time() * 1000
for lg, lid in LEAGUES.items():
    mus = get(f"leagues/{lid}/matchups") or []
    if not mus:
        out["lg"][lg] = []; continue
    px = {}
    for m in get(f"leagues/{lid}/markets/straight") or []:
        if m.get("period") == 0 and m.get("type") == "total" and m.get("matchupId"):
            px[m["matchupId"]] = m
    games = {}
    for m in mus:
        if m.get("special") or m.get("parentId"):
            continue
        ps = m.get("participants") or []
        h = next((p["name"] for p in ps if p.get("alignment") == "home"), None)
        a = next((p["name"] for p in ps if p.get("alignment") == "away"), None)
        if h and a:
            games[m["id"]] = {"d": f"{a} @ {h}", "t": ms(m.get("startTime", "")), "p": {}}
    for m in mus:
        sp = m.get("special") or {}
        if sp.get("category") != "Player Props" or m.get("isLive"):
            continue
        g = games.get(m.get("parentId"))
        if not g or (g["t"] and g["t"] < now):
            continue  # pregame only: started games are priced live elsewhere
        d = (sp.get("description") or "").strip()
        tail = next((t for t in TAILS if d.endswith(" " + t)), None)
        if not tail:
            continue
        name = re.sub(r"\s*\([^)]*\)\s*$", "", d[: -len(tail)].strip())
        ids = {p.get("name"): p.get("id") for p in m.get("participants") or []}
        q = px.get(m["id"])
        if not q or "Over" not in ids or "Under" not in ids:
            continue
        pr = {p.get("participantId"): p for p in q.get("prices") or []}
        ov, un = pr.get(ids["Over"]), pr.get(ids["Under"])
        if not ov or not un or ov.get("price") is None or un.get("price") is None or ov.get("points") is None:
            continue
        typ = MKT[tail]
        line = float(ov["points"])
        if typ == "ANY TD" and line != 0.5:
            continue
        g["p"].setdefault(name, {"o": {}})["o"][typ] = [line, int(ov["price"]), int(un["price"])]
    L = [g for g in games.values() if g["p"]]
    out["lg"][lg] = L
    print(lg, "games", len(games), "with props", len(L), "players", sum(len(x["p"]) for x in L))
json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "pinprops.json", "w"), separators=(",", ":"))
