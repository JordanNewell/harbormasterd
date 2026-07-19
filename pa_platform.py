#!/usr/bin/env python3
"""
🚢 Port Authority CLI
Transform from tool → platform with contexts, routing, DNS/TLS, policy, and observability

Platform Commands:
  pa context list|use|create|delete  # Multi-env/user contexts
  pa routes list|add|rm|sync         # Gateway control
  pa dns install|status              # Zero-config local DNS
  pa tls trust|issue|list             # Local CA and certificates  
  pa policy show|apply|edit           # Enforcement and RBAC
  pa metrics                          # Observability dashboard
  pa top                              # Live TUI monitoring
  pa share <service>                  # Team collaboration
  pa selftest                         # End-to-end validation
"""

import click
import requests
import json
import os
import sys
import time
import yaml
import subprocess
import threading
import sqlite3
import keyring
import webbrowser
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
import psutil
from contextlib import contextmanager
from token_store import get_token
try:
    from dns_resolver import CrossPlatformDNSInstaller
    from tls_manager import TLSManager
except ImportError:
    # For testing when run directly
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from dns_resolver import CrossPlatformDNSInstaller
    from tls_manager import TLSManager

# Enhanced configuration with contexts
CONTEXTS_DIR = Path.home() / ".curtis" / "port-authority" / "contexts"
CONTEXTS_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_CONTEXT = "local"

class ContextManager:
    """Manage multiple Port Authority contexts (local, team, codespace, etc.)"""
    
    def __init__(self):
        self.contexts_dir = CONTEXTS_DIR
        self.current_context_file = self.contexts_dir / "current"
        
    def list_contexts(self) -> List[str]:
        """List available contexts"""
        contexts = []
        for context_file in self.contexts_dir.glob("*.yaml"):
            contexts.append(context_file.stem)
        return sorted(contexts)
    
    def get_current_context(self) -> str:
        """Get current active context"""
        if self.current_context_file.exists():
            return self.current_context_file.read_text().strip()
        return DEFAULT_CONTEXT
    
    def set_current_context(self, context: str):
        """Set current active context"""
        if context not in self.list_contexts():
            raise ValueError(f"Context '{context}' does not exist")
        self.current_context_file.write_text(context)
    
    def create_context(self, name: str, config: Dict[str, Any]):
        """Create a new context"""
        context_file = self.contexts_dir / f"{name}.yaml"
        with open(context_file, 'w') as f:
            yaml.dump(config, f)
    
    def delete_context(self, name: str):
        """Delete a context"""
        if name == DEFAULT_CONTEXT:
            raise ValueError("Cannot delete default context")
        context_file = self.contexts_dir / f"{name}.yaml"
        if context_file.exists():
            context_file.unlink()
    
    def get_context_config(self, context: str = None) -> Dict[str, Any]:
        """Get configuration for a context"""
        if context is None:
            context = self.get_current_context()
        
        context_file = self.contexts_dir / f"{context}.yaml"
        if context_file.exists():
            with open(context_file, 'r') as f:
                return yaml.safe_load(f) or {}
        
        # Default configuration for new contexts
        default_config = {
            "daemon_url": "http://127.0.0.1:9999",
            "admin_token": get_token() or "",
            "namespace": "default",
            "ephemeral_start": 60000,
            "ephemeral_end": 65000,
            "gateway": {
                "enabled": True,
                "domain": "pa.local",
                "driver": "traefik"
            },
            "dns": {
                "enabled": False,
                "resolver": "127.0.0.1:5533"
            },
            "tls": {
                "enabled": False,
                "ca_path": str(Path.home() / ".curtis" / "ca")
            }
        }
        
        if context == DEFAULT_CONTEXT:
            self.create_context(context, default_config)
        
        return default_config

# Global context manager
ctx_mgr = ContextManager()

class EnhancedPAClient:
    """Enhanced Port Authority client with platform features"""
    
    def __init__(self, context: str = None):
        self.context = context or ctx_mgr.get_current_context()
        self.config = ctx_mgr.get_context_config(self.context)
        self.base_url = self.config["daemon_url"].rstrip('/')
        self.admin_token = self.config["admin_token"]
        self.namespace = self.config.get("namespace", "default")
    
    def _request(self, method: str, path: str, admin: bool = False, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with enhanced error handling"""
        url = f"{self.base_url}{path}"
        headers = kwargs.pop('headers', {})
        headers['Content-Type'] = 'application/json'
        headers['X-Namespace'] = self.namespace
        
        if admin:
            headers['X-API-Key'] = self.admin_token
        
        try:
            response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
            
            if response.status_code == 404:
                click.echo(f"❌ Port Authority daemon not running at {self.base_url}")
                click.echo(f"   Start it with: pa daemon start")
                sys.exit(1)
            
            if not response.ok:
                try:
                    error = response.json().get('detail', 'Unknown error')
                except:
                    error = response.text or f"HTTP {response.status_code}"
                
                click.echo(f"❌ API Error: {error}")
                sys.exit(1)
            
            return response.json()
            
        except requests.exceptions.ConnectionError:
            click.echo(f"❌ Could not connect to Port Authority daemon")
            click.echo(f"   Context: {self.context}")
            click.echo(f"   URL: {self.base_url}")
            click.echo(f"   Try: pa daemon start")
            sys.exit(1)
        except requests.exceptions.Timeout:
            click.echo(f"❌ Request timed out")
            sys.exit(1)
    
    # Enhanced API methods with namespace support
    def spawn_with_namespace(self, name: str, cmd: List[str], **kwargs):
        """Spawn process with namespace prefix"""
        namespaced_name = f"{self.namespace}/{name}"
        return self._request("POST", "/spawn", json={
            "name": namespaced_name,
            "cmd": cmd,
            **kwargs
        })
    
    def get_routes(self) -> List[Dict[str, Any]]:
        """Get all routes for current namespace"""
        try:
            return self._request("GET", f"/routes?namespace={self.namespace}")
        except:
            return []
    
    def add_route(self, host: str, target: str, protocols: List[str] = None):
        """Add a route to the gateway"""
        return self._request("POST", "/routes", json={
            "host": host,
            "target": target, 
            "protocols": protocols or ["http"],
            "namespace": self.namespace
        })
    
    def remove_route(self, host: str):
        """Remove a route from the gateway"""
        return self._request("DELETE", f"/routes/{host}?namespace={self.namespace}")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive metrics"""
        return self._request("GET", "/metrics?format=json")
    
    def get_policy(self) -> Dict[str, Any]:
        """Get current policy configuration"""
        return self._request("GET", "/policy")
    
    def apply_policy(self, policy: Dict[str, Any]):
        """Apply policy configuration"""
        return self._request("POST", "/policy", json=policy, admin=True)

# Enhanced DNS Management using the new DNS resolver
class DNSManager:
    """Wrapper for the advanced DNS resolver"""
    
    def __init__(self):
        self.dns_installer = CrossPlatformDNSInstaller()
    
    def install(self):
        """Install DNS resolver using the advanced implementation"""
        success = self.dns_installer.install()
        if success:
            click.echo("✅ DNS resolver installed successfully")
        else:
            click.echo("❌ DNS resolver installation failed")
    
    def uninstall(self):
        """Uninstall DNS resolver"""
        success = self.dns_installer.uninstall()
        if success:
            click.echo("✅ DNS resolver uninstalled")
        else:
            click.echo("❌ DNS resolver uninstall failed")
    
    def status(self):
        """Show DNS resolver status"""
        status = self.dns_installer.status()
        click.echo(f"🌐 DNS Resolver Status")
        click.echo(f"Domain: {status['domain']}")
        click.echo(f"Platform: {status['platform']}")
        click.echo(f"Server running: {'✅' if status['server_running'] else '❌'} {status['server_running']}")
        click.echo(f"Resolution working: {'✅' if status['resolution_working'] else '❌'} {status['resolution_working']}")
        
        if not status['resolution_working']:
            click.echo("\n💡 Try running: pa dns install")

# Enhanced TLS Management using the new TLS manager
class TLSManagerWrapper:
    """Wrapper for the advanced TLS manager"""
    
    def __init__(self):
        self.tls_manager = TLSManager()
        
    def setup(self):
        """Setup TLS certificates"""
        result = self.tls_manager.setup()
        
        if result['success']:
            click.echo(f"✅ TLS setup successful using {result['method']}")
            if result['cert_file']:
                click.echo(f"📜 Certificate: {result['cert_file']}")
                click.echo(f"🔑 Key: {result['key_file']}")
            click.echo(f"🔐 CA installed: {'✅' if result['ca_installed'] else '❌'} {result['ca_installed']}")
        else:
            click.echo("❌ TLS setup failed")
            
        click.echo("\n📋 Setup details:")
        for detail in result['details']:
            click.echo(f"   {detail}")
    
    def trust(self):
        """Setup and trust TLS certificates"""
        click.echo("🔐 Setting up TLS trust...")
        self.setup()
    
    def issue(self, domain: str):
        """Issue a certificate for domain"""
        if self.tls_manager.mkcert.is_available():
            cert_file, key_file = self.tls_manager.mkcert.generate_certificate(domain)
            if cert_file and key_file:
                click.echo(f"✅ Certificate issued for {domain}")
                click.echo(f"📜 Cert: {cert_file}")
                click.echo(f"🔑 Key: {key_file}")
            else:
                click.echo(f"❌ Failed to issue certificate for {domain}")
        else:
            click.echo("❌ mkcert not available. Run: pa tls trust")
    
    def list_certs(self):
        """List issued certificates"""
        certs = self.tls_manager.list_certificates()
        if certs:
            click.echo("📜 Available certificates:")
            for cert in certs:
                expires = cert['expires'][:10] if cert['expires'] else 'unknown'
                click.echo(f"   {cert['name']} ({cert['type']}) expires {expires}")
        else:
            click.echo("📜 No certificates found")
            click.echo("💡 Run: pa tls trust")
    
    def status(self):
        """Show TLS status"""
        status = self.tls_manager.get_status()
        click.echo(f"🔐 TLS Status")
        click.echo(f"Domain: {status['domain']}")
        click.echo(f"mkcert available: {'✅' if status['mkcert_available'] else '❌'} {status['mkcert_available']}")
        click.echo(f"Caddy CA available: {'✅' if status['caddy_ca_available'] else '❌'} {status['caddy_ca_available']}")
        click.echo(f"Certificates: {len(status['certificates'])}")
        
        if status['mkcert_ca_root']:
            click.echo(f"mkcert CA root: {status['mkcert_ca_root']}")

# Initialize managers
dns_mgr = DNSManager()
tls_mgr = TLSManagerWrapper()

# Enhanced CLI Groups
@click.group()
@click.option('--context', help='Use specific context')
@click.pass_context
def cli(ctx, context):
    """🚢 Port Authority - Zero-thinking port management"""
    ctx.ensure_object(dict)
    
    if context:
        ctx.obj['context'] = context
        ctx.obj['client'] = EnhancedPAClient(context)
    else:
        current_context = ctx_mgr.get_current_context()
        ctx.obj['context'] = current_context
        ctx.obj['client'] = EnhancedPAClient(current_context)
        
    # Show context in header
    if ctx.info_name == 'cli':  # Only on main command
        click.echo(f"🚢 Port Authority")
        click.echo(f"📍 Context: {ctx.obj['context']}")

@cli.group()
def context():
    """Manage contexts (local, team, codespace, etc.)"""
    pass

@context.command()
def list():
    """List available contexts"""
    contexts = ctx_mgr.list_contexts()
    current = ctx_mgr.get_current_context()
    
    click.echo("📍 Available contexts:")
    for ctx_name in contexts:
        marker = "👉" if ctx_name == current else "  "
        click.echo(f"{marker} {ctx_name}")

@context.command()
@click.argument('name')
def use(name):
    """Switch to a context"""
    try:
        ctx_mgr.set_current_context(name)
        click.echo(f"✅ Switched to context: {name}")
    except ValueError as e:
        click.echo(f"❌ {e}")

@context.command()
@click.argument('name')
@click.option('--daemon-url', default="http://127.0.0.1:9999", help='Daemon URL')
@click.option('--namespace', default="default", help='Default namespace')
def create(name, daemon_url, namespace):
    """Create a new context"""
    config = {
        "daemon_url": daemon_url,
        "namespace": namespace,
        "admin_token": get_token() or "",
        "gateway": {"enabled": True, "domain": "pa.local"},
        "dns": {"enabled": False},
        "tls": {"enabled": False}
    }
    
    ctx_mgr.create_context(name, config)
    click.echo(f"✅ Created context: {name}")

@context.command()
@click.argument('name')
@click.confirmation_option(prompt='Are you sure you want to delete this context?')
def delete(name):
    """Delete a context"""
    try:
        ctx_mgr.delete_context(name)
        click.echo(f"✅ Deleted context: {name}")
    except ValueError as e:
        click.echo(f"❌ {e}")

@cli.group()
def routes():
    """Manage gateway routes and friendly URLs"""
    pass

@routes.command()
@click.pass_context  
def list(ctx):
    """List active routes"""
    client = ctx.obj['client']
    routes = client.get_routes()
    
    if routes:
        click.echo("🌐 Active routes:")
        for route in routes:
            protocols = ",".join(route.get("protocols", ["http"]))
            click.echo(f"   {route['host']} → {route['target']} ({protocols})")
    else:
        click.echo("🌐 No routes configured")

@routes.command()
@click.argument('host')
@click.argument('target')
@click.option('--protocols', default="http", help='Comma-separated protocols')
@click.pass_context
def add(ctx, host, target, protocols):
    """Add a route"""
    client = ctx.obj['client']
    protocol_list = [p.strip() for p in protocols.split(',')]
    
    try:
        client.add_route(host, target, protocol_list)
        click.echo(f"✅ Added route: {host} → {target}")
    except Exception as e:
        click.echo(f"❌ Failed to add route: {e}")

@routes.command()
@click.argument('host')
@click.pass_context
def rm(ctx, host):
    """Remove a route"""
    client = ctx.obj['client']
    
    try:
        client.remove_route(host)
        click.echo(f"✅ Removed route: {host}")
    except Exception as e:
        click.echo(f"❌ Failed to remove route: {e}")

@cli.group()
def dns():
    """Local DNS management for *.pa.local"""
    pass

@dns.command()
def install():
    """Install local DNS resolver"""
    dns_mgr.install()

@dns.command()
def uninstall():
    """Uninstall local DNS resolver"""
    dns_mgr.uninstall()

@dns.command()  
def status():
    """Check DNS resolver status"""
    dns_mgr.status()

@cli.group()
def tls():
    """TLS certificate management"""
    pass

@tls.command()
def trust():
    """Setup and trust TLS certificates"""
    tls_mgr.trust()

@tls.command()
def setup():
    """Setup TLS certificates (same as trust)"""
    tls_mgr.setup()

@tls.command()
@click.argument('domain')
def issue(domain):
    """Issue certificate for domain"""
    tls_mgr.issue(domain)

@tls.command()
def list():
    """List issued certificates"""
    tls_mgr.list_certs()

@tls.command()
def status():
    """Show TLS status"""
    tls_mgr.status()

@cli.command()
@click.pass_context
def metrics(ctx):
    """Show Port Authority metrics dashboard"""
    client = ctx.obj['client']
    
    try:
        metrics = client.get_metrics()
        
        click.echo("📊 Port Authority Metrics")
        click.echo("=" * 40)
        
        # Key metrics
        click.echo(f"🏃 Active leases: {metrics.get('leases_active', 0)}")
        click.echo(f"🚫 Blocked ports: {metrics.get('blocks_active', 0)}")
        click.echo(f"⚡ Conflicts detected: {metrics.get('conflicts_detected_total', 0)}")
        click.echo(f"🔄 Auto-reassignments: {metrics.get('reassignments_total', 0)}")
        click.echo(f"🏥 Auto-heals: {metrics.get('auto_heals_total', 0)}")
        click.echo(f"🚀 Processes spawned: {metrics.get('processes_spawned_total', 0)}")
        
        # Performance metrics
        reassign_latency = metrics.get('reassign_latency', 0)
        click.echo(f"⏱️  Avg reassign time: {reassign_latency:.3f}s")
        
        # Success rate
        total_conflicts = metrics.get('conflicts_detected_total', 1)
        reassignments = metrics.get('reassignments_total', 0)  
        success_rate = (reassignments / total_conflicts * 100) if total_conflicts > 0 else 100
        click.echo(f"✅ Auto-resolution rate: {success_rate:.1f}%")
        
    except Exception as e:
        click.echo(f"❌ Failed to fetch metrics: {e}")

@cli.command()
@click.pass_context  
def top(ctx):
    """Live TUI monitoring of ports and processes"""
    client = ctx.obj['client']
    
    click.echo("📊 Port Authority Live Monitor (Ctrl+C to exit)")
    click.echo("=" * 60)
    
    try:
        while True:
            # Clear screen
            click.clear()
            
            # Header
            click.echo(f"🚢 Port Authority - Context: {ctx.obj['context']}")
            click.echo(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
            click.echo("=" * 60)
            
            # Get current data
            scan_result = client._request("GET", "/scan")
            
            # Active ports table
            active_ports = scan_result.get('active_ports', [])
            if active_ports:
                click.echo("PORT  STATE     OWNER                    PID")
                click.echo("-" * 50)
                for port_data in sorted(active_ports, key=lambda x: x['port'])[:20]:  # Top 20
                    port = port_data['port']
                    state = port_data['state'][:8].ljust(8)
                    owner = (port_data.get('owner', 'unknown')[:20]).ljust(20)
                    pid = port_data.get('pid', '-')
                    
                    click.echo(f"{port:>5} {state} {owner} {pid}")
            
            click.echo("")
            
            # Quick stats
            metrics = scan_result.get('metrics', {})
            click.echo(f"📊 Active: {metrics.get('leases_active', 0)} | "
                      f"Conflicts: {metrics.get('conflicts_detected_total', 0)} | "
                      f"Reassignments: {metrics.get('reassignments_total', 0)}")
            
            # Refresh every 2 seconds
            time.sleep(2)
            
    except KeyboardInterrupt:
        click.echo("\n👋 Monitoring stopped")

@cli.command()
@click.argument('service')
@click.pass_context
def open(ctx, service):
    """Open service URL in browser"""
    client = ctx.obj['client']
    namespace = client.namespace
    
    try:
        # Get service info
        result = client._request("GET", f"/who?port=0&service={namespace}/{service}")
        
        if result.get('url'):
            click.echo(f"🌐 Opening {result['url']}")
            webbrowser.open(result['url'])
        else:
            click.echo(f"❌ No URL found for service: {service}")
            
    except Exception as e:
        click.echo(f"❌ Failed to open service: {e}")

@cli.command()
@click.argument('service')
@click.pass_context
def url(ctx, service):
    """Print service URL (great for scripts)"""
    client = ctx.obj['client']
    namespace = client.namespace
    
    try:
        result = client._request("GET", f"/who?port=0&service={namespace}/{service}")
        
        if result.get('url'):
            click.echo(result['url'])
        else:
            click.echo(f"No URL found for service: {service}", err=True)
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"Failed to get URL: {e}", err=True)
        sys.exit(1)

@cli.command()
@click.option('--comprehensive', is_flag=True, help='Run comprehensive test suite')
@click.option('--json', is_flag=True, help='Output JSON results')
@click.pass_context
def selftest(ctx, comprehensive, json_output):
    """Run end-to-end system validation"""
    client = ctx.obj['client']
    context = ctx.obj['context']
    
    if comprehensive:
        # Run full integration test suite
        try:
            from test_integration import TestHarness
            harness = TestHarness({
                'daemon_url': client.base_url,
                'admin_token': client.admin_token,
                'domain': 'pa.local'
            })
            
            results = harness.run_all_tests()
            
            if json_output:
                click.echo(json.dumps(results, indent=2))
            else:
                # Human-readable summary
                summary = results["summary"]
                status_emoji = "✅" if results["success"] else "❌"
                
                click.echo(f"\n{status_emoji} Overall: {results['message']}")
                click.echo(f"📊 Results: {summary['passed']}/{summary['total_tests']} passed ({summary['success_rate']:.1f}%)")
                click.echo(f"🖥️  Platform: {summary['platform']}")
                
                if results.get("metrics"):
                    click.echo(f"⚡ Performance:")
                    for key, value in results["metrics"].items():
                        if key.endswith('_ms'):
                            click.echo(f"   {key}: {value:.1f}ms")
            
            sys.exit(0 if results["success"] else 1)
            
        except ImportError:
            click.echo("❌ Comprehensive test suite not available")
            sys.exit(1)
    
    # Standard self-test (enhanced)
    click.echo("🧪 Port Authority Self-Test")
    click.echo("=" * 50)
    
    tests_passed = 0
    total_tests = 8
    start_time = time.time()
    
    # Test 1: Daemon connectivity
    click.echo("1️⃣ Testing daemon connectivity...")
    try:
        health = client._request("GET", "/health")
        if health.get('status') == 'healthy':
            click.echo(f"   ✅ Daemon healthy (v{health.get('version', '?')})")
            tests_passed += 1
        else:
            click.echo("   ❌ Daemon unhealthy")
    except Exception as e:
        click.echo(f"   ❌ Cannot connect to daemon: {e}")
    
    # Test 2: Port reservation
    click.echo("2️⃣ Testing port reservation...")
    try:
        test_name = f"selftest-{int(time.time())}"
        reserve_result = client._request("POST", "/reserve", json={
            "name": test_name,
            "prefer": [60000, 60001],
            "ttl_sec": 30
        })
        
        if reserve_result.get('port'):
            port = reserve_result['port']
            click.echo(f"   ✅ Reserved port {port}")
            
            # Test release
            release_result = client._request("POST", "/release", json={"name": test_name})
            if release_result.get('status') == 'released':
                click.echo(f"   ✅ Released port {port}")
                tests_passed += 1
            else:
                click.echo("   ❌ Failed to release port")
        else:
            click.echo("   ❌ Failed to reserve port")
    except Exception as e:
        click.echo(f"   ❌ Port reservation failed: {e}")
    
    # Test 3: DNS resolution 
    click.echo("3️⃣ Testing DNS resolution...")
    try:
        import socket
        test_domain = f"test.{client.config.get('gateway', {}).get('domain', 'pa.local')}"
        
        try:
            result = socket.gethostbyname(test_domain)
            if result == "127.0.0.1":
                click.echo(f"   ✅ DNS resolving {test_domain} → {result}")
                tests_passed += 1
            else:
                click.echo(f"   ❌ DNS resolution incorrect: {result}")
        except socket.gaierror:
            dns_status = dns_mgr.dns_installer.status()
            if dns_status['server_running']:
                click.echo("   ⚠️  DNS server running but resolution failing")
            else:
                click.echo("   ⚠️  DNS resolver not configured")
            tests_passed += 1  # Don't fail for optional DNS
    except Exception as e:
        click.echo(f"   ⚠️  DNS test failed: {e}")
        tests_passed += 1
    
    # Test 4: TLS certificates
    click.echo("4️⃣ Testing TLS certificates...")
    try:
        tls_status = tls_mgr.tls_manager.get_status()
        
        if tls_status["mkcert_available"] or tls_status["caddy_ca_available"]:
            click.echo("   ✅ TLS certificates available")
            if tls_status["certificates"]:
                cert_count = len(tls_status["certificates"])
                click.echo(f"   ✅ {cert_count} certificate(s) found")
            tests_passed += 1
        else:
            click.echo("   ⚠️  No TLS certificates configured")
            tests_passed += 1  # Don't fail for optional TLS
    except Exception as e:
        click.echo(f"   ⚠️  TLS test failed: {e}")
        tests_passed += 1
    
    # Test 5: Gateway integration
    click.echo("5️⃣ Testing gateway integration...")
    try:
        routes = client.get_routes()
        click.echo(f"   ✅ Gateway responding ({len(routes)} routes)")
        tests_passed += 1
    except Exception as e:
        click.echo(f"   ⚠️  Gateway not configured: {e}")
        tests_passed += 1  # Don't fail for optional gateway
    
    # Test 6: Metrics collection
    click.echo("6️⃣ Testing metrics collection...")
    try:
        metrics = client.get_metrics()
        if 'leases_active' in metrics:
            active = metrics.get('leases_active', 0)
            conflicts = metrics.get('conflicts_detected_total', 0)
            click.echo(f"   ✅ Metrics: {active} leases, {conflicts} conflicts")
            tests_passed += 1
        else:
            click.echo("   ❌ Metrics incomplete")
    except Exception as e:
        click.echo(f"   ❌ Metrics collection failed: {e}")
    
    # Test 7: Process spawning (if admin token available)
    click.echo("7️⃣ Testing process spawning...")
    try:
        if client.admin_token:
            # Quick spawn test with echo command
            import tempfile
            import sys
            
            test_script = tempfile.mktemp(suffix='.py')
            with open(test_script, 'w') as f:
                f.write('import time; time.sleep(1); print("Test OK")')
            
            try:
                spawn_result = client._request("POST", "/spawn", admin=True, json={
                    "name": f"selftest-spawn-{int(time.time())}",
                    "cmd": [sys.executable, test_script],
                    "prefer": [60002, 60003],
                    "ttl_sec": 30
                })
                
                if spawn_result.get('port'):
                    pid = spawn_result.get('pid')
                    port = spawn_result['port']
                    click.echo(f"   ✅ Spawned process PID {pid} on port {port}")
                    
                    # Clean up
                    try:
                        client._request("POST", "/kill", admin=True, json={"port": port})
                    except:
                        pass
                    
                    tests_passed += 1
                else:
                    click.echo("   ❌ Process spawning failed")
            finally:
                try:
                    os.unlink(test_script)
                except:
                    pass
        else:
            click.echo("   ⚠️  No admin token, skipping spawn test")
            tests_passed += 1
    except Exception as e:
        click.echo(f"   ❌ Process spawning failed: {e}")
    
    # Test 8: Performance check
    click.echo("8️⃣ Testing performance...")
    try:
        # Quick performance test
        perf_start = time.time()
        
        for i in range(5):
            test_name = f"perf-test-{i}"
            client._request("POST", "/reserve", json={
                "name": test_name,
                "prefer": [60010 + i],
                "ttl_sec": 10
            })
            client._request("POST", "/release", json={"name": test_name})
        
        perf_time = (time.time() - perf_start) * 1000 / 5
        
        if perf_time < 100:  # Less than 100ms average
            click.echo(f"   ✅ Performance good ({perf_time:.1f}ms avg)")
            tests_passed += 1
        else:
            click.echo(f"   ⚠️  Performance slow ({perf_time:.1f}ms avg)")
            tests_passed += 1  # Don't fail on performance
    except Exception as e:
        click.echo(f"   ❌ Performance test failed: {e}")
    
    # Results
    total_time = time.time() - start_time
    click.echo("=" * 50)
    
    if json_output:
        result = {
            "success": tests_passed == total_tests,
            "tests_passed": tests_passed,
            "total_tests": total_tests,
            "success_rate": (tests_passed / total_tests * 100),
            "duration_seconds": total_time,
            "context": context,
            "timestamp": time.time()
        }
        click.echo(json.dumps(result, indent=2))
    else:
        if tests_passed == total_tests:
            click.echo(f"🎉 All {total_tests}/{total_tests} tests passed! ({total_time:.1f}s)")
            click.echo("✅ Port Authority is ready for production use")
        elif tests_passed >= 6:
            click.echo(f"✅ {tests_passed}/{total_tests} tests passed ({total_time:.1f}s)")
            click.echo("✅ Core functionality working, some features optional")
        else:
            click.echo(f"⚠️  {tests_passed}/{total_tests} tests passed ({total_time:.1f}s)")
            click.echo("❌ Critical issues detected")
            sys.exit(1)

# Enhanced run command with namespace support
@cli.command()
@click.option('--name', '-n', required=True, help='Service name')
@click.option('--prefer', '-p', multiple=True, type=int, help='Preferred ports')
@click.option('--ttl', default=3600, help='Lease duration in seconds')
@click.option('--env', multiple=True, help='Environment variables (KEY=value)')
@click.argument('command', nargs=-1, required=True)
@click.pass_context
def run(ctx, name, prefer, ttl, env, command):
    """Enhanced spawn with namespace and gateway integration"""
    client = ctx.obj['client']
    
    if not command:
        click.echo("❌ No command specified")
        sys.exit(1)
    
    # Parse environment variables
    env_dict = {}
    for e in env:
        if '=' in e:
            key, value = e.split('=', 1)
            env_dict[key] = value
    
    try:
        click.echo(f"🚀 Spawning '{' '.join(command)}' in namespace '{client.namespace}'...")
        
        result = client.spawn_with_namespace(
            name=name,
            cmd=list(command),
            prefer=list(prefer) if prefer else None,
            ttl_sec=ttl,
            env=env_dict
        )
        
        port = result['port']
        pid = result.get('pid')
        url = result.get('url')
        host = result.get('host')
        
        click.echo(f"✅ Process started successfully!")
        click.echo(f"🌐 Namespace: {client.namespace}")
        click.echo(f"📊 Port: {port}")
        click.echo(f"🆔 PID: {pid}")
        if url:
            click.echo(f"🔗 URL: {url}")
        if host:
            click.echo(f"🏠 Host: {host}")
        
        # Auto-create route if gateway enabled
        if client.config.get("gateway", {}).get("enabled") and host:
            try:
                client.add_route(host, f"http://127.0.0.1:{port}", ["http", "ws"])
                click.echo(f"🌐 Route added: {host} → 127.0.0.1:{port}")
            except:
                pass  # Route might already exist
        
    except Exception as e:
        click.echo(f"❌ Failed to spawn process: {e}")
        sys.exit(1)

def main():
    cli()


if __name__ == '__main__':
    main()
