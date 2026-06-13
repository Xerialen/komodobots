# Demo lab-list UI cutover - 2026-06-13

## Scope

- QHub header: removed the `Servers` tab from the tab strip, changed `Demos / Recent games` to `/demos/`, and removed the floating green `/demos/` button.
- Botlab Demo Lab demos tab: supports the deployed flat `/v2/demos.json` index, filters to active map folders under `non-games/lab/Komodobots/<map>/`, excludes `archive`, `human`, and `records`, adds sortable `demo`, `map`, and `date recorded` columns, and defaults to newest recorded first.
- Demo naming: route-labelled releases now use `<route>__<run_id>.mvd` under `/mnt/usb-ssd/non-games/lab/Komodobots/<map>/`.
- New runs no longer mirror demos into repo `tricks/dm3/` or local nQuake watch folders.

## Lifecycle

- Active lab-generated demos live under `/mnt/usb-ssd/non-games/lab/Komodobots/<map>/`.
- "Archive" is reserved for a later lifecycle state for lab-generated demos older than 30 days from date recorded.
- That retention rule applies only to Komodobots lab recordings, not downloaded external demo corpora or human reference files.

## Remote Changes

- QHub backup: `servexeri:/home/xerial/local-hub/backups/qh-demo-tabs-20260613T071222Z/`
- QHub files patched:
  - `~/local-hub/web/assets/Header-6OXt9HiV.js`
  - `~/local-hub/web/assets/Header-DTlzTu6T.js`
  - `~/local-hub/web/index.html`
  - `~/local-hub/web/qtv/index.html`
- Demo index generator backup: `servexeri:/home/xerial/local-hub/backups/demos-index-date-20260613T071457Z.py`
- Demo index regenerated: `/home/xerial/local-hub/web/v2/demos.json`

## SSD Rename

- Before manifest: `servexeri:/home/xerial/komodobots-lab/demo-rename-20260613T071245Z.before.tsv`
- Rename plan: `servexeri:/home/xerial/komodobots-lab/demo-rename-20260613T071245Z.plan.tsv`
- Planned renames: `370`
- Applied renames: `361`
- Skipped because target existed: `9`
- Removed byte-identical duplicate old stems: `9`

Examples now present in `/v2/demos.json`:

- `sng_to_rl__20260607T151125Z.mvd`
- `getandmaintainspeed__gm25_clocktol1500m950_0420.mvd`
- `spawn_left_speedjump__zbatch_20260612T180901Z.mvd`

## Deploy

- Dashboard build: `npm run build` in `lab/dashboard`
- Stage deploy: `python lab/deploy_dashboard.py --stage --skip-build`
- Live cutover: `python lab/deploy_dashboard.py --cutover --confirm-live --skip-build`
- Live rollback archive: `servexeri:~/local-hub/web-backups/botlab-pre-cutover-20260613T071716Z.tar.gz`
- Lab demos label/filter correction live rollback archive:
  `servexeri:~/local-hub/web-backups/botlab-pre-cutover-20260613T085810Z.tar.gz`
- Standalone local-hub `/demos/` page patched in place with a sortable
  `recorded` column. Backup:
  `servexeri:/home/xerial/local-hub/backups/demos-index-html-pre-date-column-20260613T090452Z.html`
- Records rebuilt and published with route-based demo URLs:
  `python lab/server/records_build.py --rebuild --archive-ssh servexeri --publish`

## Validation

- Unit tests: `python -m unittest tests.test_demo_archive tests.test_records_build -v`
- Dashboard build: `npm run build`
- Browser: `http://192.168.86.33:8095/qtv/`
  - floating green `/demos/` button absent
  - `/games/` tab link absent
  - `Demos / Recent games` points to `/demos/`
- Browser: `http://192.168.86.33:8095/botlab/?views=demo%2Cgame&ws=ws%3A%2F%2F127.0.0.1%3A8771&port=28599`
  - Lab demos tab loaded `610` active lab demos
  - no `Archive` tab label remained
  - map filters were active map folders only: `dm2`, `dm3`, `frobodm2`, `trick`, `ztricks`
  - `date recorded` column displayed file-mtime dates
  - default order was `DATE RECORDED↓`, with newest rows first
  - route-prefixed demo names displayed
  - clicking `demo` sort changed first row from `ring_to_mega__dm3_r2m_interp_only_029.mvd` to `best_watch__20260608T093212Z.mvd`
- Browser mobile viewport `390x844`: `http://192.168.86.33:8095/demos/`,
  folder path `non-games/lab/Komodobots/dm3`
  - table headers rendered as `name`, `map`, `recorded ↓`, `watch`
  - first row rendered `ring_to_mega__dm3_r2m_interp_only_029.mvd`,
    `dm3`, `2026-06-13 08:02`
  - `size` and `source` are hidden on phone to keep the recorded date visible;
    they remain available on wider screens

## Residual Note

The browser console still reports repeated `ftewebgl.js` errors from the embedded FTE player. They were not introduced by the demo-list/header changes and did not block the lab demo list or sort validation.
