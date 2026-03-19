# Tiresias

> **This project has moved to [saluca-labs](https://github.com/saluca-labs).** This repo is now maintained at [`saluca-labs/tiresias-core`](https://github.com/saluca-labs/tiresias-core). Please update your remotes:
> ```bash
> git remote set-url origin https://github.com/saluca-labs/tiresias-core.git
> ```


**AI observability proxy — model-agnostic, self-hosted, production-ready.**

> "Tiresias sees all AI interactions, regardless of which model is speaking."

## What is Tiresias?

Tiresias is an open-source AI observability proxy. Drop it between your application
and any LLM provider (OpenAI, Anthropic, Gemini, Groq) to get:

- Full request/response logging with envelope encryption
- Token cost tracking and budget alerts
- Multi-provider routing with automatic failover
- API analytics for non-LLM APIs (Stripe, Twilio, etc.)
- License-gated enterprise features (BYOK, Aletheia security context)

**Self-hosted in under 10 minutes.** Single Docker Compose command.

## Quickstart

```bash
git clone https://github.com/cristian/tiresias
cd tiresias
cp .env.example .env   # set TIRESIAS_TENANT_ID and your API keys
docker compose up -d
# Proxy: http://localhost:8080  Dashboard: http://localhost:3000
```

Point your OpenAI SDK at `http://localhost:8080/v1` — no code changes required.

## Competitor Comparison

| Feature | Tiresias | LangSmith | Helicone | Langfuse | Datadog LLM | Portkey |
|---------|----------|-----------|----------|----------|-------------|---------|
| Self-hosted | YES | No | Partial | YES | No | No |
| Model-agnostic | YES | Partial | YES | YES | YES | YES |
| Envelope encryption (BYOK) | YES (ent) | No | No | No | No | No |
| Multi-provider failover | YES | No | No | No | No | YES |
| Non-LLM API analytics | YES | No | No | No | Yes | No |
| Open source (core) | Apache 2.0 | MIT | Apache 2.0 | MIT | Closed | Closed |
| License relay (air-gap) | YES (ent) | No | No | No | No | No |
| Aletheia security context | YES (ent) | No | No | No | No | No |

## Module Structure

| Module | License | Description |
|--------|---------|-------------|
| `tiresias-core` | Apache 2.0 | Proxy, dashboard, analytics, multi-provider routing |
| `tiresias-enterprise` | Commercial | BYOK, license system, Aletheia integration |

## Enterprise

Contact enterprise@saluca.com for BYOK encryption, Aletheia security context injection,
air-gapped license relay, and MSSP/partner licensing.

---

*Built by Saluca LLC. Apache 2.0 core. Enterprise tier available.*