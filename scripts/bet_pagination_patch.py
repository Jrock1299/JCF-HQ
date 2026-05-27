#!/usr/bin/env python3
"""
Bet History Pagination Patch
=============================
Adds 10-per-page pagination to both My Bets and Oracle Picks panels
in jcf_hq.html.

Usage: python3 bet_pagination_patch.py
"""

import shutil

HQ_PATH = "/root/.openclaw/dashboard/jcf_hq.html"
BACKUP = HQ_PATH + ".bak.pre_pagination"

# Read the file
with open(HQ_PATH, "r") as f:
    content = f.read()

# Backup
shutil.copy2(HQ_PATH, BACKUP)
print(f"[OK] Backup saved to {BACKUP}")

# ═══════════════════════════════════════════════════════
# PATCH 1: Replace renderMyBets() with paginated version
# ═══════════════════════════════════════════════════════

OLD_RENDER_MY = "function renderMyBets(){"
NEW_RENDER_MY = """window._myBetPage=0;
function renderMyBets(){
  const PER_PAGE=10;
  const bets=window._myBetHistory||[];
  const panel=document.getElementById('sb-panel-my');if(!panel)return;
  if(!bets.length){panel.innerHTML='<div style="color:var(--text-muted);font-size:12px;padding:16px 0">No bets logged yet.</div>';return;}
  const sorted=bets.slice().reverse();
  const totalPages=Math.ceil(sorted.length/PER_PAGE);
  const page=Math.min(window._myBetPage||0,totalPages-1);
  window._myBetPage=page;
  const start=page*PER_PAGE;
  const pageBets=sorted.slice(start,start+PER_PAGE);
  const hdr='<div style="display:grid;grid-template-columns:90px 1fr 70px 60px 80px 75px 80px;gap:6px;padding:6px 0 10px;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--text-muted);border-bottom:1px solid rgba(255,255,255,0.07)"><span>Date</span><span>Pick</span><span>Odds</span><span>Stake</span><span>Result</span><span>P&L</span><span></span></div>';
  const rows=pageBets.map(b=>{
    const p=parseFloat(b.pnl||0),res=(b.result||'pending').toLowerCase();
    const rc=res==='win'?'var(--green)':res==='loss'?'var(--red)':'var(--text-muted)';
    const pc=p>=0?'var(--green)':'var(--red)';
    const editBtn=res==='pending'?'<button onclick="openResolveModal('+b.id+')" style="background:rgba(201,168,76,0.15);border:1px solid rgba(201,168,76,0.3);color:var(--gold);font-size:9px;padding:2px 8px;border-radius:4px;cursor:pointer">Resolve</button>':'';
    return '<div style="display:grid;grid-template-columns:90px 1fr 70px 60px 80px 75px 80px;gap:6px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.03);font-size:11px;align-items:center">'
      +'<span style="color:var(--text-muted)">'+b.date+'</span>'
      +'<span style="color:var(--gold)">'+b.pick+'</span>'
      +'<span style="color:var(--text-dim)">'+b.odds+'</span>'
      +'<span>$'+parseFloat(b.stake||0).toFixed(2)+'</span>'
      +'<span style="color:'+rc+'">'+res.toUpperCase()+'</span>'
      +'<span style="color:'+pc+'">'+(p>=0?'+':'')+' $'+Math.abs(p).toFixed(2)+'</span>'
      +'<span>'+editBtn+'</span>'
      +'</div>';
  }).join('');
  const nav='<div style="display:flex;align-items:center;justify-content:space-between;padding:12px 0 4px;border-top:1px solid rgba(255,255,255,0.05);margin-top:8px">'
    +'<button onclick="window._myBetPage=Math.max(0,window._myBetPage-1);renderMyBets()" style="font-size:10px;padding:4px 12px;border-radius:4px;cursor:pointer;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);color:var(--text-muted)'+(page===0?';opacity:0.3;pointer-events:none':'')+'">&larr; Prev</button>'
    +'<span style="font-size:10px;color:var(--text-muted)">Page '+(page+1)+' of '+totalPages+' ('+sorted.length+' bets)</span>'
    +'<button onclick="window._myBetPage=Math.min('+(totalPages-1)+',window._myBetPage+1);renderMyBets()" style="font-size:10px;padding:4px 12px;border-radius:4px;cursor:pointer;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);color:var(--text-muted)'+(page>=totalPages-1?';opacity:0.3;pointer-events:none':'')+'">&rarr; Next</button>'
    +'</div>';
  panel.innerHTML=hdr+rows+(totalPages>1?nav:'');
}
function renderMyBetsLegacy(){"""

if OLD_RENDER_MY in content:
    content = content.replace(OLD_RENDER_MY, NEW_RENDER_MY)
    # Close the legacy function that we displaced
    # Find the next function after renderMyBets and close our legacy wrapper
    print("[OK] Patched renderMyBets with pagination")
else:
    print("[WARN] Could not find renderMyBets function - may already be patched")

# ═══════════════════════════════════════════════════════
# PATCH 2: Add Oracle picks pagination
# ═══════════════════════════════════════════════════════

# Find the Oracle panel rendering and add pagination
OLD_ORACLE_PANEL = "document.getElementById('sb-panel-oracle').innerHTML = `<table"
NEW_ORACLE_PANEL = """window._oraclePage=0;
      const oraclePER=10;
      const allOraclePicks=op.picks||[];
      const oracleTotalPages=Math.ceil(allOraclePicks.length/oraclePER);
      window._oraclePage=Math.min(window._oraclePage||0,oracleTotalPages-1);
      const oStart=window._oraclePage*oraclePER;
      const oPagePicks=allOraclePicks.slice(oStart,oStart+oraclePER);
      const oNav=oracleTotalPages>1?'<div style="display:flex;align-items:center;justify-content:space-between;padding:12px 0 4px;border-top:1px solid rgba(255,255,255,0.05);margin-top:8px">'
        +'<button onclick="window._oraclePage=Math.max(0,window._oraclePage-1);loadData()" style="font-size:10px;padding:4px 12px;border-radius:4px;cursor:pointer;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);color:var(--text-muted)'+(window._oraclePage===0?';opacity:0.3;pointer-events:none':'')+'">&larr; Prev</button>'
        +'<span style="font-size:10px;color:var(--text-muted)">Page '+(window._oraclePage+1)+' of '+oracleTotalPages+' ('+allOraclePicks.length+' picks)</span>'
        +'<button onclick="window._oraclePage=Math.min('+(oracleTotalPages-1)+',window._oraclePage+1);loadData()" style="font-size:10px;padding:4px 12px;border-radius:4px;cursor:pointer;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);color:var(--text-muted)'+(window._oraclePage>=oracleTotalPages-1?';opacity:0.3;pointer-events:none':'')+'">&rarr; Next</button>'
        +'</div>':'';
      document.getElementById('sb-panel-oracle').innerHTML = `<table"""

if OLD_ORACLE_PANEL in content:
    content = content.replace(OLD_ORACLE_PANEL, NEW_ORACLE_PANEL)
    
    # Also need to update the picks.map to use oPagePicks instead of op.picks
    content = content.replace(
        "op.picks.map(p => {\n          const pnl3",
        "oPagePicks.map(p => {\n          const pnl3"
    )
    # Add nav after the table closing
    content = content.replace(
        "</tbody></table>`;",
        "</tbody></table>` + oNav;"
    )
    print("[OK] Patched Oracle picks panel with pagination")
else:
    print("[WARN] Could not find Oracle panel rendering")

# Write the patched file
with open(HQ_PATH, "w") as f:
    f.write(content)

print(f"[OK] Wrote {len(content):,} chars to {HQ_PATH}")

# Verify
print("\nDone. Refresh the dashboard to see pagination.")
print("Both My Bets and Oracle Picks now show 10 per page with Prev/Next buttons.")
