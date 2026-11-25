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
    assert "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-2" in res.text
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


def test_security_headers_and_client_protections():
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"
    assert "default-src 'self'" in res.headers.get("content-security-policy", "")

    # Client anti-inspect deterrents present in scripts
    res_app = client.get("/static/app.js")
    assert "contextmenu" in res_app.text
    assert "debugger" in res_app.text

    res_tv = client.get("/display")
    assert "contextmenu" in res_tv.text
    assert "debugger" in res_tv.text
    assert "-webkit-touch-callout: none" in res.text
    assert "-webkit-touch-callout: none" in res_tv.text


def test_mobile_responsive_adaptations():
    res = client.get("/")
    assert res.status_code == 200
    assert "interactive-widget=resizes-content" in res.text
    assert "font-size: 16px !important" in res.text
    assert "grid grid-cols-2 sm:flex sm:flex-row gap-1.5" in res.text
    assert "h-[100dvh] max-h-[100dvh]" in res.text


def test_guest_navigation_cannot_trap_user_on_login_or_patient():
    res = client.get("/")
    assert res.status_code == 200
    # portalNav must start hidden without sm:block so desktop login hides the Patient tab
    assert 'id="portalNav" class="hidden ' in res.text
    assert 'id="portalNav" class="hidden sm:block' not in res.text
    # Header provides a Sign In exit when viewing guest portals outside login
    assert 'id="headerLoginBtn"' in res.text
    assert "openLoginGateway('login', 'patient')" in res.text

    res_app = client.get("/static/app.js")
    assert res_app.status_code == 200
    assert "syncChromeNav" in res_app.text
    assert "nav.classList.toggle('sm:block', !isLogin)" in res_app.text


def test_boot_avoids_double_reload_and_skeleton_jump():
    res_app = client.get("/static/app.js")
    assert res_app.status_code == 200
    # Only one reload path on SW update (controllerchange), never a second reload in updatefound
    assert res_app.text.count("window.location.reload()") == 1
    assert "updatefound" not in res_app.text
    # Boot settles skeleton -> portal in one swap without delayed 1200ms banner shift
    assert "revealInitialPortal" in res_app.text
    assert "1200" not in res_app.text


def test_signup_layout_and_pending_approval_ui():
    res = client.get("/")
    assert res.status_code == 200
    assert 'id="loginSplitGrid" class="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-5 gap-6 lg:gap-8 items-start"' in res.text
    assert 'id="portalLoginInfoMsg"' in res.text
    assert '<option value="admin">Administrator</option>' in res.text

    res_app = client.get("/static/app.js")
    assert res_app.status_code == 200
    assert "pending_approval" in res_app.text
    assert "approveAdminUser" in res_app.text
    assert "advanceServingTicket" in res_app.text
    assert "loadBillingHistory" in res_app.text
    assert "clinicTodayISO" in res_app.text


def test_philippine_currency_and_phone_formatting():
    res = client.get("/")
    assert res.status_code == 200
    assert "Consultation Fee (PHP)" in res.text
    assert "Itemized Fees (PHP)" in res.text
    assert "Discount (PHP)" in res.text
    assert "USD" not in res.text
    assert "+1 555-" not in res.text

    res_app = client.get("/static/app.js")
    assert res_app.status_code == 200
    assert "en-PH" in res_app.text


def test_qr_generator_and_panel_feature_hooks():
    from app.qr import _format_bits, encode_qr_matrix, make_qr_data_uri

    # ISO/IEC 18004 format info for ECC-L (01) + Mask 0 (000) == 0x77C4
    assert _format_bits(0) == 0x77C4
    assert len(encode_qr_matrix("RX:1234")) == 25
    assert len(encode_qr_matrix("REC:REC-20260905-ABCD1234|PHP:1500.00")) == 29
    uri = make_qr_data_uri("RX:ABCD1234")
    assert uri.startswith("data:image/svg+xml;base64,")

    res_html = client.get("/")
    assert res_html.status_code == 200
    assert 'id="patientPrescriptionsList"' in res_html.text
    assert 'id="staffAppointmentsList"' in res_html.text
    assert 'id="walkinNewFields"' in res_html.text

    res_app = client.get("/static/app.js")
    assert res_app.status_code == 200
    for symbol in ("loadMyPrescriptions", "loadStaffAppointments", "switchWalkinMode", "checkInAppointment"):
        assert symbol in res_app.text
    assert "formatPHP" in res_app.text
    assert "formatPHPhone" in res_app.text
    assert "loadMyAppointments" in res_app.text
    assert "lookupPatients" in res_app.text