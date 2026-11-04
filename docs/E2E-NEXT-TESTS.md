> **Superseded:** this plan is now §8 of [E2E-TESTING.md](E2E-TESTING.md), and its last section (the design doc updates) is done there. T1 (a) is built (`e2e/test_t1_a_hardening.py`) and passed live on macOS and linux-vm on 2026-11-03. Kept as the proposal it was.

# The next e2e tests: T1, first batch

A proposal carved from [docs/E2E-TESTING.md](E2E-TESTING.md), against the suite as it is on `main` (ceadac42).

**What exists today:**
- T0 only, 10 tests: `e2e/test_t0_stack.py` and `e2e/test_t0_package.py`.
- Node kinds: `mac` and `linux-vm`.
- One node per platform, created once per session and shared by every module.

**What this batch covers:** the design's step 3 in §8: T1's security properties, backup and restore, and keys. That is where past hand-run QA found the most bugs. It adds the request channel from #528, which is new and has only run against stubs. Everything here needs only the `node` role and public Tor. No new product change is needed, no Playwright, no hub or OnionHome roles.

---

## 0. Harness work first (small)

1. **A ready-node fixture.** `test_install`, `test_first_start` and `test_wordpress_setup` in T0 bring the node up; T1 modules would otherwise depend on T0 having run first in the same session. A session fixture `ready_node` does install → start → setup once, if T0 hasn't already, and records the first served key digest. T0 keeps doing those steps as its own checked tests. `run.sh --tier t1` then works on its own.
2. **Module order is the plan.** The node is shared, so modules run in filename order, read-only ones first and the ones that change identity or content last. Every destructive module ends by putting the site back, or is the last module.
3. **`node.as_www_data(argv)`.** Runs `docker exec -u www-data onionpress-wordpress …`, for writing request files the way the Settings page does.
4. **`setup_wordpress` through `setup --json`.** The password goes in `ONIONPRESS_SETUP_PASSWORD`, off argv, the way the UIs do it since #527. The JSON answer (`ok`, `name`, `onionname`) is parsed and asserted.
5. **Backup fixtures built with the product's code.** `e2e/fixtures/make_backups.py` builds the malicious archives with `backup.pack_backup` / `backup_crypto`, at run time, into the results dir. Nothing binary is committed except the existing pinned `tests/fixtures/backup-format-2.zip`.

## 1. `test_t1a_hardening.py`: security properties on live containers

About 3 min per platform. Read-only, no Tor waits. Runs first.

| Test | How | Rule it holds |
|---|---|---|
| WordPress resolves nothing outside Docker | `getent hosts example.com` fails in `onionpress-wordpress` and `onionpress-db`; `getent hosts onionpress-tor` works | WordPress Resolves No Name Outside Docker |
| WordPress has no egress | from the wordpress container, `curl --max-time 5` to an internet IP and to the gateway both fail; the egress chain's counter or log grows. The tor container reaches the internet but not RFC1918 or the gateway | #144 |
| Capabilities as the census says | `docker inspect` of every running container: `CapAdd`, `CapDrop` (`ALL`) and `SecurityOpt` (`no-new-privileges:true`) equal `tests/test_container_capabilities.py`'s `COMPOSE_CAPS`, imported rather than copied | Containers Drop Every Capability |
| The socket stays out | no mount of `docker.sock` except on `autoheal-proxy` and `onionheaven-farm` (both `:ro`) | The Docker Socket Stays Out of onionheaven |
| The data dir is the user's | `~/.onionpress` 0700; `config` and `secrets` 0600 | #397 |
| Installer refused over Tor | `install.php` and `setup-config.php` answer 403 over Tor (T0 already checks this; skip here unless T0 didn't run) | #464 |

## 2. `test_t1b_settings_requests.py`: the page's request channel (#528)

About 5 min per platform. No Tor needed except one check.

Every request is written as www-data into `/var/lib/onionpress/`, with a request id, the way the page writes it. The test then waits for the daemon's pass and reads the result.

| Test | Expect |
|---|---|
| `refresh-status` | taken (the request file is gone), no result file, `status.json` rewritten |
| `update` (read-only GitHub API is allowed) | `update-result.json` carrying the request id; `status.json`'s `release` filled; a second `update` within 60 s gets the throttled result |
| `upload-analytics` with sharing off | `analytics-result.json` refusal; no `.upload-analytics` marker in the data dir |
| An unknown verb | dropped; the host log names its byte count, never its text |
| `archive-login`, malformed only | a body that isn't JSON → "Enter an Archive.org account…", and `archive-login` gone within one pass. A well-formed one is not sent: archive.org logins are T4 only (rule 3) |
| `archive-login` file lifetime | an oversized `archive-login` (over 4 KiB) is dropped and removed |
| Config writes allowlisted | `config-updates.json` with one allowed key (`SHARE_ANALYTICS_WITH_ONIONHOME=no` → `yes` → `no`) and one forbidden key (`ONIONHEAVEN_ADDRESS`): the first applied, the second dropped, logged by key name only |
| What WordPress sees | `status.json` holds only `redact.WORDPRESS_STATUS_KEYS` (`page_actions` lists `archive-login`); `config-current.json` only `SAFE_CONFIG_KEYS`; no host path anywhere in either |
| `check-reachability` (Tor) | `reachability-result.json` says reachable, with the request id |

## 3. `test_t1c_onionname.py`: names follow OnionHeaven (#527, #554)

About 2 min per platform. Needs [brewsterkahle/onionpress#554](https://github.com/brewsterkahle/onionpress/pull/554).

- After setup: `ONIONNAME` is the admin login, `ONIONNAME_REGISTERED=no`, no `ONIONNAME_ADDRESS`. A minute after the plugin loads, the name-sync plugin logs nothing about a register (its daily reconcile's first run).
- `onionpress onionname set <new> --rename-admin --json` answers `recorded`. The old login fails and the new one works (`wp_login`). `wp super-admin list` names the new login.
- `onionpress onionname set` with an invalid name (too short, all digits) is refused with the validation message, nothing changed.

## 4. `test_t1d_keys.py`: keys and identity (#311)

About 15 min per platform: two Tor republishes.

| Test | Expect |
|---|---|
| Damaged C Tor files | truncate `hs_ed25519_secret_key` and write a wrong `hostname` in the tor container; `onionpress restart` → the same address served, the old files in `key-set-aside/`, `replaced-keys/` still empty |
| A garbage key refused | `onionpress import-key` with random bytes, a small-order key and a bit-255 key: each refused, the old address still served, nothing in `replaced-keys/` |
| A valid key imported | a key the harness generates (`onion_keys`) → `import-key --confirmed address-change` → the new address served over Tor, the old PEM in `replaced-keys/`. The node's identity changes here, so this test is the module's last, and the session's `node.address` is updated |

The key volume migration (an old `onionpress-arti-state`) stays for later: it needs a fresh node seeded before its first start.

## 5. `test_t1e_backup_restore.py`: back up, reset, restore

About 25 min per platform. Runs last.

| Test | Expect |
|---|---|
| Content to find again | wp-cli makes a post, a subsite, a user and an uploaded image with its sizes |
| CLI backup | `onionpress backup` with `ONIONPRESS_BACKUP_PASSWORD` in the environment → a format-2 zip in `~/OnionPress/`; the archive has no derivative sizes and holds the PEM |
| Refusals, nothing changed | a wrong password; a truncated archive; a header claiming a newer format |
| Malicious archives (built in §0.5) | a symlink member, `..` names, a zip bomb, a dump with `\! touch /pwned` and `LOAD DATA LOCAL INFILE`: each refused or neutralised, and `find / -name pwned` finds nothing in any container |
| Reset → restore | `onionpress reset --yes`, then `onionpress restore <zip>` → the same address over Tor, the post, subsite, user and image back, derivatives regenerated (`.regenerate-derivatives-pending` gone) |
| Format 2 fixture | `tests/fixtures/backup-format-2.zip` restores (its address replaces the node's; module end) |

Restoring onto a second node, format 1, the Settings-page backup and the large-site timing wait for a `peer` role and for Playwright (§0 doesn't cover them).

---

## What this batch costs

About 50 min per platform on public Tor; most of it is the restore's and the key import's republish waits. Run as `e2e/run.sh --tier t0,t1`, or `--tier t1` once §0.1 is in.

## Order to build it in

1. §0.1–0.4 and `test_t1a_hardening.py`: fastest, finds the most per minute, no destructive steps.
2. `test_t1b_settings_requests.py`: the newest code, never run live.
3. `test_t1c_onionname.py`, after #554 merges.
4. `test_t1d_keys.py`, then §0.5 and `test_t1e_backup_restore.py`.

## The design doc is behind; update it with the first PR

- §1 rule 2: the baseline config now also sets `ONIONHOME_ADDRESS` empty, and onionnames follow `REGISTER_WITH_ONIONHEAVEN` (#554). The name-sync plugin no longer needs a test home to stay quiet.
- §5.4 (setup provisioning without the window) is done: `onionpress setup` installs through `install_fresh_wordpress` like the setup window (#442), and since #527 it handles the onionname too; both UIs now run that command.
- §5.5 (a daemon label per data dir) is done (#505); the harness's refusal stays as a guard.
- §5.1 is still open, but it now only matters for T2's `home` role: the tor image's `web-server.py` still hard-codes OnionHome for the name-sync relay.
- §3's file layout (`platforms.py`, `nodes/` at the top of `e2e/`) is `e2e/harness/…` as built.
