#!/usr/bin/env python3
"""Extract a clean per-frame feature table + per-facet aggregations from a human
bunnyhop .cmds trace, for the multi-modal control-law sweep. Stdlib only.

.cmds cols: msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons   (fps 77)
hspeed=hypot(vx,vy); view_yaw=col8; sidemove=col11; fwd=col10; jump=buttons&2.

Outputs (to the same dir):
  <name>_features.json  per-frame table (rounded)
  <name>_summary.json   per-facet aggregations (A yaw-rate/speed, B strafe-switch,
                        C jump cadence, D straight/turn segments, E look-vs-move)
"""
import logging
import json, math, os, sys


LOGGER = logging.getLogger(__name__)
JUMP_BIT = 2

def load(path):
    fr = []
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            if len(p) < 14:
                continue
            fr.append([float(x) for x in p[:13]] + [int(float(p[13]))])
    return fr

def wrap180(d):
    while d > 180: d -= 360
    while d < -180: d += 360
    return d

def pctl(vals, p):
    v = sorted(x for x in vals if x is not None)
    if not v: return None
    return round(v[min(len(v)-1, int(p/100.0*(len(v)-1)))], 3)

def build(fr):
    n = len(fr)
    t = [0.0]*n; hs=[0.0]*n; vhead=[None]*n; vyaw=[0.0]*n; lvm=[None]*n
    side=[0.0]*n; ssign=[0]*n; fwd=[0.0]*n; jump=[0]*n; vz=[0.0]*n
    dist=[0.0]*n
    tc=0.0
    for i,f in enumerate(fr):
        if i>0:
            tc += f[0]/1000.0
            dx=f[1]-fr[i-1][1]; dy=f[2]-fr[i-1][2]
            dist[i]=dist[i-1]+math.hypot(dx,dy)
        t[i]=tc
        hs[i]=math.hypot(f[4],f[5])
        vyaw[i]=f[8]
        side[i]=f[11]; fwd[i]=f[10]; vz[i]=f[6]
        jump[i]=1 if (f[13]&JUMP_BIT) else 0
        ssign[i]= 1 if f[11]>50 else (-1 if f[11]<-50 else 0)
        if hs[i]>=80:
            vhead[i]=math.degrees(math.atan2(f[5],f[4]))
            lvm[i]=wrap180(f[8]-vhead[i])
    # view-yaw rate (deg/s), central diff on unwrapped view yaw
    uy=[0.0]*n; uy[0]=vyaw[0]
    for i in range(1,n):
        uy[i]=uy[i-1]+wrap180(vyaw[i]-vyaw[i-1])
    vyaw_rate=[0.0]*n
    for i in range(1,n-1):
        dt=t[i+1]-t[i-1]
        vyaw_rate[i]=(uy[i+1]-uy[i-1])/dt if dt>0 else 0.0
    # velocity-heading rate (deg/s)
    uh=[None]*n; last=None
    for i in range(n):
        if vhead[i] is None:
            uh[i]=last; continue
        uh[i]= vhead[i] if last is None else last+wrap180(vhead[i]-last)
        last=uh[i]
    vhead_rate=[0.0]*n
    for i in range(1,n-1):
        if uh[i-1] is None or uh[i+1] is None: continue
        dt=t[i+1]-t[i-1]
        vhead_rate[i]=(uh[i+1]-uh[i-1])/dt if dt>0 else 0.0
    return dict(t=t,hs=hs,vhead=vhead,vyaw=vyaw,vyaw_rate=vyaw_rate,
               vhead_rate=vhead_rate,lvm=lvm,side=side,ssign=ssign,fwd=fwd,
               jump=jump,vz=vz,dist=dist)

def classify_phase(d, half_w=0.30, turn_thresh=80.0, warm=400.0):
    """straight/turn per-frame via windowed NET velocity-heading rate."""
    t=d["t"]; hs=d["hs"]; uh=[None]*len(t)
    last=None
    for i,h in enumerate(d["vhead"]):
        if h is None: uh[i]=last; continue
        uh[i]=h if last is None else last+wrap180(h-last); last=uh[i]
    n=len(t); lab=[None]*n
    for i in range(n):
        if uh[i] is None or hs[i]<warm: continue
        lo=i
        while lo>0 and t[i]-t[lo]<half_w: lo-=1
        hi=i
        while hi<n-1 and t[hi]-t[i]<half_w: hi+=1
        if uh[lo] is None or uh[hi] is None or t[hi]-t[lo]<=0:
            lab[i]="straight"; continue
        rate=abs((uh[hi]-uh[lo])/(t[hi]-t[lo]))
        lab[i]="turn" if rate>=turn_thresh else "straight"
    return lab

def facet_yawrate(d, lab):
    out={"straight":{}, "turn":{}, "all":{}}
    bins=list(range(0,1100,100))
    for ph in ("straight","turn","all"):
        for b in bins:
            vy=[]; vh=[]
            for i in range(len(d["t"])):
                if d["hs"][i]<b or d["hs"][i]>=b+100: continue
                if ph!="all" and lab[i]!=ph: continue
                vy.append(abs(d["vyaw_rate"][i])); vh.append(abs(d["vhead_rate"][i]))
            if len(vy)>=3:
                out[ph][f"{b}-{b+100}"]={"n":len(vy),
                    "view_yawrate_med":pctl(vy,50),"view_yawrate_p90":pctl(vy,90),
                    "vel_headrate_med":pctl(vh,50)}
    return out

def facet_strafe(d):
    flips=[]; last_sign=0; last_t=None
    for i in range(len(d["t"])):
        s=d["ssign"][i]
        if s==0: continue
        if last_sign!=0 and s!=last_sign and last_t is not None:
            flips.append(round(d["t"][i]-last_t,3)); last_t=d["t"][i]
        elif last_sign==0:
            last_t=d["t"][i]
        last_sign=s
    nonzero=sum(1 for s in d["ssign"] if s!=0)
    return {"n_flips":len(flips),"interval_med_s":pctl(flips,50),
            "interval_p10_s":pctl(flips,10),"interval_p90_s":pctl(flips,90),
            "intervals_s":flips[:60],
            "sidemove_active_frac":round(nonzero/len(d["ssign"]),3),
            "sidemove_abs_typical":pctl([abs(x) for x in d["side"] if abs(x)>50],50)}

def facet_jump(d):
    edges=[]
    for i in range(1,len(d["t"])):
        if d["jump"][i]==1 and d["jump"][i-1]==0:
            edges.append(d["t"][i])
    periods=[round(edges[i]-edges[i-1],3) for i in range(1,len(edges))]
    return {"n_jump_presses":len(edges),"hop_period_med_s":pctl(periods,50),
            "hop_period_p10_s":pctl(periods,10),"hop_period_p90_s":pctl(periods,90),
            "periods_s":periods[:60],
            "jump_duty_frac":round(sum(d["jump"])/len(d["jump"]),3)}

def facet_segments(d, lab):
    # merge runs of equal label (>=warm) into segments
    segs=[]; i=0; n=len(lab)
    while i<n:
        if lab[i] is None: i+=1; continue
        j=i
        while j+1<n and lab[j+1]==lab[i]: j+=1
        segs.append((i,j,lab[i])); i=j+1
    # absorb sub-0.12s blips into previous
    merged=[]
    for s in segs:
        dur=d["t"][s[1]]-d["t"][s[0]]
        if merged and dur<0.12 and merged[-1][2]!=s[2]:
            merged[-1]=(merged[-1][0],s[1],merged[-1][2])
        else:
            merged.append(list(s))
    straights=[]; turns=[]
    for a,b,l in merged:
        entry=d["hs"][a]; ex=d["hs"][b]; seg=d["hs"][a:b+1]
        rec={"t0":round(d["t"][a],2),"dur_s":round(d["t"][b]-d["t"][a],3),
             "entry":round(entry),"exit":round(ex),"peak":round(max(seg)),
             "run_qu":round(d["dist"][b]-d["dist"][a])}
        if l=="straight":
            dx=d["dist"][b]-d["dist"][a]
            rec["dvdx"]=round((ex-entry)/dx,4) if dx>5 else None
            straights.append(rec)
        else:
            uh0=d["vhead"][a]; uh1=d["vhead"][b]
            rec["net_angle"]=round(wrap180((uh1 or 0)-(uh0 or 0)))
            rec["loss_pct"]=round(100*(entry-ex)/entry,1) if entry>1 else None
            turns.append(rec)
    return {"n_straight":len(straights),"n_turn":len(turns),
            "straights":straights,"turns":turns,
            "straight_run_qu_med":pctl([s["run_qu"] for s in straights],50),
            "straight_dvdx_med":pctl([s["dvdx"] for s in straights if s["dvdx"]],50),
            "turn_loss_pct_med":pctl([t["loss_pct"] for t in turns if t["loss_pct"] is not None],50),
            "turn_entry_med":pctl([t["entry"] for t in turns],50),
            "turn_exit_med":pctl([t["exit"] for t in turns],50)}

def facet_lookmove(d, lab):
    out={}
    for ph in ("straight","turn","all"):
        vals=[d["lvm"][i] for i in range(len(d["t"]))
              if d["lvm"][i] is not None and (ph=="all" or lab[i]==ph)]
        if vals:
            out[ph]={"n":len(vals),"mean":round(sum(vals)/len(vals),1),
                     "med":pctl(vals,50),"p10":pctl(vals,10),"p90":pctl(vals,90),
                     "abs_med":pctl([abs(v) for v in vals],50)}
    # correlation of look-vs-move sign with strafe sign
    agree=tot=0
    for i in range(len(d["t"])):
        if d["lvm"][i] is None or d["ssign"][i]==0: continue
        tot+=1
        if (d["lvm"][i]>0)==(d["ssign"][i]>0): agree+=1
    out["lvm_sign_eq_strafe_sign_frac"]=round(agree/tot,3) if tot else None
    return out

def main():
    path=sys.argv[1]
    name=os.path.splitext(os.path.basename(path))[0]
    outdir=os.path.dirname(os.path.abspath(sys.argv[0]))
    fr=load(path)
    d=build(fr)
    lab=classify_phase(d)
    summary={
        "demo":name,"frames":len(fr),
        "dur_s":round(d["t"][-1],2),
        "hspeed_med":round(pctl(d["hs"],50)),"hspeed_p90":round(pctl(d["hs"],90)),
        "hspeed_peak":round(max(d["hs"])),
        "phase_frac":{"straight":round(sum(1 for x in lab if x=="straight")/len(lab),3),
                      "turn":round(sum(1 for x in lab if x=="turn")/len(lab),3)},
        "A_yawrate_vs_speed":facet_yawrate(d,lab),
        "B_strafe_switch":facet_strafe(d),
        "C_jump_cadence":facet_jump(d),
        "D_segments":facet_segments(d,lab),
        "E_look_vs_move":facet_lookmove(d,lab),
    }
    with open(os.path.join(outdir,f"{name}_summary.json"),"w") as f:
        json.dump(summary,f,indent=2)
    # compact per-frame table (rounded) for agents that want to dig
    feat=[]
    for i in range(len(d["t"])):
        feat.append({"t":round(d["t"][i],3),"hs":round(d["hs"][i],1),
            "vyaw":round(d["vyaw"][i],1),
            "vhead":round(d["vhead"][i],1) if d["vhead"][i] is not None else None,
            "vyaw_rate":round(d["vyaw_rate"][i],1),
            "vhead_rate":round(d["vhead_rate"][i],1),
            "lvm":round(d["lvm"][i],1) if d["lvm"][i] is not None else None,
            "side":round(d["side"][i]),"fwd":round(d["fwd"][i]),
            "jump":d["jump"][i],"vz":round(d["vz"][i],1),
            "dist":round(d["dist"][i]),"phase":lab[i]})
    with open(os.path.join(outdir,f"{name}_features.json"),"w") as f:
        json.dump(feat,f)
    print(json.dumps(summary,indent=2))

if __name__=="__main__":
    main()
