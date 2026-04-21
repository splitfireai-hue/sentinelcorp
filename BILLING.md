# SentinelCorp — Billing & Payments Setup

Turn on paid tiers via Razorpay (India UPI/cards) + Stripe (global cards).

## Tiers

| Tier | INR/mo | USD/mo | Requests/mo | Rate limit |
|---|---|---|---|---|
| Free (signup) | ₹0 | $0 | 5,000 | 30 req/min |
| Dev | ₹499 | $6 | 50,000 | 120 req/min |
| Startup | ₹2,499 | $30 | 500,000 | 600 req/min |
| Enterprise | Custom | Custom | Custom | Custom |

Anonymous (no key): 100 req/day per IP — enough to try, not run on.

## Turn billing on

Set in Railway → Variables:

```
BILLING_ENABLED=true
ADMIN_SECRET=<long random string>
PUBLIC_BASE_URL=https://sentinelcorp-production.up.railway.app
```

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
