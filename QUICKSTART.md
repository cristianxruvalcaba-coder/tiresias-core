# Tiresias — Quickstart

From clone to first dashboard data in under 10 minutes.

## Prerequisites

- Docker + Docker Compose v2
- A Tiresias license token (get one at https://tiresias.saluca.com)
- At least one AI provider API key (OpenAI or Anthropic)

## Steps

### 1. Clone and configure (2 min)

```bash
git clone https://github.com/cristianxruvalcaba-coder/tiresias-core.git
cd tiresias
cp .env.example .env
```

Edit `.env` and set at minimum:
```
TIRESIAS_LICENSE_TOKEN=<your-license-token>
OPENAI_API_KEY=<your-openai-key>
ENCRYPTION_KEY=<32-byte-hex>  # python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Start all services (1 min)

```bash
docker compose up -d
```

Services:
| Service | URL | Purpose |
|---------|-----|---------|
| Proxy | http://localhost:8080 | Drop-in OpenAI-compatible endpoint |
| Dashboard | http://localhost:3000 | Analytics, replay, cost breakdown |
| Relay | http://localhost:8090 | License renewal relay (internal) |

### 3. Point your app at Tiresias (1 min)

Replace your OpenAI base URL with the Tiresias proxy:

```python
# Python (openai SDK)
from openai import OpenAI
client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="any-value",  # Tiresias uses your provider key from env
)
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello from Tiresias!"}],
)
print(response.choices[0].message.content)
```

### 4. View the dashboard (30 sec)

Open http://localhost:3000 — you'll see the request, token count, cost, and latency.

## Port overrides

Change ports without editing YAML:

```bash
PROXY_PORT=9090 DASHBOARD_PORT=4000 docker compose up -d
```

## Troubleshooting

**Container fails to start:**
- Check `TIRESIAS_LICENSE_TOKEN` is set and not expired
- Run `docker compose logs proxy` for details

**Renewal fails in airgapped environment:**
- Set `TIRESIAS_RELAY_URL=http://relay:8090/v1/relay/renew` to use the bundled relay
- Or set `HTTPS_PROXY=http://your-proxy:3128` for corporate proxy pass-through

**View logs:**
```bash
docker compose logs -f proxy
docker compose logs -f dashboard
```

**Stop:**
```bash
docker compose down
```

## Health checks

```bash
curl http://localhost:8080/health   # proxy
curl http://localhost:3000/health   # dashboard
curl http://localhost:8090/health   # relay
```

## Support

- Docs issues / questions: open a [GitHub issue](https://github.com/cristianxruvalcaba-coder/tiresias-core/issues)
- Email: support@saluca.com
- Enterprise: enterprise@saluca.com
