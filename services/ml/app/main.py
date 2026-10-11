"""The AI service's internal HTTP API.

    POST /internal/v1/companion/respond   one guarded companion turn
    POST /internal/v1/indicators          wellness indicators from one student's own check-ins
    POST /internal/v1/sentiment           tone of short texts (negative, neutral, positive)
    GET  /internal/v1/models              what is loaded (model, prompt, rules, indicator versions)
    GET  /internal/v1/health              liveness, no authentication, no details

Only the API calls this service, over the private network, with a signed service token. It is
stateless and keeps no text: nothing a student writes is stored, logged or put in a metric
here. Validation errors are returned without echoing the input.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import Unauthorized, verify_service_token
from app.companion.context import Turn
from app.companion.orchestrator import respond
from app.companion.prompts import PROMPT_VERSION
from app.config import Settings, get_settings
from app.providers.base import LLMProvider
from app.providers.factory import build_provider
from app.schemas import (
    CrisisOut,
    IndicatorOut,
    IndicatorsIn,
    IndicatorsOut,
    ModelsOut,
    RespondIn,
    RespondOut,
    SentimentIn,
    SentimentItemOut,
    SentimentOut,
)
from inference import registry as model_registry
from inference.indicators import assess, score_texts
from preprocessing.records import DailyRecord
from safety import templates
from safety.crisis_rules import rules_version
from training.indicators import DISCLAIMER, TABULAR_INDICATORS

PREFIX = "/internal/v1"
_bearer = HTTPBearer(auto_error=False)


def _load_models(s: Settings) -> tuple[model_registry.Registry | None, str | None]:
    try:
        expected = tuple(spec.name for spec in TABULAR_INDICATORS)
        return model_registry.load(s.ml_model_dir, expected), None
    except model_registry.ModelsUnavailable as exc:
        return None, str(exc)


def create_app(
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    models: model_registry.Registry | None = None,
) -> FastAPI:
    s = settings or get_settings()
    llm = provider or build_provider(s)
    secret = s.ml_service_token.get_secret_value()
    # The companion works without the indicator models; the indicator endpoints answer 503.
    registry, unavailable = (models, None) if models is not None else _load_models(s)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await llm.aclose()

    app = FastAPI(
        title="MindMitra AI service (internal)",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if s.app_env in ("development", "test") else None,
        redoc_url=None,
        openapi_url="/openapi.json" if s.app_env in ("development", "test") else None,
    )

    async def require_service(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> None:
        if credentials is None:
            raise Unauthorized
        verify_service_token(credentials.credentials, secret)

    @app.exception_handler(Unauthorized)
    async def _unauthorized(_: Request, __: Unauthorized) -> JSONResponse:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = sorted({".".join(str(p) for p in e.get("loc", ())) for e in exc.errors()})
        return JSONResponse({"detail": "invalid request", "fields": fields}, status_code=422)

    def version() -> str:
        return f"{llm.model_id}|{PROMPT_VERSION}|{rules_version()}"

    @app.get(f"{PREFIX}/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(f"{PREFIX}/models", dependencies=[Depends(require_service)])
    async def list_models() -> ModelsOut:
        return ModelsOut(
            provider_model=llm.model_id,
            prompt_version=PROMPT_VERSION,
            rules_version=rules_version(),
            indicator_models=registry.versions() if registry else {},
            indicators_unavailable=unavailable,
        )

    def require_models() -> model_registry.Registry:
        if registry is None:
            raise HTTPException(status_code=503, detail="indicator models unavailable")
        return registry

    # Plain functions: scikit-learn work runs in the thread pool, not on the event loop.
    @app.post(f"{PREFIX}/indicators", dependencies=[Depends(require_service)])
    def indicators(
        body: IndicatorsIn, models: Annotated[model_registry.Registry, Depends(require_models)]
    ) -> IndicatorsOut:
        records = [
            DailyRecord(
                day=d.day,
                mood=d.mood,
                energy=d.energy,
                stress=d.stress,
                sleep_minutes=d.sleep_minutes,
                sleep_quality=d.sleep_quality,
                bedtime_hour=d.bedtime_hour,
                emotions=tuple(d.emotions),
                stressors=tuple(d.stressors),
            )
            for d in body.days
        ]
        result = assess(models, records, body.notes, window_end=body.window_end)
        return IndicatorsOut(
            indicators=[
                IndicatorOut(
                    indicator=i.indicator,
                    title=i.title,
                    meaning=i.meaning,
                    status=i.status,
                    band=i.band,
                    level=i.level,
                    probabilities=i.probabilities,
                    model_version=i.model_version,
                )
                for i in result.indicators
            ],
            checkin_days=result.checkin_days,
            notes_considered=result.notes_considered,
            disclaimer=result.disclaimer,
        )

    @app.post(f"{PREFIX}/sentiment", dependencies=[Depends(require_service)])
    def sentiment(
        body: SentimentIn, models: Annotated[model_registry.Registry, Depends(require_models)]
    ) -> SentimentOut:
        return SentimentOut(
            results=[
                SentimentItemOut(label=r.label, probabilities=r.probabilities)
                for r in score_texts(models, body.texts)
            ],
            model_version=models.sentiment.version,
            disclaimer=DISCLAIMER,
        )

    @app.post(f"{PREFIX}/companion/respond", dependencies=[Depends(require_service)])
    async def companion_respond(body: RespondIn) -> RespondOut:
        history = [Turn(t.role, t.content) for t in body.history]
        result = await respond(llm, body.message, history, max_tokens=s.llm_max_tokens)
        c = result.crisis
        return RespondOut(
            kind=result.kind.value,
            reply=result.reply,
            crisis=CrisisOut(
                action=c.action.value,
                category=c.category,
                severity=c.severity.value if c.severity else None,
                rules=list(c.rules),
                third_person=c.third_person,
                requires_human=c.crisis,
            ),
            topic=result.topic.value,
            flags=list(result.flags),
            model_version=version(),
            disclaimer=templates.DISCLAIMER,
        )

    return app
