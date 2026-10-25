# Public Bovada player-prop prices -> bovprops.json (two-sided O/U lines + yes-only "N+" ladders).
# Bovada's API has no CORS header, so the site can't read it directly; this runs in the Action.
import json, re, sys, time, datetime, urllib.request
SPORTS = {"NFL": "football/nfl", "NBA": "basketball/nba", "NHL": "hockey/nhl", "MLB": "baseball/mlb",
          "NCAAF": "football/college-football", "WNBA": "basketball/wnba", "NCAAM": "basketball/college-basketball"}
OU = {  # two-sided "Total X - Player (TM)" markets
 "Total Receptions": "REC", "Total Receiving Yards": "REC YDS", "Total Rushing Yards": "RUSH YDS", "Total Rush Attempts": "CAR",
 "Total Rushing & Receiving Yards": "RUSH+REC", "Total Passing Touchdowns": "PASS TD", "Total Passing Attempts": "ATT",
 "Total Completions": "CMP", "Total Interceptions Thrown": "INT", "Total Passing Yards": "PASS YDS", "Total Passing & Rushing Yards O/U": "PASS+RUSH",
 "Total Points": "PTS", "Total Rebounds": "REB", "Total Assists": "AST", "Total Made 3 Points Shots": "3PM",
 "Total Points, Rebounds and Assists": "PRA", "Total Points and Rebounds": "P+R", "Total Points and Assists": "P+A", "Total Rebounds and Assists": "R+A",
 "Total Steals": "STL", "Total Blocks": "BLK",
 "Total Shots On Goal": "SOG", "Total Saves": "SV",
 "Total Hits": "H", "Total Bases": "TB", "Total Strikeouts": "K", "Total Runs Batted In": "RBI", "Total Hits, Runs and RBIs": "H+R+RBI",
}
LAD = {  # yes-only ladders: outcome text carries "N+"
 "Alternate Receiving Yards": "REC YDS", "Alternate Receptions": "REC", "Alternate Rushing Yards": "RUSH YDS", "Alternate Rush Attempts": "CAR",
 "Alternate Rushing & Receiving Yards": "RUSH+REC", "Alternate Passing Completions": "CMP", "Alternate Passing Yards": "PASS YDS",
 "Alternate Passing Touchdowns": "PASS TD", "Points Milestones": "PTS", "Rebounds Milestones": "REB", "Assists Milestones": "AST",
 "Total Made Threes Milestones": "3PM", "Shots on Goal Milestones": "SOG", "Blocks Milestones": "BLK", "Steals Milestones": "STL",
}
YES1 = {"Anytime Touchdown Scorer": "ANY TD", "Anytime Goalscorer": "G"}  # one outcome per player, 1+
PART = re.compile(r"\b(1H|2H|1Q|2Q|3Q|4Q|1P|2P|3P|REG)\b|1st|2nd|3rd|half|quarter|period", re.I)
def am(p):
    a = (p or {}).get("american")
    if a in (None, ""): return None
    if str(a).upper() == "EVEN": return 100
    try: return int(str(a).replace("+", ""))
    except Exception: return None
def get(path):
    u = f"https://www.bovada.lv/services/sports/event/v2/events/A/description/{path}?preMatchOnly=true&lang=en"
    for tr in range(3):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 crosscheck/1.0", "Accept": "application/json"}), timeout=30))
        except Exception as e:
            if tr == 2: print(path, "failed", e); return []
            time.sleep(2 + 3 * tr)
def who(s):
    m = re.match(r"^(.*?)\s*(?:\(([A-Z]{2,4})\))?\s*$", s.strip()); return (m.group(1).strip(), m.group(2)) if m else (s.strip(), None)
out = {"pulled": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "lg": {}}
for lg, path in SPORTS.items():
    evs = [e for blk in (get(path) or []) for e in blk.get("events", [])]
    L = []
    for e in evs:
        P = {}
        def pl(name, tm):
            x = P.setdefault(name, {"o": {}, "y": {}})
            if tm and not x.get("tm"): x["tm"] = tm
            return x
        for g in e.get("displayGroups", []):
            for m in g.get("markets", []):
                d = m.get("description", ""); per = (m.get("period") or {}).get("description", "Game")
                if per not in ("Game", "Match", "Regulation Time") and not (per == "Regulation Time" and lg == "NHL"): continue
                base, _, rest = d.partition(" - ")
                oc = m.get("outcomes", [])
                if base in OU and rest:
                    name, tm = who(rest); ov = next((o for o in oc if o.get("description") == "Over"), None); un = next((o for o in oc if o.get("description") == "Under"), None)
                    if not ov or not un: continue
                    try: line = float(ov["price"].get("handicap"))
                    except Exception: continue
                    a, b = am(ov.get("price")), am(un.get("price"))
                    if a is None or b is None: continue
                    pl(name, tm)["o"][OU[base]] = [line, a, b]
                elif base in LAD and rest:
                    name, tm = who(rest); rung = []
                    for o in oc:
                        t = o.get("description", ""); k = re.search(r"(\d+(?:\.\d+)?)\+", t)
                        if not k or PART.search(t): continue
                        a = am(o.get("price"))
                        if a is not None: rung.append([float(k.group(1)), a])
                    if rung: pl(name, tm)["y"][LAD[base]] = sorted(rung)
                elif base in YES1 and not rest:
                    for o in oc:
                        t = o.get("description", "")
                        if PART.search(t) or re.search(r"Def/ST|No (Touchdown|Goal)", t): continue
                        name, tm = who(t); a = am(o.get("price"))
                        if a is not None: pl(name, tm)["y"][YES1[base]] = [[1.0, a]]
        ed = e.get("description", "").lower()
        P = {k: v for k, v in P.items() if (v["o"] or v["y"]) and not (not v.get("tm") and k.lower() in ed)}
        for v in P.values():
            if not v["o"]: v.pop("o")
            if not v["y"]: v.pop("y")
        if P: L.append({"d": e.get("description", ""), "t": e.get("startTime"), "p": P})
    out["lg"][lg] = L
    print(lg, "events", len(evs), "with props", len(L), "players", sum(len(x["p"]) for x in L))
json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "bovprops.json", "w"), separators=(",", ":"))
