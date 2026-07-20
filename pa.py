#!/usr/bin/env python3
"""
🚢 Harbormasterd CLI (pa)
Zero-thinking port management for development teams

Commands:
  pa reserve --name web --prefer 3000     # Reserve a port
  pa run --name web -- npm start          # Spawn with port injection
  pa bind --name web --port 3001          # Bind to reserved port
  pa release --name web                   # Release port lease
  pa who 3000                             # Query port ownership  
  pa scan                                 # Scan all ports
  pa block 3000 --reason "Dev gateway"    # Block port (admin)
  pa kill 3000                            # Kill process (admin)
  pa doctor                               # Diagnose project ports
  pa events                               # Live event stream

Features:
- Zero race conditions with atomic spawn
- Framework detection (Next.js, Vite, etc.)
- Project configuration (.pa.yaml)
- Live updates via server-sent events
- Intelligent port assignment
"""

import click
import requests
import json
import os
import sys
import time
import yaml
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime

from token_store import get_token, get_or_create_token

# Configuration
DEFAULT_PAD_URL = "http://127.0.0.1:9999"
PAD_URL = os.getenv("PAD_URL", DEFAULT_PAD_URL)
ADMIN_TOKEN = get_token() or ""  # Empty forces auth failure with clear message

# Framework detection patterns
FRAMEWORK_PATTERNS = {
    "next.js": {
        "files": ["next.config.js", "next.config.ts", "package.json"],
        "package_deps": ["next"],
        "default_port": 3000,
        "port_flag": "--port",
        "start_script": "dev"
    },
    "vite": {
        "files": ["vite.config.js", "vite.config.ts", "package.json"],
        "package_deps": ["vite"],
        "default_port": 5173,
        "port_flag": "--port",
        "start_script": "dev"
    },
    "create-react-app": {
        "files": ["package.json"],
        "package_deps": ["react-scripts"],
        "default_port": 3000,
        "env_var": "PORT",
        "start_script": "start"
    },
    "vue-cli": {
        "files": ["vue.config.js", "package.json"],
        "package_deps": ["@vue/cli-service"],
        "default_port": 8080,
        "port_flag": "--port",
        "start_script": "serve"
    },
    "django": {
        "files": ["manage.py", "requirements.txt"],
        "default_port": 8000,
        "port_flag": "",
        "start_cmd": ["python", "manage.py", "runserver"]
    },
    "fastapi": {
        "files": ["main.py", "requirements.txt"],
        "package_deps": ["fastapi"],
        "default_port": 8000,
        "start_cmd": ["uvicorn", "main:app", "--reload", "--host", "0.0.0.0"]
    },
    "express": {
        "files": ["package.json"],
        "package_deps": ["express"],
        "default_port": 3000,
        "env_var": "PORT"
    }
}

class PAClient:
    """Harbormasterd API client"""
    
    def __init__(self, base_url: str = PAD_URL, admin_token: str = ADMIN_TOKEN):
        self.base_url = base_url.rstrip('/')
        self.admin_token = admin_token
        
    def _request(self, method: str, path: str, admin: bool = False, **kwargs) -> Dict[str, Any]:
        """Make HTTP request to Harbormasterd daemon.

        `admin` is kept as a conceptual marker but the X-API-Key header is
        sent unconditionally — every daemon endpoint requires it.
        """
        url = f"{self.base_url}{path}"
        headers = kwargs.pop('headers', {})

        # Every endpoint requires the admin token since v1.0.1.
        if self.admin_token:
            headers['X-API-Key'] = self.admin_token

        try:
            response = requests.request(method, url, headers=headers, timeout=30, **kwargs)

            if response.status_code in (401, 403):
                try:
                    detail = response.json().get('detail', 'Forbidden')
                except Exception:
                    detail = response.text or f"HTTP {response.status_code}"
                click.echo(f"❌ Authentication failed: {detail}")
                click.echo(f"   Set PAD_ADMIN_TOKEN or run `pa print-token` to see the daemon's token.")
                sys.exit(1)

            if response.status_code == 404:
                try:
                    detail = response.json().get('detail', 'Not found')
                except Exception:
                    detail = response.text
                click.echo(f"❌ Endpoint not found: {method} {path}")
                if detail:
                    click.echo(f"   {detail}")
                sys.exit(1)

            if not response.ok:
                try:
                    error = response.json().get('detail', 'Unknown error')
                except Exception:
                    error = response.text or f"HTTP {response.status_code}"
                click.echo(f"❌ API Error: {error}")
                sys.exit(1)

            return response.json()

        except requests.exceptions.ConnectionError:
            click.echo(f"❌ Could not connect to Harbormasterd daemon at {self.base_url}")
            click.echo(f"   Start it with: pad")
            sys.exit(1)
        except requests.exceptions.Timeout:
            click.echo(f"❌ Request timed out")
            sys.exit(1)
    
    def reserve(self, name: str, prefer: Optional[List[int]] = None, ttl_sec: int = 600, 
                requires: Optional[List[str]] = None, guard: bool = False, host: Optional[str] = None) -> Dict[str, Any]:
        """Reserve a port"""
        data = {
            "name": name,
            "ttl_sec": ttl_sec,
            "guard": guard
        }
        if prefer:
            data["prefer"] = prefer
        if requires:
            data["requires"] = requires
        if host:
            data["host"] = host
        
        return self._request("POST", "/reserve", json=data)
    
    def spawn(self, name: str, cmd: List[str], prefer: Optional[List[int]] = None, 
              ttl_sec: int = 600, env: Optional[Dict[str, str]] = None, 
              host: Optional[str] = None) -> Dict[str, Any]:
        """Spawn process with port injection"""
        data = {
            "name": name,
            "cmd": cmd,
            "ttl_sec": ttl_sec,
            "guard": True
        }
        if prefer:
            data["prefer"] = prefer
        if env:
            data["env"] = env
        if host:
            data["host"] = host
        
        return self._request("POST", "/spawn", json=data)
    
    def bind(self, name: str, port: int, pid: Optional[int] = None) -> Dict[str, Any]:
        """Bind to a reserved port"""
        data = {"name": name, "port": port}
        if pid:
            data["pid"] = pid
        
        return self._request("POST", "/bind", json=data)
    
    def release(self, name: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
        """Release port lease"""
        data = {}
        if name:
            data["name"] = name
        if port:
            data["port"] = port
        
        return self._request("POST", "/release", json=data)
    
    def who(self, port: int) -> Dict[str, Any]:
        """Query port ownership"""
        return self._request("GET", f"/who?port={port}")
    
    def scan(self) -> Dict[str, Any]:
        """Scan all ports"""
        return self._request("GET", "/scan")
    
    def block(self, port: int, reason: str = "Manual block", duration_sec: Optional[int] = None) -> Dict[str, Any]:
        """Block a port (admin)"""
        data = {"port": port, "reason": reason}
        if duration_sec:
            data["duration_sec"] = duration_sec
        
        return self._request("POST", "/block", json=data, admin=True)
    
    def unblock(self, port: int) -> Dict[str, Any]:
        """Unblock a port (admin)"""
        return self._request("POST", f"/unblock?port={port}", admin=True)
    
    def kill(self, port: int, force: bool = False) -> Dict[str, Any]:
        """Kill process on port (admin)"""
        data = {"port": port, "force": force}
        return self._request("POST", "/kill", json=data, admin=True)
    
    def health(self) -> Dict[str, Any]:
        """Get daemon health status"""
        return self._request("GET", "/health")

    def add_route(self, host: str, target: str, protocols: Optional[List[str]] = None) -> Dict[str, Any]:
        """Add a gateway route."""
        data: Dict[str, Any] = {"host": host, "target": target}
        if protocols:
            data["protocols"] = protocols
        return self._request("POST", "/routes", json=data)

def load_project_config() -> Dict[str, Any]:
    """Load .pa.yaml configuration from current directory"""
    config_file = Path(".pa.yaml")
    if not config_file.exists():
        return {}
    
    try:
        with open(config_file, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        click.echo(f"⚠️  Could not load .pa.yaml: {e}")
        return {}

def detect_framework() -> Optional[Dict[str, Any]]:
    """Detect framework in current directory"""
    cwd = Path('.')
    
    # Check for package.json first
    package_json = cwd / "package.json"
    package_data = {}
    if package_json.exists():
        try:
            with open(package_json, 'r') as f:
                package_data = json.load(f)
        except:
            pass
    
    # Check each framework pattern
    for framework, pattern in FRAMEWORK_PATTERNS.items():
        # Check files
        files_match = any((cwd / f).exists() for f in pattern.get("files", []))
        
        # Check package dependencies
        deps_match = False
        if "package_deps" in pattern and package_data:
            all_deps = {**package_data.get("dependencies", {}), 
                       **package_data.get("devDependencies", {})}
            deps_match = any(dep in all_deps for dep in pattern["package_deps"])
        
        if files_match or deps_match:
            return {"name": framework, **pattern}
    
    return None

def format_port_status(port_data: Dict[str, Any]) -> str:
    """Format port status for display"""
    port = port_data["port"]
    state = port_data["state"]
    owner = port_data.get("owner", "unknown")
    pid = port_data.get("pid")
    
    if state == "FREE":
        return f"🟢 {port:>5} │ FREE"
    elif state == "RESERVED":
        return f"🟡 {port:>5} │ RESERVED by {owner}"
    elif state == "BOUND":
        pid_str = f" (PID {pid})" if pid else ""
        return f"🔴 {port:>5} │ BOUND by {owner}{pid_str}"
    elif state == "BLOCKED":
        reason = port_data.get("reason", "blocked")
        return f"🚫 {port:>5} │ BLOCKED: {reason}"
    else:
        return f"❓ {port:>5} │ {state} by {owner}"

# CLI Commands
@click.group()
@click.option('--url', default=PAD_URL, help='Harbormasterd daemon URL')
@click.pass_context
def cli(ctx, url):
    """🚢 Harbormasterd - Zero-thinking port management"""
    ctx.ensure_object(dict)
    ctx.obj['client'] = PAClient(url)

@cli.command()
@click.option('--name', '-n', required=True, help='Service name')
@click.option('--prefer', '-p', multiple=True, type=int, help='Preferred ports')
@click.option('--ttl', default=600, help='Lease duration in seconds')
@click.option('--guard', is_flag=True, help='Guard port until bind')
@click.option('--host', help='Custom hostname')
@click.pass_context
def reserve(ctx, name, prefer, ttl, guard, host):
    """Reserve a port for a service"""
    client = ctx.obj['client']
    
    # Load project config
    config = load_project_config()
    service_config = config.get("services", {}).get(name, {})
    
    # Merge preferences
    prefer_list = list(prefer) if prefer else service_config.get("prefer", [])
    
    try:
        result = client.reserve(
            name=name,
            prefer=prefer_list,
            ttl_sec=ttl,
            guard=guard,
            host=host or service_config.get("host")
        )
        
        click.echo(f"✅ Reserved port {result['port']} for '{name}'")
        if result.get('url'):
            click.echo(f"🌐 URL: {result['url']}")
        if result.get('expires_at'):
            expires = datetime.fromtimestamp(result['expires_at'])
            click.echo(f"⏰ Expires: {expires.strftime('%H:%M:%S')}")
            
    except SystemExit:
        pass

@cli.command()
@click.option('--name', '-n', required=True, help='Service name')
@click.option('--prefer', '-p', multiple=True, type=int, help='Preferred ports')
@click.option('--ttl', default=3600, help='Lease duration in seconds')
@click.option('--host', help='Custom hostname')
@click.option('--env', multiple=True, help='Environment variables (KEY=value)')
@click.argument('command', nargs=-1, required=True)
@click.pass_context
def run(ctx, name, prefer, ttl, host, env, command):
    """Spawn process with automatic port injection"""
    client = ctx.obj['client']
    
    if not command:
        click.echo("❌ No command specified")
        sys.exit(1)
    
    # Load project config
    config = load_project_config()
    service_config = config.get("services", {}).get(name, {})
    
    # Parse environment variables
    env_dict = {}
    for e in env:
        if '=' in e:
            key, value = e.split('=', 1)
            env_dict[key] = value
    
    # Detect framework if no explicit command modification
    framework = detect_framework()
    cmd_list = list(command)
    
    # Auto-detect npm/yarn scripts
    if len(cmd_list) >= 2 and cmd_list[0] in ['npm', 'yarn', 'pnpm'] and cmd_list[1] in ['start', 'dev', 'serve']:
        if framework and 'port_flag' in framework:
            # Will be handled by PORT env var injection
            pass
    
    # Merge preferences with framework defaults
    prefer_list = list(prefer) if prefer else service_config.get("prefer", [])
    if framework and not prefer_list:
        prefer_list = [framework.get("default_port")]
    
    try:
        click.echo(f"🚀 Spawning '{' '.join(cmd_list)}' for service '{name}'...")
        
        result = client.spawn(
            name=name,
            cmd=cmd_list,
            prefer=prefer_list,
            ttl_sec=ttl,
            env=env_dict,
            host=host or service_config.get("host")
        )
        
        port = result['port']
        pid = result.get('pid')
        url = result.get('url')
        
        click.echo(f"✅ Process started successfully!")
        click.echo(f"📊 Port: {port}")
        click.echo(f"🆔 PID: {pid}")
        if url:
            click.echo(f"🌐 URL: {url}")
        
        # Framework-specific hints
        if framework:
            click.echo(f"🔧 Detected: {framework['name']}")
            if framework.get('env_var'):
                click.echo(f"💡 PORT environment variable injected automatically")
            elif framework.get('port_flag'):
                click.echo(f"💡 Consider adding {framework['port_flag']} {port} to your command")

        # Sync any routes declared in .pa.yaml to the daemon's gateway.
        routes_decl = config.get("routes") or []
        if routes_decl:
            target = f"http://127.0.0.1:{port}"
            for entry in routes_decl:
                rhost = entry.get("host") if isinstance(entry, dict) else None
                if not rhost:
                    continue
                try:
                    client.add_route(rhost, target, entry.get("protocols", ["http"]))
                    click.echo(f"🌐 Route added: {rhost} → {target}")
                except SystemExit:
                    # 409 (already exists) or other error — _request printed it.
                    pass
        
    except SystemExit:
        pass

@cli.command()
@click.option('--name', '-n', required=True, help='Service name')
@click.option('--port', '-p', required=True, type=int, help='Port to bind')
@click.option('--pid', type=int, help='Process ID')
@click.pass_context
def bind(ctx, name, port, pid):
    """Bind to a reserved port"""
    client = ctx.obj['client']
    
    try:
        result = client.bind(name=name, port=port, pid=pid)
        click.echo(f"✅ Bound port {result['port']} to '{name}'")
        if result.get('url'):
            click.echo(f"🌐 URL: {result['url']}")
    except SystemExit:
        pass

@cli.command()
@click.option('--name', '-n', help='Service name to release')
@click.option('--port', '-p', type=int, help='Specific port to release')
@click.pass_context
def release(ctx, name, port):
    """Release port lease"""
    client = ctx.obj['client']
    
    if not name and not port:
        # Try to release based on current directory project
        config = load_project_config()
        if config.get("service"):
            name = config["service"]
    
    if not name and not port:
        click.echo("❌ Must specify --name or --port")
        sys.exit(1)
    
    try:
        result = client.release(name=name, port=port)
        
        if result["status"] == "released":
            ports_str = ", ".join(map(str, result.get("ports", [])))
            click.echo(f"✅ Released {result['count']} lease(s): {ports_str}")
        else:
            click.echo(f"⚠️  No active leases found")
    except SystemExit:
        pass

@cli.command()
@click.argument('port', type=int)
@click.pass_context
def who(ctx, port):
    """Query who owns a port"""
    client = ctx.obj['client']
    
    try:
        result = client.who(port)
        
        click.echo(f"Port {port} status:")
        click.echo(f"  Listening: {'Yes' if result.get('is_listening') else 'No'}")
        click.echo(f"  Guarded: {'Yes' if result.get('guarded') else 'No'}")
        
        lease = result.get('lease')
        if lease:
            click.echo(f"  Lease: {lease['state']} by '{lease['owner']}'")
            if lease.get('expires_at'):
                expires = datetime.fromtimestamp(lease['expires_at'])
                click.echo(f"  Expires: {expires.strftime('%Y-%m-%d %H:%M:%S')}")
            if lease.get('reason'):
                click.echo(f"  Reason: {lease['reason']}")
        
        process = result.get('process')
        if process:
            click.echo(f"  Process: {process['name']} (PID {process['pid']})")
            if process.get('cmdline'):
                click.echo(f"  Command: {process['cmdline']}")
        
        if not lease and not process:
            click.echo(f"  Status: Available")
            
    except SystemExit:
        pass

@cli.command()
@click.option('--live', '-l', is_flag=True, help='Live updating scan')
@click.pass_context
def scan(ctx, live):
    """Scan all ports and show status"""
    client = ctx.obj['client']
    
    def do_scan():
        try:
            result = client.scan()
            
            click.clear()
            click.echo(f"🔍 Port scan at {result['scanned_at']}")
            click.echo("─" * 60)
            
            active_ports = result.get('active_ports', [])
            if active_ports:
                for port_data in sorted(active_ports, key=lambda x: x['port']):
                    click.echo(format_port_status(port_data))
            else:
                click.echo("No active ports found")
            
            conflicts = result.get('conflicts', [])
            if conflicts:
                click.echo("\n⚠️  Conflicts detected:")
                for conflict in conflicts:
                    click.echo(f"  Port {conflict['port']}: lease owner '{conflict['lease_owner']}' vs PID {conflict['actual_pid']}")
            
            guarded = result.get('guarded_ports', [])
            if guarded:
                click.echo(f"\n🛡️  Guarded ports: {', '.join(map(str, guarded))}")
            
            metrics = result.get('metrics', {})
            click.echo(f"\n📊 Stats: {metrics.get('leases_active', 0)} active, "
                      f"{metrics.get('conflicts_detected_total', 0)} conflicts, "
                      f"{metrics.get('reassignments_total', 0)} reassignments")
            
        except SystemExit:
            pass
    
    if live:
        try:
            while True:
                do_scan()
                time.sleep(2)
        except KeyboardInterrupt:
            click.echo("\n👋 Live scan stopped")
    else:
        do_scan()

@cli.command()
@click.argument('port', type=int)
@click.option('--reason', default="Manual block", help='Block reason')
@click.option('--duration', type=int, help='Block duration in seconds')
@click.pass_context
def block(ctx, port, reason, duration):
    """Block a port (admin)"""
    client = ctx.obj['client']
    
    try:
        result = client.block(port, reason, duration)
        click.echo(f"🚫 Blocked port {port}: {reason}")
        if result.get('expires_at'):
            expires = datetime.fromtimestamp(result['expires_at'])
            click.echo(f"⏰ Until: {expires.strftime('%Y-%m-%d %H:%M:%S')}")
    except SystemExit:
        pass

@cli.command()
@click.argument('port', type=int)
@click.pass_context
def unblock(ctx, port):
    """Unblock a port (admin)"""
    client = ctx.obj['client']
    
    try:
        result = client.unblock(port)
        if result["status"] == "unblocked":
            click.echo(f"✅ Unblocked port {port}")
        else:
            click.echo(f"⚠️  Port {port} was not blocked")
    except SystemExit:
        pass

@cli.command()
@click.argument('port', type=int)
@click.option('--force', is_flag=True, help='Force kill non-PAD processes')
@click.pass_context
def kill(ctx, port, force):
    """Kill process on port (admin)"""
    client = ctx.obj['client']
    
    # Confirm dangerous operation
    if not click.confirm(f"⚠️  Kill process on port {port}?"):
        return
    
    try:
        result = client.kill(port, force)
        click.echo(f"💀 Killed process {result['pid']} on port {port}")
    except SystemExit:
        pass

@cli.command()
@click.pass_context
def health(ctx):
    """Check daemon health and stats"""
    client = ctx.obj['client']
    
    try:
        result = client.health()
        
        click.echo(f"🚢 Harbormasterd v{result.get('version', '?')}")
        click.echo(f"Status: {result['status'].upper()}")
        
        uptime_sec = result.get('uptime', 0)
        uptime_str = f"{uptime_sec//60:.0f}m {uptime_sec%60:.0f}s"
        click.echo(f"Uptime: {uptime_str}")
        
        click.echo(f"Active leases: {result.get('active_leases', 0)}")
        click.echo(f"Blocked ports: {result.get('blocked_ports', 0)}")
        click.echo(f"Guarded ports: {result.get('guarded_ports', 0)}")
        click.echo(f"Managed processes: {result.get('managed_processes', 0)}")
        click.echo(f"Event subscribers: {result.get('event_subscribers', 0)}")
        
        ephemeral = result.get('ephemeral_range', [])
        if ephemeral:
            click.echo(f"Ephemeral range: {ephemeral[0]}-{ephemeral[1]}")
        
    except SystemExit:
        pass

@cli.command()
@click.pass_context
def events(ctx):
    """Stream live events from daemon"""
    client = ctx.obj['client']
    
    click.echo("📡 Listening for events (Ctrl+C to stop)...")
    
    try:
        # Use requests for SSE streaming
        url = f"{client.base_url}/events"
        response = requests.get(url, stream=True, timeout=None)
        
        if not response.ok:
            click.echo(f"❌ Failed to connect to event stream: {response.status_code}")
            return
        
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith('data: '):
                    try:
                        event_data = json.loads(line_str[6:])  # Remove 'data: '
                        event_type = event_data.get('type', 'unknown')
                        timestamp = event_data.get('timestamp', '')[:19]  # Trim microseconds
                        
                        if event_type == 'heartbeat':
                            click.echo(f"💓 {timestamp}")
                        elif event_type == 'lease.reserved':
                            click.echo(f"🟡 {timestamp} RESERVED port {event_data.get('port')} for {event_data.get('owner')}")
                        elif event_type == 'lease.bound':
                            click.echo(f"🔴 {timestamp} BOUND port {event_data.get('port')} to {event_data.get('owner')} (PID {event_data.get('pid')})")
                        elif event_type == 'lease.auto_healed':
                            click.echo(f"🏥 {timestamp} AUTO-HEALED port {event_data.get('port')} for {event_data.get('owner')}")
                        elif event_type == 'system.started':
                            click.echo(f"🚢 {timestamp} Harbormasterd started v{event_data.get('version')}")
                        else:
                            click.echo(f"📨 {timestamp} {event_type.upper()}: {json.dumps(event_data, indent=2)}")
                    except json.JSONDecodeError:
                        pass  # Skip malformed events
                
    except KeyboardInterrupt:
        click.echo("\n👋 Event stream stopped")
    except requests.exceptions.RequestException as e:
        click.echo(f"❌ Connection error: {e}")

@cli.command()
@click.pass_context
def doctor(ctx):
    """Diagnose project ports and suggest .pa.yaml config"""
    click.echo("🩺 Harbormasterd Doctor")
    click.echo("─" * 50)
    
    # Detect framework
    framework = detect_framework()
    if framework:
        click.echo(f"🔧 Framework: {framework['name']}")
        click.echo(f"📊 Default port: {framework.get('default_port', 'unknown')}")
    else:
        click.echo("❓ No framework detected")
    
    # Check existing config
    config = load_project_config()
    if config:
        click.echo(f"📋 Found .pa.yaml configuration")
        if config.get("service"):
            click.echo(f"   Service: {config['service']}")
    else:
        click.echo("📋 No .pa.yaml found")
    
    # Suggest configuration
    if not config and framework:
        service_name = os.path.basename(os.getcwd())
        suggested_config = {
            "service": service_name,
            "prefer": [framework.get("default_port")],
            "routes": [{
                "host": f"{service_name}.pa.local",
                "protocols": ["http", "ws"]
            }]
        }
        
        click.echo("\n💡 Suggested .pa.yaml:")
        click.echo(yaml.dump(suggested_config, default_flow_style=False))
        
        if click.confirm("Create this configuration?"):
            with open(".pa.yaml", "w") as f:
                yaml.dump(suggested_config, f)
            click.echo("✅ Created .pa.yaml")
    
    # Check common port conflicts
    client = ctx.obj['client']
    try:
        result = client.scan()
        conflicts = []
        
        if framework:
            default_port = framework.get("default_port")
            for port_data in result.get("active_ports", []):
                if port_data["port"] == default_port and port_data["state"] != "FREE":
                    conflicts.append(port_data)
        
        if conflicts:
            click.echo(f"\n⚠️  Potential conflicts on your framework's default port:")
            for conflict in conflicts:
                click.echo(f"   {format_port_status(conflict)}")
            click.echo(f"\n💡 Solution: Use 'pa run --name {service_name} -- your-start-command'")
        else:
            click.echo(f"\n✅ No port conflicts detected")
    except:
        click.echo("\n❌ Could not check for conflicts (daemon not running?)")

@cli.command(name="print-token")
def print_token():
    """Print the current admin token.

    Use for: export PAD_ADMIN_TOKEN="$(pa print-token)"
    """
    click.echo(get_or_create_token())

def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass
    cli()


if __name__ == '__main__':
    main()
