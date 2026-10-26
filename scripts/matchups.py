# Player matchups from public ESPN game logs -> matchups.json
# For each NBA/NFL/NHL/MLB game not yet final: pick each team's key players from its most recent box score
# (skipping anyone listed Out/Doubtful), pair them by role, and give each player his averages vs tonight's
# opponent over the last 3 seasons next to his current-season averages, plus a game-by-game list.
# Shape: {"pulled", "m": {"LG:AWAY@HOME": {"rng", "pairs": [{"lab", "a", "h"}]}}, "meta": {...rebuild bookkeeping}}
# Player: {"n", "pos", "role", "vs": {"gp", "avg", "rec"}, "szn": {"gp", "avg"}, "g": [{"d", "r", "s", "nt"}]}
# Entries are carried over from the previous run and rebuilt once a day (again after 2 PM ET, when lineups firm up),
# or sooner if a picked player is now Out/Doubtful or the NHL goalie / MLB starter changed.
import json, re, sys, time, datetime, urllib.request
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

OUT = sys.argv[1] if len(sys.argv) > 1 else "matchups.json"
PREV = sys.argv[2] if len(sys.argv) > 2 else ""
ET = ZoneInfo("America/New_York")
PATH = {"NBA": "basketball/nba", "NFL": "football/nfl", "NHL": "hockey/nhl", "MLB": "baseball/mlb"}
BAD = ("out", "doubtful")
BUDGET = time.time() + 9 * 60  # leave the rest of the run for the save step

def get(u, tries=3):
    for tr in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "crosscheck/1.0"}), timeout=20))
        except Exception as e:
            if "404" in str(e) or tr == tries - 1: return None
            time.sleep(1 + 2 * tr)

POOL = ThreadPoolExecutor(16)
def many(urls):
    urls = list(dict.fromkeys(urls))
    return dict(zip(urls, POOL.map(get, urls)))

def site(lg, rest): return f"https://site.api.espn.com/apis/site/v2/sports/{PATH[lg]}/{rest}"
def glog(lg, aid, yr): return f"https://site.web.api.espn.com/apis/common/v3/sports/{PATH[lg]}/athletes/{aid}/gamelog?season={yr}"

# ---------- stat columns (gamelog "names" -> short label) ----------
COLS = {
    "NBA": [("PTS", "points"), ("REB", "totalRebounds"), ("AST", "assists"), ("3PT", "threePointFieldGoalsMade-threePointFieldGoalsAttempted"), ("MIN", "minutes")],
    "QB": [("CMP", "completions"), ("ATT", "passingAttempts"), ("YDS", "passingYards"), ("TD", "passingTouchdowns"), ("INT", "interceptions")],
    "RB": [("CAR", "rushingAttempts"), ("YDS", "rushingYards"), ("TD", "rushingTouchdowns")],
    "WR": [("REC", "receptions"), ("YDS", "receivingYards"), ("TD", "receivingTouchdowns"), ("TGTS", "receivingTargets")],
    "SK": [("G", "goals"), ("A", "assists"), ("PTS", "points"), ("S", "shotsTotal")],
    "G": [("GA", "goalsAgainst"), ("SA", "shotsAgainst"), ("SV", "saves"), ("SV%", None)],
    "SP": [("IP", "innings"), ("H", "hits"), ("ER", "earnedRuns"), ("K", "strikeouts"), ("BB", "walks")],
    "B": [("AB", "atBats"), ("H", "hits"), ("HR", "homeRuns"), ("RBI", "RBIs")],
}
def colset(lg, role):
    if lg == "NBA": return COLS["NBA"]
    if lg == "NFL": return COLS["QB" if role == "QB" else "RB" if role == "RB" else "WR"]
    if lg == "NHL": return COLS["G" if role == "G" else "SK"]
    return COLS["SP" if role == "SP" else "B"]

def num(v, name):
    s = str(v or "").strip()
    if name and "-" in name and "-" in s: s = s.split("-")[0]  # "3-7" made-attempted -> made
    if name == "innings":  # 5.2 = 5 2/3 innings -> outs
        try: w, _, f = s.partition("."); return int(w) * 3 + int(f or 0)
        except Exception: return None
    try: return float(s)
    except Exception: return None

def rows(j, cols):
    """gamelog json -> [{eid, date, opp, res, score, note, v:{label:value}}] (regular season + postseason)"""
    if not j or not j.get("names"): return []
    names, ev, out, seen = j["names"], j.get("events") or {}, [], set()
    for st in j.get("seasonTypes") or []:
        if "preseason" in (st.get("displayName") or "").lower(): continue
        for c in st.get("categories") or []:
            if c.get("type") != "event": continue
            for e in c.get("events") or []:
                eid = e.get("eventId"); m = ev.get(eid)
                if not m or eid in seen: continue
                seen.add(eid); raw = dict(zip(names, e.get("stats") or []))
                v = {}
                for lab, nm in cols:
                    if nm: v[lab] = num(raw.get(nm), nm)
                if any(lab == "SV%" for lab, _ in cols): v["SV%"] = None
                out.append({"eid": eid, "date": m.get("gameDate") or "", "opp": str((m.get("opponent") or {}).get("id") or ""),
                            "res": m.get("gameResult") or "", "score": m.get("score") or "", "note": m.get("eventNote") or "", "v": v})
    return out

def ip(outs): return f"{int(outs // 3)}.{int(round(outs % 3))}"
def avg(games, cols):
    a = {}
    for lab, nm in cols:
        if lab == "SV%":
            sa = sum(g["v"].get("SA") or 0 for g in games); sv = sum(g["v"].get("SV") or 0 for g in games)
            if sa: a[lab] = round(sv / sa, 3)
            continue
        xs = [g["v"][lab] for g in games if g["v"].get(lab) is not None]
        if not xs: continue
        m = sum(xs) / len(xs)
        a[lab] = float(ip(m)) if nm == "innings" else round(m, 1)
    return a

def line(g, cols):
    parts = []
    for lab, nm in cols:
        x = g["v"].get(lab)
        if lab == "SV%":
            sa, sv = g["v"].get("SA"), g["v"].get("SV")
            if sa: parts.append(f"{sv / sa:.3f}".lstrip("0") + " SV%")
            continue
        if x is None: continue
        parts.append(f"{ip(x) if nm == 'innings' else int(x) if float(x).is_integer() else x} {lab}")
    return " · ".join(parts)

def etdate(iso):
    try: return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET)
    except Exception: return None

def player(lg, p, opp_id, seasons, logs):
    cols = colset(lg, p["role"])
    allg = []
    for yr in seasons: allg += rows(logs.get(glog(lg, p["id"], yr)), cols)
    allg.sort(key=lambda g: g["date"], reverse=True)
    cur = rows(logs.get(glog(lg, p["id"], seasons[0])), cols)
    vs = [g for g in allg if g["opp"] == opp_id]
    w = sum(g["res"] == "W" for g in vs); l = sum(g["res"] == "L" for g in vs); t = sum(g["res"] == "T" for g in vs)
    out = {"n": p["n"], "pos": p.get("pos") or p["role"], "role": p["role"],
           "vs": {"gp": len(vs), "avg": avg(vs, cols), "rec": f"{w}-{l}" + (f"-{t}" if t else "")},
           "szn": {"gp": len(cur), "avg": avg(cur, cols)}, "g": []}
    for g in vs[:6]:
        d = etdate(g["date"])
        x = {"d": f"{d.month}/{d.day}/{d.strftime('%y')}" if d else "", "r": f"{g['res']} {g['score']}".strip(), "s": line(g, cols)}
        if g["note"]: x["nt"] = g["note"]
        out["g"].append(x)
    return out

# ---------- picking each team's key players ----------
def toi(s):
    try: m, _, sec = str(s).partition(":"); return int(m) * 60 + int(sec or 0)
    except Exception: return 0

def team_box(summary, tid):
    for t in ((summary or {}).get("boxscore") or {}).get("players") or []:
        if str(t["team"]["id"]) == tid: return t.get("statistics") or []
    return []

def ath(a, role, pos=None):
    x = a.get("athlete") or {}
    return {"id": str(x.get("id")), "n": x.get("displayName") or x.get("shortName") or "", "role": role,
            "pos": pos or (x.get("position") or {}).get("abbreviation") or role}

def pick(lg, stats, hurt, prob):
    """box-score stat groups for one team -> ordered [player] with role labels"""
    ok = lambda a: str((a.get("athlete") or {}).get("id")) not in hurt and not a.get("didNotPlay")
    grp = lambda f: next((s for s in stats if f(s)), None)
    if lg == "NBA":
        s = grp(lambda s: "MIN" in (s.get("labels") or []))
        if not s: return []
        mi = s["labels"].index("MIN"); A = [a for a in s.get("athletes") or [] if ok(a)]
        mins = lambda a: num((a.get("stats") or [None] * (mi + 1))[mi] if len(a.get("stats") or []) > mi else None, "") or 0
        st = [a for a in A if a.get("starter")]
        st += sorted([a for a in A if not a.get("starter")], key=mins, reverse=True)
        return [ath(a, "") for a in st[:5]]
    if lg == "NFL":
        by = {s.get("name"): [a for a in s.get("athletes") or [] if ok(a)] for s in stats}
        out = []
        qb = (by.get("passing") or [None])[0]
        if qb: out.append(ath(qb, "QB", "QB"))
        rb = next((a for a in by.get("rushing") or [] if not qb or a["athlete"]["id"] != qb["athlete"]["id"]), None)
        if rb: out.append(ath(rb, "RB", "RB"))
        for i, a in enumerate((by.get("receiving") or [])[:3]): out.append(ath(a, f"WR{i + 1}", "REC"))
        return out
    if lg == "NHL":
        out = []
        if prob: out.append(prob)
        else:
            g = grp(lambda s: s.get("name") == "goalies")
            gs = sorted([a for a in (g or {}).get("athletes") or [] if ok(a)], key=lambda a: toi(dict(zip(g["labels"], a.get("stats") or [])).get("TOI")), reverse=True)
            if gs: out.append(ath(gs[0], "G", "G"))
        for name, n, tag in (("forwards", 3, "F"), ("defenses", 1, "D")):
            s = grp(lambda s, name=name: s.get("name") == name)
            if not s: continue
            A = sorted([a for a in s.get("athletes") or [] if ok(a)], key=lambda a: toi(dict(zip(s["labels"], a.get("stats") or [])).get("TOI")), reverse=True)
            out += [ath(a, f"{tag}{i + 1}") for i, a in enumerate(A[:n])]
        return out
    # MLB
    out = [prob] if prob else []
    s = grp(lambda s: "H-AB" in (s.get("labels") or []))
    if s:
        A = {}
        for a in s.get("athletes") or []:
            o = a.get("batOrder")
            if o in (1, 2, 3, 4) and a.get("starter") and o not in A and ok(a): A[o] = a
        out += [ath(A[o], f"B{o}") for o in sorted(A)]
    return out

LAB = {"QB": "QB", "RB": "RB", "WR1": "Top target", "WR2": "2nd target", "WR3": "3rd target", "G": "Goalie", "F1": "Top F", "F2": "2nd F", "F3": "3rd F",
       "D1": "Top D", "SP": "Starter", "B1": "Leadoff", "B2": "#2 hitter", "B3": "#3 hitter", "B4": "Cleanup"}
def bucket(pos):
    p = (pos or "").upper()
    return "C" if p.startswith("C") else "G" if p.endswith("G") else "F" if p.endswith("F") else "F"

def pairs(lg, A, H):
    if lg != "NBA":
        roles = list(dict.fromkeys([p["role"] for p in A] + [p["role"] for p in H]))
        roles.sort(key=lambda r: list(LAB).index(r) if r in LAB else 99)
        fa = {p["role"]: p for p in A}; fh = {p["role"]: p for p in H}
        return [(LAB.get(r, r), fa.get(r), fh.get(r)) for r in roles]
    for p in A + H: p["role"] = bucket(p["pos"])
    out, ra, rh = [], list(A), list(H)
    for b in ("G", "F", "C"):
        xa = [p for p in ra if p["role"] == b]; xh = [p for p in rh if p["role"] == b]
        for a, h in zip(xa, xh): out.append((b, a, h)); ra.remove(a); rh.remove(h)
    for i in range(max(len(ra), len(rh))):
        a = ra[i] if i < len(ra) else None; h = rh[i] if i < len(rh) else None
        out.append(("/".join(dict.fromkeys(p["role"] for p in (a, h) if p)), a, h))
    return out

# ---------- slate ----------
now = datetime.datetime.now(ET)
prev = {}
if PREV:
    try: prev = json.load(open(PREV))
    except Exception: prev = {}
pm, pmeta = prev.get("m") or {}, prev.get("meta") or {}
M, META, built, kept = {}, {}, 0, 0

for lg in PATH:
    days = [now] + ([now + datetime.timedelta(days=d) for d in (1, 2, 3)] if lg == "NFL" else [])
    evs, yr = [], None
    for d in days:
        sb = get(site(lg, f"scoreboard?dates={d:%Y%m%d}")) or {}
        yr = yr or (sb.get("season") or ((sb.get("leagues") or [{}])[0].get("season")) or {}).get("year")
        for e in sb.get("events") or []:
            if e["id"] not in {x["id"] for x in evs}: evs.append(e)
    evs = [e for e in evs if ((e.get("status") or {}).get("type") or {}).get("state") in ("pre", "in")]
    if not evs or not yr: continue
    seasons = [yr, yr - 1, yr - 2]
    rng = "last 3 seasons" if lg in ("NBA", "NHL") else f"{yr - 2}–{yr}"
    inj = get(site(lg, "injuries")) or {}
    hurt = set()
    for t in inj.get("injuries") or []:
        for i in t.get("injuries") or []:
            if str(i.get("status") or "").lower() in BAD:
                a = i.get("athlete") or {}
                m = re.search(r"/id/(\d+)", json.dumps(a.get("links") or []))
                hurt.add(str(a.get("id") or (m and m.group(1)) or ""))
    todo = []
    for e in evs:
        c = e["competitions"][0]; T = {x["homeAway"]: x for x in c["competitors"]}
        key = f"{lg}:{T['away']['team']['abbreviation']}@{T['home']['team']['abbreviation']}"
        probs = {}
        for side in ("away", "home"):
            pr = (T[side].get("probables") or [None])[0]
            if pr and (pr.get("athlete") or {}).get("id"):
                probs[side] = ath(pr, "G" if lg == "NHL" else "SP", "G" if lg == "NHL" else "SP") if lg in ("NHL", "MLB") else None
        mt = pmeta.get(key) or {}
        bt = datetime.datetime.fromtimestamp(mt.get("at", 0), ET)
        fresh = key in pm and bt.date() == now.date() and not (now.hour >= 14 and bt.hour < 14)
        stale = any(i in hurt for i in mt.get("ids") or []) or sorted(p["id"] for p in probs.values() if p) != sorted(mt.get("pr") or [])
        if fresh and not stale: M[key], META[key] = pm[key], mt; kept += 1
        else: todo.append((key, e, T, probs))
    if not todo or time.time() > BUDGET:
        for key, *_ in todo:
            if key in pm: M[key], META[key] = pm[key], pmeta.get(key, {}); kept += 1
        continue
    # most recent box score per team
    tids = [str(T[s]["team"]["id"]) for _, _, T, _ in todo for s in ("away", "home")]
    scheds = many([site(lg, f"teams/{t}/schedule") for t in tids])
    lastev = {}
    for t in tids:
        done = [e for e in (scheds.get(site(lg, f"teams/{t}/schedule")) or {}).get("events") or []
                if (((e.get("competitions") or [{}])[0].get("status") or {}).get("type") or {}).get("completed")]
        if done: lastev[t] = max(done, key=lambda e: e.get("date") or "")["id"]
    boxes = many([site(lg, f"summary?event={v}") for v in lastev.values()])
    plan = []
    for key, e, T, probs in todo:
        side = {}
        for s in ("away", "home"):
            tid = str(T[s]["team"]["id"]); stats = team_box(boxes.get(site(lg, f"summary?event={lastev.get(tid)}")), tid)
            side[s] = pick(lg, stats, hurt, probs.get(s))
        plan.append((key, T, probs, side))
    logs = many([glog(lg, p["id"], y) for _, _, _, side in plan for s in side.values() for p in s for y in seasons])
    for key, T, probs, side in plan:
        prs = pairs(lg, side["away"], side["home"])
        aid, hid = str(T["away"]["team"]["id"]), str(T["home"]["team"]["id"])
        out = [{"lab": lab, "a": player(lg, a, hid, seasons, logs) if a else None, "h": player(lg, h, aid, seasons, logs) if h else None} for lab, a, h in prs]
        if not out and key in pm: M[key], META[key] = pm[key], pmeta.get(key, {}); kept += 1; continue
        if not out: continue
        M[key] = {"rng": rng, "pairs": out}
        META[key] = {"at": int(time.time()), "ids": [p["id"] for s in side.values() for p in s], "pr": sorted(p["id"] for p in probs.values() if p)}
        built += 1
    print(lg, "games", len(evs), "built", len([1 for k, *_ in plan if k in META and META[k].get("at", 0) >= time.time() - 900]))

json.dump({"pulled": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "m": M, "meta": META}, open(OUT, "w"), separators=(",", ":"), ensure_ascii=False)
print("matchups", len(M), "games: built", built, "kept", kept)
