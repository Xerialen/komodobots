#!/usr/bin/env python3
"""pov_fuse_render — fuse a player's POV frames with the parsed-demo state along one route leg.

Reads a leg bundle (komodobots.route_leg.v1, from pov_fuse_extract.py) + the POV frames dir,
and emits a single HTML contact sheet: one row per 1fps frame =
   [ POV image ] [ top-down route plot: path-so-far speed-coloured + view-arrow + velocity-arrow ]
   [ HUD: match_t / teamsay / hspeed / vz / look-vs-move / pos ]
Screenshot it with pov_fuse_shot.js. The fused state MUST match the POV pixels (eval-integrity):
render, then READ the PNG back and confirm coherence before reporting.

Usage: pov_fuse_render.py <leg.json> <frames_dir> <out.html>
"""
import logging
import json
import sys
import base64
import os
import html



LOGGER = logging.getLogger(__name__)
def js_embed(obj):
    """Serialize obj to JSON safe to drop inside an HTML <script> block.

    Escapes the characters that could close the script element or that JS
    treats as line terminators inside string literals, so demo/CLI-derived
    text cannot break out of the <script> context.
    """
    s = json.dumps(obj)
    return (s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
             .replace(" ", "\\u2028").replace(" ", "\\u2029"))

leg_path = sys.argv[1] if len(sys.argv) > 1 else "leg.json"
frames_dir = sys.argv[2] if len(sys.argv) > 2 else "."
out_html = sys.argv[3] if len(sys.argv) > 3 else "pov_fuse.html"

L = json.load(open(leg_path, encoding="utf-8"))
ticks, markers, teamsay, frames, sig = L["ticks"], L["markers"], L["teamsay"], L["frames"], L["signature"]


def img_data_uri(path):
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


rows = []
for fr in frames:
    if not fr["exists"]:
        continue
    s = fr["s"]
    ni = min(range(len(ticks)), key=lambda i: abs(ticks[i]["t"] - s))  # nearest tick to this second
    bind = None
    for tb in teamsay:
        if tb["t"] <= s + 0.001:
            bind = tb
    rows.append({"s": s, "uri": img_data_uri(os.path.join(frames_dir, fr["file"])),
                 "file": fr["file"], "ni": ni, "teamsay": (bind["text"] if bind else "")})

payload = {"ticks": ticks, "markers": markers, "rows": rows,
           "label": L["label"], "player": L["player"], "demo": L["demo"], "sig": sig}

HTML = """<!doctype html><html><head><meta charset=utf-8>
<style>
 body{margin:0;background:#0d1117;color:#e6edf3;font-family:Menlo,monospace}
 .hdr{padding:10px 16px;font-size:15px;border-bottom:1px solid #30363d}
 .hdr b{color:#ffb347}
 .sig{font-size:12px;color:#9aa7b3;padding:4px 16px 10px}
 .row{display:flex;align-items:center;gap:10px;border-bottom:1px solid #21262d;padding:8px 10px}
 .row img{width:580px;height:435px;object-fit:cover;background:#000;border:1px solid #30363d}
 .hud{width:300px;font-size:14px;line-height:1.6}
 .hud .t{color:#ffb347;font-size:15px;font-weight:bold}
 .hud .say{color:#7ee787}
 .hud .spd{color:#79c0ff}
 .lbl{color:#8b949e}
</style></head><body>
<div class=hdr><b>pov_fuse</b> &nbsp; __LABEL__ &nbsp;|&nbsp; __PLAYER__ &nbsp;|&nbsp; __DEMO__</div>
<div class=sig>signature: __SIGTXT__</div>
<div id=app></div>
<script>
const D = __DATA__;
const T = D.ticks, MK = D.markers;
let xs=T.map(t=>t.x).concat(MK.map(m=>m.x)), ys=T.map(t=>t.y).concat(MK.map(m=>m.y));
const minx=Math.min(...xs),maxx=Math.max(...xs),miny=Math.min(...ys),maxy=Math.max(...ys);
const CW=580,CH=435,pad=40;
const sc=Math.min((CW-2*pad)/(maxx-minx),(CH-2*pad)/(maxy-miny));
const cw=(maxx-minx)*sc, ch=(maxy-miny)*sc, ox=(CW-cw)/2, oy=(CH-ch)/2;
const X=x=>ox+(x-minx)*sc, Y=y=>CH-(oy+(y-miny)*sc);          // flip y for screen
function spdColor(h){ const f=Math.max(0,Math.min(1,h/650));   // blue->green->yellow->red
  const r=f<.5?Math.round(510*f):255, g=f<.5?255:Math.round(510*(1-f)), b=f<.33?Math.round(255*(1-3*f)):0;
  return `rgb(${r},${g},${b})`; }
function plot(cv, ni){
  const g=cv.getContext('2d'); g.clearRect(0,0,CW,CH);
  g.fillStyle='#05080d'; g.fillRect(0,0,CW,CH);
  MK.forEach(m=>{ g.beginPath(); g.arc(X(m.x),Y(m.y), m.res?4:2, 0,7);
    g.fillStyle=m.res?'#ffb347':'#2d3748'; g.fill();
    if(m.res){ g.fillStyle='#c9a26b'; g.font='10px monospace'; g.fillText(m.name, X(m.x)+5, Y(m.y)+3);} });
  g.lineWidth=1; g.strokeStyle='rgba(120,150,180,.18)';
  g.beginPath(); T.forEach((t,i)=>{ const fx=X(t.x),fy=Y(t.y); i?g.lineTo(fx,fy):g.moveTo(fx,fy);}); g.stroke();
  for(let i=1;i<=ni;i++){ g.strokeStyle=spdColor(T[i].hs); g.lineWidth=2.4;
    g.beginPath(); g.moveTo(X(T[i-1].x),Y(T[i-1].y)); g.lineTo(X(T[i].x),Y(T[i].y)); g.stroke(); }
  const c=T[ni], px=X(c.x), py=Y(c.y);
  if(c.mdir!==null){ const a=c.mdir*Math.PI/180, len=18+0.06*c.hs;
    arrow(g, px,py, px+len*Math.cos(a), py-len*Math.sin(a), '#ff9933', 2.4); }
  const ya=c.yaw*Math.PI/180, vl=26;
  arrow(g, px,py, px+vl*Math.cos(ya), py-vl*Math.sin(ya), '#22d3ee', 1.8);
  g.beginPath(); g.arc(px,py,4,0,7); g.fillStyle='#fff'; g.fill();
  g.font='10px monospace'; g.fillStyle='#22d3ee'; g.fillText('-> view', 6, CH-18);
  g.fillStyle='#ff9933'; g.fillText('-> velocity', 6, CH-6);
}
function arrow(g,x0,y0,x1,y1,col,w){ g.strokeStyle=col; g.fillStyle=col; g.lineWidth=w;
  g.beginPath(); g.moveTo(x0,y0); g.lineTo(x1,y1); g.stroke();
  const a=Math.atan2(y1-y0,x1-x0), h=6;
  g.beginPath(); g.moveTo(x1,y1); g.lineTo(x1-h*Math.cos(a-.4),y1-h*Math.sin(a-.4));
  g.lineTo(x1-h*Math.cos(a+.4),y1-h*Math.sin(a+.4)); g.closePath(); g.fill(); }
function lookmove(c){ if(c.mdir===null) return '-'; let d=((c.yaw-c.mdir+180)%360+360)%360-180; return Math.round(Math.abs(d)); }
const app=document.getElementById('app');
D.rows.forEach(r=>{
  const c=T[r.ni];
  const row=document.createElement('div'); row.className='row';
  const im=document.createElement('img'); im.src=r.uri;
  const cv=document.createElement('canvas'); cv.width=CW; cv.height=CH; cv.style.border='1px solid #30363d';
  const hud=document.createElement('div'); hud.className='hud';
  // numeric fields come from parsed-demo math; r.file and r.teamsay are demo/CLI-derived
  // strings, so they are inserted as text nodes (textContent) and never as markup.
  const tDiv=document.createElement('div'); tDiv.className='t';
  tDiv.append('match_t '+String(r.s)+'s ');
  const fileSpan=document.createElement('span'); fileSpan.className='lbl'; fileSpan.textContent=r.file;
  tDiv.appendChild(fileSpan);
  const sayDiv=document.createElement('div'); sayDiv.className='say'; sayDiv.textContent='"'+r.teamsay+'"';
  hud.appendChild(tDiv); hud.appendChild(sayDiv);
  hud.insertAdjacentHTML('beforeend',
    `<div class=spd>hspeed <b>${c.hs}</b> qu/s &nbsp; vz ${c.vz}</div>`+
    `<div><span class=lbl>look-vs-move</span> ${lookmove(c)} deg</div>`+
    `<div><span class=lbl>pos</span> ${Math.round(c.x)}, ${Math.round(c.y)}, ${Math.round(c.z)}</div>`+
    `<div><span class=lbl>view yaw</span> ${Math.round(c.yaw)} deg</div>`);
  row.appendChild(im); row.appendChild(cv); row.appendChild(hud); app.appendChild(row);
  plot(cv, r.ni);
});
document.title='READY';
</script></body></html>"""

sigtxt = (f"{sig['dur_s']}s · hspeed {sig['hs_min']}/{sig['hs_mean']}/{sig['hs_max']} (min/mean/max qu/s) · "
          f"{sig['jumps']} jumps · look-vs-move mean {sig['lookmove_mean_deg']} deg · "
          f"path {sig['path_qu']}qu straightness {sig['straightness']}")
# Substitute the header/sig placeholders first, then __DATA__ last, so a demo/CLI
# string that happens to contain a placeholder token cannot collide with the replaces.
doc = (HTML.replace("__LABEL__", html.escape(str(L["label"])))
           .replace("__PLAYER__", html.escape(str(L["player"])))
           .replace("__DEMO__", html.escape(str(L["demo"])))
           .replace("__SIGTXT__", html.escape(sigtxt))
           .replace("__DATA__", js_embed(payload)))
open(out_html, "w", encoding="utf-8").write(doc)
print(f"WROTE {out_html}  ({len(rows)} fused rows, {len(doc) // 1024} KB)")
