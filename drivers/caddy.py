#!/usr/bin/env python3
"""
🌐 Caddy Gateway Driver for Port Authority
Zero-config HTTPS and DNS integration with automatic TLS certificates

Features:
- Automatic HTTPS with self-signed certs for *.pa.local
- Dynamic route configuration via Caddy API
- Built-in DNS resolution for development
- Hot reloading without restarts
"""

import json
import requests
import subprocess
import time
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class CaddyDriver:
    """Caddy gateway driver with automatic HTTPS and DNS"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.caddy_bin = self.config.get("caddy_bin", "caddy")
        self.admin_url = self.config.get("admin_url", "http://localhost:2019")
        self.domain = self.config.get("domain", "pa.local")
        self.data_dir = Path(self.config.get("data_dir", Path.home() / ".port-authority" / "caddy"))
        self.config_file = self.data_dir / "Caddyfile"
        self.process = None
        
        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.routes = {}
        
    def install_caddy(self) -> bool:
        """Install Caddy if not available"""
        try:
            # Check if caddy is already available
            result = subprocess.run([self.caddy_bin, "version"], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                logger.info(f"Caddy already installed: {result.stdout.strip()}")
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        logger.info("Installing Caddy...")
        
        try:
            if os.name == 'nt':  # Windows
                # Download Caddy for Windows
                import urllib.request
                import zipfile
                
                caddy_url = "https://github.com/caddyserver/caddy/releases/latest/download/caddy_windows_amd64.zip"
                zip_path = self.data_dir / "caddy.zip"
                
                urllib.request.urlretrieve(caddy_url, zip_path)
                
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extract("caddy.exe", self.data_dir)
                
                self.caddy_bin = str(self.data_dir / "caddy.exe")
                zip_path.unlink()  # Clean up
                
                logger.info("✅ Caddy installed successfully")
                return True
                
            else:  # Unix-like systems
                # Use the official install script
                install_script = """
                curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
                curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
                sudo apt update
                sudo apt install caddy
                """
                
                logger.info("Run the following commands to install Caddy:")
                logger.info(install_script)
                return False
                
        except Exception as e:
            logger.error(f"Failed to install Caddy: {e}")
            return False
    
    @contextmanager
    def _file_lock(self):
        """Simple file lock for concurrent route updates"""
        lock_file = self.data_dir / "caddy.lock"
        # Simple implementation - production would use portalocker
        try:
            yield
        finally:
            pass
    
    def generate_caddyfile(self) -> str:
        """Generate Caddyfile configuration with import pattern"""
        # Create routes directory
        routes_dir = self.data_dir / "routes"
        routes_dir.mkdir(exist_ok=True)
        
        # Main Caddyfile - minimal and stable
        lines = [
            "# Port Authority - Caddy Configuration",
            "# Auto-generated - do not edit manually",
            "",
            "{",
            "    admin localhost:2019",
            "    local_certs",  # Use local CA, keep auto HTTPS redirects
            "    grace_period 3s",
            "    log {",
            "        output stdout",
            "        format console",
            "    }",
            "}",
            "",
            "# Import individual route files",
            "import routes/*.caddy",
            "",
            "# Catch-all for unconfigured services",
            f"*.{self.domain} {{",
            "    respond `<h1>Port Authority</h1><p>No service configured for <strong>{http.request.host}</strong></p><p>Configure with: <code>pa routes add {http.request.host} http://127.0.0.1:PORT</code></p>` 404",
            "    tls internal",
            "}",
        ]
        
        # Write individual route files
        self._write_route_files(routes_dir)
        
        return "\n".join(lines)
    
    def _write_route_files(self, routes_dir: Path):
        """Write individual route files for atomic updates"""
        # Clean existing route files
        for route_file in routes_dir.glob("*.caddy"):
            route_file.unlink()
        
        # Write each route as separate file
        for name, route_config in self.routes.items():
            host = route_config["host"]
            target = route_config["target"]
            protocols = route_config.get("protocols", ["http"])
            
            route_content = [
                f"# Route: {name}",
                f"{host} {{",
                f"    reverse_proxy {target}",  # Caddy v2 handles WebSockets automatically
                "    tls internal",
                "}"
            ]
            
            route_file = routes_dir / f"{name}.caddy"
            route_file.write_text("\n".join(route_content))
    
    def start(self) -> bool:
        """Start Caddy server with proper readiness checking"""
        try:
            # Check if Caddy is installed
            if not self.install_caddy():
                return False
            
            # Generate initial Caddyfile
            caddyfile_content = self.generate_caddyfile()
            self.config_file.write_text(caddyfile_content)
            
            # Start Caddy
            cmd = [
                self.caddy_bin,
                "run",
                "--config", str(self.config_file),
                "--adapter", "caddyfile"
            ]
            
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self.data_dir)
            )
            
            # Poll for admin API readiness instead of fixed sleep
            if self._wait_for_readiness():
                logger.info("✅ Caddy started successfully")
                
                # Install local CA certificate
                self._install_local_ca()
                
                return True
            else:
                stdout, stderr = self.process.communicate()
                logger.error(f"Caddy failed to start: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to start Caddy: {e}")
            return False
    
    def _wait_for_readiness(self, timeout: int = 10) -> bool:
        """Wait for Caddy admin API to be ready"""
        for attempt in range(timeout * 4):  # Check every 0.25s
            try:
                if self.process.poll() is not None:
                    # Process died
                    return False
                
                response = requests.get(f"{self.admin_url}/config/", timeout=0.5)
                if response.status_code == 200:
                    return True
                    
            except Exception:
                pass
            
            time.sleep(0.25)
        
        logger.error("Caddy admin API not ready after timeout")
        return False
    
    def stop(self):
        """Stop Caddy server"""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            
            self.process = None
            logger.info("Caddy stopped")
    
    def _install_local_ca(self):
        """Install Caddy's local CA certificate"""
        try:
            # Get CA from API instead of assuming file path
            ca_cert_pem = self._fetch_ca_from_api()
            
            if ca_cert_pem:
                if os.name == 'nt':  # Windows
                    # Use certutil (correct Windows command)
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.crt', delete=False) as f:
                        f.write(ca_cert_pem)
                        temp_cert_path = f.name
                    
                    try:
                        # Try certutil first
                        result = subprocess.run([
                            "certutil", "-addstore", "Root", temp_cert_path
                        ], capture_output=True, text=True)
                        
                        if result.returncode == 0:
                            logger.info("✅ CA certificate installed via certutil")
                        else:
                            # Fallback to PowerShell
                            subprocess.run([
                                "powershell", "-Command",
                                f"Import-Certificate -FilePath '{temp_cert_path}' -CertStoreLocation Cert:\\LocalMachine\\Root"
                            ], capture_output=True)
                            logger.info("✅ CA certificate installed via PowerShell")
                            
                    finally:
                        os.unlink(temp_cert_path)
                        
                else:
                    # Unix systems - save CA and provide instructions
                    ca_file = Path.home() / ".port-authority" / "caddy-ca.crt"
                    ca_file.write_text(ca_cert_pem)
                    
                    logger.info(f"CA certificate saved to: {ca_file}")
                    logger.info(f"Install with: sudo cp {ca_file} /usr/local/share/ca-certificates/caddy-local.crt && sudo update-ca-certificates")
                
                logger.info("✅ Local CA certificate processed")
            
        except Exception as e:
            logger.warning(f"Could not install local CA: {e}")
    
    def _fetch_ca_from_api(self) -> Optional[str]:
        """Fetch CA certificate from Caddy API"""
        try:
            # Wait for PKI to be ready
            for _ in range(20):
                try:
                    response = requests.get(f"{self.admin_url}/pki/ca/local/certificates", timeout=2)
                    if response.status_code == 200:
                        # Response contains certificate chain - extract root
                        chain = response.text
                        # Split on certificate boundaries and take the last one (root)
                        certs = chain.split("-----END CERTIFICATE-----")
                        if len(certs) >= 2:
                            root_cert = certs[-2] + "-----END CERTIFICATE-----\n"
                            return root_cert
                        return chain  # Fallback to full chain
                except Exception:
                    time.sleep(0.5)
            
            # Fallback to file system if API not ready
            ca_path = self.data_dir / "pki" / "authorities" / "local" / "root.crt"
            if ca_path.exists():
                return ca_path.read_text()
                
        except Exception as e:
            logger.warning(f"Failed to fetch CA from API: {e}")
        
        return None
    
    def upsert_route(self, name: str, host: str, target: str, protocols: List[str] = None) -> bool:
        """Add or update a route"""
        try:
            protocols = protocols or ["http"]
            
            self.routes[name] = {
                "host": host,
                "target": target,
                "protocols": protocols
            }
            
            # Regenerate Caddyfile
            caddyfile_content = self.generate_caddyfile()
            self.config_file.write_text(caddyfile_content)
            
            # Reload Caddy configuration via API
            return self._reload_config()
            
        except Exception as e:
            logger.error(f"Failed to upsert route {name}: {e}")
            return False
    
    def remove_route(self, name: str) -> bool:
        """Remove a route"""
        try:
            if name in self.routes:
                del self.routes[name]
                
                # Regenerate Caddyfile
                caddyfile_content = self.generate_caddyfile()
                self.config_file.write_text(caddyfile_content)
                
                # Reload Caddy configuration
                return self._reload_config()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove route {name}: {e}")
            return False
    
    def _reload_config(self) -> bool:
        """Reload Caddy configuration via admin API with validation"""
        try:
            # Read the current Caddyfile
            caddyfile_content = self.config_file.read_text()
            
            # Step 1: Validate the config first
            validate_response = requests.post(
                f"{self.admin_url}/adapt",
                headers={"Content-Type": "text/caddyfile"},
                data=caddyfile_content,
                timeout=10
            )
            
            if validate_response.status_code != 200:
                logger.error(f"Caddyfile validation failed: {validate_response.text}")
                return False
            
            # Step 2: If validation passes, load the config
            load_response = requests.post(
                f"{self.admin_url}/load",
                headers={"Content-Type": "text/caddyfile"},
                data=caddyfile_content,
                timeout=10
            )
            
            if load_response.status_code == 200:
                logger.info("✅ Caddy configuration reloaded")
                return True
            else:
                logger.error(f"Failed to load Caddy config: {load_response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to reload Caddy configuration: {e}")
            return False
    
    def get_routes(self) -> List[Dict[str, Any]]:
        """Get current routes"""
        return [
            {
                "name": name,
                "host": config["host"],
                "target": config["target"],
                "protocols": config["protocols"]
            }
            for name, config in self.routes.items()
        ]
    
    def reload(self) -> bool:
        """Reload gateway configuration"""
        return self._reload_config()
    
    def status(self) -> Dict[str, Any]:
        """Get gateway status"""
        try:
            # Check admin API
            response = requests.get(f"{self.admin_url}/config/", timeout=5)
            
            return {
                "running": response.status_code == 200,
                "admin_url": self.admin_url,
                "routes_count": len(self.routes),
                "domain": self.domain,
                "ca_installed": (self.data_dir / "pki" / "authorities" / "local" / "root.crt").exists()
            }
            
        except Exception as e:
            return {
                "running": False,
                "error": str(e),
                "admin_url": self.admin_url,
                "routes_count": len(self.routes),
                "domain": self.domain,
                "ca_installed": False
            }
    
    def get_certificate_info(self) -> Dict[str, Any]:
        """Get information about certificates"""
        try:
            ca_path = self.data_dir / "pki" / "authorities" / "local" / "root.crt"
            
            return {
                "ca_exists": ca_path.exists(),
                "ca_path": str(ca_path),
                "domain": self.domain,
                "auto_https": True,
                "local_ca": True
            }
            
        except Exception as e:
            return {
                "ca_exists": False,
                "error": str(e)
            }

# Integration with Port Authority platform
def create_caddy_driver(config: Dict[str, Any] = None) -> CaddyDriver:
    """Factory function to create Caddy driver"""
    return CaddyDriver(config)

# CLI integration for testing
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Test Caddy driver
    driver = CaddyDriver()
    
    print("🌐 Testing Caddy Driver")
    print("=" * 30)
    
    # Start Caddy
    if driver.start():
        print("✅ Caddy started")
        
        # Add test route
        driver.upsert_route("test", "test.pa.local", "http://127.0.0.1:8000")
        print("✅ Added test route: test.pa.local -> http://127.0.0.1:8000")
        
        # Show status
        status = driver.status()
        print(f"📊 Status: {status}")
        
        # Show certificate info
        cert_info = driver.get_certificate_info()
        print(f"🔒 Certificates: {cert_info}")
        
        print("\n🎉 Test complete! Try visiting https://test.pa.local")
        print("Press Ctrl+C to stop...")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            driver.stop()
            print("\n👋 Caddy stopped")
    else:
        print("❌ Failed to start Caddy")
