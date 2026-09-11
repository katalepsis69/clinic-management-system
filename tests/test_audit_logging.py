import logging
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.middleware.audit import AuditLoggingMiddleware


def test_audit_logging_middleware(caplog):
    app = FastAPI()
    app.add_middleware(AuditLoggingMiddleware)

    @app.get("/api/emr/test")
    def emr_endpoint():
        return {"status": "ok"}

    @app.get("/api/other/test")
    def other_endpoint():
        return {"status": "ok"}

    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="audit"):
        res = client.get("/api/emr/test")
        assert res.status_code == 200
        assert any("[AUDIT]" in r.message and "/api/emr/test" in r.message for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="audit"):
        res = client.get("/api/other/test")
        assert res.status_code == 200
        assert not any("[AUDIT]" in r.message for r in caplog.records)

