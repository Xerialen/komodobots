# Pull Request

<!-- Open as **ready for review** (non-draft) if you want this gated and merged.
     Use draft ONLY for genuine WIP - a draft gets advisory review only and is
     never labeled `gate: ready`. See coder.md. -->

## Summary

## Linked work

- Story/issue:
- Test cases:

## Evidence produced

Paste command output, logs, metrics, screenshots, or browser geometry checks.

## Test runs

- [ ] Not applicable
- [ ] Automated tests run
- [ ] Manual/browser test run logged
- [ ] Failed/blocked tests linked to follow-up work

## Web / UI evidence

- [ ] Not a web/UI change
- [ ] Browser opened successfully
- [ ] Console checked
- [ ] Network checked where relevant
- [ ] Desktop viewport checked
- [ ] Narrow/mobile viewport checked where relevant
- [ ] Screenshot/video/geometry evidence attached

## Docs updated

- [ ] Source map
- [ ] Movement problem
- [ ] Headless test environment
- [ ] Data/MVD pipeline
- [ ] Findings log
- [ ] Decision log
- [ ] Test cases / evidence
- [ ] No docs needed; reason:

## Data contract (see docs/25_DATA_CONTRACT.md)

- [ ] No data extraction fields, transforms, or output format changed
- [ ] Extraction/transform/format changed AND all of these moved in this PR:
  `docs/25_DATA_CONTRACT.md`, `configs/extraction_spec.yaml`,
  `schemas/training_example.schema.json`, `examples/expected_training_frame.jsonl`
- [ ] `python3 -m unittest tests.test_data_contract` passes

## Risks / rollback

## Next smallest useful experiment
