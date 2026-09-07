# Local Live stack and the public face boundary

`scripts/live-up.sh` loads the repository root `.env` for **all four services**:
ai-core → Character Runtime → gateway → Studio. Studio is launched with
`--runtime-url`, so its main chat screen uses the same Runtime as Live/Joi.
During ordinary launches, values in root `.env` take precedence over old shell
exports. Shell values only fill fields absent from the file. There is no shell
`source` or command substitution when parsing it; explicit programmatic
overrides are reserved for isolated tests.

Set these root `.env` fields before starting:

```dotenv
AI_CORE_URL=http://127.0.0.1:8100
SOULFORGE_COGNITION_URL=http://127.0.0.1:8100
SOULFORGE_MEMORY_BACKEND=ai-core
SOULFORGE_COGNITION_TIMEOUT_S=25
SOULFORGE_BRAND_ID=<existing brand UUID>
SERVICE_TOKEN=<existing ai-core service token>
GATEWAY_API_TOKEN=<separate random gateway token>
CHARACTER_RUNTIME_URL=ws://127.0.0.1:8765
CHARACTER_RUNTIME_AGENT=joi
CHARACTER_RUNTIME_TIMEOUT_S=35
RUNTIME_LLM_TIMEOUT=30
GATEWAY_PORT=8081
STUDIO_PORT=8899
RUNTIME_SOCIAL=false
LIVE_TUNNEL_PROVIDER=none
TAVUS_SYNC_ON_START=false
```

`SOULFORGE_USER_ID` optionally selects the existing user for this installation;
the Runtime identity helper otherwise derives a stable user for the brand.
These are trusted installation settings. An external OpenAI `user` field is
only a conversation label, never authority to access another end user's memory.

The response time limits are nested: gateway waits up to 35 seconds for Runtime
(`CHARACTER_RUNTIME_TIMEOUT_S`), Runtime allows 30 seconds for a decision
(`RUNTIME_LLM_TIMEOUT`), and its AI Core HTTP client allows 25 seconds
(`SOULFORGE_COGNITION_TIMEOUT_S`). AI Core's provider `LLM_TIMEOUT` is a separate
setting. These limits bound waiting; they do not guarantee provider latency.

Runtime persists pending memory writes to a SQLite disk queue before accepting
them. `SOULFORGE_MEMORY_OUTBOX` can select its file; otherwise Runtime uses
`outputs/runtime-memory/<brand UUID>/<user UUID>/outbox.sqlite3`, relative to the
repository root. After a restart it reloads unacknowledged writes and retries
delivery to AI Core in order. Keep this file across restarts; its ownership is
checked against the configured brand/user. Runtime `/health/providers` reports
`durable_outbox`, `pending_writes`, and write errors. A local queued write is not
yet proof that PostgreSQL has acknowledged it.

```bash
./scripts/live-up.sh --check   # configuration validation; no services/providers invoked
./scripts/live-up.sh status    # read-only health checks
./scripts/live-up.sh           # foreground supervisor; Ctrl-C cleans up owned children
```

Postgres and Redis must already be running with the current schema. This
launcher does not run migrations or stop/reuse existing listeners.
With `SELFHOST_MEDIA_ENABLED=true`, it also starts the independently installed
`packages/media-body` service on port 8902. Install it first with
`scripts/selfhost-up.sh --install`. Its supervisor health check is process
liveness only; `scripts/selfhost-up.sh --status` checks GPU readiness separately.
Windows GPU and MacBook migration steps are in
[the migration guide](macbook-windows-5080.md).
An occupied port aborts before starting anything. On startup it waits for each
service's HTTP health, including ai-core database and Redis connectivity. A
child failure stops only processes created by this supervisor. PID metadata
and private service logs are under `outputs/live-stack/`; stale PID files are
never used as permission to kill a process. Dependency health does not certify
that a paid model call or microphone playback has succeeded.
Port checks use `SO_REUSEADDR` so recently closed connections in `TIME_WAIT` do
not masquerade as an active listener. Cloudflare URL persistence, described
below, is the launcher's deliberate `.env` update; configuration checks make no
writes and do not start tunnels or synchronize Tavus.

`outputs/live-stack/supervisor.lock` intentionally remains on disk after exit.
Ownership is an OS advisory lock on its open file descriptor, not the file's
existence or the PID metadata in `state.json`. The OS releases it on normal
exit, crashes, and `SIGKILL`; child services do not inherit it. The next launch
reuses the same file and replaces stale state without manual deletion. Never
delete a live supervisor's lock file: replacing its inode can defeat mutual
exclusion. If an abnormally terminated supervisor left child services alive,
their occupied ports still block startup safely; deleting lock/state files
cannot free those ports and the launcher will not kill those processes.

`GET /health/providers` on Studio combines central Runtime health with AI Core's
observed LLM/ASR/TTS records, using service credentials only on the server.
Unavailable/invalid Runtime health returns `unavailable` and HTTP 503. An
unreachable AI Core appears as an explicit unavailable provider while the
Runtime connection remains visible. Uncalled providers remain `unknown`; health
reads never trigger a model call. The shared indicator shows active fallback in
red, unknown/disconnected state in yellow, and confirmed healthy state in green.

## External video faces

The gateway requires `Authorization: Bearer <GATEWAY_API_TOKEN>` for
`POST /v1/chat/completions` and `POST /admin/runtime-agent`, including development.
An absent configured token returns 503; missing/invalid authorization returns
401. Read-only gateway health remains available. A failed Runtime request
returns a failure instead of a successful stock reply. OpenAI SSE framing
currently splits a completed decision into chunks; it is not token streaming.

The browser does not receive this token. Joi changes character through
`POST /api/runtime/agent` on Studio. This fixed-purpose route requires a local
same-origin browser, validates an installed character, reloads the local
Runtime roster, then calls the gateway with the server token. A refusal stays
visible as a failed switch instead of displaying a successful handover.

For an optional tunnel, install and authenticate `ngrok` or `cloudflared`, then
set `LIVE_TUNNEL_PROVIDER` accordingly. `LIVE_TUNNEL_PORT` defaults to 8091.
The tunnel targets an HTTP-only local relay whose route allowlist is exactly
`/health` and `/v1/chat/completions`; it does not expose development `/ws`,
Runtime `/control`, gateway `/admin`, or Studio. The relay forwards the caller's
Bearer token and never adds its own privilege. `NGROK_DOMAIN` may specify an
already allocated domain.

For `cloudflared`, startup reads only the new portion of
`outputs/live-stack/tunnel.log`, waits up to 60 seconds for the current
`https://*.trycloudflare.com` URL, and writes it to `TAVUS_PUBLIC_BASE_URL` in root
`.env` (permissions `0600`). An old URL from a previous run is not reused. This
discovers the URL; it does not certify public DNS/routing or Tavus connectivity.
The quick tunnel uses an explicit empty `outputs/live-stack/cloudflared-quick.yml`
so unrelated ingress rules in `~/.cloudflared/config.yml` cannot override the
relay target. Existing named-tunnel configuration is left intact.
For ngrok, configure `TAVUS_PUBLIC_BASE_URL` to the public origin yourself.

With a tunnel enabled, `TAVUS_SYNC_ON_START=true` runs `tavus_setup.py sync` after
the tunnel starts. Configure an existing `TAVUS_PAL_ID` and `TAVUS_API_KEY` first;
the PAL ID may also come from the existing `outputs/tavus.json` state. Sync only
patches the existing PAL's custom LLM connection, verifies it by reading back,
and preserves the other PAL fields. It does not create a PAL or conversation.
A rejected patch fails startup without forcing an overwrite. Keep the flag
`false` for local startup without this external configuration change.

```bash
.venv/bin/python scripts/tavus_setup.py --check  # configuration only
.venv/bin/python scripts/tavus_setup.py sync     # update an existing PAL connection only
.venv/bin/python scripts/tavus_setup.py up       # creates paid external resources
```

Tavus setup reads `TAVUS_API_KEY`, `GATEWAY_API_TOKEN` and
`TAVUS_PUBLIC_BASE_URL` from root `.env`/environment. It uses the protected
Runtime endpoint and disables speculative inference, because speculative
requests must not create extra persistent decisions. API keys are not printed.
`up` is an explicit external action and is never run by the launcher. `sync`
contacts Tavus only when explicitly requested or enabled with the startup flag.
