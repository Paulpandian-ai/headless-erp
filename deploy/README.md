# Deployment

Non-AWS by policy (DESIGN.md §16). Reference target: Fly.io + Neon/Supabase Postgres.

1. `flyctl apps create anerp-dev` and `flyctl apps create anerp-demo`; create one Postgres database per app.
2. Set secrets on each app: `ANERP_DATABASE_URL`, `ANERP_TOKEN_PEPPER`, `ANERP_BOOTSTRAP_ADMIN_TOKEN`,
   `ANERP_SIGNING_KEY_PEM` (`uv run anerp keygen`), `ANERP_PUBLIC_URL`, and LLM keys if the A2A agent needs them.
3. Add `FLY_API_TOKEN` to GitHub Actions secrets. Push to `main` deploys dev; tag `v*` deploys demo.
4. Migrations run in the Fly release command (`anerp migrate`), never at request time.
5. Backups: rely on the provider's point-in-time recovery. Restore drill: create a branch/restore of the
   database at the target time, point `ANERP_DATABASE_URL` at it, redeploy, verify `get_system_status`
   and `get_trial_balance`.
