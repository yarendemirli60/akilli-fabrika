from typing import List

from fastapi import APIRouter, HTTPException

from backend import sample_data
from backend.schemas import Machine, Measurement

router = APIRouter(prefix="/machines", tags=["Makineler"])


@router.get("", response_model=List[Machine])
def list_machines():
    """Üç makinenin listesi."""
    return sample_data.get_machines()


@router.get("/{machine_id}", response_model=Machine)
def get_machine(machine_id: int):
    """Tek bir makinenin bilgileri."""
    machine = sample_data.get_machine(machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Makine bulunamadı")
    return machine


@router.get("/{machine_id}/latest", response_model=Measurement)
def get_latest(machine_id: int):
    """Makinenin en son ölçümü (web panelindeki durum kartları için)."""
    if sample_data.get_machine(machine_id) is None:
        raise HTTPException(status_code=404, detail="Makine bulunamadı")
    latest = sample_data.get_latest_measurement(machine_id)
    if latest is None:
        raise HTTPException(status_code=404, detail="Bu makine için ölçüm yok")
    return latest
