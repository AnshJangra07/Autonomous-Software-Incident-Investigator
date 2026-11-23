
import uuid

from fastapi import FastAPI, Request

from app.api.routes import router
from app.core.logging_config import setup_logging
from app.core.request_context import request_id_ctx


# Initialize logging
setup_logging()


app = FastAPI(
    title="ASII Demo E-commerce",
    description="Demo application for Autonomous Software Incident Investigator",
    version="1.0.0"
)


# Attach a unique request ID to every incoming request
@app.middleware("http")
async def add_request_id(request: Request, call_next):

    request_id = (
        request.headers.get("X-Request-ID")
        or str(uuid.uuid4())
    )

    token = request_id_ctx.set(request_id)

    try:

        response = await call_next(request)

        response.headers["X-Request-ID"] = request_id

        return response

    finally:

        request_id_ctx.reset(token)


# Register API routes
app.include_router(router)
