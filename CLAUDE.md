# crosscheck-data - Claude Code project rules

Public data feed for Crosscheck. Repo is public on purpose: free unlimited Actions minutes + the site reads raw files with no token.

- .github/workflows/kalshi.yml pulls public Kalshi prices (game lines, main spread/total, player prop ladders) every ~5 min (slower 3-9am ET) and merges the friends leaderboard
- output goes to the `data` branch (force-pushed each run): kalshi.json, kalprops.json, leaderboard.json
- the run re-queues itself because GitHub's own cron timer is unreliable; only one chain at a time
- nothing secret belongs here - no names, no keys, no personal info. everything in this repo is visible to anyone
