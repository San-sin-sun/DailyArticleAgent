from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import load_profiles
from .digest import analyze_paper
from .llm import LlmClient, LlmSettings
from .models import FeedbackRating, RunAction, SourceConfig, WatchProfile
from .reader import PaperReader, safe_pdf_stem
from .service import AgentService, AppPaths
from .storage import Repository


class RunNowRequest(BaseModel):
    action: RunAction
    profile_id: str = "all"
    use_llm: bool = False
    fetch_lookback_days: int = 3
    week_ending: str | None = None


class FeedbackRequest(BaseModel):
    paper_uid: str
    profile_id: str
    rating: FeedbackRating
    note: str = ""


class ProfileConfigRequest(BaseModel):
    yaml_text: str


def create_app(
    config_path: Path | None = None,
    db_path: Path | None = None,
    content_dir: Path | None = None,
) -> FastAPI:
    load_dotenv()
    paths = AppPaths.from_env(config_path=config_path, db_path=db_path, content_dir=content_dir)
    app = FastAPI(title="DailyArticleAgent API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    dist_assets = Path("front-end/dist/assets")
    if dist_assets.exists():
        app.mount("/assets", StaticFiles(directory=dist_assets), name="assets")

    @app.get("/api/profiles")
    def profiles() -> list[dict]:
        return [
            {
                "id": profile.id,
                "name": profile.name,
                "description": profile.description,
                "language": profile.language,
                "max_items": profile.max_items,
                "broad_discovery": profile.broad_discovery,
                "sources": [source.__dict__ for source in profile.sources],
            }
            for profile in load_profiles(paths.config_path).values()
        ]

    @app.get("/api/digests")
    def digests() -> list[dict]:
        repo = Repository(paths.db_path)
        try:
            return repo.list_digests()
        finally:
            repo.close()

    @app.get("/api/papers")
    def papers(profile_id: str | None = None, limit: int = 200) -> list[dict]:
        repo = Repository(paths.db_path)
        try:
            return repo.list_papers(profile_id=profile_id, limit=limit)
        finally:
            repo.close()

    @app.get("/api/runs")
    def runs(limit: int = 50) -> list[dict]:
        repo = Repository(paths.db_path)
        try:
            return repo.list_runs(limit=limit)
        finally:
            repo.close()

    @app.post("/api/run-now")
    def run_now(request: RunNowRequest) -> dict:
        service = AgentService(paths, use_llm=request.use_llm)
        options: dict[str, object] = {}
        if request.action == RunAction.DAILY:
            options["fetch_lookback_days"] = request.fetch_lookback_days
        if request.action == RunAction.WEEKLY and request.week_ending:
            options["week_ending"] = request.week_ending
        try:
            run_id, result_count = service.run_with_history(request.action, request.profile_id, options=options)
            return {"run_id": run_id, "result_count": result_count}
        finally:
            service.close()

    @app.post("/api/runs/{run_id}/retry")
    def retry_run(run_id: int) -> dict:
        service = AgentService(paths, use_llm=False)
        try:
            new_run_id, result_count = service.retry_run(run_id)
            return {"run_id": new_run_id, "result_count": result_count}
        finally:
            service.close()

    @app.post("/api/feedback")
    def feedback(request: FeedbackRequest) -> dict:
        service = AgentService(paths, use_llm=False)
        try:
            service.record_feedback(request.paper_uid, request.profile_id, request.rating, note=request.note)
            return {"ok": True}
        finally:
            service.close()

    @app.post("/api/papers/{paper_uid}/upload-pdf")
    async def upload_paper_pdf(
        paper_uid: str,
        profile_id: str,
        file: UploadFile,
        use_llm: bool = True,
    ) -> dict:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF uploads are supported")
        repo = Repository(paths.db_path)
        try:
            item = repo.classified_paper(paper_uid, profile_id)
            if not item:
                raise HTTPException(status_code=404, detail="Classified paper not found")
            profile = load_profiles(paths.config_path).get(profile_id) or WatchProfile(
                id=profile_id,
                name=profile_id,
                description="Recovered from stored classification for uploaded PDF analysis.",
                language="zh-CN",
                max_items=1,
                keywords=(),
                exclude_keywords=(),
                sources=(SourceConfig(name=item.paper.source, kind=item.paper.source_kind),),
            )
            upload_dir = paths.content_dir / "readings" / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = upload_dir / f"{safe_pdf_stem(paper_uid)}.pdf"
            pdf_path.write_bytes(await file.read())
            reader = PaperReader(readings_dir=paths.content_dir / "readings", local_pdf_dir=upload_dir)
            llm = LlmClient(LlmSettings.from_env(enabled_override=True)) if use_llm else None
            insight = analyze_paper(profile, item, llm, reader)
            repo.save_paper_insights([insight])
            return {
                "ok": True,
                "paper_uid": paper_uid,
                "profile_id": profile_id,
                "insight": insight.__dict__,
            }
        finally:
            repo.close()

    @app.get("/api/profile-config")
    def profile_config() -> dict:
        if not paths.config_path.exists():
            raise HTTPException(status_code=404, detail="Profile config not found")
        return {"path": str(paths.config_path), "yaml_text": paths.config_path.read_text(encoding="utf-8")}

    @app.put("/api/profile-config")
    def save_profile_config(request: ProfileConfigRequest) -> dict:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".yaml") as temp:
            temp.write(request.yaml_text)
            temp_path = Path(temp.name)
        try:
            load_profiles(temp_path)
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=f"Invalid profile YAML: {exc}") from exc
        backup = paths.config_path.with_suffix(paths.config_path.suffix + ".bak")
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        if paths.config_path.exists():
            shutil.copy2(paths.config_path, backup)
        shutil.move(str(temp_path), paths.config_path)
        return {"ok": True, "path": str(paths.config_path), "backup_path": str(backup)}

    @app.get("/api/digest-file")
    def digest_file(path: str) -> PlainTextResponse:
        requested = Path(path)
        if not requested.is_absolute():
            requested = Path.cwd() / requested
        root = (Path.cwd() / paths.content_dir).resolve()
        resolved = requested.resolve()
        if root not in resolved.parents and resolved != root:
            raise HTTPException(status_code=400, detail="Path is outside content directory")
        if not resolved.exists():
            raise HTTPException(status_code=404, detail="Digest not found")
        return PlainTextResponse(resolved.read_text(encoding="utf-8"), media_type="text/markdown")

    @app.get("/")
    def index():
        candidate = Path("front-end/dist/index.html")
        if candidate.exists():
            return FileResponse(candidate)
        return {"message": "DailyArticleAgent API is running. Start the frontend with npm run dev."}

    return app


app = create_app()
