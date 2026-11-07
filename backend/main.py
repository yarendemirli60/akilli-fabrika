"""
Akıllı Fabrika – FastAPI backend

Çalıştırma (proje kök klasöründen):
    uvicorn backend.main:app --reload

API dokümantasyonu:
    http://127.0.0.1:8000/docs
"""
import mysql.connector
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.repository import get_repository
from backend.routers import alerts, machines, measurements

app = FastAPI(
    title="Akıllı Fabrika API",
    description="Üç CNC makinesinin ölçüm, durum ve uyarı verilerini sunar.",
    version="0.2.0",
)

# Web paneli farklı bir adresten (ör. Live Server, 127.0.0.1:5500) istek atacağı için
# tarayıcının bu isteklere izin vermesi gerekiyor. Geliştirme aşamasında herkese açık.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(mysql.connector.Error)
def database_error_handler(request: Request, exc: mysql.connector.Error):
    # MySQL kapalıysa ya da .env yanlışsa 500 yerine anlaşılır bir mesaj dön
    return JSONResponse(
        status_code=503,
        content={"detail": "Veritabanına bağlanılamadı. MySQL çalışıyor mu, .env ayarları doğru mu?"},
    )


app.include_router(machines.router)
app.include_router(measurements.router)
app.include_router(alerts.router)


@app.get("/health", tags=["Sistem"])
def health():
    """API çalışıyor mu?"""
    return {"status": "ok"}


@app.get("/health/db", tags=["Sistem"])
def health_db(repo=Depends(get_repository)):
    """Veritabanı bağlantısı çalışıyor mu?"""
    repo.ping()
    return {"database": "ok"}
