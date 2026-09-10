import logging
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

logger = logging.getLogger("audit")

class AuditLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/api/emr", "/api/billing", "/api/patients")):
            # ponytail: structured audit access log; ship to remote SIEM/CloudWatch when configured
            client_ip = request.client.host if request.client else "unknown"
            logger.info(
                "[AUDIT] method=%s path=%s status=%d ip=%s",
                request.method,
                request.url.path,
                response.status_code,
                client_ip,
            )
        return response
