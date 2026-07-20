#!/usr/bin/env python3
"""
🚢 Harbormasterd - Zero-config local development ports
The unfair advantage for development teams

New Features:
- Atomic reserve+spawn with zero race conditions
- Auto-heal when processes die
- Policy-based perma-blocks with firewall integration  
- Real-time SSE event streams for IDEs
- Gateway driver interface for *.pa.local URLs
- Process lifecycle management
- Audit trail with tamper-evident logs
"""

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Set, Tuple, AsyncGenerator
import sqlite3
import time
import socket
import psutil
import os
import signal
import subprocess
import threading
import json
import logging
import sys
import asyncio
import yaml
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("PAD")

app = FastAPI(
    title="Harbormasterd",
    description="Zero-config local development port management",
    version="1.0.1"
)

# Configuration paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
POLICY_FILE = os.path.join(DATA_DIR, "policy.yaml")
AUDIT_LOG = os.path.join(DATA_DIR, "audit.jsonl")
DB_PATH = os.path.join(DATA_DIR, "pad.db")
ROUTES_STORE = os.path.join(DATA_DIR, "routes.json")

os.makedirs(DATA_DIR, exist_ok=True)

# Detect ephemeral port range based on OS
def detect_ephemeral_range() -> Tuple[int, int]:
    """Detect OS ephemeral port range"""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/sys/net/ipv4/ip_local_port_range") as f:
                a, b = f.read().strip().split()
                return int(a), int(b)
        elif sys.platform == "darwin":
            import subprocess, re
            lo = int(re.search(r"\d+", subprocess.check_output(["sysctl", "-n", "net.inet.ip.portrange.first"]).decode()).group())
            hi = int(re.search(r"\d+", subprocess.check_output(["sysctl", "-n", "net.inet.ip.portrange.last"]).decode()).group())
            return lo, hi
        elif sys.platform.startswith("win"):
            import subprocess, re
            out = subprocess.check_output(["netsh", "int", "ipv4", "show", "dynamicport", "tcp"]).decode()
            start = int(re.search(r"Start Port\s*:\s*(\d+)", out).group(1))
            num = int(re.search(r"Number of Ports\s*:\s*(\d+)", out).group(1))
            return start, start + num - 1
    except Exception as e:
        logger.warning(f"Failed to detect ephemeral port range: {e}")
    return (49152, 65535)  # IANA default

# Global configuration
EPHEMERAL_START, EPHEMERAL_END = detect_ephemeral_range()
FAMOUS_PORTS = [3000, 3001, 5000, 5173, 8000, 8080, 9000, 9090, 9093]
ADMIN_TOKEN = os.getenv("PAD_ADMIN_TOKEN") or ""  # Set at startup, not import

# Process tracking
_managed_processes: Dict[int, subprocess.Popen] = {}
_guard_sockets: Dict[int, List[socket.socket]] = {}
_event_subscribers: Set[asyncio.Queue] = set()

# Captured at startup so background threads can schedule coroutines
# on the running event loop. None until the lifespan starts.
_main_loop: Optional[asyncio.AbstractEventLoop] = None

# Audit chain (simple Merkle-like)
_last_audit_hash = "genesis"

# Metrics tracking (counters only - gauges computed on demand)
metrics = {
    "conflicts_detected_total": 0,
    "reassignments_total": 0,
    "violations_total": 0,
    "processes_spawned_total": 0,
    "auto_heals_total": 0,
    "reassign_latency": 0.0
}

# Gateway Driver Interface
class GatewayDriver(ABC):
    """Abstract base for gateway implementations"""
    
    @abstractmethod
    def upsert_route(self, name: str, host: str, target: str, protocols: List[str]) -> bool:
        """Add or update a route"""
        pass
    
    @abstractmethod 
    def remove_route(self, name: str) -> bool:
        """Remove a route"""
        pass
    
    @abstractmethod
    def reload(self) -> bool:
        """Reload gateway configuration"""
        pass

class TraefikDriver(GatewayDriver):
    """Traefik file provider driver.

    Routes are persisted to ROUTES_STORE (JSON) so they survive restarts,
    and projected to ``traefik_routes.yaml`` for an external Traefik to
    consume via its file provider.
    """

    def __init__(self, config_path: str = None, store_path: str = None):
        self.config_path = config_path or os.path.join(DATA_DIR, "traefik_routes.yaml")
        self.store_path = store_path or ROUTES_STORE
        self.routes: Dict[str, Dict[str, Any]] = {}
        self._load_routes()

    def _load_routes(self) -> None:
        """Load persisted routes from the JSON store."""
        try:
            if os.path.exists(self.store_path):
                with open(self.store_path, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # Drop any legacy empty-key entry from the old remove_route bug.
                    self.routes = {k: v for k, v in data.items() if k}
        except Exception as e:
            logger.warning(f"Failed to load routes store: {e}")
            self.routes = {}

    def _persist_routes(self) -> None:
        """Atomically write the routes JSON store."""
        tmp = self.store_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.routes, f, indent=2)
        os.replace(tmp, self.store_path)

    def _write_config(self) -> None:
        """Regenerate the Traefik file-provider config from self.routes."""
        config = {"http": {"routers": {}, "services": {}}}
        for route_name, route_data in self.routes.items():
            config["http"]["routers"][route_name] = {
                "rule": f"Host(`{route_data['host']}`)",
                "service": route_name,
            }
            config["http"]["services"][route_name] = {
                "loadBalancer": {
                    "servers": [{"url": route_data["target"]}]
                }
            }
        with open(self.config_path, "w") as f:
            yaml.dump(config, f)

    def upsert_route(self, name: str, host: str, target: str, protocols: List[str]) -> bool:
        try:
            self.routes[name] = {
                "host": host,
                "target": target,
                "protocols": protocols,
            }
            self._write_config()
            self._persist_routes()
            logger.info(f"Updated Traefik route: {name} ({host} -> {target})")
            return True
        except Exception as e:
            logger.error(f"Failed to upsert route {name}: {e}")
            return False

    def remove_route(self, name: str) -> bool:
        try:
            if name not in self.routes:
                return False
            del self.routes[name]
            self._write_config()
            self._persist_routes()
            logger.info(f"Removed Traefik route: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove route {name}: {e}")
            return False

    def find_by_host(self, host: str) -> Optional[str]:
        """Return the route name whose host matches, or None."""
        for name, data in self.routes.items():
            if data.get("host") == host:
                return name
        return None

    def reload(self) -> bool:
        # Traefik watches the file provider automatically.
        return True


def get_gateway_driver(driver_name: str, policy_gateway_cfg: Dict[str, Any]) -> "GatewayDriver":
    """Factory selecting a gateway driver by name.

    ``traefik`` (default) writes a file-provider YAML for an external Traefik.
    ``caddy`` talks to a running Caddy's admin API and also manages TLS.
    Unknown names fall back to traefik with a warning.
    """
    name = (driver_name or "traefik").lower()
    if name == "caddy":
        try:
            from drivers.caddy import CaddyDriver
            return CaddyDriver(config={
                "domain": policy_gateway_cfg.get("domain", "pa.local"),
            })
        except Exception as e:
            logger.warning(f"Caddy driver unavailable ({e}); falling back to traefik")
            return TraefikDriver()
    if name != "traefik":
        logger.warning(f"Unknown gateway driver '{name}'; falling back to traefik")
    return TraefikDriver()


# Policy Management
class Policy:
    """Harbormasterd policy manager"""
    
    def __init__(self, policy_file: str):
        self.policy_file = policy_file
        self.policy = self._load_policy()
    
    def _load_policy(self) -> Dict[str, Any]:
        """Load policy from YAML file"""
        default_policy = {
            "block_patterns": ["^.*(3000|3001|80|443)$"],
            "auto_heal": True,
            "max_ttl": 86400,  # 24 hours
            "require_admin_for_kill": True,
            "audit_enabled": True,
            "gateway": {
                "enabled": True,
                "domain": "pa.local",
                "auto_tls": True,
                "driver": "traefik",
            }
        }
        
        try:
            if os.path.exists(self.policy_file):
                with open(self.policy_file, 'r') as f:
                    user_policy = yaml.safe_load(f) or {}
                    default_policy.update(user_policy)
            else:
                # Create default policy file
                with open(self.policy_file, 'w') as f:
                    yaml.dump(default_policy, f)
        except Exception as e:
            logger.warning(f"Failed to load policy: {e}")
        
        return default_policy
    
    def is_port_blocked_by_policy(self, port: int) -> bool:
        """Check if port should be blocked by policy patterns"""
        import re
        for pattern in self.policy.get("block_patterns", []):
            if re.match(pattern, f":{port}"):
                return True
        return False
    
    def should_auto_heal(self) -> bool:
        return self.policy.get("auto_heal", True)
    
    def max_ttl(self) -> int:
        return self.policy.get("max_ttl", 86400)

# Initialize policy
policy = Policy(POLICY_FILE)

# Initialize gateway driver based on policy. Must come after `policy` exists.
_gateway_cfg = policy.policy.get("gateway", {})
gateway_driver = get_gateway_driver(_gateway_cfg.get("driver", "traefik"), _gateway_cfg)

# Audit Trail
def audit_log(event_type: str, **data):
    """Write audit log entry with hash chain"""
    global _last_audit_hash
    
    if not policy.policy.get("audit_enabled", True):
        return
    
    timestamp = datetime.utcnow().isoformat()
    entry = {
        "timestamp": timestamp,
        "event": event_type,
        "data": data,
        "prev_hash": _last_audit_hash
    }
    
    # Calculate hash of this entry
    entry_str = json.dumps(entry, sort_keys=True)
    current_hash = hashlib.sha256(entry_str.encode()).hexdigest()[:16]
    entry["hash"] = current_hash
    
    try:
        with open(AUDIT_LOG, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        _last_audit_hash = current_hash
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")

# Event System
async def emit_event(event_type: str, **data):
    """Emit real-time event to subscribers"""
    global _event_subscribers
    
    event = {
        "type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        **data
    }
    
    # Send to all subscribers
    dead_subscribers = set()
    for subscriber in _event_subscribers.copy():
        try:
            await subscriber.put(event)
        except Exception:
            dead_subscribers.add(subscriber)
    
    # Remove dead subscribers
    _event_subscribers -= dead_subscribers

# Pydantic Models
class SpawnRequest(BaseModel):
    name: str = Field(..., description="Service name")
    cmd: List[str] = Field(..., description="Command to execute")
    prefer: Optional[List[int]] = Field(None, description="Preferred ports")
    ttl_sec: int = Field(600, description="Lease duration")
    guard: bool = Field(True, description="Guard port during spawn")
    env: Optional[Dict[str, str]] = Field(None, description="Environment variables")
    host: Optional[str] = Field(None, description="Custom hostname (defaults to {name}.pa.local)")

class ReserveRequest(BaseModel):
    name: str = Field(..., description="Service name")
    prefer: Optional[List[int]] = Field(None, description="Preferred ports in priority order")
    ttl_sec: int = Field(600, description="Lease time-to-live in seconds")
    requires: Optional[List[str]] = Field(["http"], description="Required protocols: http, ws, tcp, udp")
    guard: bool = Field(False, description="Guard the port until bind is called")
    host: Optional[str] = Field(None, description="Custom hostname")

class BindRequest(BaseModel):
    port: int = Field(..., description="Port to bind")
    name: str = Field(..., description="Service name")
    pid: Optional[int] = Field(None, description="Process ID binding the port")

class ReleaseRequest(BaseModel):
    port: Optional[int] = Field(None, description="Port to release")
    name: Optional[str] = Field(None, description="Service name to release all ports for")

class BlockRequest(BaseModel):
    port: int = Field(..., description="Port to block")
    reason: str = Field("Manual block", description="Reason for blocking")
    duration_sec: Optional[int] = Field(None, description="Block duration in seconds (None = permanent)")

class KillRequest(BaseModel):
    port: int = Field(..., description="Port whose process should be killed")
    force: bool = Field(False, description="Send SIGKILL if SIGTERM fails")

class RouteRequest(BaseModel):
    host: str = Field(..., description="Host header to route (e.g. myapp.pa.local)")
    target: str = Field(..., description="Backend URL (e.g. http://127.0.0.1:3000)")
    protocols: Optional[List[str]] = Field(["http"], description="Protocols: http, ws")
    namespace: Optional[str] = Field(None, description="Optional namespace prefix for the route name")

class LeaseResponse(BaseModel):
    port: int
    url: Optional[str] = None
    host: Optional[str] = None
    pid: Optional[int] = None
    expires_at: Optional[int] = None
    state: str

# Database management (same as before but with new columns)
@contextmanager
def get_db():
    """Get SQLite connection with WAL mode enabled"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initialize SQLite database with required tables and WAL mode"""
    with get_db() as conn:
        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        
        # Create leases table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leases (
                port INTEGER PRIMARY KEY,
                owner TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('FREE', 'RESERVED', 'BOUND', 'BLOCKED')),
                pid INTEGER,
                ttl INTEGER,
                ts INTEGER NOT NULL,
                expires_at INTEGER,
                reason TEXT,
                requires TEXT DEFAULT '["http"]',
                spawned_by_pad INTEGER DEFAULT 0,
                host TEXT,
                auto_heal INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leases_owner ON leases(owner);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leases_state ON leases(state);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leases_expires ON leases(expires_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leases_pid ON leases(pid);")
        
        conn.commit()

# Port management utilities (enhanced)
def _bind_guard(port: int) -> bool:
    """Bind guard sockets to a port (IPv4 + IPv6)"""
    if port in _guard_sockets:
        return True
        
    socks = []
    success = False
    
    # Try IPv4
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(("127.0.0.1", port))
        s.listen(1)
        socks.append(s)
        success = True
    except OSError as e:
        logger.warning(f"Failed to guard IPv4 port {port}: {e}")
    
    # Try IPv6
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(("::1", port, 0, 0))
        s.listen(1)
        socks.append(s)
        success = True
    except OSError as e:
        logger.warning(f"Failed to guard IPv6 port {port}: {e}")
    
    if success:
        _guard_sockets[port] = socks
        logger.info(f"Guarded port {port} with {len(socks)} sockets")
    
    return success

def _release_guard(port: int):
    """Release guard sockets for a port"""
    for s in _guard_sockets.pop(port, []):
        try:
            s.close()
        except Exception as e:
            logger.warning(f"Error closing guard socket for port {port}: {e}")

def port_pid_map() -> Dict[int, Set[int]]:
    """Build a map of listening ports to PIDs"""
    port_map: Dict[int, Set[int]] = {}
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == psutil.CONN_LISTEN and conn.laddr:
                port = conn.laddr.port
                port_map.setdefault(port, set()).add(conn.pid)
    except Exception as e:
        logger.error(f"Error building port-PID map: {e}")
    return port_map

def find_first_free_port(prefer: Optional[List[int]] = None, port_map: Optional[Dict[int, Set[int]]] = None) -> int:
    """Find first available port from preferences or ephemeral range"""
    if port_map is None:
        port_map = port_pid_map()
    
    tried = set()
    
    # Try preferred ports first
    if prefer:
        for port in prefer:
            if port not in tried and port not in port_map:
                return port
            tried.add(port)
    
    # Fall back to ephemeral range
    for port in range(EPHEMERAL_START, EPHEMERAL_END):
        if port not in tried and port not in port_map:
            return port
        tried.add(port)
    
    raise RuntimeError("No free ports available in ephemeral range")

def generate_host_url(port: int, name: str, host: Optional[str], requires: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """Generate hostname and URL"""
    if host is None:
        host = f"{name}.{policy.policy.get('gateway', {}).get('domain', 'pa.local')}"
    
    if "http" in requires:
        url = f"http://{host}" if port == 80 else f"http://{host}:{port}"
    elif "https" in requires:
        url = f"https://{host}" if port == 443 else f"https://{host}:{port}"
    else:
        url = None
    
    return host, url

# Process lifecycle management
def auto_heal_check():
    """Check for dead processes and auto-heal if policy allows"""
    if not policy.should_auto_heal():
        return
    
    with get_db() as conn:
        bound_leases = conn.execute("""
            SELECT port, owner, pid FROM leases 
            WHERE state = 'BOUND' AND auto_heal = 1 AND pid IS NOT NULL
        """).fetchall()
        
        for lease in bound_leases:
            port, owner, pid = lease["port"], lease["owner"], lease["pid"]
            
            # Check if process still exists
            try:
                proc = psutil.Process(pid)
                if not proc.is_running():
                    raise psutil.NoSuchProcess(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Process is dead, re-guard the port
                logger.warning(f"Auto-healing dead process {pid} on port {port} for {owner}")
                
                if _bind_guard(port):
                    # Update lease back to RESERVED
                    conn.execute("""
                        UPDATE leases SET state = 'RESERVED', pid = NULL 
                        WHERE port = ?
                    """, (port,))
                    conn.commit()
                    
                    metrics["auto_heals_total"] += 1
                    audit_log("auto_heal", port=port, owner=owner, dead_pid=pid)
                    # Background thread has no running loop — schedule onto the
                    # main uvicorn loop captured at startup.
                    if _main_loop is not None and _main_loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            emit_event("lease.auto_healed", port=port, owner=owner, pid=pid),
                            _main_loop,
                        )

# Background tasks
def background_tasks():
    """Background maintenance tasks"""
    while True:
        try:
            # Cleanup expired leases
            now = int(time.time())
            with get_db() as conn:
                expired = conn.execute("""
                    SELECT port FROM leases 
                    WHERE expires_at IS NOT NULL AND expires_at < ?
                """, (now,)).fetchall()
                
                for row in expired:
                    _release_guard(row["port"])
                
                cursor = conn.execute("""
                    DELETE FROM leases 
                    WHERE expires_at IS NOT NULL AND expires_at < ?
                """, (now,))
                conn.commit()
                
                if cursor.rowcount > 0:
                    logger.info(f"Cleaned up {cursor.rowcount} expired leases")
            
            # Auto-heal check
            auto_heal_check()
            
            # Clean up dead processes from tracking
            dead_pids = []
            for pid, proc in _managed_processes.copy().items():
                if proc.poll() is not None:
                    dead_pids.append(pid)
            
            for pid in dead_pids:
                del _managed_processes[pid]
            
            time.sleep(30)  # Run every 30 seconds
            
        except Exception as e:
            logger.error(f"Background task error: {e}")
            time.sleep(5)

# Authentication
def require_admin(x_api_key: Optional[str] = Header(None)):
    """Require admin API key for protected endpoints"""
    if not x_api_key or x_api_key != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token required")
    return True

# API Routes

@app.get("/events")
async def events(request: Request, authorized=Depends(require_admin)):
    """Server-sent events stream for real-time updates"""
    global _event_subscribers
    
    async def event_generator() -> AsyncGenerator[str, None]:
        queue = asyncio.Queue()
        _event_subscribers.add(queue)
        
        try:
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    # Wait for event with timeout
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat()})}\n\n"
                    
        except Exception as e:
            logger.error(f"Event stream error: {e}")
        finally:
            _event_subscribers.discard(queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )

@app.post("/spawn", response_model=LeaseResponse)
async def spawn_process(req: SpawnRequest, authorized=Depends(require_admin)):
    """Atomic reserve + spawn process with zero race conditions"""
    start_time = time.time()
    
    try:
        # Find available port
        current_port_map = port_pid_map()
        port = find_first_free_port(req.prefer, current_port_map)
        
        # Guard the port immediately to prevent races
        if not _bind_guard(port):
            raise HTTPException(status_code=409, detail=f"Could not secure port {port}")
        
        # Create lease — clamp TTL against policy (matches /reserve behavior).
        now = int(time.time())
        ttl = min(req.ttl_sec, policy.max_ttl()) if req.ttl_sec > 0 else 0
        expires_at = now + ttl if ttl > 0 else None
        host, url = generate_host_url(port, req.name, req.host, ["http"])
        
        with get_db() as conn:
            conn.execute("""
                INSERT INTO leases 
                (port, owner, state, ttl, ts, expires_at, host, spawned_by_pad, auto_heal)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1)
                ON CONFLICT(port) DO UPDATE SET
                    owner=excluded.owner, state=excluded.state, ttl=excluded.ttl,
                    ts=excluded.ts, expires_at=excluded.expires_at, host=excluded.host,
                    spawned_by_pad=1, auto_heal=1
            """, (port, req.name, "RESERVED", ttl, now, expires_at, host))
            conn.commit()
        
        # Prepare environment
        env = os.environ.copy()
        env.update(req.env or {})
        env["PORT"] = str(port)
        if host:
            env["HOST"] = host
            env["URL"] = url or f"http://localhost:{port}"
        
        # Spawn process
        try:
            proc = subprocess.Popen(req.cmd, env=env, 
                                  stdout=subprocess.PIPE, 
                                  stderr=subprocess.PIPE,
                                  text=True)
            
            # Update lease to BOUND
            with get_db() as conn:
                conn.execute("""
                    UPDATE leases SET state = 'BOUND', pid = ? WHERE port = ?
                """, (proc.pid, port))
                conn.commit()
            
            # Track the process
            _managed_processes[proc.pid] = proc
            
            # Release guard (process now owns the port)
            _release_guard(port)
            
            # Update gateway
            if host and gateway_driver:
                target = f"http://127.0.0.1:{port}"
                gateway_driver.upsert_route(req.name, host, target, ["http"])
            
            # Metrics and events
            metrics["processes_spawned_total"] += 1
            audit_log("process.spawned", port=port, owner=req.name, pid=proc.pid, cmd=req.cmd)
            await emit_event("lease.bound", port=port, owner=req.name, pid=proc.pid, url=url)
            
            logger.info(f"Spawned '{' '.join(req.cmd)}' for {req.name} on port {port} (PID: {proc.pid})")
            
            return LeaseResponse(
                port=port,
                url=url,
                host=host,
                pid=proc.pid,
                expires_at=expires_at,
                state="BOUND"
            )
            
        except Exception as e:
            # Clean up on spawn failure
            _release_guard(port)
            with get_db() as conn:
                conn.execute("DELETE FROM leases WHERE port = ?", (port,))
                conn.commit()
            raise HTTPException(status_code=500, detail=f"Failed to spawn process: {e}")
            
    except Exception as e:
        logger.error(f"Failed to spawn: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/reserve", response_model=LeaseResponse)
async def reserve_port(req: ReserveRequest, authorized=Depends(require_admin)):
    """Reserve a port with automatic conflict resolution"""
    # Apply TTL policy limit
    ttl = min(req.ttl_sec, policy.max_ttl())
    
    try:
        current_port_map = port_pid_map()
        port = find_first_free_port(req.prefer, current_port_map)
        
        # Check policy blocks
        if policy.is_port_blocked_by_policy(port):
            # Find alternative in ephemeral range
            port = find_first_free_port(None, current_port_map)
            metrics["reassignments_total"] += 1
        
        now = int(time.time())
        expires_at = now + ttl if ttl > 0 else None
        host, url = generate_host_url(port, req.name, req.host, req.requires or ["http"])
        
        # Guard if requested
        if req.guard:
            _bind_guard(port)
        
        # Create lease
        with get_db() as conn:
            conn.execute("""
                INSERT INTO leases 
                (port, owner, state, ttl, ts, expires_at, requires, host)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(port) DO UPDATE SET
                    owner=excluded.owner, state=excluded.state, ttl=excluded.ttl,
                    ts=excluded.ts, expires_at=excluded.expires_at, requires=excluded.requires,
                    host=excluded.host
            """, (port, req.name, "RESERVED", ttl, now, expires_at, json.dumps(req.requires), host))
            conn.commit()
        
        audit_log("port.reserved", port=port, owner=req.name, ttl=ttl)
        await emit_event("lease.reserved", port=port, owner=req.name, host=host, url=url)
        
        logger.info(f"Reserved port {port} for {req.name} (TTL: {ttl}s)")
        
        return LeaseResponse(
            port=port,
            url=url,
            host=host,
            expires_at=expires_at,
            state="RESERVED"
        )
        
    except Exception as e:
        logger.error(f"Failed to reserve port: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check(authorized=Depends(require_admin)):
    """Enhanced health check with system stats"""
    gauges = {
        "leases_active": 0,
        "blocks_active": 0
    }
    
    now = int(time.time())
    with get_db() as conn:
        gauges["leases_active"] = conn.execute("""
            SELECT COUNT(*) as count FROM leases 
            WHERE state != 'FREE' AND (expires_at IS NULL OR expires_at > ?)
        """, (now,)).fetchone()["count"]
        
        gauges["blocks_active"] = conn.execute("""
            SELECT COUNT(*) as count FROM leases 
            WHERE state = 'BLOCKED' AND (expires_at IS NULL OR expires_at > ?)
        """, (now,)).fetchone()["count"]
    
    return {
        "status": "healthy",
        "version": "1.0.1",
        "timestamp": datetime.utcnow().isoformat(),
        "uptime": time.time() - start_time if 'start_time' in globals() else 0,
        "active_leases": gauges["leases_active"],
        "blocked_ports": gauges["blocks_active"],
        "guarded_ports": len(_guard_sockets),
        "managed_processes": len(_managed_processes),
        "event_subscribers": len(_event_subscribers),
        "ephemeral_range": [EPHEMERAL_START, EPHEMERAL_END],
        "policy_loaded": bool(policy.policy)
    }

# Continue with other endpoints...

@app.post("/bind", response_model=LeaseResponse)
async def bind_port(req: BindRequest, authorized=Depends(require_admin)):
    """Mark a reserved port as bound to an external PID.

    Transitions a lease from RESERVED → BOUND and records the binding PID.
    Used when a process was started outside the daemon (via `pa run` without
    a managed subprocess, or by the OS) and now owns the port.
    """
    now = int(time.time())
    with get_db() as conn:
        row = conn.execute(
            "SELECT port, owner, state, ttl, expires_at, host FROM leases WHERE port = ?",
            (req.port,),
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail=f"No lease for port {req.port}")
        if row["state"] == "BLOCKED":
            raise HTTPException(status_code=409, detail=f"Port {req.port} is blocked")
        if row["state"] == "BOUND" and row["owner"] != req.name:
            # Allow rebinding only by the original owner to avoid clobbering.
            raise HTTPException(status_code=409, detail=f"Port {req.port} already bound")

        # Release any guard we held during the RESERVED window.
        _release_guard(req.port)

        conn.execute(
            "UPDATE leases SET state = 'BOUND', pid = ?, owner = ?, ts = ? WHERE port = ?",
            (req.pid, req.name, now, req.port),
        )
        conn.commit()

        host = row["host"]
        _, url = generate_host_url(req.port, req.name, host, ["http"])

    audit_log("port.bound", port=req.port, owner=req.name, pid=req.pid)
    await emit_event("lease.bound", port=req.port, owner=req.name, pid=req.pid, url=url)
    logger.info(f"Bound port {req.port} to {req.name} (PID: {req.pid})")

    return LeaseResponse(
        port=req.port,
        url=url,
        host=host,
        pid=req.pid,
        expires_at=row["expires_at"],
        state="BOUND",
    )


@app.post("/release")
async def release_port(req: ReleaseRequest, authorized=Depends(require_admin)):
    """Release a lease by port or by service name."""
    if req.port is None and req.name is None:
        raise HTTPException(status_code=400, detail="Provide either port or name")

    with get_db() as conn:
        if req.port is not None:
            rows = conn.execute(
                "SELECT port, owner, state FROM leases WHERE port = ?", (req.port,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT port, owner, state FROM leases WHERE owner = ?", (req.name,)
            ).fetchall()

        if not rows:
            raise HTTPException(status_code=404, detail="No matching lease")

        released = []
        for row in rows:
            _release_guard(row["port"])
            conn.execute("DELETE FROM leases WHERE port = ?", (row["port"],))
            released.append({"port": row["port"], "owner": row["owner"], "state": row["state"]})
            audit_log("port.released", port=row["port"], owner=row["owner"])
            await emit_event("lease.released", port=row["port"], owner=row["owner"])
        conn.commit()

    logger.info(f"Released {len(released)} lease(s)")
    return {"released": released, "count": len(released)}


@app.get("/who")
async def who(port: Optional[int] = None, service: Optional[str] = None,
              authorized=Depends(require_admin)):
    """Return ownership and state for a port or a named service.

    - ``?port=N`` — look up the lease for that port.
    - ``?service=<owner>`` — look up the lease whose owner matches (e.g.
      ``default/api``). Used by ``pa-platform open`` / ``url``.
    At least one of the two must be provided.
    """
    if port is None and not service:
        raise HTTPException(status_code=400, detail="Provide either port or service")

    with get_db() as conn:
        if service:
            row = conn.execute(
                """SELECT port, owner, state, pid, ttl, expires_at, host,
                          spawned_by_pad, auto_heal, reason, ts, created_at
                   FROM leases WHERE owner = ? ORDER BY ts DESC LIMIT 1""",
                (service,),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT port, owner, state, pid, ttl, expires_at, host,
                          spawned_by_pad, auto_heal, reason, ts, created_at
                   FROM leases WHERE port = ?""",
                (port,),
            ).fetchone()

    if row is None:
        # If a port was given, also report unmanaged listeners on it.
        if port is not None:
            pids = port_pid_map().get(port)
            if pids:
                return {"port": port, "state": "UNMANAGED", "pids": sorted(pids)}
        raise HTTPException(
            status_code=404,
            detail=f"No lease or listener for {f'port {port}' if port else f'service {service}'}",
        )

    # Include a derived ``url`` so ``pa-platform open``/``url`` can open it.
    _, url = generate_host_url(row["port"], row["owner"], row["host"], ["http"])
    return {**dict(row), "url": url}


@app.get("/scan")
async def scan(authorized=Depends(require_admin)):
    """Return all managed leases plus unmanaged listening ports.

    Returns both the canonical shape (``managed`` / ``unmanaged``) and a
    legacy-compatible flat view (``active_ports`` / ``conflicts`` /
    ``guarded_ports`` / ``metrics`` / ``scanned_at``) that older CLIs
    (``pa scan``, ``pa top``) read directly.
    """
    now = int(time.time())
    pid_map = port_pid_map()

    with get_db() as conn:
        managed = [dict(r) for r in conn.execute(
            """SELECT port, owner, state, pid, ttl, expires_at, host, reason
               FROM leases ORDER BY port"""
        ).fetchall()]

    managed_ports = {r["port"] for r in managed}
    unmanaged = []
    for port, pids in sorted(pid_map.items()):
        if port in managed_ports:
            continue
        unmanaged.append({"port": port, "state": "UNMANAGED", "pids": sorted(pids)})

    # Legacy "active_ports" view: combine managed leases + unmanaged listeners
    # into a single sorted list with the row shape format_port_status expects.
    active_ports = []
    conflicts = []
    for r in managed:
        active_ports.append({
            "port": r["port"],
            "state": r["state"],
            "owner": r["owner"],
            "pid": r["pid"],
            "host": r.get("host"),
            "expires_at": r.get("expires_at"),
            "reason": r.get("reason"),
        })
        # Conflict: BOUND lease whose recorded pid is dead, but the port is
        # held by a different pid.
        if r["state"] == "BOUND" and r["pid"]:
            actual = pid_map.get(r["port"], set())
            if r["pid"] not in actual and actual:
                conflicts.append({
                    "port": r["port"],
                    "lease_owner": r["owner"],
                    "lease_pid": r["pid"],
                    "actual_pid": sorted(actual),
                })
    for u in unmanaged:
        active_ports.append({
            "port": u["port"],
            "state": "UNMANAGED",
            "owner": None,
            "pid": (u["pids"][0] if u["pids"] else None),
            "host": None,
            "expires_at": None,
            "reason": None,
        })
    active_ports.sort(key=lambda x: x["port"])

    if conflicts:
        metrics["conflicts_detected_total"] += len(conflicts)

    return {
        # Canonical shape:
        "managed": managed,
        "unmanaged": unmanaged,
        "managed_count": len(managed),
        "unmanaged_count": len(unmanaged),
        # Legacy-compatible shape:
        "scanned_at": datetime.utcnow().isoformat(),
        "active_ports": active_ports,
        "conflicts": conflicts,
        "guarded_ports": sorted(_guard_sockets.keys()),
        "metrics": {
            "leases_active": sum(1 for r in managed if r["state"] != "BLOCKED"),
            "blocks_active": sum(1 for r in managed if r["state"] == "BLOCKED"),
            "conflicts_detected_total": metrics["conflicts_detected_total"],
            "reassignments_total": metrics["reassignments_total"],
        },
    }


@app.get("/leases")
async def list_leases(state: Optional[str] = None, authorized=Depends(require_admin)):
    """List leases, optionally filtered by state."""
    valid = {"FREE", "RESERVED", "BOUND", "BLOCKED"}
    if state is not None and state.upper() not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid state '{state}'. Must be one of: {sorted(valid)}",
        )

    with get_db() as conn:
        if state is not None:
            rows = conn.execute(
                """SELECT port, owner, state, pid, ttl, expires_at, host, auto_heal, ts
                   FROM leases WHERE state = ? ORDER BY port""",
                (state.upper(),),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT port, owner, state, pid, ttl, expires_at, host, auto_heal, ts
                   FROM leases ORDER BY port"""
            ).fetchall()

    return {"leases": [dict(r) for r in rows], "count": len(rows)}


@app.post("/block")
async def block_port(req: BlockRequest, authorized=Depends(require_admin)):
    """Block a port: insert a BLOCKED lease and guard the port."""
    if not _bind_guard(req.port):
        # Port is busy — record the block anyway, but surface the conflict.
        logger.warning(f"Could not fully guard port {req.port} for blocking")

    now = int(time.time())
    expires_at = now + req.duration_sec if req.duration_sec else None

    with get_db() as conn:
        conn.execute(
            """INSERT INTO leases (port, owner, state, ts, expires_at, reason)
               VALUES (?, ?, 'BLOCKED', ?, ?, ?)
               ON CONFLICT(port) DO UPDATE SET
                   state='BLOCKED', owner=excluded.owner, ts=excluded.ts,
                   expires_at=excluded.expires_at, reason=excluded.reason""",
            (req.port, "PAD_SYSTEM", now, expires_at, req.reason),
        )
        conn.commit()

    audit_log("port.blocked", port=req.port, reason=req.reason, expires_at=expires_at)
    await emit_event("port.blocked", port=req.port, reason=req.reason)
    logger.info(f"Blocked port {req.port}: {req.reason}")
    return {"port": req.port, "state": "BLOCKED", "reason": req.reason, "expires_at": expires_at}


@app.post("/unblock")
async def unblock_port(port: int, authorized=Depends(require_admin)):
    """Remove a BLOCKED lease and release its guard."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT port, owner, state FROM leases WHERE port = ?", (port,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"No lease for port {port}")
        if row["state"] != "BLOCKED":
            raise HTTPException(
                status_code=409,
                detail=f"Port {port} is {row['state']}, not BLOCKED",
            )
        conn.execute("DELETE FROM leases WHERE port = ?", (port,))
        conn.commit()

    _release_guard(port)
    audit_log("port.unblocked", port=port)
    await emit_event("port.unblocked", port=port)
    logger.info(f"Unblocked port {port}")
    return {"port": port, "state": "FREE"}


@app.post("/kill")
async def kill_port(req: KillRequest, x_api_key: Optional[str] = Header(None)):
    """Kill the process listening on a port, then release its lease.

    Auth policy is configurable: when ``policy.require_admin_for_kill`` is
    True (the default), the admin token is required. When False, any caller
    may kill (useful for shared dev boxes). Non-daemon processes are still
    gated behind ``force`` regardless of policy.

    Tries SIGTERM first; sends SIGKILL if `force` is set or the process
    survives SIGTERM. Non-daemon processes are killed only when `force`.
    """
    if policy.policy.get("require_admin_for_kill", True):
        if not x_api_key or x_api_key != ADMIN_TOKEN:
            raise HTTPException(status_code=403, detail="Admin token required")
    with get_db() as conn:
        row = conn.execute(
            "SELECT port, owner, state, pid, spawned_by_pad FROM leases WHERE port = ?",
            (req.port,),
        ).fetchone()

    if row is not None and row["pid"] is None:
        # RESERVED lease (no PID bound yet). Refuse to guess what's on the
        # port — the lease owner never bound, so anything we'd find via
        # port_pid_map is unrelated to this lease. Caller should release
        # the lease or wait for /spawn to bind a PID.
        raise HTTPException(
            status_code=409,
            detail=(
                f"Port {req.port} has lease '{row['owner']}' in state "
                f"{row['state']} with no bound PID; release the lease or "
                f"bind first"
            ),
        )

    target_pid = row["pid"] if row else None
    if target_pid is None:
        # No lease at all — fall back to whatever psutil sees on the port.
        pid_map = port_pid_map()
        pids = pid_map.get(req.port)
        if not pids:
            raise HTTPException(
                status_code=404,
                detail=f"No process or lease for port {req.port}",
            )
        if len(pids) > 1 and not req.force:
            raise HTTPException(
                status_code=409,
                detail=f"Multiple PIDs on port {req.port}: {sorted(pids)} (use --force)",
            )
        target_pid = next(iter(pids))
        is_managed = False
    else:
        is_managed = bool(row["spawned_by_pad"])

    try:
        proc = psutil.Process(target_pid)
    except psutil.NoSuchProcess:
        # Already dead — fall through to release the lease.
        proc = None

    killed = []
    if proc is not None:
        if not is_managed and not req.force:
            raise HTTPException(
                status_code=403,
                detail=f"Port {req.port} is held by non-daemon PID {target_pid}; use --force",
            )
        children = proc.children(recursive=True)
        proc.terminate()
        try:
            proc.wait(timeout=5)
            killed.append(target_pid)
        except psutil.TimeoutExpired:
            if not req.force:
                raise HTTPException(
                    status_code=409,
                    detail=f"PID {target_pid} ignored SIGTERM; use --force for SIGKILL",
                )
            proc.kill()
            killed.append(target_pid)
        for child in children:
            try:
                child.kill()
                killed.append(child.pid)
            except psutil.NoSuchProcess:
                pass

    # Release the lease if we owned it.
    if row is not None:
        with get_db() as conn:
            conn.execute("DELETE FROM leases WHERE port = ?", (req.port,))
            conn.commit()
        _release_guard(req.port)
        audit_log("port.killed", port=req.port, pid=target_pid, pids=killed)
        await emit_event("lease.killed", port=req.port, pid=target_pid)

    logger.info(f"Killed PID(s) {killed} on port {req.port}")
    return {"port": req.port, "killed_pids": killed}


@app.get("/metrics")
async def get_metrics(authorized=Depends(require_admin)):
    """Expose daemon counters and live gauges.

    Returns a nested shape (``counters`` / ``gauges``) plus flat top-level
    aliases so legacy clients that read ``metrics['leases_active']`` keep
    working without per-key rewrites.
    """
    now = int(time.time())
    with get_db() as conn:
        leases_active = conn.execute(
            """SELECT COUNT(*) as c FROM leases
               WHERE state != 'BLOCKED' AND (expires_at IS NULL OR expires_at > ?)""",
            (now,),
        ).fetchone()["c"]
        blocks_active = conn.execute(
            """SELECT COUNT(*) as c FROM leases
               WHERE state = 'BLOCKED' AND (expires_at IS NULL OR expires_at > ?)""",
            (now,),
        ).fetchone()["c"]

    gauges = {
        "leases_active": leases_active,
        "blocks_active": blocks_active,
        "guarded_ports": len(_guard_sockets),
        "managed_processes": len(_managed_processes),
        "event_subscribers": len(_event_subscribers),
    }
    return {
        "counters": dict(metrics),
        "gauges": gauges,
        # Flat aliases for legacy clients:
        "leases_active": leases_active,
        "blocks_active": blocks_active,
        "conflicts_detected_total": metrics["conflicts_detected_total"],
        "reassignments_total": metrics["reassignments_total"],
        "violations_total": metrics["violations_total"],
        "processes_spawned_total": metrics["processes_spawned_total"],
        "auto_heals_total": metrics["auto_heals_total"],
        "ephemeral_range": [EPHEMERAL_START, EPHEMERAL_END],
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---- Gateway routes --------------------------------------------------------

@app.get("/routes")
async def list_routes(namespace: Optional[str] = None, authorized=Depends(require_admin)):
    """List gateway routes, optionally filtered by namespace."""
    routes = []
    for name, data in gateway_driver.routes.items():
        if namespace and not name.startswith(f"{namespace}/"):
            continue
        routes.append({"name": name, **data})
    return {"routes": routes, "count": len(routes)}


@app.post("/routes")
async def add_route(req: RouteRequest, authorized=Depends(require_admin)):
    """Add or update a gateway route."""
    if gateway_driver.find_by_host(req.host) is not None:
        raise HTTPException(status_code=409, detail=f"Route for host '{req.host}' already exists")

    # Derive a route name. Namespace it if provided so list-by-namespace works.
    base_name = req.host.split(".")[0].replace("-", "_") or "route"
    name = f"{req.namespace}/{base_name}" if req.namespace else base_name
    # Guarantee uniqueness against existing names.
    if name in gateway_driver.routes:
        suffix = 1
        candidate = f"{name}_{suffix}"
        while candidate in gateway_driver.routes:
            suffix += 1
            candidate = f"{name}_{suffix}"
        name = candidate

    ok = gateway_driver.upsert_route(name, req.host, req.target, req.protocols or ["http"])
    if not ok:
        raise HTTPException(status_code=500, detail="Gateway driver rejected the route")
    audit_log("route.added", name=name, host=req.host, target=req.target)
    await emit_event("route.added", name=name, host=req.host, target=req.target)
    return {"name": name, "host": req.host, "target": req.target, "protocols": req.protocols}


@app.delete("/routes/{host}")
async def remove_route(host: str, authorized=Depends(require_admin)):
    """Remove a gateway route by host."""
    name = gateway_driver.find_by_host(host)
    if name is None:
        raise HTTPException(status_code=404, detail=f"No route for host '{host}'")
    if not gateway_driver.remove_route(name):
        raise HTTPException(status_code=500, detail="Gateway driver failed to remove route")
    audit_log("route.removed", name=name, host=host)
    await emit_event("route.removed", name=name, host=host)
    return {"removed": host, "name": name}


# ---- Policy ----------------------------------------------------------------

@app.get("/policy")
async def get_policy(authorized=Depends(require_admin)):
    """Return the currently loaded policy."""
    return {"policy": policy.policy, "policy_file": policy.policy_file}


@app.post("/policy")
async def apply_policy(fragment: Dict[str, Any], authorized=Depends(require_admin)):
    """Merge a policy fragment into the on-disk policy and reload.

    Only known top-level keys are accepted; unknown keys are rejected with
    400 so typos don't silently no-op.
    """
    allowed = {"block_patterns", "auto_heal", "max_ttl", "require_admin_for_kill",
               "audit_enabled", "gateway"}
    unknown = set(fragment.keys()) - allowed
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown policy keys: {sorted(unknown)}. Allowed: {sorted(allowed)}",
        )

    merged = dict(policy.policy)
    merged.update(fragment)

    # Atomic write: temp + rename.
    tmp = POLICY_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            yaml.dump(merged, f)
        os.replace(tmp, POLICY_FILE)
    except Exception as e:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise HTTPException(status_code=500, detail=f"Failed to write policy: {e}")

    # Reload in place so existing references see the new values.
    policy.policy = merged
    audit_log("policy.applied", keys=sorted(fragment.keys()))
    await emit_event("policy.applied", keys=sorted(fragment.keys()))
    return {"policy": policy.policy}


# Startup
@app.on_event("startup")
async def startup():
    global start_time, _main_loop
    start_time = time.time()
    _main_loop = asyncio.get_running_loop()

    # Initialize
    init_db()

    # Auto-block policy ports
    with get_db() as conn:
        for port in FAMOUS_PORTS:
            if policy.is_port_blocked_by_policy(port):
                if _bind_guard(port):
                    conn.execute("""
                        INSERT OR IGNORE INTO leases
                        (port, owner, state, ts, reason)
                        VALUES (?, ?, ?, ?, ?)
                    """, (port, "PAD_SYSTEM", "BLOCKED", int(time.time()), "Policy auto-block"))
                    logger.info(f"Policy auto-blocked port {port}")
        conn.commit()
    
    # Start background tasks
    task_thread = threading.Thread(target=background_tasks, daemon=True)
    task_thread.start()
    
    logger.info(f"🚢 Harbormasterd started")
    logger.info(f"📊 Ephemeral range: {EPHEMERAL_START}-{EPHEMERAL_END}")
    logger.info(f"🌐 Gateway domain: {policy.policy.get('gateway', {}).get('domain', 'pa.local')}")
    
    await emit_event("system.started", version="1.0.1")

def main():
    """Entry point for the `pad` console script."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="pad",
        description="Harbormasterd daemon — long-running background service.",
    )
    parser.add_argument("--host", default=os.environ.get("PAD_HOST", "127.0.0.1"),
                        help="Bind host (env: PAD_HOST, default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PAD_PORT", "9999")),
                        help="Bind port (env: PAD_PORT, default: 9999)")
    parser.add_argument("--log-level", default=os.environ.get("PAD_LOG_LEVEL", "info"),
                        dest="log_level",
                        help="Uvicorn log level: debug|info|warning|error (env: PAD_LOG_LEVEL)")
    parser.add_argument("--reload", action="store_true",
                        default=bool(os.environ.get("PAD_RELOAD")),
                        help="Enable auto-reload for development (env: PAD_RELOAD)")
    args = parser.parse_args()

    global ADMIN_TOKEN
    from token_store import get_or_create_token
    ADMIN_TOKEN = get_or_create_token()
    logger.info(f"Admin token: {ADMIN_TOKEN}")
    logger.info("Clients must set PAD_ADMIN_TOKEN=<token> or use 'pa print-token'")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port,
                log_level=args.log_level, reload=args.reload)


if __name__ == "__main__":
    main()
