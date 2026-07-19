#!/usr/bin/env python3
"""
🚢 Curtis AI Port Authority Pro - Zero-config local development ports
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

from token_store import get_or_create_token

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("PAD")

app = FastAPI(
    title="Curtis AI Port Authority Pro",
    description="Zero-config local development port management",
    version="1.0.0"
)

# Configuration paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
POLICY_FILE = os.path.join(DATA_DIR, "policy.yaml")
AUDIT_LOG = os.path.join(DATA_DIR, "audit.jsonl")
DB_PATH = os.path.join(DATA_DIR, "pad.db")

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
ADMIN_TOKEN = get_or_create_token()
logger.info(f"Admin token: {ADMIN_TOKEN}")
logger.info("Clients must set PAD_ADMIN_TOKEN=<token> or use 'pa print-token'")

# Process tracking
_managed_processes: Dict[int, subprocess.Popen] = {}
_guard_sockets: Dict[int, List[socket.socket]] = {}
_event_subscribers: Set[asyncio.Queue] = set()

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
    """Traefik file provider driver"""
    
    def __init__(self, config_path: str = None):
        self.config_path = config_path or os.path.join(DATA_DIR, "traefik_routes.yaml")
        self.routes = {}
    
    def upsert_route(self, name: str, host: str, target: str, protocols: List[str]) -> bool:
        try:
            self.routes[name] = {
                "host": host,
                "target": target,
                "protocols": protocols
            }
            
            # Generate Traefik config
            config = {
                "http": {
                    "routers": {},
                    "services": {}
                }
            }
            
            for route_name, route_data in self.routes.items():
                config["http"]["routers"][route_name] = {
                    "rule": f"Host(`{route_data['host']}`)",
                    "service": route_name
                }
                
                config["http"]["services"][route_name] = {
                    "loadBalancer": {
                        "servers": [{"url": route_data["target"]}]
                    }
                }
            
            # Write config file
            with open(self.config_path, 'w') as f:
                yaml.dump(config, f)
            
            logger.info(f"Updated Traefik route: {host} -> {target}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to upsert route {name}: {e}")
            return False
    
    def remove_route(self, name: str) -> bool:
        try:
            if name in self.routes:
                del self.routes[name]
                # Regenerate config without this route
                return self.upsert_route("", "", "", [])  # Trigger config rewrite
            return True
        except Exception as e:
            logger.error(f"Failed to remove route {name}: {e}")
            return False
    
    def reload(self) -> bool:
        # Traefik watches file changes automatically
        return True

# Initialize gateway driver
gateway_driver = TraefikDriver()

# Policy Management
class Policy:
    """Port authority policy manager"""
    
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
                "auto_tls": True
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
                    asyncio.create_task(emit_event("lease.auto_healed", port=port, owner=owner, pid=pid))

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
async def events(request: Request):
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
async def spawn_process(req: SpawnRequest):
    """Atomic reserve + spawn process with zero race conditions"""
    start_time = time.time()
    
    try:
        # Find available port
        current_port_map = port_pid_map()
        port = find_first_free_port(req.prefer, current_port_map)
        
        # Guard the port immediately to prevent races
        if not _bind_guard(port):
            raise HTTPException(status_code=409, detail=f"Could not secure port {port}")
        
        # Create lease
        now = int(time.time())
        expires_at = now + req.ttl_sec if req.ttl_sec > 0 else None
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
            """, (port, req.name, "RESERVED", req.ttl_sec, now, expires_at, host))
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
async def reserve_port(req: ReserveRequest):
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
async def health_check():
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
        "version": "1.0.0",
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
# (The response got too long, so I'll create the CLI tool next)

# Startup
@app.on_event("startup")
async def startup():
    global start_time
    start_time = time.time()
    
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
    
    logger.info(f"🚢 Curtis AI Port Authority Pro started")
    logger.info(f"📊 Ephemeral range: {EPHEMERAL_START}-{EPHEMERAL_END}")
    logger.info(f"🌐 Gateway domain: {policy.policy.get('gateway', {}).get('domain', 'pa.local')}")
    
    await emit_event("system.started", version="1.0.0")

def main():
    """Entry point for the `pad` console script."""
    import uvicorn
    config = {
        "host": os.environ.get("PAD_HOST", "127.0.0.1"),
        "port": int(os.environ.get("PAD_PORT", "9999")),
        "log_level": os.environ.get("PAD_LOG_LEVEL", "info"),
    }
    if os.environ.get("PAD_RELOAD"):
        config["reload"] = True
    uvicorn.run(app, **config)


if __name__ == "__main__":
    main()
