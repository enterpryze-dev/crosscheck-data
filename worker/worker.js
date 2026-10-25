// Crosscheck live relay (Cloudflare Worker, free plan).
// Pulls public Kalshi / Pinnacle / Bovada prices on demand and caches each answer for a few
// seconds, so the app gets ~15-30s fresh prices instead of waiting on the 5-minute GitHub run.
// Same JSON shapes as the files on the crosscheck-data `data` branch. Public prices only,
// no accounts, no keys of anyone's, nothing personal.

const TTL = { kal: 30, kalp: 30, props: 20 };
const ALLOW = /^https:\/\/[a-z0-9-]+\.github\.io$|^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/;
const UA = "Mozilla/5.0 crosscheck/1.0";
const now = () => new Date().toISOString().replace(/\.\d+Z$/, "Z");

async function getJSON(u, headers = {}, tries = 3) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(u, { headers: { "User-Agent": UA, Accept: "application/json", ...headers }, cf: { cacheTtl: 0 } });
      if (r.status === 429 && i < tries - 1) { await new Promise(z => setTimeout(z, 800 * (i + 1))); continue; }
      if (!r.ok) throw new Error(r.status);
      return await r.json();
    } catch (e) { if (i === tries - 1) throw e; }
  }
}

// ---------------- Kalshi ----------------
const KAPI = "https://api.elections.kalshi.com/trade-api/v2/markets?status=open&";
const KG = { NBA: "KXNBAGAME", NFL: "KXNFLGAME", NHL: "KXNHLGAME", MLB: "KXMLBGAME", WNBA: "KXWNBAGAME", NCAAF: "KXNCAAFGAME", NCAAM: "KXNCAAMBGAME", EPL: "KXEPLGAME" };
const KP = {
  NFL: { KXNFLTD: "TD", KXNFLPASSYDS: "PASS YDS", KXNFLRSHYDS: "RUSH YDS", KXNFLRECYDS: "REC YDS", KXNFLREC: "REC", KXNFLRRYDS: "RUSH+REC", KXNFLPASSTDS: "PASS TD", KXNFLPASSCOMP: "CMP", KXNFLPASSATT: "ATT", KXNFLRSHATT: "CAR", KXNFLPASSINT: "INT" },
  NBA: { KXNBAPTS: "PTS", KXNBAREB: "REB", KXNBAAST: "AST", KXNBA3PT: "3PM", KXNBAPRA: "PRA", KXNBAPR: "P+R", KXNBAPA: "P+A", KXNBARA: "R+A", KXNBASTL: "STL", KXNBABLK: "BLK" },
  NHL: { KXNHLGOAL: "G", KXNHLANYGOAL: "G", KXNHLPTS: "PTS", KXNHLAST: "AST", KXNHLSAVES: "SV" },
  MLB: { KXMLBHIT: "H", KXMLBTB: "TB", KXMLBHRR: "H+R+RBI", KXMLBKS: "K", KXMLBRBI: "RBI", KXMLBHR: "HR" },
};
async function kpage(series, max = 3) {
  let rows = [], cur = "";
  for (let i = 0; i < max; i++) {
    const j = await getJSON(KAPI + `series_ticker=${series}&limit=1000` + (cur ? `&cursor=${cur}` : "")).catch(() => null);
    if (!j) break;
    rows = rows.concat(j.markets || []); cur = j.cursor || "";
    if (!cur) break;
  }
  return rows;
}
function mainRung(ms) {
  const ev = {};
  for (const m of ms) {
    const b = +m.yes_bid_dollars || 0, a = +m.yes_ask_dollars || 0;
    if (b <= 0 || a <= 0 || a - b > 0.08) continue;
    const d = Math.abs((a + b) / 2 - 0.5), e = m.event_ticker;
    if (!ev[e] || d < ev[e][0]) ev[e] = [d, [e, m.ticker, m.floor_strike, +b.toFixed(2), +a.toFixed(2)]];
  }
  return Object.values(ev).map(v => v[1]);
}
async function kal() {
  const out = { pulled: now(), markets: {}, sp: {}, tot: {}, live: true };
  await Promise.all(Object.entries(KG).map(async ([lg, s]) => {
    const j = await getJSON(KAPI + `series_ticker=${s}&limit=400`).catch(() => null);
    if (j) out.markets[lg] = (j.markets || []).map(m => [m.event_ticker, m.ticker, m.last_price_dollars, m.yes_bid_dollars, m.yes_ask_dollars]);
  }));
  await Promise.all(["NBA", "NFL", "NHL", "NCAAF", "WNBA"].map(async lg => {
    const [s, t] = await Promise.all([kpage(`KX${lg}SPREAD`, 2), kpage(`KX${lg}TOTAL`, 2)]);
    out.sp[lg] = mainRung(s); out.tot[lg] = mainRung(t);
  }));
  return out;
}
async function kalp(lg) {
  const ser = KP[lg]; if (!ser) return { pulled: now(), lg: {} };
  const L = {};
  await Promise.all(Object.entries(ser).map(async ([series, typ]) => {
    for (const m of await kpage(series, 2)) {
      const b = +m.yes_bid_dollars || 0, a = +m.yes_ask_dollars || 0, k = parseFloat(m.floor_strike);
      if (!(b > 0 && a > 0 && a - b <= 0.10) || !isFinite(k)) continue;
      const t = m.title || ""; if (!t.includes(":")) continue;
      const name = t.split(":")[0].trim();
      ((((L[m.event_ticker] ||= {})[name] ||= {})[typ] ||= [])).push([k, Math.round(b * 100), Math.round(a * 100)]);
    }
  }));
  return { pulled: now(), lg: { [lg]: L }, live: true };
}

// ---------------- Pinnacle ----------------
const PKEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"; // public guest key pinnacle.com's own site sends
const PL = { NFL: 889, NCAAF: 880, NBA: 487, NHL: 1456, MLB: 246, WNBA: 578, NCAAM: 493 };
const PM = {
  "Total Receptions": "REC", "Total Receiving Yards": "REC YDS", "Total Rushing Yards": "RUSH YDS", "Total Rush Attempts": "CAR",
  "Total Pass Completions": "CMP", "Total Pass Attempts": "ATT", "Total Passing Yards": "PASS YDS", "Total Interceptions": "INT",
  "Total Touchdown Passes": "PASS TD", "Total Touchdowns": "ANY TD", "Total Points": "PTS", "Total Rebounds": "REB", "Total Assists": "AST",
  "Total Threes Made": "3PM", "Total Pts & Rebs & Asts": "PRA", "Total Steals": "STL", "Total Blocks": "BLK", "Total Goals": "G",
  "Total Shots On Goal": "SOG", "Total Saves": "SV", "Total Bases": "TB", "Total Home Runs": "HR", "Total Strikeouts": "K",
  "Total Hits Allowed": "H ALW", "Total Earned Runs": "ER", "Total Pitching Outs": "OUTS", "Total Hits": "H",
};
const PT = Object.keys(PM).sort((a, b) => b.length - a.length);
async function pin(lg) {
  const id = PL[lg]; if (!id) return [];
  const H = { "x-api-key": PKEY };
  const [mus, mk] = await Promise.all([
    getJSON(`https://guest.api.arcadia.pinnacle.com/0.1/leagues/${id}/matchups`, H).catch(() => []),
    getJSON(`https://guest.api.arcadia.pinnacle.com/0.1/leagues/${id}/markets/straight`, H).catch(() => []),
  ]);
  const px = {}; for (const m of mk || []) if (m.period === 0 && m.type === "total" && m.matchupId) px[m.matchupId] = m;
  const games = {}, t0 = Date.now();
  for (const m of mus || []) {
    if (m.special || m.parentId) continue;
    const ps = m.participants || [], h = ps.find(p => p.alignment === "home"), a = ps.find(p => p.alignment === "away");
    if (h && a) games[m.id] = { d: `${a.name} @ ${h.name}`, t: Date.parse(m.startTime) || null, p: {} };
  }
  for (const m of mus || []) {
    const sp = m.special || {}; if (sp.category !== "Player Props" || m.isLive) continue;
    const g = games[m.parentId]; if (!g || (g.t && g.t < t0)) continue;
    const d = (sp.description || "").trim(), tail = PT.find(t => d.endsWith(" " + t)); if (!tail) continue;
    const name = d.slice(0, -tail.length).trim().replace(/\s*\([^)]*\)\s*$/, "");
    const ids = {}; for (const p of m.participants || []) ids[p.name] = p.id;
    const q = px[m.id]; if (!q || ids.Over == null || ids.Under == null) continue;
    const pr = {}; for (const p of q.prices || []) pr[p.participantId] = p;
    const ov = pr[ids.Over], un = pr[ids.Under];
    if (!ov || !un || ov.price == null || un.price == null || ov.points == null) continue;
    const typ = PM[tail], line = +ov.points; if (typ === "ANY TD" && line !== 0.5) continue;
    ((g.p[name] ||= { o: {} }).o)[typ] = [line, ov.price | 0, un.price | 0];
  }
  return Object.values(games).filter(g => Object.keys(g.p).length);
}

// ---------------- Bovada ----------------
const BS = { NFL: "football/nfl", NBA: "basketball/nba", NHL: "hockey/nhl", MLB: "baseball/mlb", NCAAF: "football/college-football", WNBA: "basketball/wnba", NCAAM: "basketball/college-basketball" };
const BOU = {
  "Total Receptions": "REC", "Total Receiving Yards": "REC YDS", "Total Rushing Yards": "RUSH YDS", "Total Rush Attempts": "CAR",
  "Total Rushing & Receiving Yards": "RUSH+REC", "Total Passing Touchdowns": "PASS TD", "Total Passing Attempts": "ATT",
  "Total Completions": "CMP", "Total Interceptions Thrown": "INT", "Total Passing Yards": "PASS YDS", "Total Passing & Rushing Yards O/U": "PASS+RUSH",
  "Total Points": "PTS", "Total Rebounds": "REB", "Total Assists": "AST", "Total Made 3 Points Shots": "3PM",
  "Total Points, Rebounds and Assists": "PRA", "Total Points and Rebounds": "P+R", "Total Points and Assists": "P+A", "Total Rebounds and Assists": "R+A",
  "Total Steals": "STL", "Total Blocks": "BLK", "Total Shots On Goal": "SOG", "Total Saves": "SV",
  "Total Hits": "H", "Total Bases": "TB", "Total Strikeouts": "K", "Total Runs Batted In": "RBI", "Total Hits, Runs and RBIs": "H+R+RBI",
};
const BLAD = {
  "Alternate Receiving Yards": "REC YDS", "Alternate Receptions": "REC", "Alternate Rushing Yards": "RUSH YDS", "Alternate Rush Attempts": "CAR",
  "Alternate Rushing & Receiving Yards": "RUSH+REC", "Alternate Passing Completions": "CMP", "Alternate Passing Yards": "PASS YDS",
  "Alternate Passing Touchdowns": "PASS TD", "Points Milestones": "PTS", "Rebounds Milestones": "REB", "Assists Milestones": "AST",
  "Total Made Threes Milestones": "3PM", "Shots on Goal Milestones": "SOG", "Blocks Milestones": "BLK", "Steals Milestones": "STL",
};
const BYES = { "Anytime Touchdown Scorer": "ANY TD", "Anytime Goalscorer": "G" };
const PART = /\b(1H|2H|1Q|2Q|3Q|4Q|1P|2P|3P|REG)\b|1st|2nd|3rd|half|quarter|period/i;
const am = p => { const a = (p || {}).american; if (a == null || a === "") return null; if (String(a).toUpperCase() === "EVEN") return 100; const v = parseInt(String(a).replace("+", ""), 10); return isFinite(v) ? v : null; };
const who = s => { const m = s.trim().match(/^(.*?)\s*(?:\(([A-Z]{2,4})\))?\s*$/); return m ? [m[1].trim(), m[2] || null] : [s.trim(), null]; };
async function bov(lg) {
  const path = BS[lg]; if (!path) return [];
  const j = await getJSON(`https://www.bovada.lv/services/sports/event/v2/events/A/description/${path}?preMatchOnly=true&lang=en`).catch(() => []);
  const evs = (j || []).flatMap(b => b.events || []), L = [];
  for (const e of evs) {
    const P = {}, pl = (n, tm) => { const x = (P[n] ||= { o: {}, y: {} }); if (tm && !x.tm) x.tm = tm; return x; };
    for (const g of e.displayGroups || []) for (const m of g.markets || []) {
      const d = m.description || "", per = (m.period || {}).description || "Game";
      if (!["Game", "Match", "Regulation Time"].includes(per)) continue;
      const i = d.indexOf(" - "), base = i < 0 ? d : d.slice(0, i), rest = i < 0 ? "" : d.slice(i + 3), oc = m.outcomes || [];
      if (BOU[base] && rest) {
        const [name, tm] = who(rest), ov = oc.find(o => o.description === "Over"), un = oc.find(o => o.description === "Under");
        if (!ov || !un) continue; const line = parseFloat((ov.price || {}).handicap), a = am(ov.price), b = am(un.price);
        if (!isFinite(line) || a == null || b == null) continue; pl(name, tm).o[BOU[base]] = [line, a, b];
      } else if (BLAD[base] && rest) {
        const [name, tm] = who(rest), rung = [];
        for (const o of oc) { const t = o.description || "", k = t.match(/(\d+(?:\.\d+)?)\+/); if (!k || PART.test(t)) continue; const a = am(o.price); if (a != null) rung.push([+k[1], a]); }
        if (rung.length) pl(name, tm).y[BLAD[base]] = rung.sort((x, y) => x[0] - y[0]);
      } else if (BYES[base] && !rest) {
        for (const o of oc) { const t = o.description || ""; if (PART.test(t) || /Def\/ST|No (Touchdown|Goal)/.test(t)) continue; const [name, tm] = who(t), a = am(o.price); if (a != null) pl(name, tm).y[BYES[base]] = [[1, a]]; }
      }
    }
    const ed = (e.description || "").toLowerCase(), Q = {};
    for (const [k, v] of Object.entries(P)) {
      if (!Object.keys(v.o).length && !Object.keys(v.y).length) continue;
      if (!v.tm && ed.includes(k.toLowerCase())) continue;
      if (!Object.keys(v.o).length) delete v.o; if (!Object.keys(v.y).length) delete v.y; Q[k] = v;
    }
    if (Object.keys(Q).length) L.push({ d: e.description || "", t: e.startTime, p: Q });
  }
  return L;
}
async function props(lg) {
  const [p, b] = await Promise.all([pin(lg).catch(() => null), bov(lg).catch(() => null)]);
  const t = now();
  return { pin: p ? { pulled: t, src: "pinnacle", lg: { [lg]: p } } : null, bov: b ? { pulled: t, lg: { [lg]: b } } : null, live: true };
}

// ---------------- router with short shared cache ----------------
export default {
  async fetch(req, env, ctx) {
    const origin = req.headers.get("Origin") || "";
    const cors = { "Access-Control-Allow-Origin": ALLOW.test(origin) ? origin : "null", "Vary": "Origin" };
    if (req.method === "OPTIONS") return new Response(null, { headers: { ...cors, "Access-Control-Allow-Methods": "GET" } });
    if (origin && !ALLOW.test(origin)) return new Response("forbidden", { status: 403 });
    const u = new URL(req.url), kind = u.pathname.replace(/^\/+|\/+$/g, ""), lg = (u.searchParams.get("lg") || "").toUpperCase();
    if (!TTL[kind]) return new Response(JSON.stringify({ ok: true, routes: Object.keys(TTL) }), { headers: { ...cors, "Content-Type": "application/json" } });
    if (kind !== "kal" && !/^[A-Z]{2,5}$/.test(lg)) return new Response("lg required", { status: 400, headers: cors });
    const key = new Request(`https://cache.crosscheck/${kind}?lg=${lg}`);
    const cache = caches.default;
    let res = await cache.match(key);
    if (!res) {
      const body = kind === "kal" ? await kal() : kind === "kalp" ? await kalp(lg) : await props(lg);
      res = new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json", "Cache-Control": `public, max-age=${TTL[kind]}` } });
      ctx.waitUntil(cache.put(key, res.clone()));
    }
    const out = new Response(res.body, res);
    for (const [k, v] of Object.entries(cors)) out.headers.set(k, v);
    out.headers.set("Cache-Control", "no-store");
    return out;
  },
};
