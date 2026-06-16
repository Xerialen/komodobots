# Executive Summary — The "Stand-In Player" Project

*Plain-language overview for non-technical stakeholders. Companion to the technical plan in
`docs/13_QWD_MVD_FUSION_PLAN.md` and the program of record `docs/12_DM3_4ON4_STANDIN_PROGRAM.md`.*

## What we're building
A computer-controlled player ("bot") good enough to **drop into a real 4-on-4 QuakeWorld match
when a team is a player short** — one that moves, aims, and makes decisions like a real top-level
human. We're building it to **top-skill first** (modeled on specific elite players), proving it on
one map (DM3) before broadening. A "skill dial" to make it weaker on demand comes later.

## How it learns
The bot learns by **imitating recordings of real top players** — the same way you'd learn a sport
by studying film of the pros, frame by frame. We break a player's ability into three parts and
teach each:
- **Movement** — running and the fast "bunny-hop" technique.
- **Aiming** — tracking and hitting opponents.
- **Decisions** — the game's economy: when to grab armor, weapons, and power-ups, and how to
  control the map.

## Where we are today
- **Movement (first version): built and passed its quality test.** The bot already learns to move
  by copying real players, and it outperforms the simple baseline.
- **We have the data.** We located the recordings we need — **~965 recorded top-level DM3 games**
  featuring the exact pro players we want to model (Milton, ParadokS, zero, razor, Carapace, BPS,
  Mutilator).
- **We found and fixed a key measurement gap.** Our practice simulator couldn't realistically judge
  movement for more than ~1 second because it ignored collisions with other players. We've built the
  foundation to fix that.

## The plan
In order — each step has a quick go/no-go test, so we stop early if something doesn't work:
1. **Teach the bot to "see" opponents.** Right now it moves as if alone. We unlock realistic
   movement around other players — proven first on a single recording before scaling.
2. **Confirm that fix makes movement realistic enough to trust**, then apply it to the whole data set.
3. **Build the decision brain** (the economy / map-control understanding) from the large library of
   recorded games.
4. **Build the aiming.**
5. **Combine movement + aim + decisions into one bot and test it together.**
6. **Add the skill dial.**

## Who does the work
- **Two AI assistants split the labor:** one does the modeling, training, and analysis; an
  independent second one handles data extraction and acts as an outside quality reviewer.
- **The project owner provides** one piece of expert knowledge (a movement technique he's personally
  figured out) and arranges independent review.

## Honest scope — what it will and won't do
- **It models an individual elite player's skill** (move + aim + decisions).
- **Team coordination is scripted, not learned** — the data doesn't exist to learn how four players
  coordinate, so the bot follows a fixed team "playbook" rather than inventing teamwork.

## Current dependencies
- Project access / credentials: **resolved.**
- The owner's movement technique: **coming later** — the plan does not wait on it.
- Independent reviewer availability for sign-off before final integration.
