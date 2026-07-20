"""End-to-end tests for the Harbormasterd daemon's HTTP API.

Uses FastAPI's TestClient against the in-process ``app`` object — no need
to spawn ``pad`` separately. Runs in CI as part of the matrix.

These tests cover:
- Auth enforcement on every endpoint (403 without token, 200/4xx with).
- The full lease lifecycle: reserve → bind → who → release.
- Block / unblock.
- Kill against a spawned dummy process.
- Scan / leases / metrics response shapes.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Make the repo root importable so `import pad` works regardless of CWD.
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

# Pin the admin token BEFORE importing the app so require_admin sees a
# deterministic value. We set the module global directly (NOT the env var)
# so we don't poison token_store tests that may run in the same session.
TOKEN = "test-token-do-not-ship"

import pad  # noqa: E402  — env must be set first

pad.ADMIN_TOKEN = TOKEN

_TMP = tempfile.mkdtemp(prefix="pad-test-")
pad.DATA_DIR = _TMP
pad.DB_PATH = os.path.join(_TMP, "pad.db")
pad.AUDIT_LOG = os.path.join(_TMP, "audit.jsonl")
pad.init_db()

AUTH = {"X-API-Key": TOKEN}


@pytest.fixture()
def fresh_db():
    """Wipe all leases and routes between tests so they don't interfere."""
    with pad.get_db() as conn:
        conn.execute("DELETE FROM leases")
        # Also release any leftover guards.
        for port in list(pad._guard_sockets):
            pad._release_guard(port)
        conn.commit()
    # Reset gateway routes in-memory.
    pad.gateway_driver.routes.clear()
    import os as _os
    if _os.path.exists(pad.gateway_driver.store_path):
        _os.unlink(pad.gateway_driver.store_path)
    yield


@pytest.fixture()
def client():
    # ``with`` triggers startup/shutdown. The background thread sleeps 30s,
    # so it won't run during these short tests.
    with TestClient(pad.app) as c:
        yield c


def _free_port_hint() -> int:
    """Pick an ephemeral port unlikely to clash with a real listener."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/health",
    "/scan",
    "/leases",
    "/metrics",
])
def test_read_endpoints_require_token(client, fresh_db, path):
    """No X-API-Key → 403 on every read endpoint."""
    r = client.get(path)
    assert r.status_code == 403, f"{path} should require auth, got {r.status_code}"


@pytest.mark.parametrize("path", [
    "/health",
    "/scan",
    "/leases",
    "/metrics",
])
def test_read_endpoints_accept_valid_token(client, fresh_db, path):
    """Valid X-API-Key → not 403 (may be 200 or another legitimate code)."""
    r = client.get(path, headers=AUTH)
    assert r.status_code != 403, f"{path} rejected valid token: {r.status_code} {r.text}"


def test_wrong_token_is_rejected(client, fresh_db):
    r = client.get("/health", headers={"X-API-Key": "wrong"})
    assert r.status_code == 403


def test_health_returns_expected_shape(client, fresh_db):
    r = client.get("/health", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    for key in ("status", "version", "active_leases", "blocked_ports", "ephemeral_range"):
        assert key in body, f"health missing {key}"


# ---------------------------------------------------------------------------
# Reserve → Bind → Who → Release lifecycle
# ---------------------------------------------------------------------------

def test_reserve_creates_reserved_lease(client, fresh_db):
    r = client.post("/reserve", json={"name": "svc-a", "ttl_sec": 60}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "RESERVED"
    assert body["port"] > 0
    assert body["owner"] if "owner" in body else True  # owner implicit in name
    # Clean up
    client.post("/release", json={"port": body["port"]}, headers=AUTH)


def test_reserve_then_bind_transitions_to_bound(client, fresh_db):
    r = client.post("/reserve", json={"name": "svc-b", "ttl_sec": 60}, headers=AUTH)
    assert r.status_code == 200, r.text
    port = r.json()["port"]

    r = client.post("/bind", json={"port": port, "name": "svc-b", "pid": 12345}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "BOUND"

    r = client.get(f"/who?port={port}", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["state"] == "BOUND"
    assert r.json()["pid"] == 12345


def test_who_returns_404_for_unknown_port(client, fresh_db):
    r = client.get("/who?port=59999", headers=AUTH)
    assert r.status_code == 404


def test_release_by_port(client, fresh_db):
    r = client.post("/reserve", json={"name": "svc-c", "ttl_sec": 60}, headers=AUTH)
    port = r.json()["port"]

    r = client.post("/release", json={"port": port}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["count"] == 1

    # who should now 404
    r = client.get(f"/who?port={port}", headers=AUTH)
    assert r.status_code == 404


def test_release_by_name(client, fresh_db):
    client.post("/reserve", json={"name": "svc-d", "ttl_sec": 60}, headers=AUTH)
    client.post("/reserve", json={"name": "svc-d", "ttl_sec": 60}, headers=AUTH)

    r = client.post("/release", json={"name": "svc-d"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_bind_404_on_unknown_port(client, fresh_db):
    r = client.post("/bind", json={"port": 59999, "name": "x"}, headers=AUTH)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Block / Unblock
# ---------------------------------------------------------------------------

def test_block_then_unblock(client, fresh_db):
    port = _free_port_hint()
    r = client.post("/block", json={"port": port, "reason": "testing"}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "BLOCKED"

    r = client.get(f"/who?port={port}", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["state"] == "BLOCKED"

    r = client.post("/unblock", params={"port": port}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["state"] == "FREE"

    r = client.get(f"/who?port={port}", headers=AUTH)
    assert r.status_code == 404


def test_unblock_404_on_unknown(client, fresh_db):
    r = client.post("/unblock", params={"port": 59999}, headers=AUTH)
    assert r.status_code == 404


def test_unblock_409_on_non_blocked(client, fresh_db):
    r = client.post("/reserve", json={"name": "svc-e", "ttl_sec": 60}, headers=AUTH)
    port = r.json()["port"]
    r = client.post("/unblock", params={"port": port}, headers=AUTH)
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Scan / Leases / Metrics
# ---------------------------------------------------------------------------

def test_scan_shape(client, fresh_db):
    client.post("/reserve", json={"name": "scan-svc", "ttl_sec": 60}, headers=AUTH)
    r = client.get("/scan", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert "managed" in body and "unmanaged" in body
    assert body["managed_count"] >= 1
    assert any(l["owner"] == "scan-svc" for l in body["managed"])


def test_leases_filter_by_state(client, fresh_db):
    client.post("/reserve", json={"name": "lf", "ttl_sec": 60}, headers=AUTH)
    r = client.get("/leases?state=RESERVED", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert all(l["state"] == "RESERVED" for l in body["leases"])


def test_leases_rejects_invalid_state(client, fresh_db):
    r = client.get("/leases?state=BOGUS", headers=AUTH)
    assert r.status_code == 400


def test_metrics_shape(client, fresh_db):
    r = client.get("/metrics", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert "counters" in body and "gauges" in body
    for k in ("processes_spawned_total", "auto_heals_total"):
        assert k in body["counters"]


# ---------------------------------------------------------------------------
# Kill — uses /spawn to create a real managed process
# ---------------------------------------------------------------------------

def test_kill_managed_process(client, fresh_db):
    # Spawn a long-lived dummy process via the daemon's own /spawn endpoint.
    r = client.post("/spawn", json={
        "name": "kill-target",
        "cmd": [sys.executable, "-c", "import time; time.sleep(60)"],
        "ttl_sec": 60,
    }, headers=AUTH)
    assert r.status_code == 200, r.text
    port = r.json()["port"]
    pid = r.json()["pid"]
    assert pid, "spawned process should have a pid"

    try:
        r = client.post("/kill", json={"port": port, "force": True}, headers=AUTH)
        assert r.status_code == 200, r.text
        assert pid in r.json()["killed_pids"]
    finally:
        # Ensure cleanup even if the assertion fails.
        client.post("/kill", json={"port": port, "force": True}, headers=AUTH)
        client.post("/release", json={"port": port}, headers=AUTH)

    # Give the OS a moment to reap.
    time.sleep(0.2)
    import psutil
    try:
        assert not psutil.Process(pid).is_running()
    except psutil.NoSuchProcess:
        pass  # expected — it's dead


def test_kill_unknown_port_404(client, fresh_db):
    r = client.post("/kill", json={"port": 59999}, headers=AUTH)
    assert r.status_code == 404


# ===========================================================================
# Routes (/routes GET/POST/DELETE)
# ===========================================================================

def test_routes_require_auth(client, fresh_db):
    r = client.get("/routes")
    assert r.status_code == 403


def test_routes_lifecycle(client, fresh_db):
    # Empty initially.
    r = client.get("/routes", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["count"] == 0

    # Add a route.
    r = client.post("/routes", json={
        "host": "myapp.pa.local",
        "target": "http://127.0.0.1:3000",
        "protocols": ["http", "ws"],
    }, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["host"] == "myapp.pa.local"

    # List shows it.
    r = client.get("/routes", headers=AUTH)
    routes = r.json()["routes"]
    assert any(rt["host"] == "myapp.pa.local" for rt in routes)

    # Duplicate host → 409.
    r = client.post("/routes", json={
        "host": "myapp.pa.local",
        "target": "http://127.0.0.1:9999",
    }, headers=AUTH)
    assert r.status_code == 409

    # Delete by host.
    r = client.delete("/routes/myapp.pa.local", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["removed"] == "myapp.pa.local"

    # Now gone.
    r = client.get("/routes", headers=AUTH)
    assert r.json()["count"] == 0


def test_routes_delete_unknown_404(client, fresh_db):
    r = client.delete("/routes/nope.pa.local", headers=AUTH)
    assert r.status_code == 404


def test_routes_namespace_filter(client, fresh_db):
    client.post("/routes", json={
        "host": "a.pa.local", "target": "http://127.0.0.1:1", "namespace": "team",
    }, headers=AUTH)
    client.post("/routes", json={
        "host": "b.pa.local", "target": "http://127.0.0.1:2",
    }, headers=AUTH)

    r = client.get("/routes?namespace=team", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert r.json()["routes"][0]["host"] == "a.pa.local"


def test_routes_persist_across_driver_reload(client, fresh_db):
    """A new TraefikDriver instance should load routes from the JSON store."""
    client.post("/routes", json={
        "host": "persist.pa.local", "target": "http://127.0.0.1:5000",
    }, headers=AUTH)

    # Simulate a daemon restart: construct a fresh driver pointed at the
    # same store path.
    new_driver = pad.TraefikDriver(store_path=pad.gateway_driver.store_path)
    assert new_driver.find_by_host("persist.pa.local") is not None


# ===========================================================================
# Policy (/policy GET/POST)
# ===========================================================================

def test_policy_get(client, fresh_db):
    r = client.get("/policy", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert "policy" in body
    assert "max_ttl" in body["policy"]


def test_policy_apply_known_key(client, fresh_db):
    r = client.post("/policy", json={"max_ttl": 120}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["policy"]["max_ttl"] == 120

    # Sticks on subsequent GET.
    r = client.get("/policy", headers=AUTH)
    assert r.json()["policy"]["max_ttl"] == 120


def test_policy_apply_rejects_unknown_key(client, fresh_db):
    r = client.post("/policy", json={"bogus_key": 1}, headers=AUTH)
    assert r.status_code == 400


# ===========================================================================
# /scan rich shape, /metrics flat aliases, /who by service
# ===========================================================================

def test_scan_returns_legacy_shape(client, fresh_db):
    client.post("/reserve", json={"name": "shape-svc", "ttl_sec": 60}, headers=AUTH)
    r = client.get("/scan", headers=AUTH)
    body = r.json()
    # Canonical keys:
    assert "managed" in body and "unmanaged" in body
    # Legacy keys:
    assert "scanned_at" in body
    assert "active_ports" in body and isinstance(body["active_ports"], list)
    assert "conflicts" in body and isinstance(body["conflicts"], list)
    assert "guarded_ports" in body and isinstance(body["guarded_ports"], list)
    assert "metrics" in body and "leases_active" in body["metrics"]
    # active_ports should include our reserved port.
    ports = [p["port"] for p in body["active_ports"]]
    reserved = [m["port"] for m in body["managed"]]
    assert any(p in reserved for p in ports)


def test_metrics_has_flat_aliases(client, fresh_db):
    r = client.get("/metrics", headers=AUTH)
    body = r.json()
    # Nested shape (back-compat with v1 test):
    assert "counters" in body and "gauges" in body
    # Flat aliases consumed by pa-platform metrics:
    for k in ("leases_active", "blocks_active",
              "conflicts_detected_total", "reassignments_total"):
        assert k in body, f"flat alias {k} missing"


def test_who_by_service(client, fresh_db):
    client.post("/reserve", json={"name": "svc-byname", "ttl_sec": 60}, headers=AUTH)
    r = client.get("/who?service=svc-byname", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["owner"] == "svc-byname"
    assert "url" in body and body["url"]


def test_who_requires_port_or_service(client, fresh_db):
    r = client.get("/who", headers=AUTH)
    assert r.status_code == 400


# ===========================================================================
# TTL enforcement in /spawn
# ===========================================================================

def test_spawn_ttl_clamped_to_policy(client, fresh_db):
    """max_ttl policy should clamp an oversized ttl_sec in /spawn."""
    # Lower the policy max_ttl.
    client.post("/policy", json={"max_ttl": 60}, headers=AUTH)

    r = client.post("/spawn", json={
        "name": "ttl-svc",
        "cmd": [sys.executable, "-c", "import time; time.sleep(30)"],
        "ttl_sec": 3600,  # way over the 60s cap
    }, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["expires_at"] is not None
    # Clamp should bring it within ~60s of now.
    drift = body["expires_at"] - int(time.time())
    assert drift <= 70, f"TTL not clamped: drift={drift}"

    # Clean up the spawned process.
    client.post("/kill", json={"port": body["port"], "force": True}, headers=AUTH)


# ===========================================================================
# /kill policy branch (require_admin_for_kill=False opens it)
# ===========================================================================

def test_kill_open_when_policy_disabled(client, fresh_db):
    """When require_admin_for_kill=False, kill works without a token."""
    client.post("/policy", json={"require_admin_for_kill": False}, headers=AUTH)

    r = client.post("/spawn", json={
        "name": "kill-open",
        "cmd": [sys.executable, "-c", "import time; time.sleep(30)"],
    }, headers=AUTH)
    assert r.status_code == 200, r.text
    port = r.json()["port"]
    pid = r.json()["pid"]

    try:
        # Kill WITHOUT the auth header — should succeed now.
        r = client.post("/kill", json={"port": port, "force": True})
        assert r.status_code == 200, r.text
        assert pid in r.json()["killed_pids"]
    finally:
        # Restore policy and clean up.
        client.post("/policy", json={"require_admin_for_kill": True}, headers=AUTH)
        client.post("/kill", json={"port": port, "force": True}, headers=AUTH)
        client.post("/release", json={"port": port}, headers=AUTH)

