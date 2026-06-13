# A5 live-port servexeri overlay draft

This is a surgical overlay draft against the audited live tree at
`servexeri:~/nquakesv/build/ktx` (`08807da` plus dirty live moveprobe work).
It is **not** a `git apply` artifact. Convert it into an apply-ready patch in
the KTX tree after PR #125 / #118 round-3 scope is settled.

The required behavior is captured in `a5-live-port-spec.md`: replay activation
angle/fixangle cleanup, replay timing diagnostics, per-attempt S23 re-arm and
standstill re-snap, fixed-target mode-23 navigation, terminal carve, and S23
transition logs.

```diff
diff --git a/src/bot_movement.c b/src/bot_movement.c
--- a/src/bot_movement.c
+++ b/src/bot_movement.c
@@
 static int moveprobe_s23_launch_done[MAX_CLIENTS];         // mode 23: circle-jump launch one-shot latch (A3 #75)
 static float moveprobe_s23_launch_since[MAX_CLIENTS];      // mode 23: launch first-eval time (<=0 = not evaluated yet)
+static int moveprobe_spawn_snapped[MAX_CLIENTS];           // shared spawn-snap latch; re-armed by A5 attempts
+static int moveprobe_s23_attempt[MAX_CLIENTS];             // A5 live attempt counter
+static int moveprobe_s23_carve_armed[MAX_CLIENTS];         // A5 terminal-carve state
+static float moveprobe_s23_last_teleport_time[MAX_CLIENTS];// catcher-teleport re-arm guard
+static int moveprobe_s23_land_reset_pending[MAX_CLIENTS];  // A5 successful landing reset marker
+static int moveprobe_s23_has_prev_origin[MAX_CLIENTS];     // origin-jump fallback re-arm guard
+static vec3_t moveprobe_s23_prev_origin[MAX_CLIENTS];
 static float moveprobe_orbit_yaw[MAX_CLIENTS];             // mode 14: base heading yaw (the "direction"/orbit)
@@
 static void BotMoveProbeResetReplaySession(int slot)
 {
@@
 	moveprobe_replay_loop_cooldown[slot] = 0.0f;
 }
```
+
+static void BotMoveProbeResetS23AttemptState(int slot)
+{
+	if (slot < 0 || slot >= MAX_CLIENTS)
+	{
+		return;
+	}
+
+	moveprobe_s23_launch_done[slot] = 0;
+	moveprobe_s23_launch_since[slot] = 0.0f;
+	moveprobe_s23_carve_armed[slot] = 0;
+	moveprobe_accel_strafe_sign[slot] = 0;
+	moveprobe_accel_jump_press[slot] = 0;
+	moveprobe_s23_deleg_marker[slot] = NULL;
+	moveprobe_s23_carrot_done[slot] = NULL;
+	moveprobe_s23_prec_marker[slot] = NULL;
+	moveprobe_s23_prec_since[slot] = 0.0f;
+}
+
+static void BotLogMoveProbeS23Event(gedict_t *self, int slot, const char *event,
+									float vh, float herr, float d_lip)
+{
+	if (slot < 0 || slot >= MAX_CLIENTS)
+	{
+		return;
+	}
+	G_cprint("FBMOVEPROBE_S23 time=%.3f ed=%d name=%s event=%s "
+			 "attempt=%d armed=%d done=%d vh=%.3f herr=%.3f d_lip=%.3f "
+			 "origin=%.3f,%.3f,%.3f velocity=%.3f,%.3f,%.3f\n",
+			 g_globalvars.time, NUM_FOR_EDICT(self), self->netname, event,
+			 moveprobe_s23_attempt[slot], moveprobe_s23_carve_armed[slot],
+			 moveprobe_s23_launch_done[slot], vh, herr, d_lip,
+			 PASSVEC3(self->s.v.origin), PASSVEC3(self->s.v.velocity));
+}
+
+static qbool BotMoveProbeS23AttemptBoundary(gedict_t *self, int slot)
+{
+	vec3_t delta;
+	float jump_dist;
+	float land_reset_x = cvar("k_fb_moveprobe_s23_land_reset_x");
+	qbool onground = ((int)self->s.v.flags & FL_ONGROUND) ? true : false;
+
+	if (slot < 0 || slot >= MAX_CLIENTS)
+	{
+		return false;
+	}
+
+	moveprobe_s23_land_reset_pending[slot] = 0;
+	if ((land_reset_x != 0.0f) && onground && (self->s.v.origin[0] > land_reset_x))
+	{
+		moveprobe_s23_land_reset_pending[slot] = 1;
+		return true;
+	}
+
+	if (self->teleported && (self->teleport_time > moveprobe_s23_last_teleport_time[slot]))
+	{
+		moveprobe_s23_last_teleport_time[slot] = self->teleport_time;
+		return true;
+	}
+
+	if (!moveprobe_s23_has_prev_origin[slot])
+	{
+		VectorCopy(self->s.v.origin, moveprobe_s23_prev_origin[slot]);
+		moveprobe_s23_has_prev_origin[slot] = 1;
+		return false;
+	}
+
+	VectorSubtract(self->s.v.origin, moveprobe_s23_prev_origin[slot], delta);
+	jump_dist = sqrt(delta[0] * delta[0] + delta[1] * delta[1] + delta[2] * delta[2]);
+	VectorCopy(self->s.v.origin, moveprobe_s23_prev_origin[slot]);
+	return jump_dist > 100.0f;
+}
@@
 	if (!moveprobe_replay_active[slot])
 	{
 		f = &moveprobe_replay_frames[0];
 		setorigin(self, PASSVEC3(f->origin));
 		VectorCopy(f->velocity, self->s.v.velocity);
-		VectorCopy(f->angles, self->s.v.angles);
 		VectorCopy(f->angles, self->fb.desired_angle);
 		self->fb.desired_angle[ROLL] = 0;
+		self->s.v.angles[PITCH] = -f->angles[PITCH] / 3.0f;
+		self->s.v.angles[YAW] = f->angles[YAW];
+		self->s.v.angles[ROLL] = 0.0f;
 		self->s.v.fixangle = 1;
@@
 	// Lab instrument: one-time spawn snap. If k_fb_moveprobe_spawn_origin is set
 	// ("x y z"), teleport the bot there on its first moveprobe frame (per slot)
 	// and zero velocity -- a deterministic start for directed tests (e.g. the
 	// bot at a staircase bottom with the goal pinned at the top).
 	{
-		static int moveprobe_spawn_snapped[MAX_CLIENTS];
 		char snap_buf[64];
+		qbool rearm_snap = false;
+
+		if (mode == 23)
+		{
+			rearm_snap = BotMoveProbeS23AttemptBoundary(self, slot);
+			if (rearm_snap)
+			{
+				moveprobe_spawn_snapped[slot] = 0;
+				BotMoveProbeResetS23AttemptState(slot);
+				BotLogMoveProbeS23Event(self, slot,
+					moveprobe_s23_land_reset_pending[slot] ? "land_reset" : "rearm",
+					0.0f, 999.0f, 999999.0f);
+			}
+		}
@@
 					VectorSet(snap_org, sx, sy, sz);
 					setorigin(self, PASSVEC3(snap_org));
 					VectorClear(self->s.v.velocity);
+					if (mode == 23)
+					{
+						moveprobe_s23_attempt[slot]++;
+						BotMoveProbeResetS23AttemptState(slot);
+						BotLogMoveProbeS23Event(self, slot, "attempt", 0.0f, 999.0f, 999999.0f);
+						BotLogMoveProbeS23Event(self, slot, "snap", 0.0f, 999.0f, 999999.0f);
+					}
 				}
 				moveprobe_spawn_snapped[slot] = 1;
-				// New attempt: re-arm the one-shot circle-jump launch latch
-				// (A3 #75) together with the snap itself.
-				moveprobe_s23_launch_done[slot] = 0;
-				moveprobe_s23_launch_since[slot] = 0;
 			}
 		}
 		else
 		{
 			moveprobe_spawn_snapped[slot] = 0;
-			moveprobe_s23_launch_done[slot] = 0;
-			moveprobe_s23_launch_since[slot] = 0;
+			BotMoveProbeResetS23AttemptState(slot);
 		}
 	}
@@
 	else if (mode == 23)
 	{
@@
 		float launch_vh = cvar("k_fb_moveprobe_s23_launch_vh");
 		float launch_angle = cvar("k_fb_moveprobe_s23_launch_angle");
+		float launch_sign = cvar("k_fb_moveprobe_s23_launch_sign");
+		float lip_x = cvar("k_fb_moveprobe_s23_lip_x");
+		float carve_d = cvar("k_fb_moveprobe_s23_carve_d");
+		float carve_angle = cvar("k_fb_moveprobe_s23_carve_angle");
+		float carve_vh = cvar("k_fb_moveprobe_s23_carve_vh");
+		float release_vh = cvar("k_fb_moveprobe_s23_release_vh");
+		float carve_tol = cvar("k_fb_moveprobe_s23_carve_tol");
+		float launch_timeout = cvar("k_fb_moveprobe_s23_launch_timeout");
+		char target_buf[64];
+		vec3_t launch_target;
+		qbool has_launch_target = false;
 		qbool deleg_speed_ok;
-		float hor_speed_sq, rotation, goal_yaw, vel_yaw, signed_to_goal, herr, corner_mag;
+		float hor_speed_sq, rotation, goal_yaw, vel_yaw, signed_to_goal, herr, corner_mag;
+		float vh, d_lip = 999999.0f;
@@
 		if (launch_angle <= 0) launch_angle = 45.0f;
+		if (carve_angle <= 0) carve_angle = launch_angle;
+		if (carve_vh <= 0) carve_vh = launch_vh;
+		if (release_vh <= 0) release_vh = carve_vh;
+		if (carve_tol <= 0) carve_tol = swing;
+		if (launch_timeout <= 0) launch_timeout = 3.0f;
+		trap_cvar_string("k_fb_moveprobe_s23_launch_target", target_buf, sizeof(target_buf));
+		if (sscanf(target_buf, "%f %f %f", &launch_target[0], &launch_target[1], &launch_target[2]) == 3)
+		{
+			has_launch_target = true;
+		}
@@
-		// Per-tick bearing to the linked marker itself (fresher than dir_move_,
+		// Fixed target point for .bot-less ztricks Distance. If unset, preserve
+		// the normal marker navigation path.
+		if (has_launch_target)
+		{
+			VectorSubtract(launch_target, self->s.v.origin, nav_dir);
+			marker_dist_sq = 1e18f;
+			marker_dz = 0.0f;
+		}
+		// Per-tick bearing to the linked marker itself (fresher than dir_move_,
 		// which updates only at frogbot think rate and carries dodge noise).
 		// Falls back to dir_move_ when there is no usable marker.
-		if (self->fb.linked_marker && (self->fb.linked_marker != self->fb.touch_marker))
+		else if (self->fb.linked_marker && (self->fb.linked_marker != self->fb.touch_marker))
@@
 		hor_speed_sq = cur_dir[0] * cur_dir[0] + cur_dir[1] * cur_dir[1];
+		vh = sqrt(hor_speed_sq);
 		if (VectorNormalize(cur_dir) <= 0)
 		{
 			VectorCopy(nav_dir, cur_dir);
@@
 		herr = (signed_to_goal >= 0) ? signed_to_goal : -signed_to_goal;
+		if (lip_x != 0.0f)
+		{
+			d_lip = fabs(lip_x - self->s.v.origin[0]);
+		}
@@
-		if ((launch_vh > 0) && !moveprobe_s23_launch_done[slot])
+		if ((launch_vh > 0) && !moveprobe_s23_launch_done[slot])
 		{
@@
-			else if ((g_globalvars.time - moveprobe_s23_launch_since[slot]) >= 3.0f)
+			else if ((g_globalvars.time - moveprobe_s23_launch_since[slot]) >= launch_timeout)
 			{
 				moveprobe_s23_launch_done[slot] = 1;       // safeguard release
+				BotLogMoveProbeS23Event(self, slot, "timeout", vh, herr, d_lip);
 			}
 			else if (onground)
 			{
-				if ((hor_speed_sq >= launch_vh * launch_vh) && (herr <= swing))
+				if (!moveprobe_s23_carve_armed[slot]
+					&& has_launch_target
+					&& (lip_x != 0.0f)
+					&& (carve_d > 0.0f)
+					&& (d_lip <= carve_d)
+					&& (hor_speed_sq >= carve_vh * carve_vh))
+				{
+					moveprobe_s23_carve_armed[slot] = 1;
+					BotLogMoveProbeS23Event(self, slot, "arm", vh, herr, d_lip);
+				}
+				if (moveprobe_s23_carve_armed[slot])
+				{
+					int carve_sign = (signed_to_goal >= 0.0f) ? 1 : -1;
+
+					if (launch_sign != 0.0f)
+					{
+						carve_sign = (launch_sign > 0.0f) ? 1 : -1;
+					}
+					if (((hor_speed_sq >= release_vh * release_vh) && (herr <= carve_tol))
+						|| (d_lip <= 8.0f))
+					{
+						moveprobe_s23_launch_done[slot] = 1;
+						moveprobe_s23_carve_armed[slot] = 0;
+						moveprobe_accel_jump_press[slot] = true;
+						self->fb.desired_angle[PITCH] = 0;
+						self->fb.desired_angle[YAW] = goal_yaw;
+						self->fb.desired_angle[ROLL] = 0;
+						direction[0] = sv_maxspeed;
+						direction[1] = 0;
+						direction[2] = 0;
+						*jumping = true;
+						BotLogMoveProbeS23Event(self, slot, "release", vh, herr, d_lip);
+						return;
+					}
+					RotatePointAroundVector(proposed_dir, up_vector, cur_dir, carve_angle * carve_sign);
+					proposed_dir[2] = 0;
+					if (VectorNormalize(proposed_dir) <= 0)
+					{
+						VectorCopy(cur_dir, proposed_dir);
+					}
+					moveprobe_accel_jump_press[slot] = false;
+					self->fb.desired_angle[PITCH] = 0;
+					self->fb.desired_angle[YAW] = vectoyaw(proposed_dir);
+					self->fb.desired_angle[ROLL] = 0;
+					direction[0] = sv_maxspeed;
+					direction[1] = 0;
+					direction[2] = 0;
+					*jumping = false;
+					return;
+				}
+				else if ((hor_speed_sq >= launch_vh * launch_vh) && (herr <= swing))
 				{
 					moveprobe_s23_launch_done[slot] = 1;   // fast + aimed: release (the jump fires below)
+					BotLogMoveProbeS23Event(self, slot, "release", vh, herr, d_lip);
 				}
 				else
 				{
@@
 					if (moveprobe_accel_strafe_sign[slot] == 0)
 					{
 						moveprobe_accel_strafe_sign[slot] = (signed_to_goal >= 0.0f) ? 1 : -1;
 					}
+					if (launch_sign != 0.0f)
+					{
+						moveprobe_accel_strafe_sign[slot] = (launch_sign > 0.0f) ? 1 : -1;
+					}
 					RotatePointAroundVector(proposed_dir, up_vector, cur_dir,
 											launch_angle * moveprobe_accel_strafe_sign[slot]);
@@
 static void BotLogMoveProbeCommand(gedict_t *self, int cmd_msec, vec3_t direction, int buttons, int impulse)
 {
@@
 	G_cprint("FBMOVEPROBE_CMD time=%.3f ed=%d name=%s mode=%d msec=%d "
@@
 			 PASSVEC3(self->s.v.origin));
+
+	if (moveprobe_replay_active[slot]
+		&& (moveprobe_replay_cursor[slot] >= 0)
+		&& (moveprobe_replay_cursor[slot] < moveprobe_replay_count))
+	{
+		moveprobe_replay_frame_t *rf = &moveprobe_replay_frames[moveprobe_replay_cursor[slot]];
+		float elapsed_ms = moveprobe_replay_has_start[slot]
+			? (g_globalvars.time - moveprobe_replay_start_time[slot]) * 1000.0f
+			: 0.0f;
+		float source_start_ms = rf->cumulative_ms - rf->msec;
+		float pitch_delta = fabs(self->fb.desired_angle[PITCH] - rf->angles[PITCH]);
+		float yaw_delta = BotMoveProbeAngleDelta(self->fb.desired_angle[YAW], rf->angles[YAW]);
+
+		G_cprint("FBMOVEPROBE_REPLAY_TIMING time=%.3f ed=%d name=%s "
+				 "cursor=%d source_msec=%d cmd_msec=%d elapsed_ms=%.3f "
+				 "source_ms=%.3f angle_delta=%.3f,%.3f,%.3f\n",
+				 g_globalvars.time, ednum, self->netname, moveprobe_replay_cursor[slot],
+				 rf->msec, cmd_msec, elapsed_ms, source_start_ms,
+				 pitch_delta, yaw_delta, fabs(self->fb.desired_angle[ROLL] - rf->angles[ROLL]));
+	}
 }
