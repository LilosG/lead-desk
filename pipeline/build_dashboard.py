"""Build the Lead Desk dashboard in the Lilos Growth client-portal design language.

Visual reference is Mike's existing client portal: warm bone canvas, cream cards
with generous radii, one near-black card carrying the headline number, high-
contrast serif numerals, letterspaced uppercase micro-labels, gold and sage
accents, monospace for dense data lines, and pill toggles.
"""
from __future__ import annotations

import collections
import datetime
import json

rows = json.load(open("dashboard_data.json"))

sig = collections.Counter()
for r in rows:
    for f in r["f"]:
        sig[f["t"].split(".")[0][:60]] += 1
top_gaps = sig.most_common(6)
gmax = top_gaps[0][1] if top_gaps else 1

est_rows = [r for r in rows if r.get("est")]

S = {
    "total": len(rows),
    "A": sum(1 for r in rows if r["t"] == "A"),
    "B": sum(1 for r in rows if r["t"] == "B"),
    "C": sum(1 for r in rows if r["t"] == "C"),
    "D": sum(1 for r in rows if r["t"] == "D"),
    "em": sum(1 for r in rows if r["e"]),
    "nw": sum(1 for r in rows if not r["w"]),
    "ph": sum(1 for r in rows if r["p"] and not r["e"]),
    "real": sum(1 for r in rows if r["r"] >= 15),
    "avg": round(sum(r["s"] for r in rows) / len(rows)),
    "cities": len({r["c"] for r in rows if r["c"]}),
    "est": len(est_rows),
    "est_em": sum(1 for r in est_rows if r.get("e")),
    "est_ph": sum(1 for r in est_rows if r.get("p") and not r.get("e")),
    "live": sum(1 for r in rows if r.get("act") in ("active", "steady")),
    "miscat": sum(1 for r in rows if r.get("miscat")),
    "stale": sum(1 for r in rows if r.get("act") in ("stale", "no reviews")),
}

gapbars = "".join(
    f'<div class="bar"><div class="bl"><span>{g}</span><b>{n}</b></div>'
    f'<div class="btrack"><div class="bfill" style="width:{n / gmax * 100:.0f}%"></div></div></div>'
    for g, n in top_gaps
)

mix = "".join(
    f'<div class="mrow"><span class="mk"><i class="sw {k}"></i>Tier {k}</span>'
    f'<b>{S[k]}</b><span class="mp">{S[k] / S["total"] * 100:.0f}%</span></div>'
    for k in ("A", "B", "C", "D")
)

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lilos Growth — Lead Desk</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500;600&family=Poppins:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bone:#e8e4db; --card:#edeae2; --card-in:#e4e0d6; --dark:#16160f;
  --ink:#1c1b16; --mut:#8b8578; --faint:#a9a294; --line:#d9d4c8;
  --gold:#b8934e; --sage:#6f8f6a; --rust:#a8613f;
}
html{scroll-behavior:smooth}
body{background:var(--bone);color:var(--ink);
  font:400 14px/1.55 Poppins,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.serif{font-family:'Playfair Display',Georgia,serif}
.mono{font-family:'JetBrains Mono',monospace}
.lab{font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--mut);font-weight:500}

/* ---- header ---- */
header{position:sticky;top:0;z-index:60;background:rgba(232,228,219,.93);
  backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.hin{max-width:1560px;margin:0 auto;padding:16px 32px;display:grid;
  grid-template-columns:1fr auto 1fr;align-items:center;gap:20px}
.brand{font-weight:600;font-size:14px;letter-spacing:.13em;line-height:1.15}
.brand small{display:block;font-size:9.5px;letter-spacing:.19em;color:var(--mut);font-weight:400}
.htitle{font-size:14.5px;text-align:center;white-space:nowrap}
.pills{display:flex;gap:3px;justify-self:end;background:var(--card-in);
  padding:3px;border-radius:999px}
.pill{border:0;background:transparent;color:var(--mut);font:500 11px Poppins;
  letter-spacing:.05em;padding:7px 15px;border-radius:999px;cursor:pointer;transition:.15s}
.pill:hover{color:var(--ink)}
.pill.on{background:var(--dark);color:#f2efe7}

.wrap{max-width:1560px;margin:0 auto;padding:26px 32px 90px}
.crumb{font-size:11.5px;color:var(--faint);letter-spacing:.03em;margin-bottom:20px}

/* ---- summary cards ---- */
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin-bottom:20px}
.c{background:var(--card);border-radius:16px;padding:26px 26px 24px;position:relative}
.metric-card{cursor:pointer;transition:transform .15s ease,box-shadow .15s ease}
.metric-card:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(28,27,22,.08)}
.metric-card.on{box-shadow:0 0 0 2px var(--gold),0 8px 24px rgba(28,27,22,.08)}
.metric-card.dk.on{box-shadow:0 0 0 2px var(--gold),0 8px 24px rgba(0,0,0,.14)}
.metric-card:focus-visible{outline:2px solid var(--gold);outline-offset:3px}
.c.dk{background:var(--dark);color:#e9e5db}
.c .lab{margin-bottom:14px}
.c.dk .lab{color:#8f897b}
.big{font-size:58px;line-height:.94;font-weight:400;letter-spacing:-.02em}
.cap{font-size:13px;color:var(--mut);margin-top:9px}
.c.dk .cap{color:#9a9486}
.tag{position:absolute;top:22px;right:22px;background:var(--gold);color:#1c1b16;
  font:600 9px Poppins;letter-spacing:.13em;padding:5px 10px;border-radius:5px}
.crule{height:1px;background:var(--line);margin:20px 0 16px}
.c.dk .crule{background:#2e2e24}
.kv{display:grid;grid-template-columns:1fr 1fr;gap:14px 12px}
.kv .lab{margin:0 0 3px}
.kv b{font:500 17px 'JetBrains Mono',monospace;letter-spacing:-.01em}
.up{color:var(--sage);font-size:11.5px;margin-top:7px}

/* ---- layout ---- */
.grid{display:grid;grid-template-columns:1fr 340px;gap:18px;align-items:start}
.panel{background:var(--card);border-radius:16px;padding:24px 26px}
.ptitle{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:16px}

/* ---- filters ---- */
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:18px}
.f{border:1px solid var(--line);background:transparent;color:var(--mut);
  font:400 12px Poppins;padding:7px 15px;border-radius:999px;cursor:pointer;transition:.15s}
.f:hover{border-color:var(--faint);color:var(--ink)}
.f.on{background:var(--dark);border-color:var(--dark);color:#f2efe7;font-weight:500}
input[type=search],select{background:transparent;border:1px solid var(--line);
  color:var(--ink);font:400 12.5px Poppins;padding:7px 13px;border-radius:999px}
input[type=search]{width:210px}
input[type=search]:focus,select:focus{outline:none;border-color:var(--gold)}
.summ{font:400 12px 'JetBrains Mono',monospace;color:var(--mut);margin-bottom:6px}

/* ---- lead rows ---- */
.hd{display:grid;grid-template-columns:1fr 88px 74px 62px;gap:14px;padding:0 4px 10px;
  border-bottom:1px solid var(--line)}
.hd span{font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
.hd span:not(:first-child){text-align:right}
.row{display:grid;grid-template-columns:1fr 88px 74px 62px;gap:14px;padding:14px 4px;
  border-bottom:1px solid var(--line);cursor:pointer;transition:.12s;align-items:center}
.row:hover{background:var(--card-in)}
.rn{font-size:14.5px;font-weight:400}
.rm{font-size:11.5px;color:var(--faint);margin-top:3px;display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.rm em{font-style:normal}
.chip{font-size:9.5px;letter-spacing:.05em;padding:2px 7px;border-radius:4px;
  background:var(--card-in);color:var(--mut);text-transform:uppercase}
.chip.bad{background:rgba(168,97,63,.14);color:var(--rust)}
.chip.warn{background:rgba(184,147,78,.18);color:#8a6c33}
.chip.live{background:rgba(111,143,106,.18);color:#4f6b4b}
.num{text-align:right;font:400 13px 'JetBrains Mono',monospace;color:var(--mut)}
.badge{justify-self:end;font:500 12px 'JetBrains Mono',monospace;padding:5px 11px;
  border-radius:6px;min-width:52px;text-align:center}
.bA{background:var(--gold);color:#1c1b16}
.bB{background:var(--dark);color:#efece4}
.bC{background:var(--card-in);color:var(--mut)}
.bD{background:transparent;color:var(--faint);border:1px solid var(--line)}

.det{grid-column:1/-1;display:none;padding:18px 2px 8px}
.row.open .det{display:block}
.row.open{background:var(--card-in)}
.dgrid{display:grid;grid-template-columns:1fr 260px;gap:26px}
.find{display:flex;gap:10px;padding:6px 0;font-size:13px;color:#4a463c;line-height:1.5}
.sev{width:5px;height:5px;border-radius:50%;margin-top:8px;flex:0 0 5px;background:var(--faint)}
.sev.critical{background:var(--rust)} .sev.high{background:var(--gold)}
.sev.medium{background:#a39a84}
.acts{display:flex;flex-direction:column;gap:7px}
.act{display:block;background:var(--bone);border:1px solid var(--line);border-radius:8px;
  padding:9px 13px;font-size:12.5px;color:var(--ink);text-decoration:none;transition:.15s}
.act:hover{border-color:var(--gold);color:#8a6c33}
.act b{font-weight:500}
.act small{display:block;color:var(--faint);font-size:10.5px;letter-spacing:.03em}
.noc{font-size:12px;color:var(--faint);font-style:italic}
.addr{font-size:11.5px;color:var(--faint);margin-top:12px}

/* ---- sidebar ---- */
.side{display:flex;flex-direction:column;gap:18px;position:sticky;top:88px}
.mrow{display:grid;grid-template-columns:1fr auto 46px;align-items:center;gap:10px;
  padding:11px 0;border-bottom:1px solid var(--line);font-size:13px}
.mrow:last-child{border:0}
.mk{display:flex;align-items:center;gap:9px;color:#4a463c}
.sw{width:9px;height:9px;border-radius:2px;display:inline-block}
.sw.A{background:var(--gold)} .sw.B{background:var(--dark)}
.sw.C{background:#bdb6a4} .sw.D{background:var(--line)}
.mrow b{font:500 15px 'JetBrains Mono',monospace}
.mp{text-align:right;font-size:11.5px;color:var(--faint)}
.bar{margin-bottom:14px}
.bl{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:6px}
.bl span{font-size:12px;color:#4a463c;line-height:1.35}
.bl b{font:500 12px 'JetBrains Mono',monospace;color:var(--mut);flex:0 0 auto}
.btrack{height:5px;background:var(--card-in);border-radius:3px;overflow:hidden}
.bfill{height:100%;background:var(--gold);border-radius:3px}
.note{font-size:11.5px;color:var(--faint);line-height:1.6;margin-top:4px}
.empty{padding:60px 10px;text-align:center;color:var(--faint)}
@media(max-width:1200px){.cards{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}
  .side{position:static}}
@media(max-width:720px){.hin{grid-template-columns:1fr}.htitle,.pills{justify-self:start}
  .cards{grid-template-columns:1fr}.hd,.row{grid-template-columns:1fr 60px 56px}
  .hd span:nth-child(2),.row .num:nth-of-type(1){display:none}.dgrid{grid-template-columns:1fr}}
</style></head><body>

<header><div class="hin">
  <div class="brand">LILOS GROWTH<small>LEAD DESK</small></div>
  <div class="htitle">San Diego County &middot; Electricians</div>
  <div class="pills">
    <button class="pill on" data-v="est">ESTABLISHED</button>
    <button class="pill" data-v="all">ALL</button>
    <button class="pill" data-v="call">CALL</button>
    <button class="pill" data-v="email">EMAIL</button>
  </div>
</div></header>

<div class="wrap">
<div class="crumb">Google Business Profiles &middot; website audits &middot; PageSpeed &middot; scored __DATE__</div>

<div class="cards">
  <div class="c metric-card" data-card="all" role="button" tabindex="0" aria-pressed="false"><div class="lab">Prospects surveyed</div>
    <div class="big serif">__TOTAL__</div><div class="cap">across __CITIES__ cities</div>
    <div class="crule"></div>
    <div class="kv"><div><div class="lab">With email</div><b>__EM__</b></div>
      <div><div class="lab">Phone only</div><b>__PH__</b></div></div></div>

  <div class="c metric-card" data-card="live" role="button" tabindex="0" aria-pressed="false"><div class="lab">Confirmed trading</div>
    <div class="big serif">__LIVE__</div><div class="cap">reviewed within the last year</div>
    <div class="crule"></div>
    <div class="kv"><div><div class="lab">Looks stale</div><b>__STALE__</b></div>
      <div><div class="lab">No website</div><b>__NW__</b></div></div></div>

  <div class="c metric-card" data-card="miscat" role="button" tabindex="0" aria-pressed="false"><div class="lab">Wrong Google category</div>
    <div class="big serif">__MISCAT__</div><div class="cap">15-minute fix, big ranking lever</div>
    <div class="crule"></div>
    <div class="kv"><div><div class="lab">Avg score</div><b>__AVG__</b></div>
      <div><div class="lab">Tier A</div><b>__TA__</b></div></div></div>

  <div class="c dk metric-card" data-card="est" role="button" tabindex="0" aria-pressed="true"><span class="tag">WORK FIRST</span>
    <div class="lab">Established &amp; neglected</div>
    <div class="big serif">__EST__</div>
    <div class="cap">trading, at/above local median reviews, 2+ real gaps</div>
    <div class="up">the segment most able to pay</div>
    <div class="crule"></div>
    <div class="kv"><div><div class="lab">Emailable</div><b>__EST_EM__</b></div>
      <div><div class="lab">Phone only</div><b>__EST_PH__</b></div></div></div>
</div>

<div class="grid">
  <div class="panel">
    <div class="ptitle"><div class="lab">Prospect list</div>
      <div class="summ" id="summ"></div></div>
    <div class="filters">
      <input type="search" id="q" placeholder="Search name or city">
      <button class="f" data-f="live">Trading now</button>
      <button class="f" data-f="miscat">Wrong category</button>
      <button class="f" data-f="nosite">No website</button>
      <button class="f" data-f="email">Has email</button>
      <button class="f" data-f="slow">Slow mobile</button>
      <button class="f" data-f="A">Tier A</button>
      <select id="city"></select>
      <select id="sort">
        <option value="s">Score</option><option value="r">Reviews</option>
        <option value="lrd">Most recently active</option>
        <option value="n">Name</option></select>
    </div>
    <div class="hd"><span>Business</span><span>Reviews</span><span>Mobile</span><span>Score</span></div>
    <div id="list"></div>
  </div>

  <div class="side">
    <div class="panel"><div class="lab" style="margin-bottom:6px">Pipeline mix</div>
      __MIX__
      <div class="note">Tier reflects opportunity size discounted by how reachable the
        business is. A lead you cannot contact is not a lead.</div></div>

    <div class="panel"><div class="lab" style="margin-bottom:16px">Most common gaps</div>
      __GAPS__</div>

    <div class="panel"><div class="lab" style="margin-bottom:10px">Read this first</div>
      <div class="note"><b>Established</b> = reviewed recently, review count at or above
        the local median, and two or more real gaps. That is the segment most able to
        pay you, and it is the default view.<br><br>
        Score still ranks by gap SIZE, so no-website micro-businesses sit at the top of
        <b>All</b>. Whether that or Established should lead is a revenue judgment, not a
        modelling one.<br><br>
        Review recency comes from the 5 reviews Google samples by relevance, not
        recency — so "active" is reliable, "no recent reviews" is only a hint.</div></div>
  </div>
</div>
</div>

<script>
const D=__DATA__;
const F=new Set(); let CITY='',SORT='s',Q='',VIEW='est';
const esc=s=>(s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const cities=[...new Set(D.map(d=>d.c).filter(Boolean))].sort();
document.getElementById('city').innerHTML='<option value="">All cities</option>'+
  cities.map(c=>`<option>${esc(c)}</option>`).join('');

function match(d){
  if(VIEW==='est'&&!d.est)return false;
  if(VIEW==='call'&&(d.e||!d.p))return false;
  if(VIEW==='email'&&!d.e)return false;
  if(Q&&!(d.n+' '+d.c).toLowerCase().includes(Q.toLowerCase()))return false;
  if(CITY&&d.c!==CITY)return false;
  for(const f of F){
    if(f==='A'&&d.t!=='A')return false;
    if(f==='live'&&!(d.act==='active'||d.act==='steady'))return false;
    if(f==='miscat'&&!d.miscat)return false;
    if(f==='nosite'&&d.w)return false;
    if(f==='email'&&!d.e)return false;
    if(f==='slow'&&!(d.psi!=null&&d.psi<50))return false;
  }
  return true;
}
function row(d){
  const chips=[];
  if(!d.w)chips.push('<span class="chip bad">no website</span>');
  if(d.cms)chips.push(`<span class="chip">${esc(d.cms)}</span>`);
  if(d.blocked)chips.push('<span class="chip warn">verify by hand</span>');
  if(d.miscat)chips.push(`<span class="chip warn">category: ${esc(d.cat||'').replace(/_/g,' ')}</span>`);
  if(d.act==='active')chips.push(`<span class="chip live">active ${d.lrd}d</span>`);
  else if(d.act==='steady')chips.push(`<span class="chip">reviewed ${d.lrd}d ago</span>`);
  else if(d.act==='stale')chips.push('<span class="chip">no recent reviews</span>');
  else if(d.act==='no reviews')chips.push('<span class="chip">no reviews</span>');
  return `<div class="row" onclick="this.classList.toggle('open')">
    <div><div class="rn">${esc(d.n)}</div>
      <div class="rm"><em>${esc(d.c)||'—'}</em>${d.g?`<em>&middot; ${d.g}★</em>`:''}${chips.join('')}</div></div>
    <div class="num">${d.r}</div>
    <div class="num">${d.psi!=null?d.psi:'—'}</div>
    <div class="badge b${d.t}">${d.s}</div>
    <div class="det"><div class="dgrid">
      <div><div class="lab" style="margin-bottom:9px">What to fix</div>
        ${d.f.map(f=>`<div class="find"><span class="sev ${f.s}"></span><span>${esc(f.t)}</span></div>`).join('')
          ||'<div class="noc">No findings recorded.</div>'}
        ${d.a?`<div class="addr">${esc(d.a)}</div>`:''}</div>
      <div><div class="lab" style="margin-bottom:9px">Reach out</div><div class="acts">
        ${d.p?`<a class="act" href="tel:${esc(d.p)}" onclick="event.stopPropagation()"><b>${esc(d.p)}</b><small>CALL</small></a>`:''}
        ${d.e?`<a class="act" href="mailto:${esc(d.e)}" onclick="event.stopPropagation()"><b>${esc(d.e)}</b><small>EMAIL</small></a>`
             :'<div class="noc">No email found — call instead.</div>'}
        ${d.w?`<a class="act" href="${esc(d.w)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()"><b>Open website</b><small>NEW TAB</small></a>`:''}
        ${d.m?`<a class="act" href="${esc(d.m)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()"><b>Google profile</b><small>NEW TAB</small></a>`:''}
      </div></div></div></div></div>`;
}
function render(){
  syncFilterButtons();
  syncMetricCards();

  let r=D.filter(match);
  r.sort((a,b)=>SORT==='n'?a.n.localeCompare(b.n):SORT==='r'?b.r-a.r
    :SORT==='lrd'?((a.lrd==null?9e9:a.lrd)-(b.lrd==null?9e9:b.lrd)):(b.s-a.s)||(b.r-a.r));
  document.getElementById('summ').textContent=
    `${r.length} shown · ${r.filter(x=>x.e).length} emailable · ${r.filter(x=>x.act==='active'||x.act==='steady').length} confirmed trading`;
  document.getElementById('list').innerHTML=r.length?r.map(row).join('')
    :'<div class="empty">No prospects match those filters.</div>';
}
document.getElementById('q').oninput=e=>{Q=e.target.value;render()};
document.getElementById('city').onchange=e=>{CITY=e.target.value;render()};
document.getElementById('sort').onchange=e=>{SORT=e.target.value;render()};
function syncFilterButtons(){
  document.querySelectorAll('.f').forEach(btn=>{
    btn.classList.toggle('on',F.has(btn.dataset.f));
  });
}

function syncMetricCards(){
  document.querySelectorAll('.metric-card').forEach(card=>{
    let active=false;

    if(card.dataset.card==='all'){
      active=VIEW==='all' && F.size===0;
    }else if(card.dataset.card==='est'){
      active=VIEW==='est' && F.size===0;
    }else if(card.dataset.card==='live'){
      active=VIEW==='all' && F.size===1 && F.has('live');
    }else if(card.dataset.card==='miscat'){
      active=VIEW==='all' && F.size===1 && F.has('miscat');
    }

    card.classList.toggle('on',active);
    card.setAttribute('aria-pressed',active?'true':'false');
  });
}

function setView(view){
  VIEW=view;
  document.querySelectorAll('.pill').forEach(btn=>{
    btn.classList.toggle('on',btn.dataset.v===view);
  });
}

function clearWorkspaceFilters(){
  F.clear();
  CITY='';
  Q='';
  document.getElementById('q').value='';
  document.getElementById('city').value='';
  syncFilterButtons();
}

function activateMetricCard(card){
  clearWorkspaceFilters();

  if(card.dataset.card==='all'){
    setView('all');
  }else if(card.dataset.card==='est'){
    setView('est');
  }else if(card.dataset.card==='live'){
    setView('all');
    F.add('live');
  }else if(card.dataset.card==='miscat'){
    setView('all');
    F.add('miscat');
  }

  render();
}

document.addEventListener('keydown',e=>{
  const card=e.target.closest('.metric-card');
  if(card && (e.key==='Enter' || e.key===' ')){
    e.preventDefault();
    activateMetricCard(card);
  }
});

document.addEventListener('click',e=>{
  const card=e.target.closest('.metric-card');
  if(card){
    activateMetricCard(card);
    return;
  }

  const filter=e.target.closest('.f');
  if(filter){
    const f=filter.dataset.f;
    F.has(f)?F.delete(f):F.add(f);
    syncFilterButtons();
    render();
    return;
  }

  const pill=e.target.closest('.pill');
  if(pill){
    setView(pill.dataset.v);
    render();
  }
});
render();
</script></body></html>"""

out = (HTML
   .replace("__DATA__", json.dumps(rows, separators=(",", ":")))
   .replace("__TOTAL__", str(S["total"])).replace("__CITIES__", str(S["cities"]))
   .replace("__EM__", str(S["em"])).replace("__PH__", str(S["ph"]))
   .replace("__EST_EM__", str(S["est_em"])).replace("__EST_PH__", str(S["est_ph"]))
   .replace("__NW__", str(S["nw"])).replace("__AVG__", str(S["avg"]))
   .replace("__REAL__", str(S["real"])).replace("__TA__", str(S["A"]))
   .replace("__TB__", str(S["B"])).replace("__TC__", str(S["C"]))
   .replace("__APCT__", f'{S["A"] / S["total"] * 100:.0f}')
   .replace("__MIX__", "".join(
       f'<div class="mrow"><span class="mk"><i class="sw {k}"></i>Tier {k}</span>'
       f'<b>{S[k]}</b><span class="mp">{S[k] / S["total"] * 100:.0f}%</span></div>'
       for k in ("A", "B", "C", "D")))
   .replace("__GAPS__", gapbars)
   .replace("__EST__", str(S["est"])).replace("__LIVE__", str(S["live"]))
   .replace("__MISCAT__", str(S["miscat"])).replace("__STALE__", str(S["stale"]))
   .replace("__DATE__", datetime.date.today().strftime("%b %d, %Y")))

open("dashboard.html", "w").write(out)
print("bytes", len(out), "| leads", S["total"], "| A", S["A"], "| qualified", S["real"])
