from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os
import logging

# 配置日志系统
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('logs/translation.log'),
        logging.StreamHandler()
    ]
)

from app.config import settings
from app.database import init_db, SessionLocal
from app.api.v1.router import api_router
from app.services.scheduler_service import scheduler_service
from app.services.tts_service import tts_service
from app.services.content_retry_service import content_retry_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    import logging
    import asyncio
    logger = logging.getLogger(__name__)

    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        logger.warning("Application starting with database unavailable")

    try:
        scheduler_service.start()
        logger.info("Scheduler started successfully")
    except Exception as e:
        logger.error(f"Scheduler start failed: {e}")
        logger.warning("Application starting without scheduler")

    # Pre-generate voice previews in background (non-blocking, no await)
    try:
        asyncio.create_task(tts_service.generate_all_previews())
        logger.info("TTS preview generation started in background")
    except Exception as e:
        logger.error(f"TTS preview generation failed: {e}")
        logger.warning("Application starting without TTS previews")

    # Startup healing for content retry
    try:
        db = SessionLocal()
        healing_result = await content_retry_service.startup_healing(db)
        db.close()
        logger.info(f"Content retry healing completed: {healing_result}")
    except Exception as e:
        logger.error(f"Content retry healing failed: {e}")
        logger.warning("Application starting without healing")

    yield

    # Shutdown
    try:
        scheduler_service.shutdown()
        logger.info("Scheduler shutdown successfully")
    except Exception as e:
        logger.error(f"Scheduler shutdown failed: {e}")


app = FastAPI(
    title="AI News API",
    description="Backend API for AI News WeChat Mini Program",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    """Health check endpoint with service status details"""
    from app.database import SessionLocal
    from sqlalchemy import text

    # Check database
    db_status = "unknown"
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)[:50]}"

    # Check scheduler
    scheduler_status = "running" if scheduler_service._is_running else "stopped"

    return {
        "status": "healthy",
        "service": "ai-news-api",
        "components": {
            "database": db_status,
            "scheduler": scheduler_status
        }
    }


# Serve static files
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    """Serve the main HTML page with no-cache headers"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        # Add cache-control headers to prevent browser caching
        return FileResponse(
            index_path,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"message": "AI News API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
