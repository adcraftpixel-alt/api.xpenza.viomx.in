import logging
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Rupexi API",
    version="1.0.0",
    description="AI-powered expense management backend",
    docs_url="/docs",
    redoc_url=None,          # disabled — use /api-docs instead (self-hosted)
)

# CORS — allow all origins; JWT is passed via Authorization header (not cookies)
# so allow_credentials stays False, which is compatible with allow_origins=["*"].
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail, "errors": []},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": "Internal server error", "errors": []},
    )


# Mount static files for test page assets
_static_dir = os.path.join(os.path.dirname(__file__), "api", "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Serve locally-stored uploads (avatars, receipts) when S3 isn't configured.
from app.utils.storage import LOCAL_UPLOAD_DIR  # noqa: E402
app.mount(
    "/local-uploads",
    StaticFiles(directory=str(LOCAL_UPLOAD_DIR)),
    name="local-uploads",
)


# Health endpoint
@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "version": "1.0.0", "environment": settings.ENVIRONMENT}


@app.get("/test", response_class=HTMLResponse, tags=["Dev"])
async def api_test_page():
    html_path = os.path.join(os.path.dirname(__file__), "api", "test_page.html")
    with open(html_path) as f:
        return f.read()


@app.get("/api-docs", response_class=HTMLResponse, tags=["Dev"],
         summary="Self-hosted API documentation (no CDN required)")
async def api_docs_page():
    """Full interactive API docs using Swagger UI — works offline, no CDN."""
    from fastapi.openapi.docs import get_swagger_ui_html
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Rupexi — API Docs",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
        swagger_favicon_url="https://fastapi.tiangolo.com/img/favicon.png",
    )


@app.get("/api-status", tags=["Dev"])
async def api_status():
    routes = []
    for route in app.routes:
        if hasattr(route, "methods"):
            routes.append({
                "path": route.path,
                "methods": list(route.methods),
                "name": route.name,
            })
    return {"total": len(routes), "routes": routes}


# Include all routes
from app.api.v1.router import router  # noqa: E402
app.include_router(router)


# Startup
@app.on_event("startup")
def startup_event():
    logger.info("Starting Rupexi API...")
    try:
        from app.database import create_tables, apply_schema_patches
        create_tables()
        apply_schema_patches()
        logger.info("Database tables created/verified")
    except Exception as e:
        logger.error(f"Startup error during table creation: {e}")

    try:
        from app.database import check_schema_drift
        check_schema_drift()
    except Exception as e:
        logger.error(f"Startup error during schema-drift check: {e}")

    try:
        _seed_billing_plans()
    except Exception as e:
        logger.error(f"Startup error during billing plan seed: {e}")

    try:
        _seed_demo_user()
    except Exception as e:
        logger.error(f"Startup error during demo user seed: {e}")


def _seed_demo_user():
    """Create a demo user for Swagger UI testing."""
    from app.database import SessionLocal
    from app.models.user import User
    from app.core.security import hash_password

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == "demo@rupexi.com").first()
        if existing:
            return
        demo = User(
            name="Demo User",
            email="demo@rupexi.com",
            phone="+919999999999",
            password_hash=hash_password("demo123"),
            user_type="personal",
            monthly_income=50000,
            is_verified=True,
            is_active=True,
            onboarding_done=True,
        )
        db.add(demo)
        db.commit()
        logger.info("Demo user created: demo@rupexi.com / demo123")
    finally:
        db.close()


def _seed_billing_plans():
    from app.database import SessionLocal
    from app.models.billing import BillingPlan

    db = SessionLocal()
    try:
        count = db.query(BillingPlan).count()
        if count > 0:
            return
        plans = [
            BillingPlan(name="Free", price_monthly=0, price_yearly=0, is_active=True),
            # ₹199/mo is the Razorpay auto-pay plan (mandate amount = price_monthly).
            BillingPlan(name="Pro", price_monthly=199, price_yearly=1999, is_active=True),
            BillingPlan(name="Business", price_monthly=799, price_yearly=6999, is_active=True),
            BillingPlan(name="Enterprise", price_monthly=None, price_yearly=None, is_active=True),
        ]
        db.add_all(plans)
        db.commit()
        logger.info("Seeded 4 default billing plans")
    finally:
        db.close()
