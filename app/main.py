import io
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn

from models import SearchRequest
from services.agencies import public_agency_options
from services.processor import ResearchProcessor, resolve_sources
from services.semantic import warmup_semantic_ranker
from services.export import (
    build_csv_document,
    build_excel_workbook,
    build_word_document,
    report_filename,
)
from config.settings import get_settings
from i18n import load_translations, resolve_lang, make_translator, text_direction
from auth.clerk_auth import (
    authenticate_bearer,
    authenticate_request,
    clear_session_cookie,
    sign_in_with_password,
    create_clerk_user,
    delete_clerk_user,
    frontend_host,
    list_clerk_users,
    publishable_key,
    set_session_cookie,
)
from prefs import load_prefs, save_prefs

get_settings()
processor = ResearchProcessor()
logger = logging.getLogger("research-fetcher")

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR.mkdir(exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

PUBLIC_PATHS = {
    "/login",
    "/sign-in",
    "/sign-up",
    "/set-lang",
    "/api/health",
    "/api/session",
    "/api/login",
    "/api/logout",
    "/logout",
    "/favicon.ico",
}
app = FastAPI(
    title="Research Data Fetcher",
    description="A local research assistant for collecting public information from multiple sources",
    version="1.0.0",
)


@app.on_event("startup")
def _start_semantic_ranker():
    warmup_semantic_ranker()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_auth(request: Request, call_next):
    path = request.url.path
    request.state.user = authenticate_request(request)

    if path.startswith("/static") or path in PUBLIC_PATHS:
        return await call_next(request)

    if not request.state.user:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        destination = "/sign-in"
        if path.startswith("/"):
            destination += f"?next={quote(path)}"
        return RedirectResponse(destination, status_code=302)
    return await call_next(request)


@app.get("/favicon.ico")
async def favicon():
    return FileResponse(STATIC_DIR / "favicon.png")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _resolve_theme(request: Request) -> str:
    cookie = request.cookies.get("theme")
    if cookie in ("light", "dark", "auto"):
        return cookie
    return load_prefs().get("theme") or "light"


def _page_context(request: Request, active_page: str = "", extra: dict | None = None) -> dict:
    language = resolve_lang(request)
    translator = make_translator(language)
    context = {
        "title": translator("appNameFull"),
        "translations": load_translations(language),
        "t": translator,
        "lang": language,
        "text_dir": text_direction(language),
        "theme": _resolve_theme(request),
        "user": getattr(request.state, "user", None),
        "active_page": active_page,
        "clerk_publishable_key": publishable_key(),
        "clerk_frontend_host": frontend_host(),
        "clerk_protect": extra.get("clerk_protect", True) if extra else True,
        "clerk_page": extra.get("clerk_page", "") if extra else "",
        "agency_options": public_agency_options(language),
    }
    if extra:
        context.update(extra)
    return context


@app.get("/login", response_class=HTMLResponse)
async def login_legacy(request: Request, next: str = "/"):
    destination = "/sign-in"
    if next and next.startswith("/"):
        destination += f"?next={quote(next)}"
    return RedirectResponse(destination, status_code=303)


@app.get("/sign-in", response_class=HTMLResponse)
async def sign_in_page(request: Request, next: str = "/", switch: int = 0):
    if switch:
        response = RedirectResponse("/sign-in" + (f"?next={quote(next)}" if next.startswith("/") else ""), status_code=303)
        clear_session_cookie(response)
        return response
    if request.state.user:
        destination = next if next.startswith("/") else "/"
        return RedirectResponse(destination, status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        _page_context(request, extra={"clerk_protect": False, "clerk_page": "sign-in"}),
    )


@app.get("/sign-up", response_class=HTMLResponse)
async def sign_up_page(request: Request):
    return RedirectResponse("/sign-in", status_code=303)


@app.get("/set-lang")
async def set_lang(lang: str = "en", next: str = "/"):
    if lang not in ("en", "ar"):
        lang = "en"
    destination = next if next.startswith("/") else "/"
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html", _page_context(request, "search"))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", _page_context(request, "dashboard"))


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", _page_context(request, "settings"))


@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    user = request.state.user
    if not user or not user.is_admin:
        return RedirectResponse("/dashboard", status_code=303)
    try:
        people = list_clerk_users()
    except Exception:
        logger.exception("Could not list Clerk users")
        people = []
    return templates.TemplateResponse(
        request,
        "users.html",
        _page_context(request, "users", extra={"users": people}),
    )


@app.post("/api/login")
async def login_with_password(payload: dict):
    user = sign_in_with_password(
        str(payload.get("username") or ""),
        str(payload.get("password") or ""),
    )
    if user is None:
        return JSONResponse({"detail": "Incorrect username or password."}, status_code=401)
    response = JSONResponse(
        {
            "status": "ok",
            "user": {
                "id": user.id,
                "display_name": user.display_name,
                "is_admin": user.is_admin,
            },
        }
    )
    set_session_cookie(response, user)
    return response


@app.post("/api/session")
async def establish_session(request: Request):
    user = authenticate_bearer(request)
    if user is None:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    response = JSONResponse(
        {
            "status": "ok",
            "user": {
                "id": user.id,
                "display_name": user.display_name,
                "is_admin": user.is_admin,
            },
        }
    )
    set_session_cookie(response, user)
    return response


@app.post("/api/logout")
async def logout():
    response = JSONResponse({"status": "ok"})
    clear_session_cookie(response)
    return response


@app.get("/logout")
async def logout_page():
    response = RedirectResponse("/sign-in", status_code=303)
    clear_session_cookie(response)
    return response


@app.get("/api/users")
async def api_list_users(request: Request):
    if not request.state.user or not request.state.user.is_admin:
        return JSONResponse({"detail": "Only admins can manage users."}, status_code=403)
    return list_clerk_users()


@app.post("/api/users")
async def api_create_user(request: Request, payload: dict):
    if not request.state.user or not request.state.user.is_admin:
        return JSONResponse({"detail": "Only admins can manage users."}, status_code=403)
    try:
        created = create_clerk_user(
            username=str(payload.get("username") or ""),
            password=str(payload.get("password") or ""),
            display_name=str(payload.get("display_name") or ""),
            role=str(payload.get("role") or "user"),
        )
        return created
    except ValueError as exc:
        code = str(exc)
        messages = {
            "max_users": "The team already has 10 users.",
            "invalid_username": "Username must be at least 2 characters.",
            "weak_password": "Password must be at least 6 characters.",
        }
        return JSONResponse({"detail": messages.get(code, "Could not create user.")}, status_code=400)
    except Exception as exc:
        logger.exception("Clerk create user failed: %s", exc)
        return JSONResponse({"detail": "Could not create user. Enable username + password in Clerk."}, status_code=400)


@app.delete("/api/users/{user_id}")
async def api_delete_user(request: Request, user_id: str):
    if not request.state.user or not request.state.user.is_admin:
        return JSONResponse({"detail": "Only admins can manage users."}, status_code=403)
    if user_id == request.state.user.id:
        return JSONResponse({"detail": "You cannot remove your own account."}, status_code=400)
    try:
        delete_clerk_user(user_id)
    except Exception as exc:
        logger.exception("Clerk delete user failed: %s", exc)
        return JSONResponse({"detail": "Could not remove user."}, status_code=400)
    return {"status": "ok"}


@app.post("/api/search")
async def search_topic(body: SearchRequest, background_tasks: BackgroundTasks):
    settings = get_settings()
    content_type = (body.content_type or "all").lower()
    if content_type not in {"social", "agencies", "all", "news"}:
        content_type = "all"
    sources = resolve_sources(content_type, body.sources)

    task_id = await processor.process_research(
        topic=body.topic,
        sources=sources,
        max_results=body.max_results,
        settings=settings,
        date_from=body.date_from,
        date_to=body.date_to,
        content_type=content_type,
        province=body.province,
        agencies=body.agencies,
    )
    background_tasks.add_task(processor.start_processing, task_id)

    return {
        "task_id": task_id,
        "status": "started",
        "message": "Research started successfully",
    }


@app.get("/api/results/{task_id}")
async def get_results(task_id: str):
    return await processor.get_results(task_id)


@app.get("/api/dashboard/stats")
async def dashboard_stats():
    tasks = list(processor.active_tasks.values())
    completed = [t for t in tasks if t.get("status") == "completed"]
    total_results = sum(len(t.get("results") or []) for t in completed)
    duplicates = 0
    exec_seconds = 0.0
    for task in completed:
        stats = task.get("stats")
        if stats:
            duplicates += getattr(stats, "duplicates_found", 0) or 0
            exec_seconds += getattr(stats, "execution_time", 0) or 0

    return {
        "total_searches": len(tasks),
        "total_results": total_results,
        "duplicates_removed": duplicates,
        "execution_time": f"{exec_seconds:.1f}s",
    }


@app.get("/api/dashboard/history")
async def dashboard_history():
    history = []
    for task_id, task in processor.active_tasks.items():
        history.append(
            {
                "id": task_id,
                "date": task.get("start_time").isoformat() if task.get("start_time") else None,
                "topic": task.get("topic"),
                "sources": task.get("sources") or [],
                "results_count": len(task.get("results") or []),
                "status": task.get("status"),
            }
        )
    history.sort(key=lambda item: item.get("date") or "", reverse=True)
    return history


@app.get("/api/settings")
async def get_app_settings():
    return load_prefs()


@app.post("/api/settings")
async def save_app_settings(payload: dict):
    saved = save_prefs(payload)
    response = JSONResponse({"status": "ok", "saved": saved})
    theme = saved.get("theme") or "light"
    if theme in ("light", "dark", "auto"):
        response.set_cookie("theme", theme, max_age=60 * 60 * 24 * 365, samesite="lax")
    language = saved.get("language")
    if language in ("en", "ar"):
        response.set_cookie("lang", language, max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/export/{format}")
async def export_results(format: str, payload: dict):
    results = payload.get("results", [])
    if not results:
        return JSONResponse({"error": "No results to export"}, status_code=400)

    fmt = (format or "").lower()
    now = datetime.now()

    if fmt == "excel":
        body = build_excel_workbook(payload, now)
        filename = report_filename(now, "xlsx")
        return StreamingResponse(
            io.BytesIO(body),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )

    if fmt == "csv":
        body = build_csv_document(payload, now)
        filename = report_filename(now, "csv")
        return StreamingResponse(
            io.BytesIO(body),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )

    if fmt in {"word", "docx"}:
        body = build_word_document(payload, now)
        filename = report_filename(now, "docx")
        return StreamingResponse(
            io.BytesIO(body),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )

    return JSONResponse({"error": "Unsupported export format"}, status_code=400)


@app.exception_handler(StarletteHTTPException)
async def http_error_page(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api/") or exc.status_code < 400:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return templates.TemplateResponse(
        request,
        "error.html",
        _page_context(request),
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def unhandled_error_page(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Internal server error"}, status_code=500)
    return templates.TemplateResponse(
        request,
        "error.html",
        _page_context(request),
        status_code=500,
    )


def run_app():
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level
    )


if __name__ == "__main__":
    run_app()
