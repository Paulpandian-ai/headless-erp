# Deployment (Railway)

Non-AWS by policy (DESIGN.md §16). Target: Railway with its Postgres plugin. `railway.json` at the
repository root builds `deploy/Dockerfile` and starts the service with `anerp migrate && anerp serve`,
so migrations always run before the server and never at request time.

## Variables

Railway injects `DATABASE_URL` (plain `postgresql://`), `PORT` and `RAILWAY_PUBLIC_DOMAIN`; anerp
accepts all three when the `ANERP_*` equivalents are unset and rewrites the database scheme to
`postgresql+psycopg://`. Set on the service:

| Variable | Required | Notes |
|---|---|---|
| `ANERP_ENV` | yes | `dev` (allows `reset_and_seed`) or `demo` / `prod` |
| `ANERP_TOKEN_PEPPER` | yes | random 32+ bytes; changing it invalidates every token |
| `ANERP_BOOTSTRAP_ADMIN_TOKEN` | first start | `uv run anerp token bootstrap` prints one; revoke it after minting your own |
| `ANERP_SIGNING_KEY_PEM` | no | when unset an Ed25519 key is generated on first start and kept in `server_key` |
| `ANERP_PUBLIC_URL` | no | defaults to `https://$RAILWAY_PUBLIC_DOMAIN` (Agent Card, well-known documents) |
| `LLM_PROVIDER` + key | no | only for the A2A agent's LLM loop |

## Steps

1. Create a Railway project from this repository and add the Postgres plugin (it sets `DATABASE_URL`).
2. Set the variables above. Generate a public domain for the service (Settings > Networking).
3. Every push to `main` deploys (Railway's GitHub integration); `GET /healthz` is the health check.
4. From Claude Code: `claude mcp add --transport http anerp https://<domain>/mcp --header "Authorization: Bearer $ANERP_ADMIN_TOKEN"`,
   then `mint_token` your personal admin token and `revoke_token` on `admin:bootstrap`.
5. Backups: rely on Railway Postgres backups. Restore drill: restore into a new database, point
   `DATABASE_URL` at it, redeploy, verify `get_system_status` and `get_trial_balance`.

Local image check: `docker build -f deploy/Dockerfile . && docker run --rm -e ANERP_ENV=dev -e ANERP_DATABASE_URL=sqlite:////tmp/a.db -e ANERP_TOKEN_PEPPER=x -p 8000:8000 anerp`.
