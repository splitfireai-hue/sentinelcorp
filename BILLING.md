# Sentinel Series — Billing & Payments Setup

Turn on paid tiers via Razorpay (India UPI/cards) + Stripe (global cards) + x402 (USDC for agents). One API key works on both **SentinelCorp** and **SentinelX402**.

> **Architecture**: SentinelCorp owns the issuance side — signup, checkout, webhooks, dashboard. SentinelX402 reuses the same `api_keys` and `usage_counters` tables (shared Postgres) to validate keys and track per-product usage. Each request to either service hits its own quota counter, but the underlying tier and limits come from one place.

## Tiers

| Tier | INR/mo | USD/mo | Requests/mo | Rate limit |
|---|---|---|---|---|
| Free (signup) | ₹0 | $0 | 5,000 | 30 req/min |
| Dev | ₹499 | $6 | 50,000 | 120 req/min |
| Startup | ₹2,499 | $30 | 500,000 | 600 req/min |
| Enterprise | Custom | Custom | Custom | Custom |

Anonymous (no key): 100 req/day per IP — enough to try, not run on.

## Turn billing on (BOTH services share the same Postgres)

### On the SentinelCorp Railway service

```
BILLING_ENABLED=true
BILLING_PRODUCT=sentinelcorp
ADMIN_SECRET=<long random string>
PUBLIC_BASE_URL=https://sentinelcorp-production.up.railway.app
DATABASE_URL=<reference Postgres service in Railway>
```

### On the SentinelX402 Railway service

Point at the **same** Postgres service (Railway → Variables → "+ New Variable" → "Reference" → pick the Postgres' `DATABASE_URL`):

```
BILLING_ENABLED=true
BILLING_PRODUCT=sentinelx402
PUBLIC_BASE_URL=https://sentinelx402-production.up.railway.app
DATABASE_URL=<same Postgres reference as sentinelcorp>
```

You do **not** need to set `RAZORPAY_*` / `STRIPE_*` on SentinelX402 — checkout and webhooks only run on the SentinelCorp service. SentinelX402 just validates keys.

Generate `ADMIN_SECRET` with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.

Without rails configured, `/signup` still works (free tier) and paid checkout returns 503. Good for a soft launch.

---

## Razorpay (India — UPI/cards/netbanking)

### 1. Create account
- [dashboard.razorpay.com](https://dashboard.razorpay.com) → sign up
- Start in **test mode** (toggle top right). Switch to live after KYC.

### 2. Create plans
- Dashboard → **Subscriptions → Plans → + New Plan**
- Plan 1: `SentinelCorp Dev` — ₹499/month, billing cycle 1 month
- Plan 2: `SentinelCorp Startup` — ₹2,499/month, billing cycle 1 month
- Copy the `plan_id` of each (format `plan_XXXX`)

### 3. Get API keys
- Dashboard → **Settings → API Keys → Generate**
- Copy `Key ID` (starts `rzp_test_` or `rzp_live_`) and `Key Secret`

### 4. Configure webhook
- Dashboard → **Settings → Webhooks → + Add New**
- URL: `https://sentinelcorp-production.up.railway.app/billing/webhooks/razorpay`
- Secret: generate a long random string — you'll set it in Railway
- Active events:
  - `subscription.activated`
  - `subscription.charged`
  - `subscription.cancelled`
  - `subscription.halted`
  - `subscription.completed`

### 5. Set Railway env vars

```
RAZORPAY_KEY_ID=rzp_test_XXXXXXXX
RAZORPAY_KEY_SECRET=XXXXXXXX
RAZORPAY_WEBHOOK_SECRET=<what you set in step 4>
RAZORPAY_PLAN_DEV=plan_XXXX
RAZORPAY_PLAN_STARTUP=plan_YYYY
```

### 6. Test
- Visit `https://YOUR_URL/pricing` → "India (INR)" tab shows Subscribe buttons
- Click Subscribe → enter test card `4111 1111 1111 1111`, any CVV, any future expiry
- Razorpay's test UPI: enter `success@razorpay` as VPA
- Webhook should fire; check Railway logs for `Razorpay: activated sub=...`
- Confirm with `curl -H "X-API-Key: <your_key>" https://YOUR_URL/billing/me` — tier should be `dev` or `startup`

---

## Stripe (global — cards)

### 1. Create account
- [dashboard.stripe.com](https://dashboard.stripe.com) → sign up
- Indian users: Stripe requires a foreign entity (Stripe Atlas, or a Delaware C-Corp) OR use LemonSqueezy as an alternative merchant-of-record
- Start in **test mode**

### 2. Create products + prices
- Dashboard → **Products → + Add product**
- Product 1: `SentinelCorp Dev` — recurring, $6/month USD → copy `price_XXXX`
- Product 2: `SentinelCorp Startup` — recurring, $30/month USD → copy `price_YYYY`

### 3. Get API keys
- Dashboard → **Developers → API keys**
- Copy **Secret key** (`sk_test_...` or `sk_live_...`)
- (Optional) Copy **Publishable key** for future client-side use

### 4. Configure webhook
- Dashboard → **Developers → Webhooks → + Add endpoint**
- URL: `https://sentinelcorp-production.up.railway.app/billing/webhooks/stripe`
- Events to send:
  - `checkout.session.completed`
  - `customer.subscription.created`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.payment_failed`
- After creation, reveal the **Signing secret** (`whsec_...`)

### 5. Set Railway env vars

```
STRIPE_SECRET_KEY=sk_test_XXXXXXXX
STRIPE_PUBLISHABLE_KEY=pk_test_XXXXXXXX
STRIPE_WEBHOOK_SECRET=whsec_XXXXXXXX
STRIPE_PRICE_DEV=price_XXXX
STRIPE_PRICE_STARTUP=price_YYYY
```

### 6. Test
- Visit `https://YOUR_URL/pricing` → "Global (USD)" tab
- Click Subscribe → redirected to Stripe Checkout
- Test card: `4242 4242 4242 4242`, any future expiry, any CVV
- After success, you'll be redirected back to `/billing/success`
- Webhook fires; confirm with `/billing/me` that tier upgraded

---

---

## x402 (per-call USDC for autonomous agents)

x402 is the third payment rail. Subscriptions don't fit autonomous agents — an agent that runs once a week shouldn't sign up and remember a credential. x402 lets the agent pay USDC per call.

### When to enable

- You want self-driving agents to use the API without any human signup
- You have a USDC wallet and want micropayments to flow there
- Subscription customers are still served via API key — x402 is additive

### 1. Get a wallet
- Use any EVM wallet (Coinbase, MetaMask, Rabby) on **Base mainnet** (or Base Sepolia for test)
- Copy the address — agents will pay USDC to this address

### 2. Set Railway env vars

```
X402_ENABLED=true
X402_WALLET_ADDRESS=0xYourWalletHere
X402_NETWORK_ID=eip155:8453        # Base mainnet (or eip155:84532 for Sepolia)
X402_FACILITATOR_URL=https://x402.org/facilitator
# Per-call prices (defaults are conservative)
X402_PRICE_VALIDATE=$0.005
X402_PRICE_PROFILE=$0.01
X402_PRICE_DEBARRED=$0.005
X402_PRICE_BATCH=$0.10
```

### 3. Confirm

After redeploy, hit a paid endpoint **without** an API key:

```bash
curl -i "https://YOUR_URL/api/v1/company/profile?identifier=Sahara+India"
```

You should get `HTTP/1.1 402 Payment Required` with a JSON body containing payment requirements (wallet, amount, scheme). An x402-aware agent will see this, sign a USDC payment with EIP-3009, and retry with the `X-PAYMENT` header.

### How it interacts with API keys

- Request has valid `X-API-Key` → billing logic runs (key tier, monthly quota). x402 is bypassed.
- Request has no key + `X402_ENABLED=true` → x402 middleware demands payment.
- Request has no key + `X402_ENABLED=false` → anonymous trial bucket (100/day per IP).

### Caveats

- The `x402[fastapi,evm]>=0.1.0` SDK requires Python 3.10+. Railway's container is 3.11 so this is fine.
- The Dockerfile installs x402 as best-effort (`|| echo`) — if PyPI is unreachable at build time the image still ships, x402 just won't load. Toggle off and on for diagnostics.
- Test mode: use `eip155:84532` (Base Sepolia) to avoid spending real USDC during dev.

---

## Ops cheat sheet

### Issue a key manually (give someone a free premium account)

```bash
curl -X POST https://YOUR_URL/billing/admin/keys \
  -H "X-Admin-Secret: $ADMIN_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"email":"vip@example.com","tier":"startup","notes":"Partner comp"}'
```

Response includes the raw key — email it to them, never shown again.

### Upgrade someone's tier

```bash
curl -X PATCH https://YOUR_URL/billing/admin/keys/42/tier \
  -H "X-Admin-Secret: $ADMIN_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"tier":"startup"}'
```

### Revoke a key (abuse, chargeback)

```bash
curl -X DELETE https://YOUR_URL/billing/admin/keys/42 \
  -H "X-Admin-Secret: $ADMIN_SECRET"
```

### Check a customer's usage

```bash
curl -H "X-API-Key: <their_key>" https://YOUR_URL/billing/me
```

---

## Gotchas

- **Razorpay subscriptions require KYC** before live mode. Test mode works immediately.
- **Stripe from India**: direct Stripe India accounts have restrictions (no international cards). Use Stripe Atlas, a foreign entity, or [LemonSqueezy](https://lemonsqueezy.com) as merchant-of-record.
- **Webhook failures** leave subscriptions in `pending` state — customer has a free-tier key until the webhook lands. Monitor `/billing/admin/keys?status=pending` in logs.
- **Test mode keys** (`rzp_test_` / `sk_test_`) only work against test mode subscriptions. Don't mix.
- **Currency**: the system issues ONE key per subscription. A customer subscribing with INR and USD separately gets two keys. Dedup by email if needed.

---

## Monitoring billing

- **Successful activations**: grep logs for `Razorpay: activated` or `Stripe: checkout complete`
- **Failed webhooks**: both providers retry. Check dashboards for webhook delivery logs.
- **Revenue**: Razorpay Dashboard → Reports, Stripe Dashboard → Payments
