// Matchday Edge - static front end. Reads data/latest.json produced by the pipeline.
const $ = (s, el = document) => el.querySelector(s);
const app = $("#app");
let DATA = null;
let LEGS = null;

// ------------------------------------------------------------------ helpers
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (p, d = 0) => (p == null ? "–" : `${(p * 100).toFixed(d)}%`);
const fx2 = (v, d = 2) => (v == null ? "–" : Number(v).toFixed(d));
const fair = (p) => (p > 0 ? (1 / p).toFixed(2) : "–");
const heatColor = (p) => {
  if (p == null) return "transparent";
  const h = Math.max(0, Math.min(1, p)) * 125;
  return `hsl(${h} 62% ${30 + Math.abs(p - 0.5) * 8}%)`;
};
const heat = (p, text) => `<span class="heat" style="background:${heatColor(p)}">${text ?? pct(p)}</span>`;
const lum = (hex) => {
  const n = parseInt(hex, 16);
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
// Team colour that stays visible on a dark background (falls back to the alternate kit colour, then grey)
const teamColor = (t) => {
  const ok = (h) => h && /^[0-9a-f]{6}$/i.test(h) && lum(h) > 0.035 && lum(h) < 0.85;
  if (ok(t.color)) return `#${t.color}`;
  if (ok(t.alt_color)) return `#${t.alt_color}`;
  return "#5d6675";
};
const label = (s, fx) => s.replace("{home}", fx.home.short || fx.home.name).replace("{away}", fx.away.short || fx.away.name);
const fxName = (fx) => `${fx.home.short || fx.home.name} v ${fx.away.short || fx.away.name}`;
const kickoff = (iso) => new Date(iso);
const fmtTime = (iso) => kickoff(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const fmtDay = (iso) => kickoff(iso).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
const fmtShort = (iso) => kickoff(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

function crest(team, cls = "") {
  if (team.logo) return `<img class="crest ${cls}" src="${esc(team.logo)}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'crest ${cls} crest-fallback',style:'background:${teamColor(team)}',textContent:'${esc(team.abbr || "")}'}))">`;
  return `<span class="crest ${cls} crest-fallback" style="background:${teamColor(team)}">${esc(team.abbr || team.name.slice(0, 3))}</span>`;
}
const dots = (arr, big = false) => `<span class="form-dots">${arr.map((x) => `<i class="dot ${big ? "lg " : ""}${x === true ? "y" : x === false ? "n" : x || ""}"></i>`).join("")}</span>`;

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 1600);
}

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};

// ------------------------------------------------------------------ legs (everything you can put on a slip)
const PLAYER_LABELS = {
  sh1: "1+ shots", sh2: "2+ shots", sot1: "1+ shots on target", sot2: "2+ shots on target",
  fc1: "1+ fouls committed", fc2: "2+ fouls committed", fw1: "1+ fouls won", fw2: "2+ fouls won",
  card: "to be carded", goal: "anytime goalscorer",
};

function buildLegs() {
  const legs = [];
  for (const fx of DATA.fixtures) {
    for (const m of fx.markets) {
      legs.push({
        key: `${fx.id}|${m.id}`, fx: fx.id, match: fxName(fx), kickoff: fx.kickoff, kind: "team", group: m.group,
        label: label(m.label, fx), p: m.p, bp: m.blended_p ?? m.p, odds: m.best ?? null, book: m.best_book ?? null,
        edge: m.edge ?? null, value: m.value ?? null, market_p: m.market_p ?? null,
      });
    }
    for (const side of ["home", "away"]) {
      for (const pl of fx.players[side]) {
        if (pl.exp_min <= 0 || pl.pos === "G") continue;
        for (const [k, mk] of Object.entries(pl.markets)) {
          legs.push({
            key: `${fx.id}|p${pl.id}:${k}`, fx: fx.id, match: fxName(fx), kickoff: fx.kickoff, kind: "player",
            group: "Players", stat: k, label: `${pl.short} ${PLAYER_LABELS[k]}`, p: mk.p, bp: mk.p, odds: null,
            hit: mk.hit, hit_n: mk.hit_n, exp_min: pl.exp_min, status: pl.status,
          });
        }
      }
    }
  }
  return legs;
}
const legByKey = (k) => LEGS.find((l) => l.key === k);

// ------------------------------------------------------------------ slip
let slip = store.get("mde-slip", []);
function saveSlip() { store.set("mde-slip", slip); renderSlipFab(); }
function inSlip(key) { return slip.some((s) => s.key === key); }
function toggleLeg(key) {
  if (inSlip(key)) {
    slip = slip.filter((s) => s.key !== key);
    toast("Removed from slip");
  } else {
    const l = legByKey(key);
    if (!l) return;
    slip.push({ key, label: l.label, match: l.match, fx: l.fx, p: l.bp, odds: l.odds });
    toast("Added to slip");
  }
  saveSlip();
  document.querySelectorAll(`[data-leg="${CSS.escape(key)}"]`).forEach((b) => {
    b.classList.toggle("in", inSlip(key));
    b.textContent = inSlip(key) ? "✓" : "+";
  });
  if ($("#drawer").classList.contains("open")) renderDrawer();
}
const addBtn = (key, sm = false) => `<button class="add ${sm ? "sm" : ""} ${inSlip(key) ? "in" : ""}" data-leg="${esc(key)}" title="Add to slip">${inSlip(key) ? "✓" : "+"}</button>`;

function renderSlipFab() {
  const fab = $("#slipFab");
  $("#slipCount").textContent = slip.length;
  fab.classList.toggle("empty", slip.length === 0);
  fab.hidden = slip.length === 0;
}

function slipMaths(legs) {
  const p = legs.reduce((a, l) => a * l.p, 1);
  const priced = legs.every((l) => l.odds > 1);
  const odds = priced ? legs.reduce((a, l) => a * l.odds, 1) : null;
  const ev = priced ? p * odds - 1 : null;
  const fxs = legs.map((l) => l.fx);
  const sameGame = fxs.length !== new Set(fxs).size;
  return { p, odds, ev, sameGame, fair: p > 0 ? 1 / p : null };
}

function renderDrawer() {
  const d = $("#drawer");
  const m = slipMaths(slip);
  d.innerHTML = `
    <div class="drawer-h"><h2>Bet slip</h2><button class="x" id="closeDrawer" aria-label="Close">✕</button></div>
    <div class="drawer-b">
      ${slip.length === 0 ? `<div class="empty-state">Tap <b>+</b> next to any market or player stat to build a single, double or acca here.</div>` : ""}
      ${slip.map((l, i) => `
        <div class="leg">
          <div><div class="t">${esc(l.label)}</div><small>${esc(l.match)} · model ${pct(l.p)} · fair ${fair(l.p)}</small></div>
          <input inputmode="decimal" placeholder="odds" value="${l.odds ?? ""}" data-i="${i}" aria-label="Your bookmaker's odds">
          <button class="x" data-rm="${i}" aria-label="Remove">✕</button>
        </div>`).join("")}
      ${slip.length ? `<p class="note">Type the decimal odds your bookmaker offers for each leg (e.g. 1.85). Prices we know are filled in.</p>` : ""}
    </div>
    ${slip.length ? `<div class="drawer-f">
      <div class="sum-row"><span>${slip.length === 1 ? "Single" : slip.length === 2 ? "Double" : `${slip.length}-fold acca`}</span><b>${pct(m.p, 1)} chance</b></div>
      <div class="sum-row"><span>Fair odds (model)</span><b>${m.fair ? m.fair.toFixed(2) : "–"}</b></div>
      <div class="sum-row"><span>Your odds</span><b>${m.odds ? m.odds.toFixed(2) : "enter all legs"}</b></div>
      <div class="sum-row big"><span>Expected return per £10</span><b style="color:${m.ev == null ? "var(--text)" : m.ev >= 0 ? "var(--accent)" : "var(--loss)"}">${m.ev == null ? "–" : `£${(10 * (1 + m.ev)).toFixed(2)}`}</b></div>
      ${m.ev != null ? `<p class="note">${m.ev >= 0 ? `The odds beat the model's fair price by ${pct(m.ev, 1)}.` : `The bookmaker's price is ${pct(-m.ev, 1)} worse than the model's fair price.`} Every extra leg multiplies the bookmaker's margin.</p>` : ""}
      ${m.sameGame ? `<div class="warn-box">Two or more legs are from the same match. These outcomes are linked (e.g. shots and goals), so the combined chance shown is only a rough guide, and bookmakers price bet builders differently.</div>` : ""}
      <div style="display:flex;gap:8px;margin-top:12px"><button class="btn" id="clearSlip">Clear</button></div>
    </div>` : ""}`;
  $("#closeDrawer").onclick = closeDrawer;
  d.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = () => { slip.splice(+b.dataset.rm, 1); saveSlip(); renderDrawer(); route(); }));
  d.querySelectorAll("input[data-i]").forEach((inp) => (inp.onchange = () => {
    const v = parseFloat(inp.value.replace(",", "."));
    slip[+inp.dataset.i].odds = v > 1 ? v : null;
    saveSlip();
    renderDrawer();
  }));
  const c = $("#clearSlip");
  if (c) c.onclick = () => { slip = []; saveSlip(); renderDrawer(); route(); };
}
function openDrawer() { renderDrawer(); $("#drawer").classList.add("open"); $("#drawerBg").classList.add("open"); }
function closeDrawer() { $("#drawer").classList.remove("open"); $("#drawerBg").classList.remove("open"); }

// ------------------------------------------------------------------ shared bits
const RG = `<div class="rg"><div class="age">18+</div><div><b>Gamble responsibly.</b> These are model estimates, not guarantees. Bookmakers build a margin into every price and most bettors lose over time. Only stake what you can afford to lose, set a limit before you start, and never chase losses. Free, confidential help: <a href="https://www.begambleaware.org" target="_blank" rel="noopener">BeGambleAware.org</a> · National Gambling Helpline 0808 8020 133 · self-exclude at <a href="https://www.gamstop.co.uk" target="_blank" rel="noopener">GAMSTOP</a>.</div></div>`;

const rgb = (hex) => { const n = parseInt(hex.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
const colorDist = (a, b) => { const x = rgb(a), y = rgb(b); return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]); };
// Home and away colours that can be told apart (Liverpool v Arsenal are both red)
function pairColors(fx) {
  const h = teamColor(fx.home);
  let a = teamColor(fx.away);
  if (colorDist(h, a) < 90) {
    const alt = fx.away.alt_color && /^[0-9a-f]{6}$/i.test(fx.away.alt_color) ? `#${fx.away.alt_color}` : null;
    a = alt && colorDist(h, alt) >= 90 && lum(alt.slice(1)) > 0.035 ? alt : "#cfd6e0";
  }
  return [h, a];
}
function probBar(fx, withOdds = false) {
  const m = (id) => fx.markets.find((x) => x.id === id) || {};
  const [h, d, a] = [m("home"), m("draw"), m("away")];
  const [hc, ac] = pairColors(fx);
  const odds = (x) => (withOdds && x.best ? `<small class="bk">best odds ${x.best.toFixed(2)}</small>` : "");
  return `<div class="probbar"><div style="flex:${h.p};background:${hc}"></div><div style="flex:${d.p};background:#4a5261"></div><div style="flex:${a.p};background:${ac}"></div></div>
  <div class="problabels"><span>Home <b>${pct(h.p)}</b>${odds(h)}</span><span>Draw <b>${pct(d.p)}</b>${odds(d)}</span><span>Away <b>${pct(a.p)}</b>${odds(a)}</span></div>`;
}

function valueCount(fx) { return fx.markets.filter((m) => m.value).length; }

// ------------------------------------------------------------------ pages
function pageFixtures() {
  const fxs = DATA.fixtures;
  if (!fxs.length) return `<div class="empty-state"><h2>No fixtures yet</h2><p>The next round appears here once it is scheduled.</p></div>${RG}`;
  const byDay = {};
  for (const fx of fxs) (byDay[fmtDay(fx.kickoff)] ||= []).push(fx);
  return `
    <div class="page-head"><div><h1>Matchday sheets</h1><p>${esc(DATA.league)} · ${esc(DATA.season)} · tap a match for the full stats sheet, player hit rates and model prices.</p></div>
    <div style="display:flex;gap:6px;flex-wrap:wrap"><span class="pill">${fxs.length} fixtures</span><span class="pill accent">${fxs.reduce((a, f) => a + valueCount(f), 0)} value spots</span></div></div>
    ${Object.entries(byDay).map(([day, list]) => `<div class="day">${esc(day)}</div><div class="fx-list">${list.map(fxCard).join("")}</div>`).join("")}
    ${RG}`;
}

function fxCard(fx) {
  const v = valueCount(fx);
  const xg = fx.expected.goals;
  return `<a class="card fx" href="#/match/${fx.id}" style="--hc:${pairColors(fx)[0]};--ac:${pairColors(fx)[1]}">
    <div class="fx-row">
      <div class="fx-team">${crest(fx.home)}<span>${esc(fx.home.short || fx.home.name)}</span></div>
      <div class="fx-time">${fmtTime(fx.kickoff)}<small>${fx.home.table ? `${ord(fx.home.table.pos)} v ${ord(fx.away.table?.pos)}` : ""}</small></div>
      <div class="fx-team away">${crest(fx.away)}<span>${esc(fx.away.short || fx.away.name)}</span></div>
    </div>
    ${probBar(fx, true)}
    <div class="fx-meta">
      <span class="pill">xG ${fx2(xg[0], 1)} – ${fx2(xg[1], 1)}</span>
      ${fx.referee ? `<span class="pill">🟨 ${esc(fx.referee.name)}</span>` : `<span class="pill">Referee TBC</span>`}
      ${v ? `<span class="pill accent">${v} value bet${v > 1 ? "s" : ""}</span>` : ""}
      ${fx.has_odds ? "" : `<span class="pill warn">No odds yet</span>`}
    </div>
  </a>`;
}
const ord = (n) => (n == null ? "" : n + (["th", "st", "nd", "rd"][(n % 100 - 20) % 10] || ["th", "st", "nd", "rd"][n % 100] || "th"));

// ---- match page
const TEAM_ROWS = [
  ["Goals scored", "goals_for", "goals"], ["Goals conceded", "goals_against", "goals"],
  ["xG created", "xg_for", "xg"], ["xG conceded", "xg_against", "xg"],
  ["Shots taken", "shots_for", "shots"], ["Shots faced", "shots_against", "shots"],
  ["Shots on target", "sot_for", "sot"], ["Shots on target faced", "sot_against", "sot"],
  ["Corners won", "corners_for", "corners"], ["Corners conceded", "corners_against", "corners"],
  ["Fouls committed", "fouls_for", "fouls"], ["Fouls won", "fouls_won", "fouls"],
  ["Cards received", "cards_for", "cards"], ["Opponent cards", "cards_against", "cards"],
  ["Keeper saves", "saves_for", null], ["Opponent keeper saves", "saves_against", null],
];

function pageMatch(id, tab = "overview") {
  const fx = DATA.fixtures.find((f) => f.id === id);
  if (!fx) return `<div class="empty-state"><h2>Match not found</h2><p><a href="#/">Back to fixtures</a></p></div>`;
  const tabs = [["overview", "Overview"], ["team", "Team stats"], ["shooting", "Player shots"], ["fouls", "Player fouls"], ["cards", "Cards & goals"], ["markets", "All markets"]];
  const body = { overview: matchOverview, team: matchTeam, shooting: (f) => matchPlayers(f, "shooting"), fouls: (f) => matchPlayers(f, "fouls"), cards: (f) => matchPlayers(f, "cards"), markets: matchMarkets }[tab] || matchOverview;
  const e = fx.expected;
  return `
    <div class="card hero" style="--hc:${pairColors(fx)[0]};--ac:${pairColors(fx)[1]}">
      <div class="hero-bg"></div>
      <div class="hero-row">
        <div class="hero-team">${crest(fx.home, "lg")}<h2>${esc(fx.home.name)}</h2>${dots(fx.home.form.map((f) => f.r), true)}<span class="sub">${fx.home.table ? `${ord(fx.home.table.pos)} · ${fx.home.table.pts} pts` : ""}</span></div>
        <div class="hero-mid"><div class="sub">${fmtShort(fx.kickoff)}</div><div class="ko">${fmtTime(fx.kickoff)}</div><div class="sub" style="font-size:12px">${esc(fx.venue || "")}</div></div>
        <div class="hero-team">${crest(fx.away, "lg")}<h2>${esc(fx.away.name)}</h2>${dots(fx.away.form.map((f) => f.r), true)}<span class="sub">${fx.away.table ? `${ord(fx.away.table.pos)} · ${fx.away.table.pts} pts` : ""}</span></div>
      </div>
      ${probBar(fx, true)}
      <div class="hero-stats">
        <div class="kpi"><b>${fx2(e.goals[0], 2)} – ${fx2(e.goals[1], 2)}</b><span>Expected goals</span></div>
        <div class="kpi"><b>${fx2(e.corners?.[0] + e.corners?.[1], 1)}</b><span>Expected corners</span></div>
        <div class="kpi"><b>${fx2(e.cards?.[0] + e.cards?.[1], 1)}</b><span>Expected cards</span></div>
        <div class="kpi"><b>${esc(fx.top_scores[0]?.score || "–")}</b><span>Likeliest score ${pct(fx.top_scores[0]?.p)}</span></div>
      </div>
    </div>
    <div class="subtabs">${tabs.map(([k, l]) => `<button class="${k === tab ? "on" : ""}" data-tab="${k}">${l}</button>`).join("")}</div>
    <div id="matchBody">${body(fx)}</div>
    ${RG}`;
}

function marketRow(fx, m) {
  const key = `${fx.id}|${m.id}`;
  const hasOdds = m.best != null;
  return `<div class="mkt">
    <div class="name">${esc(label(m.label, fx))} ${m.value ? `<span class="vbadge ${m.value}">${m.value} value</span>` : ""}
      <small>${hasOdds ? `Market thinks ${pct(m.market_p)} · edge <span class="edge ${m.edge > 0 ? "pos" : "neg"}">${m.edge > 0 ? "+" : ""}${pct(m.edge, 1)}</span>` : `Fair odds ${m.fair.toFixed(2)} · value if your bookie offers more than ${(m.fair * 1.05).toFixed(2)}`}</small></div>
    <div class="prob">${pct(m.p)}<small>fair ${m.fair.toFixed(2)}</small></div>
    <div class="odds">${hasOdds ? `<b>${m.best.toFixed(2)}</b><small>${esc(m.best_book)}</small>` : `<small>no free price</small>`}</div>
    ${addBtn(key)}
  </div>`;
}

function matchOverview(fx) {
  const value = fx.markets.filter((m) => m.value).sort((a, b) => b.edge - a.edge);
  // Strongest pick from each market type, skipping near-certainties that bookies price at ~1.05
  const byGroup = {};
  for (const m of fx.markets) {
    if (m.p < 0.6 || m.p > 0.88 || /over_0\.5$|under_(0|1)\./.test(m.id)) continue;
    const score = m.p + (m.best ? 0.05 : 0) + (m.edge > 0 ? m.edge : 0);
    if (!byGroup[m.group] || score > byGroup[m.group].score) byGroup[m.group] = { m, score };
  }
  const likely = Object.values(byGroup).sort((a, b) => b.score - a.score).map((x) => x.m);
  const players = [];
  for (const side of ["home", "away"]) for (const pl of fx.players[side]) {
    if (pl.exp_min < 60 || pl.pos === "G") continue;
    for (const k of ["sot1", "sh2", "fc1", "fc2", "fw1", "fw2"]) {
      const mk = pl.markets[k];
      if (mk && mk.hit_n >= 4) players.push({ pl, k, mk, side });
    }
  }
  players.sort((a, b) => b.mk.p - a.mk.p);
  const topPlayers = players.filter((x) => x.mk.p <= 0.9 && x.mk.hit >= 0.6).slice(0, 8);
  const cardStars = [];
  for (const side of ["home", "away"]) for (const pl of fx.players[side]) {
    const mk = pl.markets.card;
    if (mk && pl.exp_min >= 45 && pl.pos !== "G" && mk.hit_n >= 3) cardStars.push({ pl, k: "card", mk, side });
  }
  cardStars.sort((a, b) => b.mk.p - a.mk.p).splice(4);
  return `<div class="grid g2">
    <div class="card"><div class="card-h"><h3>Value spots</h3><span class="pill">model vs bookies</span></div>
      ${value.length ? value.map((m) => marketRow(fx, m)).join("") : `<div class="card-b note">No priced market here beats the model's fair odds by enough to flag. That's normal for most matches: the main markets are priced sharply. Player props below have no free odds feed, so compare their fair odds with your bookie.</div>`}
    </div>
    ${refereeCard(fx)}
    <div class="card"><div class="card-h"><h3>Best pick per market</h3><span class="pill">60–88% chance</span></div>
      ${likely.map((m) => marketRow(fx, m)).join("")}
    </div>
    <div class="card"><div class="card-h"><h3>Strongest player stats</h3><span class="pill">regular starters</span></div>
      ${topPlayers.map(playerLegRow(fx)).join("") || `<div class="card-b note">No player data yet.</div>`}
      ${cardStars.length ? `<div class="card-b" style="border-top:1px solid var(--line)"><div class="note" style="margin-bottom:6px">Most likely to be booked</div>${cardStars.map(playerLegRow(fx)).join("")}</div>` : ""}
    </div>
    ${hitCard(fx, "home")}${hitCard(fx, "away")}
  </div>`;
}

const playerLegRow = (fx) => ({ pl, k, mk, side }) => `<div class="mkt">
  <div class="name">${esc(pl.short)} ${esc(PLAYER_LABELS[k])}<small>${esc(fx[side].short || fx[side].name)} · hit ${pct(mk.hit)} of last ${mk.hit_n} games${pl.note ? ` · ${esc(pl.note)}` : ""}</small></div>
  <div class="prob">${pct(mk.p)}<small>fair ${fair(mk.p)}</small></div>
  <div class="odds"><small>value above</small><b>${(1.05 / mk.p).toFixed(2)}</b></div>
  ${addBtn(`${fx.id}|p${pl.id}:${k}`)}
</div>`;

function refereeCard(fx) {
  const r = fx.referee;
  if (!r) return `<div class="card"><div class="card-h"><h3>Referee</h3></div><div class="card-b note">Not announced yet. Premier League referees are usually confirmed early in the week, and card predictions update when they are.</div></div>`;
  const block = (t, s) => s && s.games ? `<div class="label">${t} · ${s.games} games</div><div class="ref-grid">
      <div class="kpi"><b>${fx2(s.yellows)}</b><span>Yellows</span></div><div class="kpi"><b>${fx2(s.reds)}</b><span>Reds</span></div>
      <div class="kpi"><b>${fx2(s.fouls, 1)}</b><span>Fouls</span></div><div class="kpi"><b>${s.factor ? `×${fx2(s.factor)}` : "–"}</b><span>Card factor</span></div></div>` : `<div class="label">${t}</div><div class="note">No games yet.</div>`;
  return `<div class="card ref-card"><div class="card-h"><h3>🟨 ${esc(r.name)}</h3><span class="pill">per game</span></div><div class="card-b">
    ${block("This season", r.season)}${block("Last 5 seasons", r.career)}
    <p class="note" style="margin-bottom:0">Card factor compares the referee with the league average (×1.10 means about 10% more cards). It feeds into every card prediction for this match.</p></div></div>`;
}

function hitCard(fx, side) {
  const t = fx[side];
  return `<div class="card"><div class="team-band" style="background:${teamColor(t)}">${crest(t)}${esc(t.name)} · match hit rates</div><div class="card-b hits">
    <div class="hit-row note"><span></span><span>last 5 (oldest → newest)</span><span style="text-align:right">season</span></div>
    ${Object.values(t.hits).map((h) => `<div class="hit-row"><span>${esc(h.label)}</span>${dots(h.last5)}<b style="text-align:right">${pct(h.season)}</b></div>`).join("")}
    <div class="hit-row" style="margin-top:6px"><span>Form</span><span class="form-dots">${t.form.map((f) => `<i class="dot ${f.r}" title="${esc(`${f.venue === "H" ? "v" : "@"} ${f.opp} ${f.score}`)}"></i>`).join("")}</span><span></span></div>
  </div></div>`;
}

function matchTeam(fx) {
  const h = fx.home, a = fx.away;
  const [hc, ac] = pairColors(fx);
  const lg = DATA.league_avgs || {};
  const vs = (v, base) => {
    if (v == null || !base) return "";
    const d = v / base - 1;
    if (Math.abs(d) < 0.08) return `<span class="vs flat">avg</span>`;
    return `<span class="vs ${d > 0 ? "up" : "down"}">${d > 0 ? "▲" : "▼"} ${Math.abs(Math.round(d * 100))}%</span>`;
  };
  const cell = (t, key, lk) => `<td class="big">${fx2(t.season[key])}${vs(t.season[key], lg[lk]?.mean)}</td><td class="formstr">${(t.last5[key] || []).map((v) => v ?? "–").join("-")}</td>`;
  return `<div class="card"><div class="tbl-wrap"><table class="stat-compare">
    <thead><tr><th class="l sticky-col" rowspan="2">Per game</th><th rowspan="2" title="League average per team per game">League</th>
      <th colspan="2" class="team-th" style="background:${hc}">${esc(h.short || h.name)}</th><th colspan="2" class="team-th" style="background:${ac}">${esc(a.short || a.name)}</th></tr>
    <tr><th>Season</th><th>Last 5</th><th>Season</th><th>Last 5</th></tr></thead>
    <tbody>${TEAM_ROWS.map(([l, k, lk]) => `<tr><td class="lbl l sticky-col">${l}</td><td class="sub">${lk && lg[lk] ? fx2(lg[lk].mean) : "–"}</td>${cell(h, k, lk)}${cell(a, k, lk)}</tr>`).join("")}</tbody></table></div>
    <div class="card-b note">▲/▼ compare each team with the league average. Last 5 reads oldest → newest. Keeper saves are estimated from shots on target minus goals. Based on ${h.played} and ${a.played} league games this season.</div></div>
    <div class="grid g2" style="margin-top:14px">${hitCard(fx, "home")}${hitCard(fx, "away")}</div>`;
}

const PLAYER_VIEWS = {
  shooting: [{ stat: "sot", title: "Shots on target", keys: ["sot1", "sot2"] }, { stat: "sh", title: "Shots", keys: ["sh1", "sh2"] }],
  fouls: [{ stat: "fc", title: "Fouls committed", keys: ["fc1", "fc2"] }, { stat: "fw", title: "Fouls won", keys: ["fw1", "fw2"] }],
  cards: [{ stat: "card", title: "Cards", keys: ["card"] }, { stat: "g", title: "Goals", keys: ["goal"] }],
};
let showAllPlayers = false;
const KEY_SHORT = { sh1: "1+", sh2: "2+", sot1: "1+", sot2: "2+", fc1: "1+", fc2: "2+", fw1: "1+", fw2: "2+", card: "Card", goal: "Score" };

function matchPlayers(fx, view) {
  const blocks = PLAYER_VIEWS[view];
  const sortKey = blocks[0].keys[0];
  const table = (side) => {
    const t = fx[side];
    const all = fx.players[side].filter((p) => p.pos !== "G")
      .sort((a, b) => (b.exp_min > 0) - (a.exp_min > 0) || (b.markets[sortKey]?.p ?? 0) - (a.markets[sortKey]?.p ?? 0));
    const players = showAllPlayers ? all : all.filter((p) => p.exp_min >= 30).slice(0, 12);
    const hidden = all.length - players.length;
    return `<div class="card" style="margin-bottom:14px"><div class="team-band" style="background:${teamColor(t)}">${crest(t)}${esc(t.name)}</div><div class="tbl-wrap"><table>
      <thead><tr><th class="l sticky-col" rowspan="2">Player</th><th rowspan="2" title="Expected minutes / appearances">Mins</th>
        ${blocks.map((b) => `<th colspan="${2 + b.keys.length * 2}" style="border-left:1px solid var(--line)">${b.title}</th>`).join("")}</tr>
      <tr>${blocks.map((b) => `<th style="border-left:1px solid var(--line)">Avg</th><th>Last 5</th>${b.keys.map((k) => `<th title="Season hit rate in games with 45+ minutes">${KEY_SHORT[k]} hit</th><th title="Model probability for this match">${KEY_SHORT[k]} model</th>`).join("")}`).join("")}</tr></thead>
      <tbody>${players.map((p) => `<tr class="${p.exp_min <= 0 ? "out" : ""}">
        <td class="player sticky-col">${esc(p.short)} <span class="sub" style="font-size:11px">${p.pos}</span>${p.note ? `<small title="${esc(p.note)}">${p.status !== "available" ? "⚠️ " : ""}${esc(p.note.length > 34 ? p.note.slice(0, 32) + "…" : p.note)}</small>` : ""}</td>
        <td>${p.exp_min}<small class="sub"> /${p.apps}</small></td>
        ${blocks.map((b) => `<td style="border-left:1px solid var(--line)">${fx2(p.per_game[b.stat])}</td><td class="formstr">${(p.last5[b.stat] || []).join("-")}</td>
          ${b.keys.map((k) => { const mk = p.markets[k]; if (!mk) return "<td>–</td><td>–</td>"; return `<td>${heat(mk.hit)}</td><td><div style="display:flex;gap:6px;align-items:center;justify-content:center">${heat(mk.p)}${p.exp_min > 0 ? addBtn(`${fx.id}|p${p.id}:${k}`, true) : ""}</div><small class="sub">${fair(mk.p)}</small></td>`; }).join("")}`).join("")}
      </tr>`).join("")}</tbody></table></div>${hidden > 0 || showAllPlayers ? `<div class="card-b" style="padding:10px 16px"><button class="btn" data-showall>${showAllPlayers ? "Show regular players only" : `Show ${hidden} more (bench, injured, rarely used)`}</button></div>` : ""}</div>`;
  };
  return `<p class="note" style="margin-top:0">Hit = how often the player reached it this season (games with 45+ minutes). Model = chance for <b>this</b> match, adjusted for opponent, venue, referee, expected minutes and injury news. Small number under the model figure = fair odds; a bookie price above it is value by the model.</p>
    ${table("home")}${table("away")}`;
}

function matchMarkets(fx) {
  const groups = {};
  for (const m of fx.markets) (groups[m.group] ||= []).push(m);
  return `<div class="grid g2">${Object.entries(groups).map(([g, ms]) => `<div class="card mkt-group"><div class="card-h"><h3>${esc(g)}</h3></div>${ms.map((m) => marketRow(fx, m)).join("")}</div>`).join("")}</div>`;
}

// ---- value page
function pageValue() {
  const vals = LEGS.filter((l) => l.value).sort((a, b) => b.edge - a.edge);
  const doubles = [];
  for (let i = 0; i < Math.min(vals.length, 8); i++) for (let j = i + 1; j < Math.min(vals.length, 8); j++) {
    const a = vals[i], b = vals[j];
    if (a.fx === b.fx) continue;
    const odds = a.odds * b.odds, p = a.bp * b.bp;
    doubles.push({ a, b, odds, p, ev: p * odds - 1 });
  }
  doubles.sort((x, y) => y.ev - x.ev);
  const props = LEGS.filter((l) => l.kind === "player" && l.p >= 0.55 && l.p <= 0.96 && l.exp_min >= 60 && l.hit_n >= 4 && l.hit >= 0.6)
    .sort((a, b) => b.p - a.p).slice(0, 24);
  return `<div class="page-head"><div><h1>Value bets</h1><p>Prices where the bookmaker pays more than our estimate says they should. To be conservative, the edge uses a 50/50 blend of our model and the market's own view, and the bet has to clear both.</p>
    ${DATA.backtest?.bets?.count ? `<p>Honest check: over ${DATA.backtest.seasons.join(", ")} the same rule flagged ${DATA.backtest.bets.count} bets, which returned <b>${DATA.backtest.bets.roi >= 0 ? "+" : ""}${pct(DATA.backtest.bets.roi, 1)}</b> per bet. Roughly break-even beats the ~5% most bettors lose to the margin, but it is not a money machine. <a href="#/record" style="text-decoration:underline">See the track record</a>.</p>` : ""}</div></div>
    <div class="card"><div class="card-h"><h3>Singles</h3><span class="pill">${vals.length} found</span></div>
      ${vals.length ? `${vals.map((l) => `<div class="mkt">
        <div class="name">${esc(l.label)} <span class="vbadge ${l.value}">${l.value}</span><small><a href="#/match/${l.fx}" style="text-decoration:underline">${esc(l.match)}</a> · ${fmtShort(l.kickoff)} ${fmtTime(l.kickoff)} · market ${pct(l.market_p)} · edge <span class="edge pos">+${pct(l.edge, 1)}</span></small></div>
        <div class="prob">${pct(l.p)}<small>model</small></div>
        <div class="odds"><b>${l.odds.toFixed(2)}</b><small>${esc(l.book)}</small></div>
        ${addBtn(l.key)}</div>`).join("")}` : `<div class="card-b note">No value singles this round. The free odds feed covers match result, double chance and over/under 2.5, which are the sharpest markets. Use the player props list below with your bookie's prices instead.</div>`}
    </div>
    ${doubles.length ? `<div class="card" style="margin-top:14px"><div class="card-h"><h3>Suggested doubles</h3><span class="pill">two value picks, different matches</span></div>
      ${doubles.slice(0, 4).map((d) => `<div class="mkt"><div class="name">${esc(d.a.label)} + ${esc(d.b.label)}<small>${esc(d.a.match)} · ${esc(d.b.match)}</small></div>
        <div class="prob">${pct(d.p)}<small>chance</small></div><div class="odds"><b>${d.odds.toFixed(2)}</b><small>combined</small></div>
        <button class="add" data-multi="${esc(JSON.stringify([d.a.key, d.b.key]))}" title="Add both">+</button></div>`).join("")}</div>` : ""}
    <div class="card" style="margin-top:14px"><div class="card-h"><h3>Player props: the price to beat</h3><span class="pill">regular starters</span></div>
      <div class="card-b note" style="padding-bottom:0">No free feed has player-prop odds, so here is the model's fair price. If your bookmaker offers more than the "value above" number, the bet is value by our model.</div>
      <div class="tbl-wrap"><table><thead><tr><th class="l">Player bet</th><th class="l">Match</th><th>Season hit</th><th>Model</th><th>Fair odds</th><th>Value above</th><th></th></tr></thead><tbody>
      ${props.map((l) => `<tr><td class="l"><b>${esc(l.label)}</b></td><td class="l"><a href="#/match/${l.fx}">${esc(l.match)}</a></td><td>${heat(l.hit)}</td><td>${heat(l.p)}</td><td>${fair(l.p)}</td><td><b>${(1.05 / l.p).toFixed(2)}</b></td><td>${addBtn(l.key, true)}</td></tr>`).join("")}
      </tbody></table></div></div>${RG}`;
}

// ---- acca builder
const ACCA_GROUPS = ["Result", "Goals", "Corners", "Cards", "Shots on target", "Players"];
let accaCfg = store.get("mde-acca", { legs: 4, minP: 0.7, groups: ["Result", "Goals", "Corners", "Players"] });

function accaPool() {
  // Legs above 90% pay so little (≈1.05) that they only add bookmaker margin, so they're left out
  return LEGS.filter((l) => accaCfg.groups.includes(l.group) && l.p >= accaCfg.minP && l.p <= 0.9 &&
    (l.kind === "team" || (l.exp_min >= 60 && l.hit_n >= 4 && l.hit >= accaCfg.minP - 0.15)) &&
    !/(^under_0|over_0\.5$)/.test(l.key.split("|")[1]));
}

function pickPerMatch(pool, score) {
  const best = {};
  for (const l of pool) { const s = score(l); if (s == null) continue; if (!best[l.fx] || s > best[l.fx].s) best[l.fx] = { l, s }; }
  return Object.values(best).sort((a, b) => b.s - a.s).slice(0, accaCfg.legs).map((x) => x.l);
}

function accaCard(title, blurb, legs) {
  if (legs.length < 2) return `<div class="card"><div class="card-h"><h3>${title}</h3></div><div class="card-b note">Not enough legs match these filters. Try lowering the minimum chance or adding markets.</div></div>`;
  const m = slipMaths(legs.map((l) => ({ ...l, p: l.bp })));
  return `<div class="card"><div class="card-h"><div><h3>${title}</h3><div class="note">${blurb}</div></div><button class="btn primary" data-multi="${esc(JSON.stringify(legs.map((l) => l.key)))}">Add to slip</button></div>
    <div class="card-b"><div class="acca-legs">${legs.map((l) => `<div class="acca-leg"><div><b>${esc(l.label)}</b><small>${esc(l.match)} · ${fmtShort(l.kickoff)}</small></div><div style="text-align:right"><b>${pct(l.p)}</b><small>${l.odds ? `${l.odds.toFixed(2)} ${esc(l.book)}` : `fair ${fair(l.p)}`}</small></div></div>`).join("")}</div>
    <div class="acca-sum"><div class="kpi"><b>${pct(m.p, 1)}</b><span>Chance all win</span></div><div class="kpi"><b>${m.fair.toFixed(2)}</b><span>Fair odds</span></div><div class="kpi"><b>${m.odds ? m.odds.toFixed(2) : "–"}</b><span>${m.odds ? "Bookie odds" : "Some legs unpriced"}</span></div></div></div></div>`;
}

function pageAccas() {
  const pool = accaPool();
  const banker = pickPerMatch(pool, (l) => l.p);
  // Value legs are usually bigger prices, so they ignore the minimum-chance slider (but stay above 30%)
  const value = pickPerMatch(LEGS.filter((l) => l.value && l.p >= 0.3), (l) => l.edge).slice(0, 3);
  const bigger = pickPerMatch(pool, (l) => (l.p < accaCfg.minP + 0.12 ? l.p : null));
  return `<div class="page-head"><div><h1>Acca builder</h1><p>Builds accumulators from one leg per match so the legs don't depend on each other. Set how safe each leg must be. The "chance all win" figure is what really matters: four 75% legs only land about 32% of the time.</p></div></div>
    <div class="card controls">
      <div class="ctl"><label>Legs: <b id="lv">${accaCfg.legs}</b></label><input type="range" min="2" max="8" value="${accaCfg.legs}" id="legsR"></div>
      <div class="ctl"><label>Min chance per leg: <b id="pv">${pct(accaCfg.minP)}</b></label><input type="range" min="0.5" max="0.88" step="0.01" value="${accaCfg.minP}" id="minR"></div>
      <div class="ctl"><label>Markets</label><div class="chips">${ACCA_GROUPS.map((g) => `<button class="chip ${accaCfg.groups.includes(g) ? "on" : ""}" data-g="${g}">${g}</button>`).join("")}</div></div>
      <span class="pill">${pool.length} eligible legs</span>
    </div>
    <div class="grid g3" style="margin-top:14px">
      ${accaCard("Banker acca", "The most likely leg from each match.", banker)}
      ${accaCard("Bigger price", `Legs just above ${pct(accaCfg.minP)}, for a longer price.`, bigger)}
      ${accaCard("Value treble", "Up to three flagged value bets, any chance above 30%. Long odds and high risk, but every leg is priced above our fair odds.", value)}
    </div>
    <p class="note">Player legs only include regular starters (60+ expected minutes) with at least 4 games of data. Bookmakers often price accas and player props with extra margin, so compare the fair odds with what you're offered.</p>${RG}`;
}

// ---- track record
function pageRecord() {
  const bt = DATA.backtest;
  if (!bt) return `<div class="empty-state">No backtest yet.</div>`;
  const b = bt.bets;
  const curve = b.curve || [];
  let svg = "";
  if (curve.length > 1) {
    const W = 800, H = 220, P = 30;
    const ys = curve.map((c) => c[1]);
    const lo = Math.min(0, ...ys), hi = Math.max(0, ...ys);
    const x = (i) => P + (i / (curve.length - 1)) * (W - 2 * P);
    const y = (v) => H - P - ((v - lo) / (hi - lo || 1)) * (H - 2 * P);
    const path = curve.map((c, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(c[1]).toFixed(1)}`).join("");
    svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Profit over time">
      <line x1="${P}" x2="${W - P}" y1="${y(0)}" y2="${y(0)}" stroke="#3a4352" stroke-dasharray="4 4"/>
      <path d="${path}" fill="none" stroke="${ys[ys.length - 1] >= 0 ? "#c8f54a" : "#e5484d"}" stroke-width="2.5" stroke-linejoin="round"/>
      <text x="${P}" y="${H - 8}">${esc(curve[0][0])}</text><text x="${W - P}" y="${H - 8}" text-anchor="end">${esc(curve[curve.length - 1][0])}</text>
      <text x="${P - 4}" y="${y(hi) + 4}" text-anchor="end">${hi.toFixed(0)}</text><text x="${P - 4}" y="${y(lo) + 4}" text-anchor="end">${lo.toFixed(0)}</text></svg>`;
  }
  const ll = bt.logloss_1x2;
  return `<div class="page-head"><div><h1>Track record</h1><p>Every past match (${bt.seasons.join(", ")}) re-predicted using only what was known before kick-off. This is how you tell whether the "value" flags are worth anything.</p></div></div>
    <div class="grid g2">
      <div class="card"><div class="card-h"><h3>Is the model honest?</h3><span class="pill">calibration</span></div><div class="card-b">
        <p class="note" style="margin-top:0">When the model says a market is, say, 70–80% likely, the blue bar shows how often it really happened. The dashed line is what the model predicted. Close together means you can trust the percentages.</p>
        ${bt.calibration.map((c) => `<div class="calib-row"><span class="sub">${c.range}</span><div class="calib-bar">${c.n ? `<div class="act" style="width:${c.actual * 100}%"></div><div class="pred" style="width:${c.predicted * 100}%"></div>` : ""}</div><span class="num">${c.n ? `${pct(c.actual, 1)} <span class="sub">of ${c.n}</span>` : "–"}</span></div>`).join("")}
      </div></div>
      <div class="card"><div class="card-h"><h3>Flagged value bets</h3><span class="pill">1 unit each</span></div><div class="card-b">
        <div class="acca-sum" style="margin-top:0;grid-template-columns:repeat(4,1fr)"><div class="kpi"><b>${b.count}</b><span>Bets</span></div><div class="kpi"><b>${b.count ? pct(b.won / b.count) : "–"}</b><span>Won</span></div>
          <div class="kpi"><b style="color:${b.profit >= 0 ? "var(--accent)" : "var(--loss)"}">${b.profit >= 0 ? "+" : ""}${fx2(b.profit, 1)}</b><span>Units</span></div><div class="kpi"><b>${b.roi == null ? "–" : (b.roi >= 0 ? "+" : "") + pct(b.roi, 1)}</b><span>ROI</span></div></div>
        ${svg}
        <div class="note">${Object.entries(b.by_market || {}).map(([k, s]) => `${esc(k)}: ${s.bets} bets, ${s.roi >= 0 ? "+" : ""}${pct(s.roi, 1)} ROI`).join(" · ")}</div>
      </div></div>
      <div class="card"><div class="card-h"><h3>Model vs bookmakers</h3><span class="pill">match result accuracy</span></div><div class="card-b">
        <p class="note" style="margin-top:0">Log loss scores how good the probabilities were (lower is better) over ${ll.matches} matches. Bookmaker odds are very hard to beat. If the model is close to the market, the blend usually does best, which is why value flags use it.</p>
        <div class="acca-sum" style="margin-top:0"><div class="kpi"><b>${ll.model}</b><span>Our model</span></div><div class="kpi"><b>${ll.market}</b><span>Bookmakers</span></div><div class="kpi"><b>${ll.blend}</b><span>50/50 blend</span></div></div>
      </div></div>
      <div class="card span-all"><div class="card-h"><h3>Latest flagged bets</h3></div><div class="tbl-wrap"><table><thead><tr><th class="l">Date</th><th class="l">Match</th><th>Pick</th><th>Price</th><th>Result</th></tr></thead><tbody>
        ${(b.recent || []).map((r) => `<tr><td class="l sub">${esc(r.date)}</td><td class="l">${esc(r.match)}</td><td>${esc(r.pick.replace("_", " "))}</td><td>${fx2(r.price)}</td><td style="color:${r.won ? "var(--win)" : "var(--loss)"}">${r.won ? "Won" : "Lost"}</td></tr>`).join("")}
      </tbody></table></div></div>
    </div>
    <p class="note">Over/under 2.5 goals edges are shown on match pages but never flagged as value, because in this test they lost about 7%. Past results use the pre-match prices published by football-data.co.uk. Those are early-week prices, which are softer than the closing line. Treat any profit here as encouraging, not proof.</p>${RG}`;
}

function pageAbout() {
  const s = DATA.sources || {};
  return `<div class="page-head"><div><h1>How it works</h1><p>Free data, transparent maths, refreshed automatically every few hours.</p></div></div>
  <div class="grid g2">
    <div class="card"><div class="card-h"><h3>Data</h3></div><div class="card-b">
      <p><b>ESPN</b>: fixtures, team crests and every player's match stats (minutes, shots, shots on target, fouls committed and won, cards, goals). ${s.player_matches ?? "–"} matches this season.</p>
      <p><b>football-data.co.uk</b>: team stats per match (shots, corners, fouls, cards, xG), referees, and bookmaker odds (Bet365, Betfair Exchange, Sky Bet, Paddy Power and others).</p>
      <p><b>Fantasy Premier League</b>: injury and suspension news ${s.fpl ? "(connected)" : "(not reachable on last run)"}.</p>
      <p><b>The Odds API</b> (optional, free key): more UK bookmaker prices ${s.odds_api ? "(connected)" : "(not set up)"}.</p>
    </div></div>
    <div class="card"><div class="card-h"><h3>The model</h3></div><div class="card-b">
      <p><b>Team markets.</b> Each team's attack and defence are rated against the league average for goals (blended with xG), shots, corners, fouls and cards. Small samples are pulled towards average, and a home-advantage factor is applied. Goals use a Poisson score grid with a Dixon-Coles low-score adjustment. Corners, cards and shots use a negative binomial, with the spread measured from the league.</p>
      <p><b>Referees.</b> Their card rate over five seasons scales card and foul predictions.</p>
      <p><b>Players.</b> Per-90 rates (stabilised with positional averages) × expected minutes × opponent and venue adjustment × referee factor. Doubtful players are scaled by the FPL chance of playing, and injured or suspended players are removed.</p>
      <p><b>Value.</b> Edge = blended probability × best price − 1, where blended is 50% model and 50% bookmaker consensus with the margin removed. Exchange prices are reduced for 5% commission.</p>
    </div></div>
  </div>
  <p class="note">Last updated ${new Date(DATA.generated).toLocaleString("en-GB")}. ${DATA.matches_played} league matches played this season.</p>${RG}`;
}

// ------------------------------------------------------------------ router
function route() {
  const [, page = "", id, tab] = location.hash.split("/");
  document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.r === (page || "fixtures") || (page === "match" && a.dataset.r === "fixtures")));
  const html = page === "match" ? pageMatch(id, tab) : page === "value" ? pageValue() : page === "accas" ? pageAccas() : page === "record" ? pageRecord() : page === "about" ? pageAbout() : pageFixtures();
  app.innerHTML = html;
  bind();
}

function bind() {
  app.querySelectorAll("[data-leg]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); toggleLeg(b.dataset.leg); }));
  app.querySelectorAll("[data-multi]").forEach((b) => (b.onclick = () => {
    let n = 0;
    for (const k of JSON.parse(b.dataset.multi)) if (!inSlip(k)) { const l = legByKey(k); if (l) { slip.push({ key: k, label: l.label, match: l.match, fx: l.fx, p: l.bp, odds: l.odds }); n++; } }
    saveSlip();
    toast(n ? `Added ${n} legs` : "Already in slip");
    openDrawer();
  }));
  app.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => {
    const [, , id] = location.hash.split("/");
    history.replaceState(null, "", `#/match/${id}/${b.dataset.tab}`);
    route();
  }));
  app.querySelectorAll("[data-showall]").forEach((b) => (b.onclick = () => { showAllPlayers = !showAllPlayers; route(); }));
  const legsR = $("#legsR"), minR = $("#minR");
  if (legsR) {
    legsR.oninput = () => { accaCfg.legs = +legsR.value; store.set("mde-acca", accaCfg); route(); };
    minR.onchange = () => { accaCfg.minP = +minR.value; store.set("mde-acca", accaCfg); route(); };
    minR.oninput = () => { $("#pv").textContent = pct(+minR.value); };
    app.querySelectorAll("[data-g]").forEach((c) => (c.onclick = () => {
      const g = c.dataset.g;
      accaCfg.groups = accaCfg.groups.includes(g) ? accaCfg.groups.filter((x) => x !== g) : [...accaCfg.groups, g];
      store.set("mde-acca", accaCfg);
      route();
    }));
  }
}

async function init() {
  $("#slipFab").onclick = openDrawer;
  $("#drawerBg").onclick = closeDrawer;
  renderSlipFab();
  try {
    const res = await fetch(`data/latest.json?t=${Math.floor(Date.now() / 600000)}`);
    if (!res.ok) throw new Error(res.status);
    DATA = await res.json();
  } catch (e) {
    app.innerHTML = `<div class="empty-state"><h2>Data not ready</h2><p>The first data refresh hasn't finished yet. Check back in a few minutes.</p></div>`;
    return;
  }
  LEGS = buildLegs();
  const ago = Math.round((Date.now() - new Date(DATA.generated)) / 3600000);
  $("#updated").textContent = `· updated ${ago < 1 ? "just now" : `${ago}h ago`}`;
  // drop slip legs from fixtures that no longer exist
  slip = slip.filter((s) => DATA.fixtures.some((f) => f.id === s.fx));
  saveSlip();
  window.addEventListener("hashchange", () => { route(); window.scrollTo(0, 0); });
  route();
}
init();
