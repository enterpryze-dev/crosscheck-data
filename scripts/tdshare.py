"""NFL touchdown-share model inputs from public nflverse play-by-play.

For every player: how much of his team's scoring chances he gets, weighted by
where on the field they happen (a carry at the 2 is worth far more than one at
the 40). Output is keyed by ESPN athlete id so the site can match players
exactly. Nothing personal or secret - public football stats only.

Writes tdshare.json:
  pulled, season, weeks, tdPerPt (offensive TDs per point scored, league-wide),
  p: {espn_id: {n name, t team, g games, s share, xs opportunity share,
                td weighted TDs, rz [red-zone carries, red-zone targets],
                i10 [inside-10 carries, inside-10 targets]}}
"""
import csv, gzip, io, json, sys, time, urllib.request
from collections import defaultdict

_t = time.gmtime()
SEASON = int(sys.argv[1]) if len(sys.argv) > 1 else (_t.tm_year - 1 if _t.tm_mon <= 2 else _t.tm_year)  # Jan-Feb games belong to last year's season
BASE = "https://github.com/nflverse/nflverse-data/releases/download"
UA = {"User-Agent": "crosscheck-data/1.0"}
DECAY = 0.85      # each older game counts 15% less than the one after it
PRIOR = 8.0       # pseudo team-TDs pulling a player's real TD share toward his opportunity share


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()


def bucket(yl):
    if yl <= 2: return 0
    if yl <= 5: return 1
    if yl <= 10: return 2
    if yl <= 20: return 3
    return 4


def main():
    pbp = csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(get(f"{BASE}/pbp/play_by_play_{SEASON}.csv.gz"))), "utf-8"))
    roster = {}
    for r in csv.DictReader(io.StringIO(get(f"{BASE}/rosters/roster_{SEASON}.csv").decode())):
        if r.get("gsis_id") and r.get("espn_id"):
            roster[r["gsis_id"]] = (r["espn_id"], r["full_name"], r["team"])

    plays = []
    final = {}  # (game, team) -> points
    for x in pbp:
        if x["season_type"] != "REG" or not x["posteam"]:
            continue
        g, t = x["game_id"], x["posteam"]
        try:
            final[(g, x["home_team"])] = float(x["total_home_score"] or 0)
            final[(g, x["away_team"])] = float(x.get("total_away_score") or 0)
        except ValueError:
            pass
        if x["two_point_attempt"] == "1" or x["qb_kneel"] == "1" or not x["yardline_100"]:
            continue
        yl = float(x["yardline_100"])
        if x["rush_attempt"] == "1" and x["rusher_player_id"]:
            pid, kind = x["rusher_player_id"], 0
        elif x["pass_attempt"] == "1" and x["receiver_player_id"]:
            pid, kind = x["receiver_player_id"], 1
        else:
            continue
        scored = x["td_player_id"] == pid and (x["rush_touchdown"] == "1" or x["pass_touchdown"] == "1")
        plays.append((g, int(x["week"]), t, pid, kind, bucket(yl), yl, scored))

    if not plays:
        raise SystemExit("no plays yet for %d" % SEASON)

    # league TD rate per (carry/target, field zone)
    n = defaultdict(int); s = defaultdict(int)
    for _, _, _, _, k, b, _, sc in plays:
        n[(k, b)] += 1; s[(k, b)] += sc
    rate = {key: s[key] / n[key] for key in n}

    # offensive TDs per point, league-wide (turns implied points into expected TDs)
    tds = sum(p[7] for p in plays)
    pts = sum(final.values())
    td_per_pt = tds / pts if pts else 0.1

    # recency weight per team game
    team_games = defaultdict(list)
    for g, wk, t, *_ in plays:
        if (wk, g) not in team_games[t]:
            team_games[t].append((wk, g))
    w = {}
    for t, gl in team_games.items():
        gl.sort()
        for i, (_, g) in enumerate(gl):
            w[(t, g)] = DECAY ** (len(gl) - 1 - i)

    team_x = defaultdict(float); team_td = defaultdict(float)
    px = defaultdict(float); ptd = defaultdict(float); pgames = defaultdict(set)
    rz = defaultdict(lambda: [0, 0]); i10 = defaultdict(lambda: [0, 0]); pteam = {}
    for g, wk, t, pid, k, b, yl, sc in plays:
        ww = w[(t, g)]
        team_x[(t, g)] += rate[(k, b)] * ww
        team_td[(t, g)] += sc * ww
        key = (pid, t)
        px[key] += rate[(k, b)] * ww
        ptd[key] += sc * ww
        pgames[key].add(g)
        pteam[key] = t
        if yl <= 20: rz[key][k] += 1
        if yl <= 10: i10[key][k] += 1

    out = {}
    for key, xv in px.items():
        pid, t = key
        if pid not in roster:
            continue
        espn, name, cur_team = roster[pid]
        if cur_team and cur_team != t:
            continue  # traded or released: old-team usage doesn't carry over
        games = pgames[key]
        tx = sum(team_x[(t, g)] for g in games)
        tt = sum(team_td[(t, g)] for g in games)
        if tx <= 0:
            continue
        xs = xv / tx
        share = (ptd[key] + PRIOR * xs) / (tt + PRIOR)
        if share < 0.003 and not rz[key][0] and not rz[key][1]:
            continue
        out[espn] = {"n": name, "t": t, "g": len(games), "s": round(share, 4), "xs": round(xs, 4),
                     "td": round(ptd[key], 2), "rz": rz[key], "i10": i10[key]}

    weeks = sorted({p[1] for p in plays})
    json.dump({"pulled": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "season": SEASON,
               "weeks": [weeks[0], weeks[-1]], "tdPerPt": round(td_per_pt, 4), "p": out},
              open("tdshare.json", "w"), separators=(",", ":"))
    print("tdshare players", len(out), "weeks", weeks[0], "-", weeks[-1], "tdPerPt", round(td_per_pt, 4))


if __name__ == "__main__":
    main()
