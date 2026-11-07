"""
Akıllı Fabrika – FastAPI backend

Çalıştırma (proje kök klasöründen):
    uvicorn backend.main:app --reload

Otomatik API dokümantasyonu:
    http://127.0.0.1:8000/docs
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import alerts, machines, measurements

app = FastAPI(
    title="Akıllı Fabrika API",
    description="Üç CNC makinesinin ölçüm, durum ve uyarı verilerini sunar.",
    version="0.1.0",
)

# Web paneli farklı bir adresten (ör. Live Server, 127.0.0.1:5500) istek atacağı için
# tarayıcının bu isteklere izin vermesi gerekir. Geliştirme aşamasında herkese açık.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(machines.router)
app.include_router(measurements.router)
app.include_router(alerts.router)


@app.get("/health", tags=["Sistem"])
def health():
    """API ayakta mı? Basit kontrol."""
    return {"status": "ok"}
