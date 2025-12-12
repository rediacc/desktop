#!/usr/bin/env python3
"""
System Status Window for Rediacc CLI

Provides comprehensive status information about platform integration,
tools, fallback mechanisms, dependencies, and configuration.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import sys
import os
import platform
import shutil
import subprocess
import json
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

# Add parent directories to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli.core.config import get_config_dir, get_main_config_file, TokenManager, i18n
from cli.core.shared import is_windows, get_cli_command
from cli.core.protocol_handler import get_protocol_status, get_platform
from cli.core.env_config import EnvironmentConfig
from cli.gui.base import BaseWindow, create_tooltip
from cli.gui.utilities import (
    COLOR_SUCCESS, COLOR_ERROR, COLOR_INFO,
    FONT_FAMILY_DEFAULT, FONT_SIZE_MEDIUM, FONT_SIZE_SMALL
)

# Define COLOR_WARNING if not available
try:
    from cli.gui.utilities import COLOR_WARNING
except ImportError:
    COLOR_WARNING = 'orange'


class SystemStatusChecker:
    """Core system status checking functionality"""

    def __init__(self):
        self.platform_info = self._get_platform_info()
        self.python_info = self._get_python_info()

    def _get_platform_info(self) -> Dict[str, Any]:
        """Get comprehensive platform information"""
        info = {
            'os': platform.system(),
            'os_version': platform.release(),
            'architecture': platform.machine(),
            'platform': platform.platform(),
            'hostname': platform.node(),
            'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            'python_path': sys.executable,
            'is_windows': is_windows(),
            'msys2_detected': False,
            'msys2_path': None
        }

        # Check for MSYS2 on Windows
        if is_windows():
            info['msys2_detected'] = bool(os.environ.get('MSYSTEM'))
            if info['msys2_detected']:
                info['msys2_path'] = os.environ.get('MSYS2_ROOT', 'Unknown')
                info['msys2_system'] = os.environ.get('MSYSTEM', 'Unknown')

        return info

    def _get_python_info(self) -> Dict[str, Any]:
        """Get Python interpreter information and detection"""
        # Try to find Python interpreters
        python_cmd = None
        for cmd in ['python3', 'python', 'py']:
            if shutil.which(cmd):
                python_cmd = cmd
                break

        info = {
            'current_executable': sys.executable,
            'detected_command': python_cmd,
            'available_interpreters': []
        }

        # Check all possible Python commands
        for cmd in ['python3', 'python', 'py']:
            path = shutil.which(cmd)
            if path:
                try:
                    result = subprocess.run(
                        [cmd, '--version'],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        info['available_interpreters'].append({
                            'command': cmd,
                            'path': path,
                            'version': result.stdout.strip()
                        })
                except Exception:
                    pass

        return info

    def check_environment_context(self) -> Dict[str, Any]:
        """Check runtime environment context (WSL, containers, etc.)"""
        context = {
            'wsl': False,
            'wsl_version': None,
            'container': False,
            'container_type': None,
            'virtual_env': False,
            'virtual_env_type': None,
            'virtualization': False,
            'virtualization_type': None
        }

        # WSL Detection
        try:
            if os.path.exists('/proc/version'):
                with open('/proc/version', 'r') as f:
                    proc_version = f.read().lower()
                    if 'microsoft' in proc_version:
                        context['wsl'] = True
                        if 'wsl2' in proc_version:
                            context['wsl_version'] = 'WSL2'
                        elif 'wsl' in proc_version:
                            context['wsl_version'] = 'WSL1'
        except Exception:
            pass

        # Container Detection
        try:
            # Check for Docker container
            if os.path.exists('/.dockerenv'):
                context['container'] = True
                context['container_type'] = 'Docker'

            # Check for other container types
            if os.path.exists('/run/.containerenv'):
                context['container'] = True
                context['container_type'] = 'Podman'

            # Check cgroup for container indicators
            if os.path.exists('/proc/1/cgroup'):
                with open('/proc/1/cgroup', 'r') as f:
                    cgroup_content = f.read()
                    if 'docker' in cgroup_content:
                        context['container'] = True
                        context['container_type'] = 'Docker'
                    elif 'lxc' in cgroup_content:
                        context['container'] = True
                        context['container_type'] = 'LXC'
        except Exception:
            pass

        # Virtual Environment Detection
        if os.environ.get('VIRTUAL_ENV'):
            context['virtual_env'] = True
            context['virtual_env_type'] = 'venv/virtualenv'
        elif os.environ.get('CONDA_DEFAULT_ENV'):
            context['virtual_env'] = True
            context['virtual_env_type'] = 'Conda'
        elif os.environ.get('PIPENV_ACTIVE'):
            context['virtual_env'] = True
            context['virtual_env_type'] = 'Pipenv'

        # Virtualization Detection
        try:
            # Check for common virtualization indicators
            if shutil.which('systemd-detect-virt'):
                result = subprocess.run(['systemd-detect-virt'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip() != 'none':
                    context['virtualization'] = True
                    context['virtualization_type'] = result.stdout.strip()

            # Check DMI info for VM detection
            dmi_paths = ['/sys/class/dmi/id/product_name', '/sys/class/dmi/id/sys_vendor']
            for path in dmi_paths:
                if os.path.exists(path):
                    try:
                        with open(path, 'r') as f:
                            content = f.read().lower()
                            if any(vm in content for vm in ['virtualbox', 'vmware', 'qemu', 'kvm', 'hyper-v']):
                                context['virtualization'] = True
                                for vm_type in ['virtualbox', 'vmware', 'qemu', 'kvm', 'hyper-v']:
                                    if vm_type in content:
                                        context['virtualization_type'] = vm_type.upper()
                                        break
                                break
                    except Exception:
                        pass
        except Exception:
            pass

        return context

    def check_active_plugins(self) -> Dict[str, Any]:
        """Check active plugin connections"""
        plugins_status = {
            'connections_file_exists': False,
            'connections_file_path': None,
            'active_connections': [],
            'stale_connections': [],
            'connection_count': 0
        }

        try:
            from cli.core.config import get_plugin_connections_file
            connections_file = get_plugin_connections_file()
            plugins_status['connections_file_path'] = str(connections_file)
            plugins_status['connections_file_exists'] = connections_file.exists()

            if connections_file.exists():
                import json
                with open(connections_file, 'r') as f:
                    connections = json.load(f)

                plugins_status['connection_count'] = len(connections)

                # Check which connections are still active
                for conn_id, conn_info in connections.items():
                    pid = conn_info.get('ssh_pid')
                    if pid:
                        try:
                            # Check if process is still running
                            os.kill(pid, 0)
                            plugins_status['active_connections'].append({
                                'id': conn_id,
                                'pid': pid,
                                'plugin': conn_info.get('plugin_name'),
                                'local_port': conn_info.get('local_port'),
                                'team': conn_info.get('team'),
                                'machine': conn_info.get('machine'),
                                'repository': conn_info.get('repository')
                            })
                        except OSError:
                            # Process not running
                            plugins_status['stale_connections'].append({
                                'id': conn_id,
                                'pid': pid,
                                'plugin': conn_info.get('plugin_name')
                            })

        except Exception as e:
            plugins_status['error'] = str(e)

        return plugins_status

    def check_core_tools(self) -> Dict[str, Dict[str, Any]]:
        """Check availability and status of core tools"""
        tools = {}

        # rsync check
        tools['rsync'] = self._check_tool_with_fallback('rsync', ['rsync'], ['--version'])
        if is_windows() and not tools['rsync']['available']:
            # Check for MSYS2 rsync
            tools['rsync']['msys2_path'] = self._find_msys2_executable('rsync')
            if tools['rsync']['msys2_path']:
                tools['rsync']['available'] = True
                tools['rsync']['path'] = tools['rsync']['msys2_path']
                tools['rsync']['source'] = 'MSYS2'

        # ssh check with Unix socket support detection
        tools['ssh'] = self._check_tool_with_fallback('ssh', ['ssh'], ['-V'])
        if tools['ssh']['available']:
            if is_windows():
                # Distinguish between Windows OpenSSH and MSYS2 SSH
                ssh_path = tools['ssh'].get('path', '')
                if 'msys' in ssh_path.lower() or 'mingw' in ssh_path.lower():
                    tools['ssh']['source'] = 'MSYS2'
                elif 'system32' in ssh_path.lower() or 'windows' in ssh_path.lower():
                    tools['ssh']['source'] = 'Windows OpenSSH'
                else:
                    tools['ssh']['source'] = 'Unknown'

            # Check Unix socket forwarding support
            tools['ssh']['unix_forwarding'] = self._check_ssh_unix_support()

        # git check
        tools['git'] = self._check_tool_with_fallback('git', ['git'], ['--version'])

        # docker check
        tools['docker'] = self._check_tool_with_fallback('docker', ['docker'], ['--version'])
        if tools['docker']['available']:
            # Check if Docker daemon is running
            tools['docker']['daemon_running'] = self._check_docker_daemon()

        # VS Code check
        tools['vscode'] = self._check_vscode_availability()

        # tkinter check (for GUI)
        tools['tkinter'] = {
            'available': False,
            'error': None,
            'version': None
        }
        try:
            import tkinter
            tools['tkinter']['available'] = True
            tools['tkinter']['version'] = tkinter.TkVersion
        except ImportError as e:
            tools['tkinter']['error'] = str(e)

        return tools

    def _check_tool_with_fallback(self, name: str, commands: List[str], version_args: List[str]) -> Dict[str, Any]:
        """Check tool availability with command fallbacks"""
        result = {
            'available': False,
            'path': None,
            'version': None,
            'error': None,
            'source': 'System PATH'
        }

        for cmd in commands:
            path = shutil.which(cmd)
            if path:
                result['available'] = True
                result['path'] = path

                # Try to get version
                try:
                    version_result = subprocess.run(
                        [cmd] + version_args,
                        capture_output=True, text=True, timeout=10
                    )
                    if version_result.returncode == 0:
                        result['version'] = version_result.stdout.strip()
                    else:
                        result['version'] = version_result.stderr.strip()
                except Exception as e:
                    result['error'] = f"Version check failed: {e}"
                break

        return result

    def _find_msys2_executable(self, exe_name: str) -> Optional[str]:
        """Find executable in MSYS2 installation"""
        if not is_windows():
            return None

        for msys2_path in [
            os.environ.get('MSYS2_ROOT'),
            'C:\\msys64',
            'C:\\msys2',
            os.path.expanduser('~\\msys64'),
            os.path.expanduser('~\\msys2')
        ]:
            if msys2_path and os.path.exists(msys2_path):
                for subdir in ['usr\\bin', 'mingw64\\bin', 'mingw32\\bin']:
                    exe_path = os.path.join(msys2_path, subdir, f'{exe_name}.exe')
                    if os.path.exists(exe_path):
                        return exe_path
        return None

    def _check_ssh_unix_support(self) -> bool:
        """Check if SSH supports Unix socket forwarding"""
        try:
            result = subprocess.run(['ssh', '-V'], capture_output=True, text=True, timeout=5)
            ssh_version_output = (result.stdout + result.stderr).lower()

            if 'openssh' not in ssh_version_output:
                return False

            # Extract version number
            import re
            match = re.search(r'openssh[_\s]+(\d+)\.(\d+)', ssh_version_output)
            if match:
                major, minor = map(int, match.groups())
                return major > 6 or (major == 6 and minor >= 7)

            return False
        except Exception:
            return False

    def _check_docker_daemon(self) -> bool:
        """Check if Docker daemon is running"""
        try:
            result = subprocess.run(['docker', 'info'], capture_output=True, timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    def _check_vscode_availability(self) -> Dict[str, Any]:
        """Check VS Code availability and integration"""
        vscode_info = {
            'available': False,
            'path': None,
            'version': None,
            'source': None,
            'wsl_support': False
        }

        # Check environment variable first
        vscode_path = os.environ.get('REDIACC_VSCODE_PATH')
        if vscode_path and shutil.which(vscode_path):
            vscode_info['available'] = True
            vscode_info['path'] = vscode_path
            vscode_info['source'] = 'Environment Variable'
        else:
            # Platform-specific detection
            system = platform.system().lower()
            candidates = []

            if system == 'linux':
                # Check for WSL
                is_wsl = os.path.exists('/proc/version') and 'microsoft' in open('/proc/version', 'r').read().lower()
                if is_wsl:
                    vscode_info['wsl_support'] = True
                    candidates = ['code', '/mnt/c/Users/*/AppData/Local/Programs/Microsoft VS Code/Code.exe']
                else:
                    candidates = ['code', 'code-insiders']
            elif system == 'darwin':  # macOS
                candidates = [
                    'code',
                    '/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code'
                ]
            elif system == 'windows':
                candidates = [
                    'code',
                    'code.cmd',
                    os.path.expanduser('~\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe')
                ]

            for candidate in candidates:
                if '*' in candidate:
                    # Handle wildcard paths
                    import glob
                    for path in glob.glob(candidate):
                        if os.path.exists(path):
                            vscode_info['available'] = True
                            vscode_info['path'] = path
                            vscode_info['source'] = 'Auto-detected'
                            break
                elif shutil.which(candidate):
                    vscode_info['available'] = True
                    vscode_info['path'] = shutil.which(candidate)
                    vscode_info['source'] = 'PATH'
                    break

        # Get version if available
        if vscode_info['available'] and vscode_info['path']:
            try:
                result = subprocess.run([vscode_info['path'], '--version'],
                                      capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    vscode_info['version'] = result.stdout.strip().split('\n')[0]
            except Exception:
                pass

        return vscode_info

    def check_protocol_registration(self) -> Dict[str, Any]:
        """Check rediacc:// protocol registration status"""
        try:
            status = get_protocol_status()
            platform_name = get_platform()

            result = {
                'platform': platform_name,
                'supported': status.get('supported', False),
                'registered': status.get('registered', False),
                'user_registered': status.get('user_registered', False),
                'system_registered': status.get('system_registered', False),
                'details': status,
                'error': status.get('error')
            }

            return result
        except Exception as e:
            return {
                'platform': get_platform(),
                'supported': False,
                'registered': False,
                'user_registered': False,
                'system_registered': False,
                'error': str(e),
                'details': {}
            }

    def check_dependencies(self) -> Dict[str, Dict[str, Any]]:
        """Check platform-specific dependencies"""
        deps = {}
        platform_name = get_platform()

        if platform_name == 'windows':
            deps.update(self._check_windows_dependencies())
        elif platform_name == 'linux':
            deps.update(self._check_linux_dependencies())
        elif platform_name == 'macos':
            deps.update(self._check_macos_dependencies())

        return deps

    def _check_windows_dependencies(self) -> Dict[str, Dict[str, Any]]:
        """Check Windows-specific dependencies"""
        return {
            'reg': self._check_command_available('reg'),
            'icacls': self._check_command_available('icacls'),
            'powershell': self._check_command_available('powershell'),
            'wsl': self._check_command_available('wsl'),
        }

    def _check_linux_dependencies(self) -> Dict[str, Dict[str, Any]]:
        """Check Linux-specific dependencies"""
        return {
            'xdg-mime': self._check_command_available('xdg-mime'),
            'update-desktop-database': self._check_command_available('update-desktop-database'),
            'desktop-file-validate': self._check_command_available('desktop-file-validate'),
            'xhost': self._check_command_available('xhost'),
        }

    def _check_macos_dependencies(self) -> Dict[str, Dict[str, Any]]:
        """Check macOS-specific dependencies"""
        return {
            'duti': self._check_command_available('duti'),
            'plutil': self._check_command_available('plutil'),
            'launchctl': self._check_command_available('launchctl'),
            'lsregister': self._check_command_available('lsregister'),
            'xquartz': self._check_command_available('xhost'),  # Check for XQuartz
        }

    def _check_command_available(self, command: str) -> Dict[str, Any]:
        """Check if a command is available"""
        path = shutil.which(command)
        return {
            'available': path is not None,
            'path': path,
            'required': self._is_command_required(command),
            'description': self._get_command_description(command)
        }

    def _is_command_required(self, command: str) -> bool:
        """Determine if a command is required vs optional"""
        required_commands = {
            'reg', 'xdg-mime', 'update-desktop-database',
            'plutil', 'launchctl'
        }
        return command in required_commands

    def _get_command_description(self, command: str) -> str:
        """Get description for a command"""
        descriptions = {
            'reg': 'Windows Registry editor - required for protocol registration',
            'icacls': 'Windows ACL tool - used for file permissions',
            'powershell': 'Windows PowerShell - used for advanced operations',
            'wsl': 'Windows Subsystem for Linux - optional integration',
            'xdg-mime': 'XDG MIME type handler - required for protocol registration',
            'update-desktop-database': 'Desktop database updater - required for protocol registration',
            'desktop-file-validate': 'Desktop file validator - optional but recommended',
            'xhost': 'X11 host access control - required for GUI in containers',
            'duti': 'macOS default app utility - optional but recommended',
            'plutil': 'Property list utility - required for protocol registration',
            'launchctl': 'Launch service control - required for protocol registration',
            'lsregister': 'Launch Services register - used for protocol registration',
        }
        return descriptions.get(command, f'{command} utility')

    def check_configuration(self) -> Dict[str, Any]:
        """Check configuration files and settings"""
        config = {
            'config_dir': str(get_config_dir()),
            'config_file': str(get_main_config_file()),
            'config_exists': get_main_config_file().exists(),
            'config_readable': False,
            'config_data': None,
            'token_available': False,
            'token_valid': False,
            'env_vars': {},
            'cli_tool_path': None
        }

        # Check main config file
        if config['config_exists']:
            try:
                with open(get_main_config_file(), 'r') as f:
                    config['config_data'] = json.load(f)
                config['config_readable'] = True
            except Exception as e:
                config['config_error'] = str(e)

        # Check token
        try:
            token = TokenManager.get_token()
            config['token_available'] = bool(token)
            # TODO: Add token validation logic
            config['token_valid'] = config['token_available']
        except Exception:
            pass

        # Check important environment variables
        important_vars = [
            'SYSTEM_API_URL', 'PUBLIC_API_URL', 'REDIACC_BUILD_TYPE',
            'SYSTEM_ADMIN_EMAIL', 'SYSTEM_MASTER_PASSWORD',
            'DOCKER_REGISTRY', 'MSYSTEM', 'MSYS2_ROOT'
        ]

        for var in important_vars:
            value = os.environ.get(var)
            if value:
                # Redact sensitive values
                if any(sensitive in var.upper() for sensitive in ['PASSWORD', 'TOKEN', 'KEY']):
                    config['env_vars'][var] = '[REDACTED]'
                else:
                    config['env_vars'][var] = value

        # Check CLI tool availability
        try:
            cli_commands = get_cli_command()
            config['cli_tool_path'] = cli_commands
            config['cli_tool_available'] = True
        except Exception as e:
            config['cli_tool_available'] = False
            config['cli_tool_error'] = str(e)

        return config

    def check_connectivity(self) -> Dict[str, Any]:
        """Check network connectivity and API availability"""
        connectivity = {
            'api_endpoints': {},
            'telemetry_status': 'unknown',
            'ssh_connectivity': 'unknown'
        }

        # Check API endpoints
        endpoints = [
            ('public', 'https://www.rediacc.com/api'),
            ('sandbox', 'https://sandbox.rediacc.com/api'),
            ('local', 'http://localhost:7322/api')
        ]

        for name, url in endpoints:
            connectivity['api_endpoints'][name] = self._check_url_connectivity(url)

        # Check telemetry service
        try:
            from cli.core.telemetry import get_telemetry_service
            telemetry = get_telemetry_service()
            connectivity['telemetry_status'] = 'available' if telemetry else 'unavailable'
        except Exception:
            connectivity['telemetry_status'] = 'error'

        return connectivity

    def _check_url_connectivity(self, url: str) -> Dict[str, Any]:
        """Check if a URL is reachable"""
        result = {
            'reachable': False,
            'response_time': None,
            'error': None
        }

        try:
            import time
            start_time = time.time()

            # Try requests first, fall back to urllib
            try:
                import requests
                response = requests.get(url, timeout=10)
                result['reachable'] = response.status_code < 500
                result['status_code'] = response.status_code
            except ImportError:
                import urllib.request
                urllib.request.urlopen(url, timeout=10)
                result['reachable'] = True

            result['response_time'] = round((time.time() - start_time) * 1000, 2)

        except Exception as e:
            result['error'] = str(e)

        return result

    def generate_status_report(self) -> str:
        """Generate a comprehensive status report"""
        sections = []

        # Platform Information
        sections.append("=== PLATFORM INFORMATION ===")
        for key, value in self.platform_info.items():
            sections.append(f"{key}: {value}")

        # Python Information
        sections.append("\n=== PYTHON INFORMATION ===")
        for key, value in self.python_info.items():
            if key == 'available_interpreters':
                sections.append("Available Python interpreters:")
                for interp in value:
                    sections.append(f"  {interp['command']}: {interp['path']} ({interp['version']})")
            else:
                sections.append(f"{key}: {value}")

        # Environment Context
        sections.append("\n=== ENVIRONMENT CONTEXT ===")
        env = self.check_environment_context()
        sections.append(f"WSL: {env['wsl']} ({env['wsl_version']})" if env['wsl'] else "WSL: No")
        sections.append(f"Container: {env['container']} ({env['container_type']})" if env['container'] else "Container: No")
        sections.append(f"Virtual Environment: {env['virtual_env']} ({env['virtual_env_type']})" if env['virtual_env'] else "Virtual Environment: No")
        sections.append(f"Virtualization: {env['virtualization']} ({env['virtualization_type']})" if env['virtualization'] else "Virtualization: No")

        # Tools Status
        sections.append("\n=== TOOLS STATUS ===")
        tools = self.check_core_tools()
        for tool, info in tools.items():
            status = "✓" if info['available'] else "✗"
            sections.append(f"{status} {tool}: {info.get('path', 'Not found')}")
            if info.get('version'):
                sections.append(f"    Version: {info['version']}")
            if tool == 'ssh' and info.get('unix_forwarding') is not None:
                sections.append(f"    Unix Socket Forwarding: {'Yes' if info['unix_forwarding'] else 'No'}")
            if tool == 'docker' and info.get('daemon_running') is not None:
                sections.append(f"    Docker Daemon: {'Running' if info['daemon_running'] else 'Not Running'}")
            if tool == 'vscode' and isinstance(info, dict):
                if info.get('source'):
                    sections.append(f"    Detection: {info['source']}")

        # Plugin Connections
        sections.append("\n=== PLUGIN CONNECTIONS ===")
        plugins = self.check_active_plugins()
        sections.append(f"Connections file: {plugins['connections_file_path']}")
        sections.append(f"Active connections: {len(plugins['active_connections'])}")
        sections.append(f"Stale connections: {len(plugins['stale_connections'])}")
        if plugins['active_connections']:
            sections.append("Active plugins:")
            for conn in plugins['active_connections']:
                sections.append(f"  • {conn['plugin']} (PID: {conn['pid']}, Port: {conn['local_port']})")

        # Protocol Registration
        sections.append("\n=== PROTOCOL REGISTRATION ===")
        protocol = self.check_protocol_registration()
        sections.append(f"Platform: {protocol['platform']}")
        sections.append(f"Supported: {protocol['supported']}")
        sections.append(f"Registered: {protocol['registered']}")

        # Configuration
        sections.append("\n=== CONFIGURATION ===")
        config = self.check_configuration()
        sections.append(f"Config directory: {config['config_dir']}")
        sections.append(f"Config file exists: {config['config_exists']}")
        sections.append(f"Token available: {config['token_available']}")

        return "\n".join(sections)


class SystemStatusWindow(BaseWindow):
    """System Status Window GUI"""

    def __init__(self, root: tk.Tk):
        super().__init__(root, i18n.get('system_status_window_title'))
        self.checker = SystemStatusChecker()
        self.status_data = {}
        self.create_widgets()
        self.center_window(1000, 700)
        self.refresh_status()

    def create_widgets(self):
        """Create the GUI widgets"""
        # Create main frame with scrollbar
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Create notebook for tabbed interface
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill='both', expand=True)

        # Create tabs
        self.create_overview_tab()
        self.create_environment_tab()
        self.create_tools_tab()
        self.create_plugins_tab()
        self.create_protocol_tab()
        self.create_dependencies_tab()
        self.create_config_tab()
        self.create_connectivity_tab()
        self.create_report_tab()

        # Create bottom button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill='x', pady=(10, 0))

        ttk.Button(button_frame, text=i18n.get('refresh'), command=self.refresh_status).pack(side='left')
        ttk.Button(button_frame, text=i18n.get('export_report'), command=self.export_report).pack(side='left', padx=(10, 0))
        ttk.Button(button_frame, text=i18n.get('close'), command=self.on_closing).pack(side='right')

    def create_overview_tab(self):
        """Create overview tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=i18n.get('overview'))

        # Platform info
        platform_frame = ttk.LabelFrame(frame, text=i18n.get('platform_information'))
        platform_frame.pack(fill='x', padx=5, pady=5)

        self.platform_text = tk.Text(platform_frame, height=6, wrap='word')
        self.platform_text.pack(fill='x', padx=5, pady=5)

        # Quick status indicators
        status_frame = ttk.LabelFrame(frame, text=i18n.get('quick_status'))
        status_frame.pack(fill='x', padx=5, pady=5)

        self.status_labels = {}
        status_items = [
            ('python', 'Python Interpreter'),
            ('rsync', 'Rsync Tool'),
            ('ssh', 'SSH Client'),
            ('protocol', 'Protocol Registration'),
            ('config', 'Configuration'),
            ('connectivity', 'API Connectivity')
        ]

        for i, (key, label) in enumerate(status_items):
            row = i // 2
            col = i % 2

            frame_item = ttk.Frame(status_frame)
            frame_item.grid(row=row, column=col, sticky='w', padx=5, pady=2)

            self.status_labels[key] = {
                'indicator': tk.Label(frame_item, text="●", font=(FONT_FAMILY_DEFAULT, 12)),
                'label': tk.Label(frame_item, text=label, font=(FONT_FAMILY_DEFAULT, FONT_SIZE_MEDIUM))
            }

            self.status_labels[key]['indicator'].pack(side='left')
            self.status_labels[key]['label'].pack(side='left', padx=(5, 0))

    def create_environment_tab(self):
        """Create environment context tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=i18n.get('environment'))

        self.environment_text = scrolledtext.ScrolledText(frame, wrap='word')
        self.environment_text.pack(fill='both', expand=True, padx=5, pady=5)

    def create_plugins_tab(self):
        """Create plugins status tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=i18n.get('plugins'))

        self.plugins_text = scrolledtext.ScrolledText(frame, wrap='word')
        self.plugins_text.pack(fill='both', expand=True, padx=5, pady=5)

    def create_tools_tab(self):
        """Create tools status tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=i18n.get('tools'))

        # Create scrollable frame
        canvas = tk.Canvas(frame)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tools_frame = scrollable_frame

    def create_protocol_tab(self):
        """Create protocol registration tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=i18n.get('protocol'))

        # Protocol status
        protocol_frame = ttk.LabelFrame(frame, text="rediacc:// Protocol Status")
        protocol_frame.pack(fill='x', padx=5, pady=5)

        self.protocol_text = tk.Text(protocol_frame, height=10, wrap='word')
        self.protocol_text.pack(fill='both', expand=True, padx=5, pady=5)

        # Protocol actions
        actions_frame = ttk.LabelFrame(frame, text="Actions")
        actions_frame.pack(fill='x', padx=5, pady=5)

        ttk.Button(actions_frame, text=i18n.get('register_protocol'),
                  command=self.register_protocol).pack(side='left', padx=5, pady=5)
        ttk.Button(actions_frame, text=i18n.get('unregister_protocol'),
                  command=self.unregister_protocol).pack(side='left', padx=5, pady=5)
        ttk.Button(actions_frame, text=i18n.get('test_protocol'),
                  command=self.test_protocol).pack(side='left', padx=5, pady=5)

    def create_dependencies_tab(self):
        """Create dependencies tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=i18n.get('dependencies'))

        self.deps_text = scrolledtext.ScrolledText(frame, wrap='word')
        self.deps_text.pack(fill='both', expand=True, padx=5, pady=5)

    def create_config_tab(self):
        """Create configuration tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=i18n.get('configuration'))

        self.config_text = scrolledtext.ScrolledText(frame, wrap='word')
        self.config_text.pack(fill='both', expand=True, padx=5, pady=5)

    def create_connectivity_tab(self):
        """Create connectivity tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=i18n.get('connectivity'))

        self.connectivity_text = scrolledtext.ScrolledText(frame, wrap='word')
        self.connectivity_text.pack(fill='both', expand=True, padx=5, pady=5)

    def create_report_tab(self):
        """Create report export tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=i18n.get('report'))

        self.report_text = scrolledtext.ScrolledText(frame, wrap='word', font=('Courier', 9))
        self.report_text.pack(fill='both', expand=True, padx=5, pady=5)

    def refresh_status(self):
        """Refresh all status information"""
        def refresh_thread():
            try:
                # Update status data
                self.status_data = {
                    'platform': self.checker.platform_info,
                    'python': self.checker.python_info,
                    'environment': self.checker.check_environment_context(),
                    'tools': self.checker.check_core_tools(),
                    'plugins': self.checker.check_active_plugins(),
                    'protocol': self.checker.check_protocol_registration(),
                    'dependencies': self.checker.check_dependencies(),
                    'config': self.checker.check_configuration(),
                    'connectivity': self.checker.check_connectivity()
                }

                # Update GUI in main thread
                self.root.after(0, self.update_gui)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to refresh status: {e}"))

        # Run refresh in background thread
        threading.Thread(target=refresh_thread, daemon=True).start()

    def update_gui(self):
        """Update GUI with current status data"""
        self.update_overview_tab()
        self.update_environment_tab()
        self.update_tools_tab()
        self.update_plugins_tab()
        self.update_protocol_tab()
        self.update_dependencies_tab()
        self.update_config_tab()
        self.update_connectivity_tab()
        self.update_report_tab()

    def update_overview_tab(self):
        """Update overview tab"""
        # Update platform info
        platform_info = []
        for key, value in self.status_data['platform'].items():
            platform_info.append(f"{key.replace('_', ' ').title()}: {value}")

        self.platform_text.delete(1.0, tk.END)
        self.platform_text.insert(tk.END, "\n".join(platform_info))

        # Update status indicators
        statuses = {
            'python': self.status_data['python']['detected_command'] is not None,
            'rsync': self.status_data['tools']['rsync']['available'],
            'ssh': self.status_data['tools']['ssh']['available'],
            'protocol': self.status_data['protocol']['registered'],
            'config': self.status_data['config']['config_exists'],
            'connectivity': any(ep['reachable'] for ep in self.status_data['connectivity']['api_endpoints'].values())
        }

        for key, status in statuses.items():
            if key in self.status_labels:
                color = COLOR_SUCCESS if status else COLOR_ERROR
                self.status_labels[key]['indicator'].config(fg=color)

    def update_environment_tab(self):
        """Update environment context tab"""
        env_data = self.status_data['environment']

        info_lines = [i18n.get('runtime_environment_context'), ""]

        # WSL Information
        if env_data['wsl']:
            info_lines.append(f"✓ {i18n.get('running_in_wsl')} ({env_data['wsl_version']})")
        else:
            info_lines.append(f"✗ {i18n.get('not_running_in_wsl')}")

        # Container Information
        if env_data['container']:
            info_lines.append(f"✓ {i18n.get('running_in_container')} ({env_data['container_type']})")
        else:
            info_lines.append(f"✗ {i18n.get('not_running_in_container')}")

        # Virtual Environment Information
        if env_data['virtual_env']:
            info_lines.append(f"✓ {i18n.get('python_virtual_environment_active')} ({env_data['virtual_env_type']})")
        else:
            info_lines.append(f"✗ {i18n.get('no_python_virtual_environment_detected')}")

        # Virtualization Information
        if env_data['virtualization']:
            info_lines.append(f"✓ {i18n.get('running_on_virtualized_hardware')} ({env_data['virtualization_type']})")
        else:
            info_lines.append(f"✗ {i18n.get('running_on_physical_hardware')}")

        info_lines.append("")
        info_lines.append(i18n.get('environment_details'))
        for key, value in env_data.items():
            if value and key.endswith('_type'):
                continue  # Skip type fields, already shown above
            info_lines.append(f"  {key}: {value}")

        self.environment_text.delete(1.0, tk.END)
        self.environment_text.insert(tk.END, "\n".join(info_lines))

    def update_plugins_tab(self):
        """Update plugins status tab"""
        plugins_data = self.status_data['plugins']

        info_lines = [i18n.get('plugin_connections_status'), ""]

        info_lines.append(f"{i18n.get('connections_file')}: {plugins_data['connections_file_path']}")
        info_lines.append(f"{i18n.get('file_exists')}: {plugins_data['connections_file_exists']}")
        info_lines.append(f"{i18n.get('total_connections')}: {plugins_data['connection_count']}")
        info_lines.append(f"{i18n.get('active_connections')}: {len(plugins_data['active_connections'])}")
        info_lines.append(f"{i18n.get('stale_connections')}: {len(plugins_data['stale_connections'])}")

        if plugins_data.get('error'):
            info_lines.append(f"{i18n.get('error')}: {plugins_data['error']}")

        if plugins_data['active_connections']:
            info_lines.append(f"\n{i18n.get('active_plugin_connections')}")
            for conn in plugins_data['active_connections']:
                info_lines.append(f"  ✓ {conn['plugin']} (PID: {conn['pid']}, Port: {conn['local_port']})")
                info_lines.append(f"    Team: {conn['team']}, Machine: {conn['machine']}, Repository: {conn['repository']}")
                info_lines.append("")

        if plugins_data['stale_connections']:
            info_lines.append("Stale Plugin Connections:")
            for conn in plugins_data['stale_connections']:
                info_lines.append(f"  ✗ {conn['plugin']} (PID: {conn['pid']} - not running)")

        self.plugins_text.delete(1.0, tk.END)
        self.plugins_text.insert(tk.END, "\n".join(info_lines))

    def update_tools_tab(self):
        """Update tools tab"""
        # Clear existing widgets
        for widget in self.tools_frame.winfo_children():
            widget.destroy()

        tools_data = self.status_data['tools']

        for tool_name, tool_info in tools_data.items():
            # Create frame for each tool
            tool_frame = ttk.LabelFrame(self.tools_frame, text=tool_name.upper())
            tool_frame.pack(fill='x', padx=5, pady=5)

            # Status indicator
            status_color = COLOR_SUCCESS if tool_info['available'] else COLOR_ERROR
            status_text = f"✓ {i18n.get('available')}" if tool_info['available'] else f"✗ {i18n.get('not_found')}"

            status_label = tk.Label(tool_frame, text=status_text, fg=status_color,
                                  font=(FONT_FAMILY_DEFAULT, FONT_SIZE_MEDIUM, 'bold'))
            status_label.pack(anchor='w', padx=5, pady=2)

            # Tool details
            details = []
            if tool_info.get('path'):
                details.append(f"{i18n.get('path')}: {tool_info['path']}")
            if tool_info.get('version'):
                details.append(f"{i18n.get('version')}: {tool_info['version']}")
            if tool_info.get('source'):
                details.append(f"{i18n.get('source')}: {tool_info['source']}")
            if tool_info.get('error'):
                details.append(f"{i18n.get('error')}: {tool_info['error']}")

            # Add tool-specific details
            if tool_name == 'ssh':
                if tool_info.get('unix_forwarding') is not None:
                    support = "Yes" if tool_info['unix_forwarding'] else "No"
                    details.append(f"{i18n.get('unix_socket_forwarding')}: {support}")

            elif tool_name == 'docker':
                if tool_info.get('daemon_running') is not None:
                    status = i18n.get('running') if tool_info['daemon_running'] else i18n.get('not_running')
                    details.append(f"{i18n.get('docker_daemon')}: {status}")

            elif tool_name == 'vscode':
                if isinstance(tool_info, dict):
                    if tool_info.get('wsl_support'):
                        details.append(f"{i18n.get('wsl_support')}: {i18n.get('detected')}")
                    if tool_info.get('source'):
                        details.append(f"{i18n.get('detection')}: {tool_info['source']}")

            for detail in details:
                detail_label = tk.Label(tool_frame, text=detail,
                                      font=(FONT_FAMILY_DEFAULT, FONT_SIZE_SMALL))
                detail_label.pack(anchor='w', padx=20, pady=1)

    def update_protocol_tab(self):
        """Update protocol tab"""
        protocol_data = self.status_data['protocol']

        info_lines = [
            f"Platform: {protocol_data['platform']}",
            f"Protocol Supported: {protocol_data['supported']}",
            f"Protocol Registered: {protocol_data['registered']}",
            f"User Registration: {protocol_data['user_registered']}",
            f"System Registration: {protocol_data['system_registered']}"
        ]

        if protocol_data.get('error'):
            info_lines.append(f"Error: {protocol_data['error']}")

        # Add detailed information
        if protocol_data.get('details'):
            info_lines.append("\nDetailed Information:")
            for key, value in protocol_data['details'].items():
                info_lines.append(f"  {key}: {value}")

        self.protocol_text.delete(1.0, tk.END)
        self.protocol_text.insert(tk.END, "\n".join(info_lines))

    def update_dependencies_tab(self):
        """Update dependencies tab"""
        deps_data = self.status_data['dependencies']

        info_lines = [f"Platform-specific Dependencies for {self.status_data['platform']['os']}:", ""]

        for dep_name, dep_info in deps_data.items():
            status = "✓" if dep_info['available'] else "✗"
            required = " (Required)" if dep_info.get('required', False) else " (Optional)"

            info_lines.append(f"{status} {dep_name}{required}")

            if dep_info.get('path'):
                info_lines.append(f"    Path: {dep_info['path']}")
            if dep_info.get('description'):
                info_lines.append(f"    Description: {dep_info['description']}")

            info_lines.append("")

        self.deps_text.delete(1.0, tk.END)
        self.deps_text.insert(tk.END, "\n".join(info_lines))

    def update_config_tab(self):
        """Update configuration tab"""
        config_data = self.status_data['config']

        info_lines = [
            f"Configuration Directory: {config_data['config_dir']}",
            f"Config File: {config_data['config_file']}",
            f"Config Exists: {config_data['config_exists']}",
            f"Config Readable: {config_data.get('config_readable', False)}",
            f"Token Available: {config_data['token_available']}",
            f"Token Valid: {config_data['token_valid']}",
            f"CLI Tool Available: {config_data.get('cli_tool_available', False)}",
            ""
        ]

        if config_data.get('cli_tool_path'):
            info_lines.append(f"CLI Tool Path: {config_data['cli_tool_path']}")
            info_lines.append("")

        if config_data.get('env_vars'):
            info_lines.append("Environment Variables:")
            for var, value in config_data['env_vars'].items():
                info_lines.append(f"  {var}: {value}")
            info_lines.append("")

        if config_data.get('config_error'):
            info_lines.append(f"Config Error: {config_data['config_error']}")

        self.config_text.delete(1.0, tk.END)
        self.config_text.insert(tk.END, "\n".join(info_lines))

    def update_connectivity_tab(self):
        """Update connectivity tab"""
        conn_data = self.status_data['connectivity']

        info_lines = ["API Endpoints:", ""]

        for endpoint_name, endpoint_info in conn_data['api_endpoints'].items():
            status = "✓" if endpoint_info['reachable'] else "✗"
            info_lines.append(f"{status} {endpoint_name.upper()}")

            if endpoint_info.get('response_time'):
                info_lines.append(f"    Response Time: {endpoint_info['response_time']}ms")
            if endpoint_info.get('status_code'):
                info_lines.append(f"    Status Code: {endpoint_info['status_code']}")
            if endpoint_info.get('error'):
                info_lines.append(f"    Error: {endpoint_info['error']}")
            info_lines.append("")

        info_lines.append(f"Telemetry Status: {conn_data['telemetry_status']}")

        self.connectivity_text.delete(1.0, tk.END)
        self.connectivity_text.insert(tk.END, "\n".join(info_lines))

    def update_report_tab(self):
        """Update report tab"""
        report = self.checker.generate_status_report()
        self.report_text.delete(1.0, tk.END)
        self.report_text.insert(tk.END, report)

    def register_protocol(self):
        """Register the rediacc:// protocol"""
        try:
            from cli.core.protocol_handler import register_protocol
            success = register_protocol(force=True)
            if success:
                messagebox.showinfo("Success", "Protocol registered successfully!")
                self.refresh_status()
            else:
                messagebox.showerror("Error", "Failed to register protocol")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to register protocol: {e}")

    def unregister_protocol(self):
        """Unregister the rediacc:// protocol"""
        try:
            from cli.core.protocol_handler import unregister_protocol
            success = unregister_protocol()
            if success:
                messagebox.showinfo("Success", "Protocol unregistered successfully!")
                self.refresh_status()
            else:
                messagebox.showerror("Error", "Failed to unregister protocol")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to unregister protocol: {e}")

    def test_protocol(self):
        """Test the protocol registration"""
        test_url = "rediacc://test-token/test-team/test-machine/test-repository/terminal"
        messagebox.showinfo("Protocol Test",
                          f"To test the protocol, try opening this URL in your browser:\n\n{test_url}\n\n"
                          f"This should launch the Rediacc CLI terminal (if properly registered).")

    def export_report(self):
        """Export status report to file"""
        try:
            from tkinter import filedialog

            filename = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                title="Save Status Report"
            )

            if filename:
                report = self.checker.generate_status_report()
                with open(filename, 'w') as f:
                    f.write(f"Rediacc CLI System Status Report\n")
                    f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("=" * 50 + "\n\n")
                    f.write(report)

                messagebox.showinfo("Success", f"Report exported to {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export report: {e}")


def show_system_status():
    """Show the system status window"""
    root = tk.Tk()
    app = SystemStatusWindow(root)
    root.mainloop()


if __name__ == "__main__":
    show_system_status()