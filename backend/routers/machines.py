from typing import List

from fastapi import APIRouter, Depends, HTTPException

from backend.repository import get_repository
from backend.schemas import Machine, Measurement

router = APIRouter(prefix="/machines", tags=["Makineler"])


@router.get("", response_model=List[Machine])
def list_machines(repo=Depends(get_repository)):
    """Makine listesi."""
    return repo.get_machines()


@router.get("/{machine_id}", response_model=Machine)
def get_machine(machine_id: int, repo=Depends(get_repository)):
    """Tek bir makinenin bilgileri."""
    machine = repo.get_machine(machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Makine bulunamadı")
    return machine


@router.get("/{machine_id}/latest", response_model=Measurement)
def get_latest(machine_id: int, repo=Depends(get_repository)):
    """Makinenin en son ölçümü (web panelindeki durum kartları için)."""
    if repo.get_machine(machine_id) is None:
        raise HTTPException(status_code=404, detail="Makine bulunamadı")
    latest = repo.get_latest_measurement(machine_id)
    if latest is None:
        raise HTTPException(status_code=404, detail="Bu makine için ölçüm yok")
    return latest
