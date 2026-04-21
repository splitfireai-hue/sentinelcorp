# SentinelCorp

**India Company Risk Profile API for AI Agents.**

Validate GSTIN/CIN/PAN, check SEBI debarred entities, get unified risk scores — all via a free, agent-native API. 1,000 requests, no signup.

Part of the **Sentinel Series** alongside [SentinelX402](https://github.com/splitfireai-hue/sentinelx402) (threat intelligence).

---

## What It Does

| Capability | Endpoint | What You Get |
|------------|----------|--------------|
| **GSTIN validation** | `/api/v1/validate/gstin` | Format + checksum + state + PAN extraction (<20ms) |
| **CIN validation** | `/api/v1/validate/cin` | Listing status, state, year, industry, ownership type |
| **PAN validation** | `/api/v1/validate/pan` | Format + entity type (Person/Company/HUF/Trust...) |
| **Company risk profile** | `/api/v1/company/profile` | Unified 0-100 risk score from all signals |
| **Batch profiling** | `/api/v1/company/batch` | Up to 100 companies in one request |
| **SEBI debarred search** | `/api/v1/debarred/search` | 14,000+ debarred entities (NSE/BSE/SEBI) |

---

## Why This Exists

Indian fintech, banking, audit firms, and compliance consultants waste hours per day looking up:
- Is this GSTIN valid?
- Is this company on a SEBI defaulter list?
- What's the risk profile of this entity?

AI agents can now do this in one API call.

**Example:**
```bash
curl "https://YOUR_API/api/v1/company/profile?identifier=Sahara+India"
```

Returns:
```json
{
  "query": "Sahara India",
  "overall_risk_score": 66.5,
  "risk_level": "high",
  "is_debarred": true,
  "debarred_matches": [
    {"matched_name": "M/s Sahara India (and its constituent partners)", "confidence": 1.0, "source": "opensanctions:nse"}
  ],
  "signals": [{"source": "sebi", "signal_type": "sebi_debarred", "severity": "critical"}]
}
```

---

## Quickstart

### curl

```bash
# Validate a GSTIN
curl "https://YOUR_API/api/v1/validate/gstin?gstin=27AAACT1234A1Z5"

# Get company risk profile (auto-detects CIN/GSTIN/PAN/name)
curl "https://YOUR_API/api/v1/company/profile?identifier=L17110MH1973PLC019786"

# Search SEBI debarred list
curl "https://YOUR_API/api/v1/debarred/search?name=sahara"

# Batch 100 companies
curl -X POST "https://YOUR_API/api/v1/company/batch" \
  -H "Content-Type: application/json" \
  -d '{"identifiers": ["Sahara", "Tata", "Reliance"]}'
```

### Python SDK

```bash
pip install sentinelcorp
```

```python
from sentinelcorp import SentinelCorp

client = SentinelCorp()
profile = client.profile("Sahara India")
print(profile["overall_risk_score"])  # 66.5
print(profile["is_debarred"])          # True
```

### LangChain

```python
from integrations.langchain_tool import get_sentinelcorp_tools

tools = get_sentinelcorp_tools()
agent = initialize_agent(tools, llm)
agent.run("Is Sahara India a high-risk company for us to partner with?")
```

### MCP (Claude, Cursor)

```json
{
  "mcpServers": {
    "sentinelcorp": {
      "command": "python",
      "args": ["integrations/mcp_server.py"]
    }
  }
}
```

---

## Use Cases

### 1. KYB Automation (Know Your Business)
Before onboarding a vendor/customer, check their Indian identifiers and sanction status in one call.

### 2. Due Diligence at Scale
Batch-check 100 companies against SEBI debarred list in a single request.

### 3. Fraud Detection
Validate GSTINs on incoming invoices — catch fake GSTINs instantly with checksum verification.

### 4. Compliance Monitoring
Daily cron job checking your vendor list against updated SEBI debarred entities.

### 5. AI Agent Due Diligence
Your AI compliance agent can now verify Indian counterparties autonomously.

---

## Data Sources

| Source | Coverage | Legal Status |
|--------|----------|--------------|
| **SEBI/NSE/BSE debarred** | 14,858 entities | Public (via OpenSanctions) |
| **GSTIN validation** | All Indian GSTINs | Pure algorithmic (Luhn mod-36) |
| **CIN validation** | All Indian companies | Pure algorithmic + metadata extraction |
| **PAN validation** | All PANs | Pure algorithmic |

Future additions (with proper licensing):
- MCA V3 lookup (via Surepass/APIclub)
- Court records (via IndianKanoon API + openjustice-in/ecourts)
- GSTIN live lookup (via Jamku/KnowYourGST)
- Udyam MSME registry
- IBBI/NCLT bankruptcy orders

---

## Architecture

```
sentinelcorp/
├── app/
│   ├── main.py                  # FastAPI app + middleware
│   ├── config.py                # Environment configuration
│   ├── database.py              # Async SQLAlchemy
│   ├── models/                  # DB models
│   ├── schemas/                 # Pydantic schemas
│   ├── routers/                 # API endpoints
│   ├── services/                # Business logic
│   │   ├── validators.py        # GSTIN/CIN/PAN (pure algorithmic)
│   │   ├── risk_scoring.py      # Noisy-OR signal combination
│   │   └── risk_service.py      # Orchestration
│   ├── scrapers/                # Data ingestion
│   │   └── sebi_defaulters.py   # OpenSanctions NSE data
│   └── data/                    # Seed scripts
├── sdk/sentinelcorp/            # Python SDK (sync + async)
├── integrations/                # Agent framework integrations
│   ├── langchain_tool.py
│   ├── crewai_tool.py
│   ├── openai_functions.py
│   └── mcp_server.py
├── tests/                       # 25 tests
├── Dockerfile                   # Production container
└── mcp.json                     # Agent discovery metadata
```

---

## Tech Stack

- **Backend**: FastAPI + Uvicorn/Gunicorn
- **Database**: SQLite (dev) / PostgreSQL (prod)
- **Validation**: Pure Python checksums (no external calls)
- **Data sources**: OpenSanctions (NSE debarred), scrapers for public gov data
- **Integrations**: LangChain, CrewAI, OpenAI, MCP, Python SDK

---

## Free Tier

- **1,000 requests** per client — no signup, no API key
- **60 req/min** rate limit per endpoint
- **Batch**: 100 identifiers per request
- After free tier: register for free API key with 10K/month quota

---

## License

AGPL-3.0. The reference risk scoring implementation is public; the production-tuned weights, additional data sources, and proprietary integrations remain on the hosted API.

---

## Related Products

- **[SentinelX402](https://github.com/splitfireai-hue/sentinelx402)** — Threat intelligence API for AI agents, with CERT-In India advisories

Use both together for complete India due diligence coverage (threats + company risk).
