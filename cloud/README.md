# cloud/ — pinnacle-independent komodobots cloud box

Infrastructure that runs the whole komodobots lab on one on-demand AWS box, reachable
from anywhere through Cloudflare Access (Gmail login — no SSH key, no local install).
It is the cloud **hub** + **dashboard** host + QuakeWorld **server lab**, designed to
start smoothly on demand and sleep when idle without losing any data.

## Services on the box (systemd, auto-start on boot — see `systemd/`)
- **cloudflared** — Cloudflare Tunnel. The public URLs point at the tunnel id (account-
  bound), **not** the box IP, so they survive every stop/start with no DNS changes.
- **ttyd** (`systemd/ttyd.service`) — browser terminal at `https://komodo.xerious.org`
  (Gmail-gated) into a persistent `tmux` as `ubuntu`. Loopback-only; tunnel-fronted.
- **quakelab** (`systemd/quakelab.service`) — the standing nQuake servers
  (`~/nquakesv/start_servers.sh` → mvdsv/KTX on UDP 28501-28504 + qtv).
- **cloudhub** (`systemd/cloudhub.service`) — `cloud_hub.py`, the hub web tier.

## Cloud hub — `cloud_hub.py` + `web/index.html`
Stdlib HTTP server (loopback :8099, fronted by the tunnel at
`https://komodolab.xerious.org`, Gmail-gated). Shows exactly three things, nothing else:
1. **Cloud servers** — live `quakestat -json` of 28501-28504.
2. **Demos recorded online** — MVDs in `~/nquakesv/ktx/demos`.
3. **Successful attempts** — committed `tricks/<map>/<route>__<runid>.mvd`.

It also serves the built dashboard at `/botlab/`, the demo files under `/demos/…`, the
map BSPs under `/maps/…`, and `/api/{servers,online-demos,attempts}`. Any listed demo
plays in-browser via the dashboard FTE pane (`/botlab/panes/demo.html`). Demo filenames
are URL-decoded and resolved strictly inside their base dir (so KTX names like
`4on4_leap[dm3]…mvd` serve correctly without allowing path traversal).

Deploy: copy `cloud_hub.py` → `~/cloud-hub/`, `web/index.html` → `~/cloud-hub/index.html`,
install `systemd/cloudhub.service`, then `sudo systemctl enable --now cloudhub`.

## Real 4on4 match — `start_match.sh`, `match_4v4_demo.sh`
Proven recipe for a KTX 4on4 frogbot match that forms teams, fights, and records:
- `k_matchless 0` + `k_defmode 4on4` + **`k_allowed_free_modes 4095`**. Without 4095, KTX
  logs `UserMode: sv 4on4 discarded due to k_allowed_free_modes` and falls back to ffa
  (which zeroes teamplay — the project's long-standing "no teams" blocker).
- A **ready client-player on a team** anchors the match start; an idle, team-less client
  never starts it. The anchor (`experiments/qw_min_client.py`) adds the frogbots via
  `botcmd addbot <skill> <team>` (auto-balanced); once ready → `The match has begun!`.
- Manual `sv_demoeasyrecord`/`sv_demostop` persists the MVD into `~/nquakesv/ktx/demos`,
  where the cloud hub lists it and it plays in-browser.

## Start / sleep — `manage.sh`
`manage.sh {start|stop|status}` starts/stops the box via the AWS CLI (profile `komodo`).
After `start`, every service returns automatically (tunnel URLs unchanged). `stop` saves
cost; the EBS root volume (demos, records, repos, configs) persists. **Never stop mid-
match** — recorded demos on disk are safe, but live in-RAM match state is not.

## Known gaps / next
- The **named, policy-driven komodobots** (team `leap`: ScaryM/pietro/hib/Angua) are the
  real komodobot client driven by the MOVE policy; `qw_min_client.py` is only its skeleton
  (it can join a team + ready + add bots, but carries no netname and idles).
- **Live in-browser QTV** spectating (recorded-demo playback works today).
- **Auto-sleep watchdog** for true hands-off sleep needs an EC2 instance-profile role
  (one-time owner IAM: `ec2:StopInstances` on self) so the box can stop itself when idle.
