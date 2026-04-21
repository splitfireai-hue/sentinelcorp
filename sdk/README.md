# SentinelCorp Python SDK

```python
from sentinelcorp import SentinelCorp

client = SentinelCorp(base_url="https://sentinelcorp-production.up.railway.app")

# Get company risk profile (auto-detects CIN/GSTIN/PAN/name)
profile = client.profile("Sahara India")
print(profile["overall_risk_score"])  # 66.5
print(profile["risk_level"])          # "high"
print(profile["is_debarred"])         # True

# Validate formats (fast, no external calls)
v = client.validate_gstin("27AAACT1234A1Z5")
print(v["is_valid"], v["parsed"]["state_name"])

# Batch (up to 100 companies)
result = client.batch(["Sahara", "Tata", "Reliance"])

# Debarred search
matches = client.search_debarred("sharma")
```

## Async

```python
import asyncio
from sentinelcorp import AsyncSentinelCorp

async def main():
    async with AsyncSentinelCorp() as client:
        profile = await client.profile("L17110MH1973PLC019786")
        print(profile)

asyncio.run(main())
```

## Install

```bash
pip install sentinelcorp
```

## Features

- **Format validation** — GSTIN (with checksum), CIN, PAN
- **SEBI debarred search** — 14,000+ debarred entities
- **Unified risk scoring** — 0-100 score combining all signals
- **Batch processing** — up to 100 lookups per request
- **Sync & async clients**
- **Free tier** — 1,000 requests, no signup

Part of the Sentinel Series alongside [SentinelX402](https://github.com/splitfireai-hue/sentinelx402) (threat intel).
