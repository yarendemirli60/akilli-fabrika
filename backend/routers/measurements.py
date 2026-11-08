from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.repository import get_repository
from backend.schemas import Measurement

router = APIRouter(prefix="/measurements", tags=["Ölçümler"])


@router.get("", response_model=List[Measurement])
def list_measurements(
    machine_id: Optional[int] = Query(None, description="Sadece bu makinenin ölçümleri"),
    simulation_id: Optional[int] = Query(None, description="Sadece bu simülasyonun ölçümleri"),
    limit: int = Query(100, ge=1, le=5000, description="En fazla kaç kayıt dönsün"),
    repo=Depends(get_repository),
):
    """Ölçümler, zamana göre sıralı. Grafikler için kullanılır."""
    if machine_id is not None and repo.get_machine(machine_id) is None:
        raise HTTPException(status_code=404, detail="Makine bulunamadı")
    return repo.get_measurements(machine_id=machine_id, limit=limit, simulation_id=simulation_id)
