from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.bootstrap import first_boot
from tiresias.config import TiresiasSettings, parse_providers
from tiresias.encryption.envelope import EnvelopeEncryption
from tiresias.encryption.providers import resolve_kek_provider
from tiresias.proxy.interceptor import record_error_turn, record_turn
from tiresias.providers import build_provider
from tiresias.providers.health import HealthTracker
from tiresias.providers.router import ProviderCascadeExhausted, ProviderRouter
from tiresias.storage.engine import get_engine
from tiresias.tracking.sessions import parse_session_id

logger = logging.getLogger(__name__)

_settings: TiresiasSettings | None = None
_envelope: EnvelopeEncryption | None = None
_http_client: httpx.AsyncClient | None = None
_router: ProviderRouter | None = None
_health: HealthTracker | None = None


def get_settings() -> TiresiasSettings:
    if _settings is None:
        raise RuntimeError("App not initialized")
    return _settings


def get_envelope() -> EnvelopeEncryption:
    if _envelope is None:
        raise RuntimeError("App not initialized")
    return _envelope


def get_http_client() -> httpx.AsyncClient:
    if _http_client is None:
        raise RuntimeError("App not initialized")
    return _http_client


def get_router() -> ProviderRouter:
    if _router is None:
        raise RuntimeError("App not initialized")
    return _router


def get_health() -> HealthTracker:
    if _health is None:
        raise RuntimeError("App not initialized")
    return _health


def _detect_provider(upstream_url: str) -> str:
    if "anthropic" in upstream_url:
        return "anthropic"
    if "generativelanguage" in upstream_url or "gemini" in upstream_url:
        return "gemini"
    if "groq" in upstream_url:
        return "groq"
    return "openai"


def _build_router(
    cfg: TiresiasSettings, http_client: httpx.AsyncClient
) -> tuple[ProviderRouter, HealthTracker]:
    cascade = parse_providers(cfg.providers)
    health = HealthTracker(cascade)

    single_provider_base: str | None = None
    if len(cascade) == 1:
        single_provider_base = cfg.upstream_url.rstrip("/")

    def builder(name: str):
        base = single_provider_base if (single_provider_base and len(cascade) == 1) else None
        return build_provider(name, dict(os.environ), api_base=base)

    router = ProviderRouter(
        cascade=cascade,
        health=health,
        builder=builder,
        http_client=http_client,
    )
    return router, health


def create_app(settings: TiresiasSettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global _settings, _envelope, _http_client, _router, _health
        cfg = settings or TiresiasSettings()
        _settings = cfg
        provider = resolve_kek_provider(cfg)
        _envelope = EnvelopeEncryption(provider)
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
        _router, _health = _build_router(cfg, _http_client)
        engine = await get_engine(cfg.tenant_id, cfg.data_root)
        async with AsyncSession(engine) as session:
            api_key = await first_boot(cfg.tenant_id, cfg, session)
            if api_key:
                logger.info("First boot complete. Tenant: %s", cfg.tenant_id)
        cascade = parse_providers(cfg.providers)
        logger.info(
            "Tiresias proxy started. Tenant: %s, Providers: %s",
            cfg.tenant_id,
            cascade,
        )
        yield
        if _http_client:
            await _http_client.aclose()

    app = FastAPI(
        title="Tiresias Proxy",
        description="OpenAI-compatible proxy with encrypted audit logging",
        version="0.5.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "tiresias-proxy"}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        cfg = get_settings()
        envelope = get_envelope()
        router = get_router()
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        model = body.get("model", "unknown")
        is_streaming = body.get("stream", False)
        session_id = parse_session_id(request.headers.get("x-tiresias-session-id"))
        extra_metadata = body.pop("tiresias_metadata", None)
        upstream_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ("host", "content-length", "transfer-encoding")
        }

        if is_streaming:
            upstream_url = cfg.upstream_url.rstrip("/")
            target_url = f"{upstream_url}/v1/chat/completions"
            upstream_provider = _detect_provider(upstream_url)
            client = get_http_client()
            return await _handle_streaming(
                client=client,
                target_url=target_url,
                upstream_headers=upstream_headers,
                body=body,
                tenant_id=cfg.tenant_id,
                model=model,
                provider=upstream_provider,
                session_id=session_id,
                extra_metadata=extra_metadata,
                envelope=envelope,
                settings=cfg,
            )
        else:
            return await _handle_non_streaming_router(
                router=router,
                upstream_headers=upstream_headers,
                body=body,
                tenant_id=cfg.tenant_id,
                model=model,
                session_id=session_id,
                extra_metadata=extra_metadata,
                envelope=envelope,
                settings=cfg,
            )

    @app.post("/v1/sessions/{session_id}/tag")
    async def tag_session_endpoint(session_id: str, request: Request) -> dict:
        cfg = get_settings()
        try:
            metadata = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        engine = await get_engine(cfg.tenant_id, cfg.data_root)
        async with AsyncSession(engine) as db_session:
            from tiresias.tracking.sessions import tag_session

            updated = await tag_session(session_id, metadata, db_session)
        return {"session_id": session_id, "rows_updated": updated}

    @app.get("/v1/sessions/{session_id}")
    async def get_session(session_id: str) -> dict:
        cfg = get_settings()
        engine = await get_engine(cfg.tenant_id, cfg.data_root)
        async with AsyncSession(engine) as db_session:
            from tiresias.tracking.sessions import get_session_stats

            stats = await get_session_stats(session_id, db_session)
        return stats

    @app.get("/v1/admin/providers")
    async def admin_providers() -> dict:
        h = get_health()
        cfg = get_settings()
        return {
            "cascade": parse_providers(cfg.providers),
            "providers": h.status(),
        }

    @app.post("/v1/admin/reload")
    async def admin_reload() -> dict:
        global _router, _health
        cfg = get_settings()
        new_providers_str = os.environ.get("TIRESIAS_PROVIDERS", cfg.providers)
        cfg.providers = new_providers_str  # type: ignore[assignment]
        client = get_http_client()
        _router, _health = _build_router(cfg, client)
        cascade = parse_providers(new_providers_str)
        logger.info("Provider cascade reloaded: %s", cascade)
        return {"cascade": cascade, "reloaded": True}

    # -------------------------------------------------------------------------
    # Phase 5: Generic API proxy routes (APIP-01 to APIP-04)
    # -------------------------------------------------------------------------

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def generic_api_proxy(request: Request, path: str) -> Response:
        """
        Generic reverse proxy: forward any request to TIRESIAS_UPSTREAM_URL/{path}.
        Records per-endpoint telemetry (method, path_pattern, status_code, latency).
        Activated when TIRESIAS_GENERIC_PROXY_MODE=true OR always available at /api/.
        """
        cfg = get_settings()
        client = get_http_client()
        body_bytes = await request.body()
        params = dict(request.query_params)
        upstream_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ("host", "content-length", "transfer-encoding")
        }

        from tiresias.proxy.generic import forward_generic_request

        engine = await get_engine(cfg.tenant_id, cfg.data_root)
        async with AsyncSession(engine) as db_session:
            try:
                upstream_resp = await forward_generic_request(
                    client=client,
                    upstream_url=cfg.upstream_url,
                    api_service=cfg.api_service,
                    method=request.method,
                    path=path,
                    headers=upstream_headers,
                    body_bytes=body_bytes,
                    params=params,
                    tenant_id=cfg.tenant_id,
                    db_session=db_session,
                )
            except httpx.RequestError as exc:
                raise HTTPException(status_code=502, detail=f"Upstream error: {exc}")

        resp_headers = dict(upstream_resp.headers)
        for h in ("transfer-encoding", "content-encoding", "content-length"):
            resp_headers.pop(h, None)

        return Response(
            content=upstream_resp.content,
            status_code=upstream_resp.status_code,
            headers=resp_headers,
            media_type=upstream_resp.headers.get("content-type"),
        )

    # -------------------------------------------------------------------------
    # Phase 5: Analytics endpoints (APIP-02 to APIP-06)
    # -------------------------------------------------------------------------

    @app.get("/v1/analytics/api/endpoints")
    async def analytics_api_endpoints(hours: int = 24, api_service: str | None = None) -> dict:
        """Per-endpoint metrics: volume, avg latency, error rate (APIP-02/03/04)."""
        cfg = get_settings()
        engine = await get_engine(cfg.tenant_id, cfg.data_root)
        async with AsyncSession(engine) as db_session:
            from tiresias.analytics.api_telemetry import get_endpoint_metrics

            endpoints = await get_endpoint_metrics(
                cfg.tenant_id, db_session, hours=hours, api_service=api_service
            )
        return {"tenant_id": cfg.tenant_id, "window_hours": hours, "endpoints": endpoints}

    @app.get("/v1/analytics/api/costs")
    async def analytics_api_costs(hours: int = 24) -> dict:
        """Cost by endpoint/service (APIP-05)."""
        cfg = get_settings()
        engine = await get_engine(cfg.tenant_id, cfg.data_root)
        async with AsyncSession(engine) as db_session:
            from tiresias.analytics.api_telemetry import get_cost_by_endpoint

            costs = await get_cost_by_endpoint(cfg.tenant_id, db_session, hours=hours)
        return {"tenant_id": cfg.tenant_id, "window_hours": hours, "costs": costs}

    @app.get("/v1/analytics/api/errors")
    async def analytics_api_errors(hours: int = 24, api_service: str | None = None) -> dict:
        """Error breakdown by path_pattern and status code (APIP-04)."""
        cfg = get_settings()
        engine = await get_engine(cfg.tenant_id, cfg.data_root)
        async with AsyncSession(engine) as db_session:
            from tiresias.analytics.api_telemetry import get_error_breakdown

            errors = await get_error_breakdown(
                cfg.tenant_id, db_session, hours=hours, api_service=api_service
            )
        return {"tenant_id": cfg.tenant_id, "window_hours": hours, "errors": errors}

    @app.get("/v1/analytics/unified")
    async def analytics_unified(hours: int = 24) -> dict:
        """Unified LLM + API telemetry in single pane (APIP-06)."""
        cfg = get_settings()
        engine = await get_engine(cfg.tenant_id, cfg.data_root)
        async with AsyncSession(engine) as db_session:
            from tiresias.analytics.unified import get_unified_analytics

            data = await get_unified_analytics(cfg.tenant_id, db_session, hours=hours)
        return data

    @app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def proxy_other(request: Request, path: str) -> Response:
        if path.startswith("sessions/") or path.startswith("admin/") or path.startswith("analytics/"):
            raise HTTPException(status_code=404, detail="Not found")
        cfg = get_settings()
        client = get_http_client()
        upstream_url = cfg.upstream_url.rstrip("/")
        target_url = f"{upstream_url}/v1/{path}"
        upstream_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ("host", "content-length", "transfer-encoding")
        }
        body_bytes = await request.body()
        params = dict(request.query_params)
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=upstream_headers,
                content=body_bytes,
                params=params,
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Upstream error: {exc}")
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
            media_type=resp.headers.get("content-type"),
        )

    return app


async def _handle_non_streaming_router(
    router,
    upstream_headers,
    body,
    tenant_id,
    model,
    session_id,
    extra_metadata,
    envelope,
    settings,
):
    from sqlalchemy.ext.asyncio import AsyncSession as _AS
    from tiresias.storage.engine import get_engine as _get_engine
    import json as _json

    try:
        response_json, provider_name = await router.execute(body, upstream_headers)
    except ProviderCascadeExhausted as exc:
        engine = await _get_engine(tenant_id, settings.data_root)
        async with _AS(engine) as db_session:
            await record_error_turn(tenant_id, model, db_session)
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        engine = await _get_engine(tenant_id, settings.data_root)
        async with _AS(engine) as db_session:
            await record_error_turn(tenant_id, model, db_session)
        raise HTTPException(status_code=502, detail=str(exc))

    engine = await _get_engine(tenant_id, settings.data_root)
    async with _AS(engine) as db_session:
        await record_turn(
            tenant_id=tenant_id,
            model=model,
            provider=provider_name,
            request_body=body,
            response_body=response_json,
            session_id=session_id,
            metadata=extra_metadata,
            envelope=envelope,
            db_session=db_session,
        )

    response_bytes = _json.dumps(response_json).encode()
    return Response(
        content=response_bytes,
        status_code=200,
        media_type="application/json",
    )


async def _handle_non_streaming(
    client,
    target_url,
    upstream_headers,
    body,
    tenant_id,
    model,
    provider,
    session_id,
    extra_metadata,
    envelope,
    settings,
):
    from sqlalchemy.ext.asyncio import AsyncSession as _AS
    from tiresias.storage.engine import get_engine as _get_engine

    try:
        upstream_resp = await client.post(target_url, headers=upstream_headers, json=body)
    except Exception as exc:
        engine = await _get_engine(tenant_id, settings.data_root)
        async with _AS(engine) as db_session:
            await record_error_turn(tenant_id, model, db_session)
        raise HTTPException(status_code=502, detail=str(exc))

    response_bytes = upstream_resp.content
    status_code = upstream_resp.status_code
    resp_headers = dict(upstream_resp.headers)

    if 200 <= status_code < 300:
        try:
            response_json = upstream_resp.json()
        except Exception:
            response_json = {}
        engine = await _get_engine(tenant_id, settings.data_root)
        async with _AS(engine) as db_session:
            await record_turn(
                tenant_id=tenant_id,
                model=model,
                provider=provider,
                request_body=body,
                response_body=response_json,
                session_id=session_id,
                metadata=extra_metadata,
                envelope=envelope,
                db_session=db_session,
            )
    else:
        engine = await _get_engine(tenant_id, settings.data_root)
        async with _AS(engine) as db_session:
            await record_error_turn(tenant_id, model, db_session)

    for h in ("transfer-encoding", "content-encoding", "content-length"):
        resp_headers.pop(h, None)

    return Response(
        content=response_bytes,
        status_code=status_code,
        headers=resp_headers,
        media_type=upstream_resp.headers.get("content-type", "application/json"),
    )


async def _handle_streaming(
    client,
    target_url,
    upstream_headers,
    body,
    tenant_id,
    model,
    provider,
    session_id,
    extra_metadata,
    envelope,
    settings,
):
    import json as _json

    accumulated_chunks = []
    accumulated_response = {}

    async def stream_generator():
        nonlocal accumulated_response
        try:
            async with client.stream(
                "POST", target_url, headers=upstream_headers, json=body
            ) as upstream_resp:
                if upstream_resp.status_code >= 400:
                    yield await upstream_resp.aread()
                    return
                async for chunk in upstream_resp.aiter_bytes():
                    accumulated_chunks.append(chunk.decode("utf-8", errors="replace"))
                    yield chunk
        except Exception as exc:
            yield (
                "data: " + _json.dumps({"error": str(exc)}) + "\n\n"
            ).encode("utf-8")
            return

        full_text = "".join(accumulated_chunks)
        assembled = _assemble_sse_response(full_text, model)
        accumulated_response.update(assembled)
        try:
            from sqlalchemy.ext.asyncio import AsyncSession as _AS2
            from tiresias.storage.engine import get_engine as _ge

            engine = await _ge(tenant_id, settings.data_root)
            async with _AS2(engine) as db_session:
                await record_turn(
                    tenant_id=tenant_id,
                    model=model,
                    provider=provider,
                    request_body=body,
                    response_body=accumulated_response,
                    session_id=session_id,
                    metadata=extra_metadata,
                    envelope=envelope,
                    db_session=db_session,
                )
        except Exception as exc:
            logging.getLogger(__name__).error(
                "Failed to record streaming turn: %s", exc
            )

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _assemble_sse_response(full_sse_text, model):
    import json as _json

    content_parts = []
    prompt_tokens = 0
    completion_tokens = 0
    finish_reason = None
    response_id = None

    for line in full_sse_text.splitlines():
        if not line.startswith("data: "):
            continue
        data_str = line[6:].strip()
        if data_str == "[DONE]":
            continue
        try:
            chunk = _json.loads(data_str)
        except _json.JSONDecodeError:
            continue
        if response_id is None:
            response_id = chunk.get("id")
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            c = delta.get("content")
            if c:
                content_parts.append(c)
            fr = choice.get("finish_reason")
            if fr:
                finish_reason = fr
        usage = chunk.get("usage")
        if usage:
            prompt_tokens = usage.get("prompt_tokens", 0) or 0
            completion_tokens = usage.get("completion_tokens", 0) or 0

    assembled_content = "".join(content_parts)
    if prompt_tokens == 0 and completion_tokens == 0:
        from tiresias.tracking.tokens import count_tokens_from_string

        completion_tokens = count_tokens_from_string(assembled_content, model)

    return {
        "id": response_id or "stream-assembled",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "message": {"role": "assistant", "content": assembled_content},
                "finish_reason": finish_reason,
                "index": 0,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


app = create_app()
