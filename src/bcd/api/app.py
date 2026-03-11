"""FastAPI application for the bcd MVP."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from bcd.config import Settings, get_settings
from bcd.decision.schemas import DecisionPredictionInput, FeedbackInput, PredictionResponse
from bcd.decision.service import DecisionService
from bcd.profile.schemas import ChatGPTImportResponse, UserOnboardingInput, UserProfileRead
from bcd.profile.service import ProfileService
from bcd.reflection.service import ReflectionService
from bcd.storage.database import get_engine, init_db


def get_session(settings: Settings = Depends(get_settings)):
    session = Session(get_engine(settings.database_url))
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db(get_settings())
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="bcd",
        version="0.1.0",
        description="Research-friendly personalized decision prediction MVP.",
        lifespan=lifespan,
    )
    demo_path = Path(__file__).with_name("static") / "demo.html"

    @app.get("/", include_in_schema=False)
    def root_redirect():
        return RedirectResponse(url="/app")

    @app.get("/app", include_in_schema=False, response_class=HTMLResponse)
    def demo_page():
        return HTMLResponse(demo_path.read_text(encoding="utf-8"))

    @app.post("/profiles/bootstrap-sample", response_model=UserProfileRead)
    def bootstrap_sample_profile(session: Session = Depends(get_session)):
        try:
            return ProfileService(session).bootstrap_sample_profile()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/profiles/{user_id}", response_model=UserProfileRead)
    def get_profile(user_id: str, session: Session = Depends(get_session)):
        try:
            return ProfileService(session).get_profile_bundle(user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/profiles/{user_id}/card")
    def get_profile_card(user_id: str, session: Session = Depends(get_session)):
        try:
            return ProfileService(session).get_profile_card(user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/profiles/onboard", response_model=UserProfileRead)
    def create_profile_from_onboarding(payload: UserOnboardingInput, session: Session = Depends(get_session)):
        try:
            return ProfileService(session).create_profile_from_onboarding(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/profiles/import-chatgpt-export", response_model=ChatGPTImportResponse)
    async def import_chatgpt_export(
        display_name: str = Form(...),
        user_id: str | None = Form(default=None),
        file: UploadFile = File(...),
        session: Session = Depends(get_session),
    ):
        try:
            return ProfileService(session).import_profile_from_chatgpt_export(
                display_name=display_name,
                user_id=user_id,
                filename=file.filename or "chatgpt-export.zip",
                file_bytes=await file.read(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/decisions/predict", response_model=PredictionResponse)
    def predict_choice(payload: DecisionPredictionInput, session: Session = Depends(get_session)):
        try:
            return DecisionService(session).predict(payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/decisions/{request_id}/feedback")
    def record_feedback(request_id: str, payload: FeedbackInput, session: Session = Depends(get_session)):
        try:
            return ReflectionService(session).record_feedback(request_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/users/{user_id}/history")
    def get_history(
        user_id: str,
        limit: int = Query(default=50, ge=1, le=200),
        session: Session = Depends(get_session),
    ):
        return ReflectionService(session).list_user_history(user_id=user_id, limit=limit)

    @app.get("/users/{user_id}/memories")
    def get_memories(
        user_id: str,
        limit: int = Query(default=20, ge=1, le=100),
        session: Session = Depends(get_session),
    ):
        return ReflectionService(session).list_user_memories(user_id=user_id, limit=limit)

    return app


app = create_app()
