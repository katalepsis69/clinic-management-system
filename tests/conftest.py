import os

# Keep the app-level engine (used by test_main and test_e2e_flow, which import
# app.main) away from the developer's live data/clinic.db. Every other test
# module builds its own in-memory SQLite engine, so this only guards the two
# files that reuse the real engine. Override by exporting DATABASE_URL yourself.
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test-run.db")
