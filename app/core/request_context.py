
from contextvars import ContextVar

# Stores the unique ID of the current HTTP request.
# Each request gets its own context.
request_id_ctx = ContextVar(
    "request_id",
    default=None
)
