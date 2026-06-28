/* Commander/Motor-Cortex handoff gate -- C unit (bot-program T3.1, #422).
 *
 * Pure C + libm, no engine types (mirrors move_world_view.{c,h}), so the same translation unit
 * compiles standalone for the test harness (tests/test_move_highway.py via tests/_live_c_harness.py)
 * AND inside the KTX .so (frogbot-moveprobe-handoff.patch). Under Q3_VM the whole unit is a no-op
 * (the live handoff is a native-only feature).
 *
 * The decision is keyed on ROUTE GEOMETRY -- the base-highway trajectories baked into the generated
 * route_canon_dm3.h -- NEVER on the (from_resource,to_resource) pair (route_class + traced
 * trajectory only; #421 _match_key / F5). The handoff is a latched CONJUNCTION: to yield movement
 * the bot must (i) intend to head toward a base highway's end (Commander intent) AND (ii) physically
 * be on that highway's traced polyline (geometric latch). It hands back to the Commander on arrival,
 * drift, intent loss, or a change of nearest highway.
 */
#ifndef KOMODO_MOVE_HIGHWAY_H
#define KOMODO_MOVE_HIGHWAY_H

#ifndef Q3_VM

/* Handoff radii (quake units). R_ON < R_OFF gives engage/disengage hysteresis. PoC defaults
 * (#422); tune by-eye in the live run, together with the route_canon_dm3.h downsample cap (a
 * coarse polyline can sit > R_ON off a high-curvature leg -> spurious DISENGAGE). */
#define MHW_R_ON      48.0   /* engage: within this of a base polyline (precise membership)  */
#define MHW_R_OFF     96.0   /* disengage: drifted beyond this off the polyline (hysteresis)  */
#define MHW_R_ARRIVE  64.0   /* disengage: within this of the highway end (arrival)           */
#define MHW_R_GOAL   256.0   /* intent: Commander goal within this of the highway end (loose) */

/* Squared min (x,y) distance from (x,y) to the nearest base-highway polyline (point-to-segment over
 * every base highway). Sets *which to that highway's index (-1 if there are none). Pure / stateless
 * -- the testable membership primitive. */
double mhw_nearest_base_highway(double x, double y, int *which);

/* Per-slot LATCHED conjunction handoff gate. Returns 1 = engaged (yield movement to the Motor
 * Cortex), 0 = disengaged (stock Commander drives). Engages from disengaged only when the bot is
 * within R_ON of a base polyline AND has a goal within R_GOAL of that highway's end; stays engaged
 * (hysteresis to R_OFF) until it drifts off (> R_OFF), arrives (end within R_ARRIVE), loses intent,
 * or the nearest base highway changes. State is per-slot; C zero-init == disengaged (a bot must
 * reach a base highway to engage). */
int mhw_handoff_engaged(int slot, double bx, double by, int have_goal, double gx, double gy);

#endif /* !Q3_VM */

#endif /* KOMODO_MOVE_HIGHWAY_H */
