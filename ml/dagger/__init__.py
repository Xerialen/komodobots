"""DAgger (DAtaset AGGregation) offline relabeling for the v5 movement policy.

This package holds the analytic optimal air-strafe EXPERT (the DAgger oracle) and its
offline validation harness. The expert reuses the sim-proven `optimal_strafe_yaw` seam
(ml/eval_broad_closedloop.optimal_strafe_yaw, proven vs the exact pmove_sim by
ml/tests/test_optimal_aim) -- it does NOT reimplement the air-accel physics.

D-1 (this package): build + validate the expert (the owner check-in gate). The DAgger
training loop itself (D-2, GPU) lives elsewhere and consumes `expert.expert_action`.
"""
