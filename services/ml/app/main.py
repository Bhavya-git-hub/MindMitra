"""The AI service's internal HTTP API.

    POST /internal/v1/companion/respond   one guarded companion turn
    GET  /internal/v1/models              what is loaded (model, prompt and rules versions)
    GET  /internal/v1/health              liveness, no authentication, no details

Only the API calls this service, over the private network, with a signed service token. It is
stateless and keeps no text: nothing a student writes is stored, logged or put in a metric
here. Validation errors are returned without echoing the input.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
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
from app.schemas import CrisisOut, ModelsOut, RespondIn, RespondOut
from safety import templates
from safety.crisis_rules import rules_version

PREFIX = "/internal/v1"
_bearer = HTTPBearer(auto_error=False)


def create_app(settings: Settings | None = None, provider: LLMProvider | None = None) -> FastAPI:
    s = settings or get_settings()
    llm = provider or build_provider(s)
    secret = s.ml_service_token.get_secret_value()

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
    async def models() -> ModelsOut:
        return ModelsOut(
            provider_model=llm.model_id,
            prompt_version=PROMPT_VERSION,
            rules_version=rules_version(),
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
