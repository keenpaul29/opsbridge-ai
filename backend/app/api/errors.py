"""Maps decision errors to HTTP so route handlers stay free of try/except."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agent.decisions import NotApprovable, TicketNotFound


def register_error_handlers(app: FastAPI) -> None:
    async def _conflict(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    async def _not_found(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    app.add_exception_handler(NotApprovable, _conflict)
    app.add_exception_handler(TicketNotFound, _not_found)
