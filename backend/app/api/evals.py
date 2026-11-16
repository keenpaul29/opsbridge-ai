from fastapi import APIRouter, Depends, HTTPException

from app.models import EvalRun
from app.repository import TicketRepository, get_repository
from app.schemas import EvalRunOut

router = APIRouter(prefix="/evals", tags=["evals"])


@router.get("/latest", response_model=EvalRunOut)
async def latest_eval(repo: TicketRepository = Depends(get_repository)) -> EvalRun:
    run = await repo.latest_eval_run()
    if run is None:
        raise HTTPException(status_code=404, detail="no eval runs recorded yet")
    return run
