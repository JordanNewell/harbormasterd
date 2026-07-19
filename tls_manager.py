#!/usr/bin/env python3
"""
🔐 Port Authority TLS Manager
Zero-config HTTPS with mkcert integration and fallback to Caddy internal CA

Features:
- mkcert wildcard certificate generation (*.pa.local)
- Automatic trust store installation (Windows/macOS/Linux)
- Caddy internal CA fallback and integration
- Certificate rotation and renewal
- Cross-platform certificate installation
- Firefox support via NSS database
"""

import os
import sys
import subprocess
import platform
import shutil
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import logging
import ssl
import socket
import tempfile
from datetime import datetime, timedelta
import cryptography
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import requests

logger = logging.getLogger(__name__)

class MkcertManager:
    """Manage mkcert installation and certificate generation"""
    
    def __init__(self):
        self.platform = platform.system().lower()
        self.mkcert_path = self._find_mkcert()
        self.ca_root_path = self._get_ca_root_path()
    
    def _find_mkcert(self) -> Optional[str]:
        """Find mkcert binary or return None"""
        # Check if mkcert is in PATH
        mkcert_cmd = "mkcert.exe" if self.platform == "windows" else "mkcert"
        
        if shutil.which(mkcert_cmd):
            return mkcert_cmd
        
        # Check common installation paths
        common_paths = []
        
        if self.platform == "windows":
            common_paths = [
                Path.home() / "bin" / "mkcert.exe",
                Path("C:/Program Files/mkcert/mkcert.exe"),
                Path("C:/tools/mkcert.exe")
            ]
        elif self.platform == "darwin":  # macOS
            common_paths = [
                Path("/opt/homebrew/bin/mkcert"),
                Path("/usr/local/bin/mkcert"),
                Path.home() / "bin" / "mkcert"
            ]
        else:  # Linux
            common_paths = [
                Path("/usr/local/bin/mkcert"),
                Path("/usr/bin/mkcert"),
                Path.home() / "bin" / "mkcert",
                Path.home() / ".local/bin/mkcert"
            ]
        
        for path in common_paths:
            if path.exists():
                return str(path)
        
        return None
    
    def _get_ca_root_path(self) -> Optional[Path]:
        """Get mkcert CA root path"""
        if not self.mkcert_path:
            return None
        
        try:
            result = subprocess.run(
                [self.mkcert_path, "-CAROOT"],
                capture_output=True, text=True, timeout=5
            )
            
            if result.returncode == 0:
                return Path(result.stdout.strip())
        except:
            pass
        
        return None
    
    def is_available(self) -> bool:
        """Check if mkcert is available"""
        return self.mkcert_path is not None
    
    def install(self) -> bool:
        """Install mkcert if not available"""
        if self.is_available():
            print(f"✅ mkcert already available at {self.mkcert_path}")
            return True
        
        print(f"📦 Installing mkcert for {self.platform}...")
        
        try:
            if self.platform == "windows":
                return self._install_windows()
            elif self.platform == "darwin":
                return self._install_macos()
            elif self.platform == "linux":
                return self._install_linux()
            else:
                print(f"⚠️  Unsupported platform: {self.platform}")
                return False
        except Exception as e:
            print(f"❌ mkcert installation failed: {e}")
            return False
    
    def _install_windows(self) -> bool:
        """Install mkcert on Windows"""
        print("🪟 Installing mkcert for Windows...")
        
        try:
            # Method 1: Check if Chocolatey is available
            if shutil.which("choco"):
                result = subprocess.run(
                    ["choco", "install", "mkcert", "-y"],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    print("✅ mkcert installed via Chocolatey")
                    self.mkcert_path = self._find_mkcert()
                    return True
            
            # Method 2: Check if Scoop is available
            if shutil.which("scoop"):
                subprocess.run(["scoop", "install", "mkcert"], capture_output=True)
                self.mkcert_path = self._find_mkcert()
                if self.mkcert_path:
                    print("✅ mkcert installed via Scoop")
                    return True
            
            # Method 3: Direct download
            return self._download_mkcert_direct()
                
        except Exception as e:
            print(f"❌ Windows mkcert installation failed: {e}")
            return False
    
    def _install_macos(self) -> bool:
        """Install mkcert on macOS"""
        print("🍎 Installing mkcert for macOS...")
        
        try:
            # Method 1: Homebrew
            if shutil.which("brew"):
                result = subprocess.run(
                    ["brew", "install", "mkcert"],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    print("✅ mkcert installed via Homebrew")
                    self.mkcert_path = self._find_mkcert()
                    return True
            
            # Method 2: Direct download
            return self._download_mkcert_direct()
            
        except Exception as e:
            print(f"❌ macOS mkcert installation failed: {e}")
            return False
    
    def _install_linux(self) -> bool:
        """Install mkcert on Linux"""
        print("🐧 Installing mkcert for Linux...")
        
        try:
            # Method 1: Check if available in package manager
            distro_info = self._detect_linux_distro()
            
            if distro_info["family"] in ["debian", "ubuntu"]:
                # Try apt
                result = subprocess.run(
                    ["sudo", "apt", "update"], capture_output=True
                )
                if result.returncode == 0:
                    result = subprocess.run(
                        ["sudo", "apt", "install", "-y", "libnss3-tools"],
                        capture_output=True
                    )
                    # mkcert usually not in apt, so download directly
            
            elif distro_info["family"] in ["fedora", "centos", "rhel"]:
                # Install NSS tools for Firefox support
                subprocess.run(
                    ["sudo", "dnf", "install", "-y", "nss-tools"],
                    capture_output=True
                )
            
            # Direct download for all Linux
            return self._download_mkcert_direct()
            
        except Exception as e:
            print(f"❌ Linux mkcert installation failed: {e}")
            return False
    
    def _detect_linux_distro(self) -> Dict[str, str]:
        """Detect Linux distribution"""
        try:
            with open("/etc/os-release", "r") as f:
                lines = f.readlines()
            
            info = {}
            for line in lines:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    info[key.lower()] = value.strip('"')
            
            # Determine family
            distro_id = info.get("id", "").lower()
            if distro_id in ["ubuntu", "debian", "mint"]:
                family = "debian"
            elif distro_id in ["fedora", "centos", "rhel", "rocky", "alma"]:
                family = "fedora"
            elif distro_id in ["arch", "manjaro"]:
                family = "arch"
            else:
                family = "unknown"
            
            return {"id": distro_id, "family": family, **info}
            
        except:
            return {"id": "unknown", "family": "unknown"}
    
    def _download_mkcert_direct(self) -> bool:
        """Download mkcert binary directly from GitHub"""
        print("⬇️ Downloading mkcert from GitHub...")
        
        try:
            # Determine architecture and platform
            machine = platform.machine().lower()
            if machine in ["x86_64", "amd64"]:
                arch = "amd64"
            elif machine in ["arm64", "aarch64"]:
                arch = "arm64"
            elif machine in ["i386", "i686"]:
                arch = "386"
            else:
                print(f"⚠️  Unsupported architecture: {machine}")
                return False
            
            # Build download URL
            if self.platform == "windows":
                filename = f"mkcert-v1.4.4-windows-{arch}.exe"
            elif self.platform == "darwin":
                filename = f"mkcert-v1.4.4-darwin-{arch}"
            else:  # Linux
                filename = f"mkcert-v1.4.4-linux-{arch}"
            
            url = f"https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/{filename}"
            
            # Download
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            # Save to local bin directory
            bin_dir = Path.home() / "bin"
            bin_dir.mkdir(exist_ok=True)
            
            if self.platform == "windows":
                mkcert_file = bin_dir / "mkcert.exe"
            else:
                mkcert_file = bin_dir / "mkcert"
            
            mkcert_file.write_bytes(response.content)
            mkcert_file.chmod(0o755)  # Make executable
            
            self.mkcert_path = str(mkcert_file)
            print(f"✅ mkcert downloaded to {mkcert_file}")
            
            # Add to PATH if not already there
            if str(bin_dir) not in os.environ.get("PATH", ""):
                print(f"💡 Add {bin_dir} to your PATH for global access")
            
            return True
            
        except Exception as e:
            print(f"❌ Direct download failed: {e}")
            return False
    
    def install_ca(self) -> bool:
        """Install mkcert CA into system trust store"""
        if not self.mkcert_path:
            print("❌ mkcert not available")
            return False
        
        try:
            print("🔐 Installing mkcert CA into system trust store...")
            
            result = subprocess.run(
                [self.mkcert_path, "-install"],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode == 0:
                print("✅ mkcert CA installed successfully")
                return True
            else:
                print(f"❌ mkcert CA installation failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ CA installation error: {e}")
            return False
    
    def generate_certificate(self, domain: str, additional_domains: List[str] = None) -> Tuple[Optional[Path], Optional[Path]]:
        """Generate certificate for domain(s)"""
        if not self.mkcert_path:
            print("❌ mkcert not available")
            return None, None
        
        additional_domains = additional_domains or []
        all_domains = [domain] + additional_domains
        
        try:
            print(f"📜 Generating certificate for {', '.join(all_domains)}...")
            
            # Create certificates directory
            cert_dir = Path.home() / ".curtis" / "certificates"
            cert_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate certificate
            cert_file = cert_dir / f"{domain}.pem"
            key_file = cert_dir / f"{domain}-key.pem"
            
            cmd = [
                self.mkcert_path,
                "-cert-file", str(cert_file),
                "-key-file", str(key_file)
            ] + all_domains
            
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            
            if result.returncode == 0 and cert_file.exists() and key_file.exists():
                print(f"✅ Certificate generated:")
                print(f"   Cert: {cert_file}")
                print(f"   Key:  {key_file}")
                return cert_file, key_file
            else:
                print(f"❌ Certificate generation failed: {result.stderr}")
                return None, None
                
        except Exception as e:
            print(f"❌ Certificate generation error: {e}")
            return None, None
    
    def get_ca_cert(self) -> Optional[str]:
        """Get CA certificate content"""
        if not self.ca_root_path:
            return None
        
        try:
            ca_file = self.ca_root_path / "rootCA.pem"
            if ca_file.exists():
                return ca_file.read_text()
        except:
            pass
        
        return None

class CaddyCAManager:
    """Manage Caddy internal CA certificates"""
    
    def __init__(self, caddy_data_dir: Path = None, admin_url: str = "http://localhost:2019"):
        self.caddy_data_dir = caddy_data_dir or (Path.home() / ".curtis" / "caddy")
        self.admin_url = admin_url
        self.ca_dir = self.caddy_data_dir / "pki" / "authorities" / "local"
    
    def get_ca_cert(self) -> Optional[str]:
        """Get Caddy CA certificate"""
        try:
            # Method 1: Try admin API
            response = requests.get(f"{self.admin_url}/pki/ca/local/certificates", timeout=5)
            if response.status_code == 200:
                chain = response.text
                # Extract root certificate (last in chain)
                certs = chain.split("-----END CERTIFICATE-----")
                if len(certs) >= 2:
                    root_cert = certs[-2] + "-----END CERTIFICATE-----\n"
                    return root_cert
                return chain
        except:
            pass
        
        # Method 2: Try file system
        try:
            ca_file = self.ca_dir / "root.crt"
            if ca_file.exists():
                return ca_file.read_text()
        except:
            pass
        
        return None
    
    def install_ca(self) -> bool:
        """Install Caddy CA into system trust store"""
        ca_cert = self.get_ca_cert()
        if not ca_cert:
            print("❌ Could not retrieve Caddy CA certificate")
            return False
        
        try:
            return self._install_ca_to_system(ca_cert)
        except Exception as e:
            print(f"❌ Caddy CA installation failed: {e}")
            return False
    
    def _install_ca_to_system(self, ca_cert: str) -> bool:
        """Install CA certificate to system trust store"""
        platform_name = platform.system().lower()
        
        if platform_name == "windows":
            return self._install_ca_windows(ca_cert)
        elif platform_name == "darwin":
            return self._install_ca_macos(ca_cert)
        elif platform_name == "linux":
            return self._install_ca_linux(ca_cert)
        else:
            print(f"⚠️  Unsupported platform: {platform_name}")
            return False
    
    def _install_ca_windows(self, ca_cert: str) -> bool:
        """Install CA on Windows"""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.crt', delete=False) as f:
                f.write(ca_cert)
                temp_cert_path = f.name
            
            try:
                # Try certutil first
                result = subprocess.run([
                    "certutil", "-addstore", "Root", temp_cert_path
                ], capture_output=True, text=True)
                
                if result.returncode == 0:
                    print("✅ CA certificate installed via certutil")
                    return True
                else:
                    # Fallback to PowerShell
                    result = subprocess.run([
                        "powershell", "-Command",
                        f"Import-Certificate -FilePath '{temp_cert_path}' -CertStoreLocation Cert:\\LocalMachine\\Root"
                    ], capture_output=True, text=True)
                    
                    if result.returncode == 0:
                        print("✅ CA certificate installed via PowerShell")
                        return True
                    else:
                        print(f"❌ Certificate installation failed: {result.stderr}")
                        return False
            finally:
                os.unlink(temp_cert_path)
                
        except Exception as e:
            print(f"❌ Windows CA installation error: {e}")
            return False
    
    def _install_ca_macos(self, ca_cert: str) -> bool:
        """Install CA on macOS"""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.crt', delete=False) as f:
                f.write(ca_cert)
                temp_cert_path = f.name
            
            try:
                # Add to system keychain
                result = subprocess.run([
                    "sudo", "security", "add-trusted-cert", 
                    "-d", "-r", "trustRoot", 
                    "-k", "/Library/Keychains/System.keychain",
                    temp_cert_path
                ], capture_output=True, text=True)
                
                if result.returncode == 0:
                    print("✅ CA certificate installed to macOS keychain")
                    return True
                else:
                    print(f"❌ macOS CA installation failed: {result.stderr}")
                    return False
            finally:
                os.unlink(temp_cert_path)
                
        except Exception as e:
            print(f"❌ macOS CA installation error: {e}")
            return False
    
    def _install_ca_linux(self, ca_cert: str) -> bool:
        """Install CA on Linux"""
        try:
            # Save to ca-certificates directory
            ca_cert_path = Path("/usr/local/share/ca-certificates/curtis-caddy-ca.crt")
            
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
                f.write(ca_cert)
                temp_path = f.name
            
            try:
                # Copy to ca-certificates
                result = subprocess.run([
                    "sudo", "cp", temp_path, str(ca_cert_path)
                ], capture_output=True)
                
                if result.returncode == 0:
                    # Update ca-certificates
                    update_result = subprocess.run([
                        "sudo", "update-ca-certificates"
                    ], capture_output=True)
                    
                    if update_result.returncode == 0:
                        print("✅ CA certificate installed to Linux trust store")
                        return True
                    else:
                        print("❌ Failed to update ca-certificates")
                        return False
                else:
                    print("❌ Failed to copy CA certificate")
                    return False
            finally:
                os.unlink(temp_path)
                
        except Exception as e:
            print(f"❌ Linux CA installation error: {e}")
            return False

class TLSManager:
    """Unified TLS certificate manager with mkcert and Caddy CA support"""
    
    def __init__(self, domain: str = "pa.local", prefer_mkcert: bool = True):
        self.domain = domain
        self.prefer_mkcert = prefer_mkcert
        self.mkcert = MkcertManager()
        self.caddy_ca = CaddyCAManager()
        self.cert_dir = Path.home() / ".curtis" / "certificates"
        self.cert_dir.mkdir(parents=True, exist_ok=True)
    
    def setup(self) -> Dict[str, Any]:
        """Setup TLS certificates using best available method"""
        print(f"🔐 Setting up TLS for *.{self.domain}")
        
        result = {
            "success": False,
            "method": None,
            "cert_file": None,
            "key_file": None,
            "ca_installed": False,
            "details": []
        }
        
        # Method 1: Try mkcert (preferred)
        if self.prefer_mkcert:
            if self._setup_mkcert(result):
                return result
        
        # Method 2: Try Caddy internal CA
        if self._setup_caddy_ca(result):
            return result
        
        # Method 3: Generate self-signed certificate
        if self._setup_self_signed(result):
            return result
        
        result["details"].append("All TLS setup methods failed")
        return result
    
    def _setup_mkcert(self, result: Dict[str, Any]) -> bool:
        """Setup using mkcert"""
        try:
            result["details"].append("Trying mkcert...")
            
            # Install mkcert if needed
            if not self.mkcert.is_available():
                if not self.mkcert.install():
                    result["details"].append("mkcert installation failed")
                    return False
            
            # Install CA
            if not self.mkcert.install_ca():
                result["details"].append("mkcert CA installation failed")
                return False
            
            # Generate wildcard certificate
            cert_file, key_file = self.mkcert.generate_certificate(
                f"*.{self.domain}",
                [self.domain, f"*.local.{self.domain}"]
            )
            
            if cert_file and key_file:
                result.update({
                    "success": True,
                    "method": "mkcert",
                    "cert_file": str(cert_file),
                    "key_file": str(key_file),
                    "ca_installed": True
                })
                result["details"].append("mkcert setup successful")
                return True
            else:
                result["details"].append("mkcert certificate generation failed")
                return False
                
        except Exception as e:
            result["details"].append(f"mkcert setup error: {e}")
            return False
    
    def _setup_caddy_ca(self, result: Dict[str, Any]) -> bool:
        """Setup using Caddy internal CA"""
        try:
            result["details"].append("Trying Caddy internal CA...")
            
            # Install Caddy CA
            if not self.caddy_ca.install_ca():
                result["details"].append("Caddy CA installation failed")
                return False
            
            result.update({
                "success": True,
                "method": "caddy_internal",
                "cert_file": None,  # Caddy manages certificates internally
                "key_file": None,
                "ca_installed": True
            })
            result["details"].append("Caddy internal CA setup successful")
            return True
            
        except Exception as e:
            result["details"].append(f"Caddy CA setup error: {e}")
            return False
    
    def _setup_self_signed(self, result: Dict[str, Any]) -> bool:
        """Generate self-signed certificate as fallback"""
        try:
            result["details"].append("Generating self-signed certificate...")
            
            cert_file, key_file = self._generate_self_signed_cert()
            
            if cert_file and key_file:
                result.update({
                    "success": True,
                    "method": "self_signed",
                    "cert_file": str(cert_file),
                    "key_file": str(key_file),
                    "ca_installed": False
                })
                result["details"].append("Self-signed certificate generated")
                result["details"].append("⚠️  Browser will show security warnings")
                return True
            else:
                result["details"].append("Self-signed certificate generation failed")
                return False
                
        except Exception as e:
            result["details"].append(f"Self-signed certificate error: {e}")
            return False
    
    def _generate_self_signed_cert(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Generate self-signed certificate using cryptography library"""
        try:
            # Generate private key
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
            
            # Certificate details
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, f"*.{self.domain}"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Port Authority"),
                x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Development")
            ])
            
            # Build certificate
            cert = x509.CertificateBuilder().subject_name(
                subject
            ).issuer_name(
                issuer
            ).public_key(
                private_key.public_key()
            ).serial_number(
                x509.random_serial_number()
            ).not_valid_before(
                datetime.utcnow()
            ).not_valid_after(
                datetime.utcnow() + timedelta(days=365)
            ).add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName(f"*.{self.domain}"),
                    x509.DNSName(self.domain),
                    x509.DNSName(f"*.local.{self.domain}"),
                    x509.DNSName("localhost"),
                    x509.IPAddress("127.0.0.1"),
                    x509.IPAddress("::1"),
                ]),
                critical=False,
            ).sign(private_key, hashes.SHA256())
            
            # Save certificate and key
            cert_file = self.cert_dir / f"{self.domain}.crt"
            key_file = self.cert_dir / f"{self.domain}.key"
            
            # Write certificate
            with open(cert_file, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
            
            # Write private key
            with open(key_file, "wb") as f:
                f.write(private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            
            return cert_file, key_file
            
        except Exception as e:
            print(f"❌ Self-signed certificate generation failed: {e}")
            return None, None
    
    def list_certificates(self) -> List[Dict[str, Any]]:
        """List available certificates"""
        certificates = []
        
        # Check mkcert certificates
        for cert_file in self.cert_dir.glob("*.pem"):
            if not cert_file.name.endswith("-key.pem"):
                key_file = cert_file.with_name(cert_file.name.replace(".pem", "-key.pem"))
                if key_file.exists():
                    certificates.append({
                        "name": cert_file.stem,
                        "type": "mkcert",
                        "cert_file": str(cert_file),
                        "key_file": str(key_file),
                        "expires": self._get_cert_expiry(cert_file)
                    })
        
        # Check self-signed certificates
        for cert_file in self.cert_dir.glob("*.crt"):
            key_file = cert_file.with_suffix(".key")
            if key_file.exists():
                certificates.append({
                    "name": cert_file.stem,
                    "type": "self_signed",
                    "cert_file": str(cert_file),
                    "key_file": str(key_file),
                    "expires": self._get_cert_expiry(cert_file)
                })
        
        return certificates
    
    def _get_cert_expiry(self, cert_file: Path) -> Optional[str]:
        """Get certificate expiry date"""
        try:
            with open(cert_file, 'rb') as f:
                cert_data = f.read()
            
            cert = x509.load_pem_x509_certificate(cert_data)
            return cert.not_valid_after.isoformat()
        except:
            return None
    
    def test_https(self, host: str = None, port: int = 443) -> Dict[str, Any]:
        """Test HTTPS connectivity"""
        host = host or f"test.{self.domain}"
        
        result = {
            "host": host,
            "port": port,
            "success": False,
            "cert_valid": False,
            "details": []
        }
        
        try:
            # Create SSL context
            context = ssl.create_default_context()
            
            # Connect and get certificate
            with socket.create_connection((host, port), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = ssock.getpeercert()
                    
                    result.update({
                        "success": True,
                        "cert_valid": True,
                        "cert_info": {
                            "subject": cert.get("subject", []),
                            "issuer": cert.get("issuer", []),
                            "version": cert.get("version"),
                            "notAfter": cert.get("notAfter"),
                            "notBefore": cert.get("notBefore")
                        }
                    })
                    result["details"].append("HTTPS connection successful")
                    
        except ssl.SSLCertVerificationError as e:
            result["details"].append(f"Certificate verification failed: {e}")
        except ConnectionRefusedError:
            result["details"].append("Connection refused")
        except socket.timeout:
            result["details"].append("Connection timeout")
        except Exception as e:
            result["details"].append(f"Connection error: {e}")
        
        return result
    
    def get_status(self) -> Dict[str, Any]:
        """Get TLS status summary"""
        return {
            "domain": self.domain,
            "mkcert_available": self.mkcert.is_available(),
            "mkcert_ca_root": str(self.mkcert.ca_root_path) if self.mkcert.ca_root_path else None,
            "caddy_ca_available": bool(self.caddy_ca.get_ca_cert()),
            "certificates": self.list_certificates(),
            "cert_directory": str(self.cert_dir)
        }

if __name__ == "__main__":
    # Test/demo mode
    tls_mgr = TLSManager()
    
    print("🔐 Port Authority TLS Manager")
    print("=" * 50)
    
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        result = tls_mgr.setup()
        print("\n🎯 TLS Setup Results:")
        print(f"Success: {result['success']}")
        print(f"Method: {result['method']}")
        if result['cert_file']:
            print(f"Certificate: {result['cert_file']}")
            print(f"Key: {result['key_file']}")
        print(f"CA Installed: {result['ca_installed']}")
        print("\nDetails:")
        for detail in result['details']:
            print(f"  - {detail}")
    else:
        status = tls_mgr.get_status()
        print(f"Domain: {status['domain']}")
        print(f"mkcert available: {status['mkcert_available']}")
        print(f"Caddy CA available: {status['caddy_ca_available']}")
        print(f"Certificates found: {len(status['certificates'])}")
        
        for cert in status['certificates']:
            print(f"  - {cert['name']} ({cert['type']}) expires {cert['expires']}")
