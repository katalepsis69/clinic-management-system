from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root_serves_html():
    res = client.get("/")
    assert res.status_code == 200
    assert "Clinic Management System" in res.text


def test_api_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "service" in data


def test_public_display_serves_html():
    res = client.get("/display")
    assert res.status_code == 200
    assert "NOW SERVING" in res.text or "Queue" in res.text


def test_static_files_served():
    res = client.get("/static/app.js")
    assert res.status_code == 200


def test_compiled_css_served():
    res = client.get("/static/css/app.css")
    assert res.status_code == 200
    assert len(res.text) > 10000  # compiled Tailwind + design system
    assert ".card" in res.text


def test_no_runtime_cdn_dependencies():
    # Pages must not depend on the Tailwind CDN (offline/air-gapped ready).
    for path in ("/", "/display"):
        res = client.get(path)
        assert res.status_code == 200
        assert "cdn.tailwindcss.com" not in res.text
        assert 'href="/static/css/app.css"' in res.text


def test_responsive_layout_present():
    # Portal grids collapse 1 -> 2 -> 3 columns; body reserves dvh height.
    res = client.get("/")
    assert "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3" in res.text
    assert "min-h-[100dvh]" in res.text


def test_aria_tabs_and_labels():
    # WAI-ARIA tab semantics and explicit label/input associations.
    res = client.get("/")
    assert 'role="tablist"' in res.text
    assert 'aria-selected="true"' in res.text
    assert '<label for="appointmentDate"' in res.text


def test_pwa_manifest_and_sw_endpoints():
    # PWA Manifest
    res_m = client.get("/manifest.json")
    assert res_m.status_code == 200
    assert "application/manifest+json" in res_m.headers.get("content-type", "")
    manifest_data = res_m.json()
    assert manifest_data["short_name"] == "ClinicCare"
    assert manifest_data["display"] == "standalone"
    assert len(manifest_data["icons"]) >= 3

    # Service Worker
    res_sw = client.get("/sw.js")
    assert res_sw.status_code == 200
    assert "application/javascript" in res_sw.headers.get("content-type", "")
    assert res_sw.headers.get("service-worker-allowed") == "/"
    assert "CACHE_NAME" in res_sw.text


def test_pwa_mobile_navigation_and_banners():
    res = client.get("/")
    assert res.status_code == 200
    assert '<link rel="manifest" href="/manifest.json">' in res.text
    assert 'id="mobileBottomNav"' in res.text
    assert 'id="pwaInstallBanner"' in res.text
    assert 'id="offlineStatusBar"' in res.text
    assert 'id="headerInstallBtn"' in res.text