# SentinelCorp — Railway Deployment Guide

This guide walks through deploying SentinelCorp to Railway in ~5 minutes.

## Prerequisites

- Railway account (free tier works)
- GitHub account connected to Railway

## Option A: Deploy in existing Railway project (alongside SentinelX402)

**Recommended** if you already have a Railway project with SentinelX402. You can share the same PostgreSQL instance.

### Step 1: Add new service to existing project

1. Go to [railway.app/dashboard](https://railway.app/dashboard)
2. Open your existing project (the one running SentinelX402)
3. Click **"+ New"** in the top-right → **"GitHub Repo"**
4. Select **`splitfireai-hue/sentinelcorp`**
5. Railway auto-detects the Dockerfile and starts building

### Step 2: Configure environment variables

Click the **new SentinelCorp service** → **Variables** tab. Add:

```
ENVIRONMENT=production
FREE_TIER_ENABLED=true
FREE_TIER_REQUESTS=1000
PORT=8080
```

### Step 3: Connect to shared PostgreSQL (optional but recommended)

If your project already has a Postgres service:

1. In the **SentinelCorp service → Variables** tab
2. Click **"+ New Variable" → "Reference"**
3. Select the **Postgres service → DATABASE_URL**
4. Rename it to `DATABASE_URL`
5. Change the value prefix from `postgresql://` to `postgresql+asyncpg://`

If you want a **separate database** (cleaner isolation):
- Use the default SQLite — it writes to a persistent volume
- Or add a new Postgres service: **+ New → Database → PostgreSQL** (same steps as SentinelX402 setup)

### Step 4: Generate public domain

1. SentinelCorp service → **Settings → Networking**
2. Click **"Generate Domain"**
3. Set port to **`8080`**
4. You'll get a URL like `sentinelcorp-production-xxxx.up.railway.app`

### Step 5: Verify deployment

```bash
# Replace YOUR_URL with the domain Railway gave you
curl https://YOUR_URL/health
curl https://YOUR_URL/info
curl https://YOUR_URL/api/v1/validate/gstin?gstin=27AAACT1234A1Z1
curl "https://YOUR_URL/api/v1/company/profile?identifier=Sahara+India&type=name"
```

Expected:
- `/health` → `{"status":"ok"}`
- `/info` → full endpoint list
- `/api/v1/validate/gstin` → validation result
- `/api/v1/company/profile?identifier=Sahara+India` → risk score 85.5, level `critical`

### Step 6: Update API_URL in integrations

Once you have the deployed URL, the integrations auto-pick it up via env var. Just set in Railway (or pass to clients):

```
SENTINELCORP_API_URL=https://YOUR_URL
```

## Option B: Deploy as separate Railway project

1. Go to [railway.app/dashboard](https://railway.app/dashboard)
2. Click **"New Project" → "Deploy from GitHub repo"**
3. Select **`splitfireai-hue/sentinelcorp`**
4. Railway creates a new project with one service
5. Follow steps 2-6 above

## Post-deployment checks

- [ ] `/health` returns 200
- [ ] `/info` shows correct endpoint list
- [ ] `/docs` Swagger UI loads
- [ ] `/api/v1/validate/gstin` returns valid parsing
- [ ] `/api/v1/company/profile?identifier=Sahara+India` returns high risk
- [ ] `/api/v1/debarred/search?name=mallya` returns matches
- [ ] `/stats` shows 14,858 debarred entities loaded

## First-boot behavior

The Dockerfile CMD:
1. Runs `app.scrapers.sebi_defaulters` — fetches fresh OpenSanctions data (~4MB, 14K entities)
2. Runs `app.data.seed_debarred` — loads data into DB
3. Starts gunicorn

First boot takes ~30-60 seconds. Subsequent deploys skip re-scraping if file exists.

## Troubleshooting

**Build fails**
- Check Railway logs for Python version mismatch (project needs 3.9+)
- Dockerfile uses `python:3.11-slim` — should always work

**Healthcheck fails after deploy**
- Verify Port is set to 8080 in Networking
- Check deploy logs for DB connection errors

**Scraper fails**
- Railway may need egress enabled (usually default)
- If persistent, the app still boots — just with empty data
- Run manually: `railway run python -m app.scrapers.sebi_defaulters`

## Auto-deploy on git push

By default Railway auto-deploys on every push to `main`. To disable:

1. Service → **Settings → Source**
2. Toggle off **"Automatic Deployments"**

## Cost estimate

- **Free tier**: 500 hours/month of compute (enough for ~1 service running 24/7 if under $5 usage)
- **Hobby plan ($5/mo)**: unlimited compute, better for production
- **Database**: PostgreSQL is free up to 500MB (enough for SentinelCorp)

Total expected cost: **$0-5/month** for both SentinelX402 and SentinelCorp on the Hobby plan.
