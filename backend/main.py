import logging
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# --- Render runs `uvicorn main:app --app-dir backend`, which only puts backend/ on the import path ---
# --- Adding the project folder lets the `backend.app...` imports work with that command and with `uvicorn backend.main:app` ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.api.v1.router import api_router

logger = logging.getLogger("car_tracking")

app = FastAPI(title="Car Tracking API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
def validation_error_handler(request: Request, exc: RequestValidationError):
    """FastAPI answers bad input with 422 by default. The API spec wants 400 (malformed JSON,
    wrong types, bad query values). Driver field validation and road GeoJSON query
    validation use 422 as required by their endpoint contracts."""
    status_code = 422 if request.url.path.endswith("/road-segments/geojson") else 400
    errors = exc.errors()
    # Driver bodies distinguish invalid field values (422) from malformed shapes (400).
    if (
        request.method in ("POST", "PUT")
        and request.url.path.rstrip("/").split("/")[1:4] == ["api", "v1", "drivers"]
        and errors
        and all(
            len(error.get("loc", ())) == 2
            and error["loc"][0] == "body"
            and error.get("type") in ("missing", "string_type")
            for error in errors
        )
    ):
        status_code = 422
    problems = []
    for error in errors:
        where = ".".join(str(part) for part in error.get("loc", ()) if part not in ("body", "query", "path"))
        problems.append(f"{where}: {error.get('msg')}" if where else str(error.get("msg")))
    return JSONResponse(status_code=status_code, content={"detail": "; ".join(problems) or "Invalid request."})


@app.exception_handler(Exception)
def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


@app.get("/", tags=["Health"])
async def root():
    return {"service": "Car Tracking API", "status": "ok", "docs": "/docs"}


app.include_router(api_router)
