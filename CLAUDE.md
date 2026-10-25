# crosscheck-data - Claude Code project rules

Public data feed for Crosscheck. Repo is public on purpose: free unlimited Actions minutes + the site reads raw files with no token.

- .github/workflows/kalshi.yml pulls public Kalshi prices (game lines, main spread/total, player prop ladders) every ~5 min (slower 3-9am ET) and merges the friends leaderboard
- the same run calls scripts/bovada.py for public Bovada player props (two-sided O/U + "N+" ladders, pregame only); Bovada sends no CORS header, so the site can't read it directly
- scripts/pinnacle.py pulls public Pinnacle player props (two-sided O/U, pregame) -> pinprops.json, same shape as bovprops.json; Pinnacle is the sharpest anchor so the site weights it highest
- scripts/tdshare.py builds the NFL touchdown-share model from public nflverse play-by-play (red-zone/inside-10 usage, keyed by ESPN id) -> tdshare.json; rebuilt when older than 12h, carried over otherwise
- leaderboard entries must be signed by the app (ECDSA P-256); the workflow holds only the public key, unsigned/forged/replayed posts are dropped
- output goes to the `data` branch (force-pushed each run): kalshi.json, kalprops.json, bovprops.json, pinprops.json, tdshare.json, leaderboard.json
- the run re-queues itself because GitHub's own cron timer is unreliable; only one chain at a time
- nothing secret belongs here - no names, no keys, no personal info. everything in this repo is visible to anyone
