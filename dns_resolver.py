#!/usr/bin/env python3
"""
🌐 Harbormasterd DNS Resolver
Zero-config local DNS for *.pa.local domains

Features:
- Stub domain resolver for *.pa.local → 127.0.0.1/::1
- Cross-platform installation (Windows/macOS/Linux)
- UDP + TCP DNS server on port 53 (with fallback)
- NRPT rules on Windows, systemd-resolved on Linux, /etc/resolver on macOS
- Automatic fallback to hosts file if no admin permissions
- IPv4 and IPv6 support (A and AAAA records)
"""

import socket
import struct
import threading
import time
import os
import sys
import subprocess
import platform
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
import logging
import json
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class DNSQuery:
    """Parsed DNS query"""
    transaction_id: bytes
    flags: int
    questions: List[Dict[str, Any]]
    raw_data: bytes

class SimpleDNSServer:
    """Lightweight DNS server for *.pa.local resolution"""
    
    def __init__(self, port: int = 53, domain: str = "pa.local", 
                 ipv4: str = "127.0.0.1", ipv6: str = "::1"):
        self.port = port
        self.domain = domain.lower()
        self.ipv4_bytes = socket.inet_aton(ipv4)
        self.ipv6_bytes = socket.inet_pton(socket.AF_INET6, ipv6)
        self.running = False
        self.udp_socket = None
        self.tcp_socket = None
        
    def start(self):
        """Start DNS server (UDP + TCP)"""
        try:
            # Try to bind to port 53
            self._start_servers()
            self.running = True
            logger.info(f"🌐 DNS resolver started on 127.0.0.1:{self.port}")
            logger.info(f"📡 Resolving *.{self.domain} → 127.0.0.1/::1")
            
            # Start server threads
            udp_thread = threading.Thread(target=self._udp_server, daemon=True)
            tcp_thread = threading.Thread(target=self._tcp_server, daemon=True)
            
            udp_thread.start()
            tcp_thread.start()
            
            return True
            
        except PermissionError:
            logger.error(f"❌ Permission denied binding to port {self.port}")
            logger.info("💡 Try running as administrator/sudo or use hosts file fallback")
            return False
        except OSError as e:
            if e.errno == 10048:  # Port already in use (Windows)
                logger.error(f"❌ Port {self.port} already in use")
                logger.info("💡 Another DNS server might be running")
            else:
                logger.error(f"❌ Failed to start DNS server: {e}")
            return False
    
    def _start_servers(self):
        """Initialize UDP and TCP sockets"""
        # UDP server
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.bind(('127.0.0.1', self.port))
        
        # TCP server  
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_socket.bind(('127.0.0.1', self.port))
        self.tcp_socket.listen(5)
    
    def _udp_server(self):
        """Handle UDP DNS queries"""
        while self.running:
            try:
                data, addr = self.udp_socket.recvfrom(512)
                response = self._handle_query(data)
                self.udp_socket.sendto(response, addr)
            except Exception as e:
                if self.running:  # Don't log errors during shutdown
                    logger.error(f"UDP DNS error: {e}")
    
    def _tcp_server(self):
        """Handle TCP DNS queries"""
        while self.running:
            try:
                conn, addr = self.tcp_socket.accept()
                with conn:
                    # TCP DNS has 2-byte length prefix
                    length_data = conn.recv(2)
                    if len(length_data) == 2:
                        query_length = struct.unpack('!H', length_data)[0]
                        query_data = conn.recv(query_length)
                        
                        response = self._handle_query(query_data)
                        response_length = struct.pack('!H', len(response))
                        conn.send(response_length + response)
            except Exception as e:
                if self.running:
                    logger.error(f"TCP DNS error: {e}")
    
    def _handle_query(self, data: bytes) -> bytes:
        """Handle DNS query and return response"""
        try:
            query = self._parse_query(data)
            
            # Build response
            response_flags = 0x8180  # Standard response, recursion available
            answers = []
            
            for question in query.questions:
                qname = question['name']
                qtype = question['type']
                
                # Check if it's a *.pa.local query
                if qname.endswith(f'.{self.domain}.') or qname == f'{self.domain}.':
                    if qtype == 1:  # A record (IPv4)
                        answers.append(self._build_a_record(qname, self.ipv4_bytes))
                    elif qtype == 28:  # AAAA record (IPv6)
                        answers.append(self._build_aaaa_record(qname, self.ipv6_bytes))
            
            return self._build_response(query, response_flags, answers)
            
        except Exception as e:
            logger.error(f"DNS query handling error: {e}")
            # Return SERVFAIL response
            return self._build_error_response(data, 0x8182)
    
    def _parse_query(self, data: bytes) -> DNSQuery:
        """Parse DNS query packet"""
        if len(data) < 12:
            raise ValueError("DNS query too short")
        
        transaction_id = data[:2]
        flags = struct.unpack('!H', data[2:4])[0]
        qdcount = struct.unpack('!H', data[4:6])[0]
        
        questions = []
        offset = 12
        
        for _ in range(qdcount):
            qname, offset = self._parse_name(data, offset)
            if offset + 4 > len(data):
                raise ValueError("Invalid DNS query format")
            
            qtype = struct.unpack('!H', data[offset:offset+2])[0]
            qclass = struct.unpack('!H', data[offset+2:offset+4])[0]
            offset += 4
            
            questions.append({
                'name': qname,
                'type': qtype,
                'class': qclass
            })
        
        return DNSQuery(transaction_id, flags, questions, data)
    
    def _parse_name(self, data: bytes, offset: int) -> Tuple[str, int]:
        """Parse domain name from DNS packet"""
        labels = []
        original_offset = offset
        jumped = False
        
        while offset < len(data):
            length = data[offset]
            
            if length == 0:  # End of name
                offset += 1
                break
            elif (length & 0xC0) == 0xC0:  # Compression pointer
                if not jumped:
                    original_offset = offset + 2
                    jumped = True
                pointer = struct.unpack('!H', data[offset:offset+2])[0] & 0x3FFF
                offset = pointer
            else:  # Regular label
                offset += 1
                if offset + length > len(data):
                    raise ValueError("Invalid name in DNS query")
                labels.append(data[offset:offset+length].decode('utf-8'))
                offset += length
        
        return '.'.join(labels) + '.', original_offset if jumped else offset
    
    def _build_a_record(self, name: str, ip_bytes: bytes) -> bytes:
        """Build A record answer"""
        # Name pointer (points to question)
        name_ref = b'\xc0\x0c'
        record_type = struct.pack('!H', 1)  # A record
        record_class = struct.pack('!H', 1)  # IN class
        ttl = struct.pack('!I', 300)  # 5 minutes
        rdlength = struct.pack('!H', 4)  # IPv4 is 4 bytes
        
        return name_ref + record_type + record_class + ttl + rdlength + ip_bytes
    
    def _build_aaaa_record(self, name: str, ipv6_bytes: bytes) -> bytes:
        """Build AAAA record answer"""
        # Name pointer (points to question)  
        name_ref = b'\xc0\x0c'
        record_type = struct.pack('!H', 28)  # AAAA record
        record_class = struct.pack('!H', 1)   # IN class
        ttl = struct.pack('!I', 300)  # 5 minutes
        rdlength = struct.pack('!H', 16)  # IPv6 is 16 bytes
        
        return name_ref + record_type + record_class + ttl + rdlength + ipv6_bytes
    
    def _build_response(self, query: DNSQuery, flags: int, answers: List[bytes]) -> bytes:
        """Build DNS response packet"""
        header = (
            query.transaction_id +
            struct.pack('!H', flags) +  # Response flags
            struct.pack('!H', len(query.questions)) +  # Questions
            struct.pack('!H', len(answers)) +  # Answers  
            struct.pack('!H', 0) +  # Authority
            struct.pack('!H', 0)    # Additional
        )
        
        # Copy question section from original query
        questions_data = query.raw_data[12:]
        
        # Find end of questions section
        offset = 0
        for _ in range(len(query.questions)):
            # Skip name
            while offset < len(questions_data):
                length = questions_data[offset]
                offset += 1
                if length == 0:
                    break
                elif (length & 0xC0) == 0xC0:
                    offset += 1
                    break
                else:
                    offset += length
            offset += 4  # Skip QTYPE and QCLASS
        
        questions_section = questions_data[:offset]
        answers_section = b''.join(answers)
        
        return header + questions_section + answers_section
    
    def _build_error_response(self, original_query: bytes, error_flags: int) -> bytes:
        """Build error response (SERVFAIL, NXDOMAIN, etc.)"""
        if len(original_query) < 12:
            return b''
        
        transaction_id = original_query[:2]
        qdcount = original_query[4:6]
        
        header = (
            transaction_id +
            struct.pack('!H', error_flags) +
            qdcount +  # Questions
            struct.pack('!H', 0) +  # Answers
            struct.pack('!H', 0) +  # Authority  
            struct.pack('!H', 0)    # Additional
        )
        
        return header
    
    def stop(self):
        """Stop DNS server"""
        self.running = False
        if self.udp_socket:
            self.udp_socket.close()
        if self.tcp_socket:
            self.tcp_socket.close()
        logger.info("🌐 DNS resolver stopped")

class CrossPlatformDNSInstaller:
    """Cross-platform DNS installation manager"""
    
    def __init__(self, domain: str = "pa.local", resolver_ip: str = "127.0.0.1", 
                 resolver_port: int = 5533):
        self.domain = domain
        self.resolver_ip = resolver_ip
        self.resolver_port = resolver_port
        self.platform = platform.system().lower()
        self.dns_server = None
        
    def install(self) -> bool:
        """Install DNS resolver for *.pa.local"""
        print(f"🌐 Installing DNS resolver for *.{self.domain}")
        print(f"📡 Platform: {self.platform}")
        
        try:
            if self.platform == "windows":
                return self._install_windows()
            elif self.platform == "darwin":  # macOS
                return self._install_macos()
            elif self.platform == "linux":
                return self._install_linux()
            else:
                print(f"⚠️  Unsupported platform: {self.platform}")
                return self._install_hosts_fallback()
                
        except Exception as e:
            print(f"❌ DNS installation failed: {e}")
            print("🔄 Falling back to hosts file method...")
            return self._install_hosts_fallback()
    
    def _install_windows(self) -> bool:
        """Install DNS resolver on Windows using NRPT"""
        print("🪟 Installing Windows DNS resolver...")
        
        try:
            # Method 1: Try NRPT (Name Resolution Policy Table) - requires admin
            nrpt_cmd = [
                "powershell", "-Command",
                f"Add-DnsClientNrptRule -Namespace '.{self.domain}' -NameServers '{self.resolver_ip}:{self.resolver_port}'"
            ]
            
            result = subprocess.run(nrpt_cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print("✅ NRPT rule added successfully")
                return self._start_embedded_server()
            else:
                print("⚠️  NRPT rule failed (need admin?), trying hosts file...")
                return self._install_hosts_fallback()
                
        except Exception as e:
            print(f"❌ NRPT installation failed: {e}")
            return self._install_hosts_fallback()
    
    def _install_macos(self) -> bool:
        """Install DNS resolver on macOS using /etc/resolver"""
        print("🍎 Installing macOS DNS resolver...")
        
        try:
            # Create /etc/resolver/pa.local
            resolver_dir = Path("/etc/resolver")
            resolver_file = resolver_dir / self.domain
            
            # Check if directory exists, create if needed
            if not resolver_dir.exists():
                subprocess.run(["sudo", "mkdir", "-p", str(resolver_dir)], check=True)
            
            # Create resolver file
            resolver_content = f"nameserver {self.resolver_ip}\nport {self.resolver_port}\n"
            
            # Write with sudo
            process = subprocess.Popen(
                ["sudo", "tee", str(resolver_file)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True
            )
            process.communicate(resolver_content)
            
            if process.returncode == 0:
                print(f"✅ Created {resolver_file}")
                print(f"🔄 Flushing DNS cache...")
                subprocess.run(["sudo", "dscacheutil", "-flushcache"], check=True)
                return self._start_embedded_server()
            else:
                print("❌ Failed to create resolver file")
                return self._install_hosts_fallback()
                
        except subprocess.CalledProcessError as e:
            print(f"❌ macOS DNS setup failed: {e}")
            return self._install_hosts_fallback()
        except Exception as e:
            print(f"❌ macOS DNS installation error: {e}")
            return self._install_hosts_fallback()
    
    def _install_linux(self) -> bool:
        """Install DNS resolver on Linux using systemd-resolved"""
        print("🐧 Installing Linux DNS resolver...")
        
        try:
            # Method 1: systemd-resolved (Ubuntu/Debian/modern distros)
            if self._has_systemd_resolved():
                return self._install_systemd_resolved()
            
            # Method 2: NetworkManager
            if self._has_networkmanager():
                return self._install_networkmanager()
            
            # Method 3: Direct /etc/resolv.conf (risky)
            print("⚠️  No supported DNS manager found, using hosts fallback")
            return self._install_hosts_fallback()
            
        except Exception as e:
            print(f"❌ Linux DNS installation failed: {e}")
            return self._install_hosts_fallback()
    
    def _has_systemd_resolved(self) -> bool:
        """Check if systemd-resolved is available"""
        try:
            result = subprocess.run(["systemctl", "is-active", "systemd-resolved"], 
                                  capture_output=True)
            return result.returncode == 0
        except:
            return False
    
    def _has_networkmanager(self) -> bool:
        """Check if NetworkManager is available"""
        try:
            result = subprocess.run(["which", "nmcli"], capture_output=True)
            return result.returncode == 0
        except:
            return False
    
    def _install_systemd_resolved(self) -> bool:
        """Configure systemd-resolved for *.pa.local"""
        print("🔧 Configuring systemd-resolved...")
        
        try:
            # Create resolved config drop-in
            config_dir = Path("/etc/systemd/resolved.conf.d")
            config_file = config_dir / "harbormasterd.conf"
            
            config_content = f"""[Resolve]
Domains=~{self.domain}
DNS={self.resolver_ip}:{self.resolver_port}
"""
            
            # Create directory and file with sudo
            subprocess.run(["sudo", "mkdir", "-p", str(config_dir)], check=True)
            
            process = subprocess.Popen(
                ["sudo", "tee", str(config_file)],
                stdin=subprocess.PIPE,
                text=True
            )
            process.communicate(config_content)
            
            if process.returncode == 0:
                # Restart systemd-resolved
                subprocess.run(["sudo", "systemctl", "restart", "systemd-resolved"], check=True)
                print("✅ systemd-resolved configured")
                return self._start_embedded_server()
            else:
                return False
                
        except subprocess.CalledProcessError as e:
            print(f"❌ systemd-resolved configuration failed: {e}")
            return False
    
    def _install_networkmanager(self) -> bool:
        """Configure NetworkManager for *.pa.local"""
        print("🔧 Configuring NetworkManager...")
        
        try:
            # Add DNS server to current connection
            connections = subprocess.check_output(
                ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"],
                text=True
            ).strip().split('\n')
            
            if connections and connections[0]:
                connection_name = connections[0].split(':')[0]
                
                # Add our DNS server
                subprocess.run([
                    "sudo", "nmcli", "connection", "modify", connection_name,
                    f"ipv4.dns-search", f"~{self.domain}",
                    f"ipv4.dns", f"{self.resolver_ip}"
                ], check=True)
                
                # Restart connection
                subprocess.run([
                    "sudo", "nmcli", "connection", "down", connection_name
                ], check=True)
                subprocess.run([
                    "sudo", "nmcli", "connection", "up", connection_name  
                ], check=True)
                
                print("✅ NetworkManager configured")
                return self._start_embedded_server()
            else:
                print("❌ No active NetworkManager connection found")
                return False
                
        except subprocess.CalledProcessError as e:
            print(f"❌ NetworkManager configuration failed: {e}")
            return False
    
    def _install_hosts_fallback(self) -> bool:
        """Fallback: Add entries to hosts file"""
        print(f"📝 Using hosts file fallback for *.{self.domain}")
        
        try:
            if self.platform == "windows":
                hosts_file = Path("C:/Windows/System32/drivers/etc/hosts")
            else:
                hosts_file = Path("/etc/hosts")
            
            # Read current hosts file
            if hosts_file.exists():
                hosts_content = hosts_file.read_text()
            else:
                hosts_content = ""
            
            # Add our entries if not present
            marker = f"# Harbormasterd - {self.domain}"
            if marker not in hosts_content:
                new_entries = f"\n{marker}\n127.0.0.1 *.{self.domain}\n::1 *.{self.domain}\n"
                
                # Write with appropriate method
                if self.platform == "windows":
                    # Windows: try to write directly or use PowerShell
                    try:
                        with open(hosts_file, "a") as f:
                            f.write(new_entries)
                        print("✅ Added to hosts file")
                        return True
                    except PermissionError:
                        print("❌ Permission denied writing to hosts file")
                        print("💡 Run as administrator or manually add:")
                        print(f"127.0.0.1 *.{self.domain}")
                        return False
                else:
                    # Unix: use sudo
                    process = subprocess.Popen(
                        ["sudo", "tee", "-a", str(hosts_file)],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        text=True
                    )
                    process.communicate(new_entries)
                    
                    if process.returncode == 0:
                        print("✅ Added to hosts file")
                        return True
                    else:
                        print("❌ Failed to update hosts file")
                        return False
            else:
                print("✅ Hosts file already configured")
                return True
                
        except Exception as e:
            print(f"❌ Hosts file fallback failed: {e}")
            print("💡 Manually add these entries to your hosts file:")
            print(f"127.0.0.1 web.{self.domain}")
            print(f"127.0.0.1 api.{self.domain}")
            return False
    
    def _start_embedded_server(self) -> bool:
        """Start embedded DNS server"""
        print(f"🚀 Starting DNS server on port {self.resolver_port}...")
        
        try:
            self.dns_server = SimpleDNSServer(
                port=self.resolver_port,
                domain=self.domain
            )
            
            if self.dns_server.start():
                print("✅ DNS resolver running and configured")
                return True
            else:
                print("❌ Failed to start DNS server")
                return False
                
        except Exception as e:
            print(f"❌ DNS server startup failed: {e}")
            return False
    
    def uninstall(self) -> bool:
        """Remove DNS resolver configuration"""
        print(f"🗑️ Uninstalling DNS resolver for *.{self.domain}")
        
        try:
            if self.dns_server:
                self.dns_server.stop()
            
            if self.platform == "windows":
                return self._uninstall_windows()
            elif self.platform == "darwin":
                return self._uninstall_macos()
            elif self.platform == "linux":
                return self._uninstall_linux()
            
        except Exception as e:
            print(f"❌ DNS uninstallation failed: {e}")
            return False
            
        return True
    
    def _uninstall_windows(self) -> bool:
        """Remove Windows NRPT rule"""
        try:
            subprocess.run([
                "powershell", "-Command",
                f"Remove-DnsClientNrptRule -Namespace '.{self.domain}' -Force"
            ], capture_output=True)
            print("✅ Windows DNS configuration removed")
            return True
        except:
            print("⚠️  Could not remove NRPT rule (may not have existed)")
            return True
    
    def _uninstall_macos(self) -> bool:
        """Remove macOS resolver file"""
        try:
            resolver_file = Path(f"/etc/resolver/{self.domain}")
            if resolver_file.exists():
                subprocess.run(["sudo", "rm", str(resolver_file)], check=True)
                subprocess.run(["sudo", "dscacheutil", "-flushcache"], check=True)
                print("✅ macOS DNS configuration removed")
            return True
        except:
            print("⚠️  Could not remove resolver file")
            return True
    
    def _uninstall_linux(self) -> bool:
        """Remove Linux DNS configuration"""
        try:
            config_file = Path("/etc/systemd/resolved.conf.d/harbormasterd.conf")
            if config_file.exists():
                subprocess.run(["sudo", "rm", str(config_file)], check=True)
                subprocess.run(["sudo", "systemctl", "restart", "systemd-resolved"], check=True)
                print("✅ Linux DNS configuration removed")
            return True
        except:
            print("⚠️  Could not remove systemd-resolved configuration")
            return True
    
    def is_working(self) -> bool:
        """Test if DNS resolution is working"""
        try:
            # Try to resolve a test subdomain
            test_domain = f"test.{self.domain}"
            result = socket.gethostbyname(test_domain)
            return result == "127.0.0.1"
        except:
            return False
    
    def status(self) -> Dict[str, Any]:
        """Get DNS resolver status"""
        return {
            "domain": self.domain,
            "resolver_ip": self.resolver_ip,
            "resolver_port": self.resolver_port,
            "platform": self.platform,
            "server_running": self.dns_server and self.dns_server.running,
            "resolution_working": self.is_working()
        }

if __name__ == "__main__":
    # Test/demo mode
    installer = CrossPlatformDNSInstaller()
    
    print("🌐 Harbormasterd DNS Resolver")
    print("=" * 50)
    
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        success = installer.install()
        if success:
            print("\n🎉 DNS resolver installed successfully!")
            print(f"💡 Try: nslookup web.pa.local 127.0.0.1")
            
            # Keep server running
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n👋 Shutting down DNS resolver...")
                installer.dns_server.stop()
        else:
            print("\n❌ DNS resolver installation failed")
            sys.exit(1)
    else:
        status = installer.status()
        print(f"Domain: {status['domain']}")
        print(f"Platform: {status['platform']}")
        print(f"Server running: {status['server_running']}")
        print(f"Resolution working: {status['resolution_working']}")
