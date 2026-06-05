# Experiment 000 - Smoke Test

Purpose:

Determine whether the laboratory can produce bot movement evidence automatically.

This experiment is intentionally simple.

It is not a bunnyjump experiment.

## Goal

Prove the loop:

server -> bot -> MVD -> parser -> report

## Proposed sequence

1. Start MVDSV/KTX.
2. Use a convenient test port (for example 28599).
3. Load `frobodm2`.
4. Enable bot commands.
5. Add one bot.
6. Let it move for approximately 30-60 seconds.
7. Record MVD output.
8. Parse MVD output.
9. Generate report.
10. Record findings.

## Success criteria

- Bot moves.
- MVD exists.
- MVD parses successfully.
- Findings are documented.

## Failure handling

If the experiment fails:

Record:

- command executed
- working directory
- error output
- suspected cause
- next suggested fix

Update docs/07_FINDINGS_LOG.md.

## Outputs

Expected outputs:

- MVD artifact
- parser output
- findings log entry
- environment documentation updates
