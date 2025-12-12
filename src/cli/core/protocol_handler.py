#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows Protocol Handler for rediacc:// URLs
Provides Windows registry management and URL parsing for browser integration
"""

import os
import sys
import re
import subprocess
import urllib.parse
import platform
import time
import shutil
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

from .shared import is_windows
from .config import get_logger, get_config_file

logger = get_logger(__name__)

class ProtocolHandlerError(Exception):
    """Protocol handler specific errors"""
    pass

def display_protocol_error_with_wait(error_message: str, wait_seconds: int = 30):
    """Display error message with countdown for protocol handler calls"""
    print("\n" + "="*60, file=sys.stderr)
    print("REDIACC PROTOCOL HANDLER ERROR", file=sys.stderr)
    print("="*60, file=sys.stderr)
    print(f"\nError: {error_message}\n", file=sys.stderr)
    print("This window will close automatically in 30 seconds.", file=sys.stderr)
    print("You can close it manually or wait for the countdown.\n", file=sys.stderr)
    print("For help, visit: https://docs.rediacc.com/cli/troubleshooting", file=sys.stderr)
    print("="*60, file=sys.stderr)

    # Countdown with overwrite
    for i in range(wait_seconds, 0, -1):
        print(f"\rClosing in {i:2d} seconds... (Press Ctrl+C to close immediately)", end="", file=sys.stderr)
        sys.stderr.flush()
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            print("\n\nClosed by user.", file=sys.stderr)
            break

    print("\n", file=sys.stderr)

def get_platform() -> str:
    """Get the current platform (windows, linux, macos)"""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    elif system == "linux":
        return "linux"
    elif system == "windows":
        return "windows"
    else:
        return "unknown"

def get_platform_handler(platform_name: str = None):
    """Get the appropriate protocol handler for the current platform"""
    if platform_name is None:
        platform_name = get_platform()
    
    if platform_name == "windows":
        return WindowsProtocolHandler()
    elif platform_name == "linux":
        from .linux_protocol_handler import LinuxProtocolHandler
        return LinuxProtocolHandler()
    elif platform_name == "macos":
        from .macos_protocol_handler import MacOSProtocolHandler
        return MacOSProtocolHandler()
    else:
        raise ProtocolHandlerError(f"Unsupported platform: {platform_name}")

def is_protocol_supported() -> bool:
    """Check if protocol registration is supported on the current platform"""
    return get_platform() in ["windows", "linux", "macos"]

class WindowsProtocolHandler:
    """Handles Windows registry operations for rediacc:// protocol"""

    PROTOCOL_SCHEME = "rediacc"
    SYSTEM_REGISTRY_ROOT = r"HKEY_CLASSES_ROOT"
    USER_REGISTRY_ROOT = r"HKEY_CURRENT_USER\Software\Classes"

    def __init__(self, test_mode: bool = False):
        """
        Initialize Windows Protocol Handler

        Args:
            test_mode: If True, skip platform check (for testing on non-Windows platforms)
        """
        if not test_mode and not is_windows():
            raise ProtocolHandlerError("Windows Protocol Handler can only be used on Windows")

    def register(self, cli_path: str = None, force: bool = False, system_wide: bool = False) -> bool:
        """Compatibility method for tests - calls register_protocol()"""
        return self.register_protocol(force=force, system_wide=system_wide)

    def get_registry_root(self, system_wide: bool = False) -> str:
        """Get the appropriate registry root based on system_wide parameter"""
        return self.SYSTEM_REGISTRY_ROOT if system_wide else self.USER_REGISTRY_ROOT
    
    def get_registry_key(self, system_wide: bool = False) -> str:
        """Get the main registry key for the protocol"""
        return f"{self.get_registry_root(system_wide)}\\{self.PROTOCOL_SCHEME}"
    
    def get_command_key(self, system_wide: bool = False) -> str:
        """Get the command registry key for the protocol"""
        return f"{self.get_registry_key(system_wide)}\\shell\\open\\command"
    
    # Legacy properties for backward compatibility
    @property
    def registry_key(self) -> str:
        """Get the main registry key for the protocol (system-wide)"""
        return self.get_registry_key(system_wide=True)
    
    @property
    def command_key(self) -> str:
        """Get the command registry key for the protocol (system-wide)"""
        return self.get_command_key(system_wide=True)
    
    def get_python_executable(self) -> str:
        """Get the current Python executable path"""
        return sys.executable
    
    def get_rediacc_executable_path(self) -> Optional[str]:
        """
        Get the path to the rediacc.exe executable.
        Works for both traditional Python installs and Windows Store Python.
        """
        try:
            # Method 1: Try to find rediacc.exe in Scripts directory relative to current Python
            python_exe = sys.executable
            python_dir = Path(python_exe).parent
            
            # For traditional Python installations
            scripts_dir = python_dir / "Scripts"
            rediacc_exe = scripts_dir / "rediacc.exe"
            
            if rediacc_exe.exists():
                return str(rediacc_exe)
            
            # For Windows Store Python installations
            # Path structure: ...\PythonSoftwareFoundation.Python.X.Y_...\LocalCache\local-packages\PythonXYZ\Scripts
            if "Microsoft\\WindowsApps" in str(python_dir) or "Packages\\PythonSoftwareFoundation" in str(python_dir):
                # This is likely Windows Store Python
                # Try to find the LocalCache\local-packages\PythonXYZ\Scripts directory
                current_path = python_dir
                while current_path.parent != current_path:  # Stop at root
                    local_cache = current_path / "LocalCache" / "local-packages"
                    if local_cache.exists():
                        # Find PythonXYZ directory
                        for python_ver_dir in local_cache.glob("Python*"):
                            scripts_dir = python_ver_dir / "Scripts"
                            rediacc_exe = scripts_dir / "rediacc.exe"
                            if rediacc_exe.exists():
                                return str(rediacc_exe)
                    current_path = current_path.parent
            
            # Method 2: Try using shutil.which to find rediacc.exe in PATH
            rediacc_in_path = shutil.which("rediacc")
            if rediacc_in_path and rediacc_in_path.endswith(".exe"):
                return rediacc_in_path
            
            # Method 3: Try to use pip to locate the installed scripts
            try:
                import subprocess
                result = subprocess.run([
                    python_exe, "-m", "pip", "show", "-f", "rediacc"
                ], capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    # Parse the output to find the Scripts directory
                    for line in result.stdout.splitlines():
                        if line.strip().startswith("Location:"):
                            location = line.split(":", 1)[1].strip()
                            # The Scripts directory should be at the same level as site-packages
                            site_packages = Path(location)
                            scripts_dir = site_packages.parent / "Scripts"
                            rediacc_exe = scripts_dir / "rediacc.exe"
                            if rediacc_exe.exists():
                                return str(rediacc_exe)
                            
                            # For Windows Store Python, try the alternate path
                            if "local-packages" in str(site_packages):
                                scripts_dir = site_packages.parent / "Scripts"
                                rediacc_exe = scripts_dir / "rediacc.exe"
                                if rediacc_exe.exists():
                                    return str(rediacc_exe)
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
                logger.debug(f"Failed to use pip show to locate rediacc.exe: {e}")
            
            # Method 4: Try to find based on this module's location
            try:
                # Get the site-packages directory containing this module
                this_file = Path(__file__)
                site_packages = None
                
                # Walk up to find site-packages
                current = this_file.parent
                while current.parent != current:
                    if current.name == "site-packages":
                        site_packages = current
                        break
                    current = current.parent
                
                if site_packages:
                    # Try Scripts directory at same level as site-packages
                    scripts_dir = site_packages.parent / "Scripts"
                    rediacc_exe = scripts_dir / "rediacc.exe"
                    if rediacc_exe.exists():
                        return str(rediacc_exe)
            except Exception as e:
                logger.debug(f"Failed to locate rediacc.exe via module path: {e}")
            
            logger.warning("Could not locate rediacc.exe executable")
            return None
            
        except Exception as e:
            logger.error(f"Error finding rediacc executable: {e}")
            return None
    
    def get_cli_script_path(self) -> str:
        """Get the path to the CLI main script"""
        # Try to find the CLI script in the package
        cli_module = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cli_script = os.path.join(cli_module, "commands", "cli_main.py")
        
        if os.path.exists(cli_script):
            return cli_script
        
        # Fallback: try to use the module import path
        try:
            import cli.commands.cli_main
            return cli.commands.cli_main.__file__
        except ImportError:
            pass
        
        # Last resort: use the current file's relative path
        current_dir = Path(__file__).parent.parent
        return str(current_dir / "commands" / "cli_main.py")
    
    def get_protocol_command(self) -> str:
        """Get the command string for protocol handling"""
        # Try to get the rediacc.exe path first (preferred method)
        rediacc_exe = self.get_rediacc_executable_path()
        
        if rediacc_exe:
            # Use the rediacc.exe directly for protocol handling
            return f'"{rediacc_exe}" protocol run "%1"'
        else:
            # Fallback to Python + script method (original behavior)
            logger.warning("Could not locate rediacc.exe, falling back to Python script method")
            python_exe = self.get_python_executable()
            
            # Find the wrapper script (rediacc.py)
            # Go up from src/cli/core to get to the CLI root directory
            cli_dir = Path(__file__).parent.parent.parent.parent
            wrapper_script = cli_dir / "rediacc.py"
            
            if wrapper_script.exists():
                # Always use the wrapper script for consistency
                return f'"{python_exe}" "{wrapper_script}" protocol run "%1"'
            else:
                # If wrapper doesn't exist, try to find it relative to the installed package
                # This handles cases where the package is installed via pip
                import cli
                cli_package_dir = Path(cli.__file__).parent.parent
                wrapper_script = cli_package_dir / "rediacc.py"
                
                if wrapper_script.exists():
                    return f'"{python_exe}" "{wrapper_script}" protocol run "%1"'
                else:
                    # Last resort: assume rediacc.py is in the current working directory
                    # or accessible via PATH
                    return f'"{python_exe}" rediacc.py protocol run "%1"'
    
    def check_admin_privileges(self) -> bool:
        """Check if running with administrator privileges"""
        try:
            # Try to access a system registry key
            result = subprocess.run([
                "reg", "query", "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion",
                "/v", "ProgramFilesDir"
            ], capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def is_protocol_registered(self, system_wide: bool = False) -> bool:
        """Check if the rediacc protocol is already registered"""
        try:
            registry_key = self.get_registry_key(system_wide)
            result = subprocess.run([
                "reg", "query", registry_key
            ], capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def register_protocol(self, force: bool = False, system_wide: bool = False) -> bool:
        """Register the rediacc:// protocol in Windows registry"""
        if not force and self.is_protocol_registered(system_wide):
            logger.info(f"Protocol already registered ({'system-wide' if system_wide else 'user-level'})")
            return True
        
        # Only check admin privileges for system-wide registration
        if system_wide and not self.check_admin_privileges():
            raise ProtocolHandlerError(
                "Administrator privileges required for system-wide protocol registration. "
                "Please run PowerShell as Administrator and try again, or use user-level registration."
            )
        
        try:
            # Get the appropriate registry keys based on system_wide
            registry_key = self.get_registry_key(system_wide)
            command_key = self.get_command_key(system_wide)
            
            # Create main protocol key with friendly display name
            result1 = subprocess.run([
                "reg", "add", registry_key,
                "/ve", "/d", "URL:Rediacc Desktop",
                "/f"
            ], capture_output=True, text=True, timeout=30)
            
            # Add URL Protocol value
            result2 = subprocess.run([
                "reg", "add", registry_key,
                "/v", "URL Protocol",
                "/t", "REG_SZ",
                "/d", "",
                "/f"
            ], capture_output=True, text=True, timeout=30)

            # Add friendly type name for better Windows display
            result3 = subprocess.run([
                "reg", "add", registry_key,
                "/v", "FriendlyTypeName",
                "/t", "REG_SZ",
                "/d", "Rediacc Desktop",
                "/f"
            ], capture_output=True, text=True, timeout=30)

            # Create command key with protocol handler
            command = self.get_protocol_command()
            result4 = subprocess.run([
                "reg", "add", command_key,
                "/ve", "/d", command,
                "/f"
            ], capture_output=True, text=True, timeout=30)

            # Check if all operations succeeded
            success = all(r.returncode == 0 for r in [result1, result2, result3, result4])
            
            if success:
                logger.info(f"Successfully registered {self.PROTOCOL_SCHEME}:// protocol")
                return True
            else:
                error_msgs = []
                for i, result in enumerate([result1, result2, result3, result4], 1):
                    if result.returncode != 0:
                        error_msgs.append(f"Step {i}: {result.stderr.strip()}")

                raise ProtocolHandlerError(f"Registry operations failed: {'; '.join(error_msgs)}")
        
        except subprocess.TimeoutExpired:
            raise ProtocolHandlerError("Registry operation timed out")
        except FileNotFoundError:
            raise ProtocolHandlerError("Registry command not found (reg.exe)")
    
    def unregister_protocol(self, system_wide: bool = False) -> bool:
        """Unregister the rediacc:// protocol from Windows registry"""
        if not self.is_protocol_registered(system_wide):
            logger.info(f"Protocol not registered ({'system-wide' if system_wide else 'user-level'})")
            return True
        
        # Only check admin privileges for system-wide unregistration
        if system_wide and not self.check_admin_privileges():
            raise ProtocolHandlerError(
                "Administrator privileges required for system-wide protocol unregistration. "
                "Please run PowerShell as Administrator and try again, or use user-level unregistration."
            )
        
        try:
            # Remove the entire protocol key tree
            registry_key = self.get_registry_key(system_wide)
            result = subprocess.run([
                "reg", "delete", registry_key,
                "/f"
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                logger.info(f"Successfully unregistered {self.PROTOCOL_SCHEME}:// protocol")
                return True
            else:
                raise ProtocolHandlerError(f"Failed to delete registry key: {result.stderr.strip()}")
        
        except subprocess.TimeoutExpired:
            raise ProtocolHandlerError("Registry operation timed out")
        except FileNotFoundError:
            raise ProtocolHandlerError("Registry command not found (reg.exe)")
    
    def get_protocol_status(self, system_wide: bool = False) -> Dict[str, Any]:
        """Get detailed status of protocol registration"""
        is_registered = self.is_protocol_registered(system_wide)
        rediacc_exe_path = self.get_rediacc_executable_path()

        status = {
            "registered": is_registered,
            "admin_privileges": self.check_admin_privileges(),
            "command": None,
            "python_executable": self.get_python_executable(),
            "rediacc_executable": rediacc_exe_path,
            "cli_script": self.get_cli_script_path(),
            "expected_command": self.get_protocol_command(),
            "registry_location": "system-wide" if system_wide else "user-level"
        }

        if is_registered:
            # Try to get the current command
            try:
                command_key = self.get_command_key(system_wide)
                result = subprocess.run([
                    "reg", "query", command_key,
                    "/ve"
                ], capture_output=True, text=True, timeout=10)

                if result.returncode == 0:
                    # Parse the output to extract the command
                    for line in result.stdout.splitlines():
                        if "(Default)" in line:
                            # Extract command after "REG_SZ"
                            parts = line.split("REG_SZ", 1)
                            if len(parts) > 1:
                                status["command"] = parts[1].strip()
                            break
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return status

class ProtocolUrlParser:
    """Parse and handle rediacc:// protocol URLs"""
    
    VALID_ACTIONS = {"sync", "terminal", "plugin", "browser", "desktop", "vscode"}
    PROTOCOL_SCHEME = "rediacc"
    
    def __init__(self):
        pass
    
    def parse_url(self, url: str) -> Dict[str, Any]:
        """Parse a rediacc:// URL into components"""
        if not url.startswith(f"{self.PROTOCOL_SCHEME}://"):
            raise ValueError(f"Invalid protocol scheme. Expected {self.PROTOCOL_SCHEME}://")
        
        try:
            parsed = urllib.parse.urlparse(url)

            # Extract path components and handle two possible formats:
            # Format 1: rediacc://token/team/machine/repository[/action]
            # Format 2: rediacc://hostname/team/machine/repository[/action] (where hostname is token)

            path_parts = [p for p in parsed.path.split('/') if p]

            # Check if token is in hostname (netloc) or path
            if parsed.netloc and len(path_parts) >= 2:
                # Format 2: token in hostname, path has team/machine[/repository][/action]
                token = parsed.netloc.replace('\n', '').replace('\r', '')
                team = urllib.parse.unquote(path_parts[0])
                machine = urllib.parse.unquote(path_parts[1])

                # Check if we have repository or action next
                if len(path_parts) >= 3:
                    # Could be repository or action
                    third_part = path_parts[2]
                    if third_part in self.VALID_ACTIONS:
                        # Third part is action, no repository
                        repository = ""
                        action_index = 2
                    else:
                        # Third part is repository
                        repository = urllib.parse.unquote(third_part)
                        action_index = 3
                else:
                    # Only team/machine provided
                    repository = ""
                    action_index = 2

            elif len(path_parts) >= 3:
                # Format 1: token/team/machine[/repository][/action] in path
                token = urllib.parse.unquote(path_parts[0]).replace('\n', '').replace('\r', '')
                team = urllib.parse.unquote(path_parts[1])
                machine = urllib.parse.unquote(path_parts[2])

                # Check if we have repository or action next
                if len(path_parts) >= 4:
                    # Could be repository or action
                    fourth_part = path_parts[3]
                    if fourth_part in self.VALID_ACTIONS:
                        # Fourth part is action, no repository
                        repository = ""
                        action_index = 3
                    else:
                        # Fourth part is repository
                        repository = urllib.parse.unquote(fourth_part)
                        action_index = 4
                else:
                    # Only token/team/machine provided
                    repository = ""
                    action_index = 3
            else:
                raise ValueError("URL must contain at least token, team, and machine")

            result = {
                "protocol": self.PROTOCOL_SCHEME,
                "token": token,
                "team": team,
                "machine": machine,
                "repository": repository,
                "action": None,
                "params": {}
            }
            
            # Extract action if present
            if len(path_parts) > action_index:
                action = path_parts[action_index].lower()
                if action in self.VALID_ACTIONS:
                    result["action"] = action
                else:
                    raise ValueError(f"Invalid action '{action}'. Must be one of: {', '.join(self.VALID_ACTIONS)}")
            
            # Parse query parameters
            if parsed.query:
                query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                # Convert lists to single values (take first occurrence)
                result["params"] = {k: v[0] if v else "" for k, v in query_params.items()}
            
            return result
        
        except Exception as e:
            raise ValueError(f"Failed to parse URL '{url}': {str(e)}")
    
    def build_cli_command(self, parsed_url: Dict[str, Any]) -> List[str]:
        """Build CLI command from parsed URL"""
        token = parsed_url["token"]
        team = parsed_url["team"]
        machine = parsed_url["machine"]
        repository = parsed_url["repository"]
        action = parsed_url["action"]
        params = parsed_url["params"]
        
        if not action:
            # Default to desktop action if no action specified (opens desktop app with team/machine/repository selection)
            action = "desktop"
            parsed_url["action"] = action  # Update the parsed URL so it's consistent
            logger.info(f"No action specified in URL, defaulting to desktop action")
        
        # Build base command based on action
        if action == "sync":
            cmd = ["sync"]
            
            # Add sync-specific parameters
            direction = params.get("direction", "download")
            if direction not in ["upload", "download"]:
                raise ValueError(f"Invalid sync direction: {direction}")
            
            cmd.append(direction)
            cmd.extend(["--token", token, "--team", team, "--machine", machine, "--repository", repository])
            
            # Optional sync parameters
            if "localPath" in params:
                cmd.extend(["--local", params["localPath"]])
            if "mirror" in params and params["mirror"].lower() in ["true", "yes", "1"]:
                cmd.append("--mirror")
            if "verify" in params and params["verify"].lower() in ["true", "yes", "1"]:
                cmd.append("--verify")
            if "preview" in params and params["preview"].lower() in ["true", "yes", "1"]:
                cmd.append("--preview")
        
        elif action == "terminal":
            cmd = ["term"]
            cmd.extend(["--token", token, "--team", team, "--machine", machine, "--repository", repository])

            # Optional terminal parameters
            if "command" in params:
                cmd.extend(["--command", params["command"]])
            if "terminalType" in params:
                if params["terminalType"] == "machine":
                    # Connect to machine directly instead of repository
                    cmd = ["term", "--token", token, "--team", team, "--machine", machine]
                elif params["terminalType"] == "container":
                    # Container-specific terminal operations
                    if "containerId" in params:
                        container_id = params["containerId"]
                        container_action = params.get("action", "terminal")

                        if container_action == "logs":
                            # View container logs
                            lines = params.get("lines", "100")
                            follow = params.get("follow", "false").lower() in ["true", "yes", "1"]
                            container_cmd = f"docker logs --tail {lines}"
                            if follow:
                                container_cmd += " -f"
                            container_cmd += f" {container_id}"
                            cmd.extend(["--command", container_cmd])
                        elif container_action == "stats":
                            # View container stats
                            cmd.extend(["--command", f"docker stats {container_id}"])
                        else:
                            # Execute shell in container
                            shell = params.get("shell", "bash")
                            cmd.extend(["--command", f"docker exec -it {container_id} {shell}"])
        
        elif action == "plugin":
            # Plugin action might need different handling
            cmd = ["plugin"]
            cmd.extend(["--token", token, "--team", team, "--machine", machine, "--repository", repository])
            
            if "name" in params:
                cmd.extend(["--plugin", params["name"]])
            if "port" in params:
                cmd.extend(["--port", params["port"]])
        
        elif action == "desktop":
            # Desktop action - opens desktop app with optional preselected values
            cmd = ["desktop"]
            cmd.extend(["--token", token, "--team", team, "--machine", machine])
            # Only add repository if it's provided and not empty
            if repository and repository.strip():
                cmd.extend(["--repository", repository])
            # Add container parameters if present
            if "containerId" in params:
                cmd.extend(["--container-id", params["containerId"]])
            if "containerName" in params:
                cmd.extend(["--container-name", params["containerName"]])

        elif action == "browser":
            # File browser action - use desktop application
            cmd = ["desktop"]  # Use the desktop application for file browsing
            cmd.extend(["--token", token, "--team", team, "--machine", machine, "--repository", repository])

            if "path" in params:
                cmd.extend(["--path", params["path"]])

        elif action == "vscode":
            # VSCode action - launches VSCode with SSH remote connection
            cmd = ["vscode"]
            cmd.extend(["--token", token, "--team", team, "--machine", machine])
            # Only add repository if it's provided and not empty
            if repository and repository.strip():
                cmd.extend(["--repository", repository])
            # Optional path parameter for specific directory
            if "path" in params:
                cmd.extend(["--path", params["path"]])

        else:
            raise ValueError(f"Unsupported action: {action}")
        
        return cmd

def handle_protocol_url(url: str, is_protocol_call: bool = False) -> int:
    """Handle a protocol URL by parsing and executing the appropriate CLI command

    Args:
        url: The rediacc:// URL to handle
        is_protocol_call: True if this is called from Windows protocol handler registry
    """
    try:
        logger.info(f"Handling protocol URL: {url}")

        parser = ProtocolUrlParser()
        parsed = parser.parse_url(url)

        logger.debug(f"Parsed URL components: {parsed}")

        # Extract and set API URL if provided in query parameters
        api_url = parsed.get('params', {}).get('apiUrl')
        if api_url:
            try:
                import json
                from pathlib import Path

                # Get config file path
                config_file = get_config_file('config.json')

                # Load existing config
                config_data = {}
                if config_file.exists():
                    with open(config_file, 'r') as f:
                        try:
                            config_data = json.load(f)
                        except json.JSONDecodeError:
                            logger.warning("Failed to parse existing config file, will create new one")
                            config_data = {}

                # Update API URL in config
                config_data['api_url'] = api_url

                # Save updated config
                with open(config_file, 'w') as f:
                    json.dump(config_data, f, indent=2)

                # Also set environment variable for current session
                os.environ['SYSTEM_API_URL'] = api_url

                logger.info(f"Updated API URL from protocol: {api_url}")
            except Exception as e:
                logger.error(f"Failed to set API URL from protocol: {e}")
                if is_protocol_call:
                    display_protocol_error_with_wait(f"Failed to configure API URL: {e}")
                    return 1
        else:
            logger.debug("No apiUrl parameter in protocol URL, using configured API URL")

        cmd_args = parser.build_cli_command(parsed)
        logger.info(f"Executing command: {cmd_args}")

        # Store the token in config file for proper rotation before executing commands
        token = parsed.get("token")
        if token:
            try:
                from .config import TokenManager
                if TokenManager.validate_token(token):
                    TokenManager.set_token(token)
                    logger.debug(f"Token stored in config for rotation: {token[:8]}...")
                else:
                    logger.warning(f"Invalid token format received from protocol URL")
                    if is_protocol_call:
                        display_protocol_error_with_wait("Invalid token format in protocol URL")
                        return 1
            except Exception as e:
                logger.error(f"Failed to store token from protocol URL: {e}")
                if is_protocol_call:
                    display_protocol_error_with_wait(f"Token storage error: {e}")
                    return 1

        # Execute the appropriate CLI tool based on the action
        action = parsed.get("action")

        # Save original argv
        original_argv = sys.argv[:]

        exit_code = 0
        command_error = None

        try:
            if action == "sync":
                # Import and call sync_main directly
                try:
                    try:
                        from ..commands import sync_main
                    except ImportError:
                        # Fallback for when relative imports don't work
                        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'commands'))
                        import sync_main
                    
                    sys.argv = ["rediacc-sync"] + cmd_args[1:]
                    exit_code = sync_main.main()
                except ImportError as e:
                    logger.error(f"Failed to import sync module: {e}")
                    command_error = f"Failed to import sync module: {e}"
                    exit_code = 1
                except SystemExit as e:
                    exit_code = e.code if e.code is not None else 1

            elif action == "terminal":
                # Check if we're running in a terminal (command line) or not (browser protocol call)
                has_terminal = sys.stdin.isatty() and sys.stdout.isatty()

                if not has_terminal and is_protocol_call:
                    # Called from browser without terminal - launch in new terminal window
                    try:
                        from .config import TerminalDetector, get_cli_root
                        import shlex

                        # Build the rediacc command with proper quoting for shell
                        # Arguments with spaces (like team names) need to be quoted
                        rediacc_cmd = ' '.join(shlex.quote(arg) for arg in cmd_args)
                        logger.info(f"Launching terminal for command: {rediacc_cmd}")

                        # Detect best terminal
                        detector = TerminalDetector()
                        method = detector.detect()

                        if not method:
                            logger.error("No working terminal emulator found")
                            command_error = "No working terminal emulator found on your system"
                            exit_code = 1
                        else:
                            # Get launch function
                            launch_func = detector.get_launch_function(method)
                            if launch_func:
                                cli_dir = str(get_cli_root())
                                logger.info(f"Launching terminal with method '{method}': {rediacc_cmd}")
                                launch_func(cli_dir, rediacc_cmd, "Rediacc Terminal")
                                exit_code = 0
                                logger.info("Terminal launched successfully")
                            else:
                                logger.error(f"Launch function not found for method: {method}")
                                command_error = f"Failed to get launch function for terminal method: {method}"
                                exit_code = 1
                    except Exception as e:
                        logger.error(f"Failed to launch terminal: {e}", exc_info=True)
                        command_error = f"Failed to launch terminal: {e}"
                        exit_code = 1
                else:
                    # Running in terminal (command line call) - execute directly
                    try:
                        # Disable bytecode writing to avoid permission issues in installed packages
                        dont_write_bytecode = sys.dont_write_bytecode
                        sys.dont_write_bytecode = True

                        try:
                            from ..commands import term_main
                        except ImportError:
                            # Fallback for when relative imports don't work
                            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'commands'))
                            import term_main
                        finally:
                            sys.dont_write_bytecode = dont_write_bytecode

                        sys.argv = ["rediacc-term"] + cmd_args[1:]
                        exit_code = term_main.main()
                    except ImportError as e:
                        logger.error(f"Failed to import term module: {e}")
                        command_error = f"Failed to import term module: {e}"
                        exit_code = 1
                    except SystemExit as e:
                        exit_code = e.code if e.code is not None else 1

            elif action == "vscode":
                # Import and call vscode_main directly
                try:
                    # Disable bytecode writing to avoid permission issues in installed packages
                    dont_write_bytecode = sys.dont_write_bytecode
                    sys.dont_write_bytecode = True

                    try:
                        from ..commands import vscode_main
                    except ImportError:
                        # Fallback for when relative imports don't work
                        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'commands'))
                        import vscode_main
                    finally:
                        sys.dont_write_bytecode = dont_write_bytecode

                    sys.argv = ["rediacc-vscode"] + cmd_args[1:]
                    exit_code = vscode_main.main()
                except ImportError as e:
                    logger.error(f"Failed to import vscode module: {e}")
                    command_error = f"Failed to import vscode module: {e}"
                    exit_code = 1
                except SystemExit as e:
                    exit_code = e.code if e.code is not None else 1

            elif action in ["plugin", "browser"]:
                # Import and call cli_main directly
                try:
                    # Disable bytecode writing to avoid permission issues in installed packages
                    dont_write_bytecode = sys.dont_write_bytecode
                    sys.dont_write_bytecode = True

                    try:
                        from ..commands import cli_main
                    except ImportError:
                        # Fallback for when relative imports don't work
                        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'commands'))
                        import cli_main
                    finally:
                        sys.dont_write_bytecode = dont_write_bytecode

                    sys.argv = ["rediacc"] + cmd_args
                    exit_code = cli_main.main()
                except ImportError as e:
                    logger.error(f"Failed to import CLI module: {e}")
                    command_error = f"Failed to import CLI module: {e}"
                    exit_code = 1
                except SystemExit as e:
                    exit_code = e.code if e.code is not None else 1

            elif action == "desktop":
                # Import and call desktop GUI directly
                try:
                    # Disable bytecode writing to avoid permission issues in installed packages
                    dont_write_bytecode = sys.dont_write_bytecode
                    sys.dont_write_bytecode = True

                    try:
                        from ..gui.main import launch_gui
                    except ImportError:
                        # Fallback for when relative imports don't work
                        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gui'))
                        from main import launch_gui
                    finally:
                        sys.dont_write_bytecode = dont_write_bytecode

                    # Pass arguments to desktop GUI for preselection
                    sys.argv = ["rediacc-desktop"] + cmd_args[1:]
                    launch_gui()  # This function calls sys.exit() internally
                    exit_code = 0  # Should not reach here normally
                except ImportError as e:
                    logger.error(f"Failed to import desktop GUI module: {e}")
                    command_error = f"Failed to import desktop GUI module: {e}"
                    exit_code = 1
                except SystemExit as e:
                    exit_code = e.code if e.code is not None else 0

            else:
                raise ValueError(f"Unsupported action: {action}")

        finally:
            # Restore original argv
            sys.argv = original_argv

        # Check if downstream command failed and we're in protocol call mode
        if is_protocol_call and exit_code != 0:
            if command_error:
                error_message = command_error
            else:
                # Create a more descriptive error message based on the action and exit code
                action_name = action.capitalize() if action else "Command"
                if exit_code == 1:
                    error_message = f"{action_name} operation failed - this may be due to invalid credentials, network issues, or missing permissions"
                else:
                    error_message = f"{action_name} operation failed with exit code {exit_code}"

            logger.error(f"Protocol handler downstream command failed: {error_message}")
            display_protocol_error_with_wait(error_message)

        return exit_code

    except Exception as e:
        logger.error(f"Protocol handler error: {e}")
        error_msg = f"Error handling protocol URL: {e}"

        if is_protocol_call:
            # Show user-friendly error with wait when called from protocol handler
            display_protocol_error_with_wait(str(e))
        else:
            # Normal CLI usage - just print error
            print(error_msg, file=sys.stderr)

        return 1

def register_protocol(force: bool = False, system_wide: bool = False) -> bool:
    """Register the rediacc:// protocol (cross-platform)"""
    if not is_protocol_supported():
        platform_name = get_platform()
        raise ProtocolHandlerError(f"Protocol registration is not supported on {platform_name}")
    
    try:
        handler = get_platform_handler()
        
        # Handle different function signatures across platforms
        if hasattr(handler, 'register_protocol'):
            # Check if the handler supports system_wide parameter
            import inspect
            sig = inspect.signature(handler.register_protocol)
            if 'system_wide' in sig.parameters:
                return handler.register_protocol(force=force, system_wide=system_wide)
            else:
                return handler.register_protocol(force=force)
        else:
            raise ProtocolHandlerError("Handler does not support protocol registration")
    
    except ImportError as e:
        raise ProtocolHandlerError(f"Failed to import platform handler: {e}")

def unregister_protocol(system_wide: bool = False) -> bool:
    """Unregister the rediacc:// protocol (cross-platform)"""
    if not is_protocol_supported():
        platform_name = get_platform()
        raise ProtocolHandlerError(f"Protocol unregistration is not supported on {platform_name}")
    
    try:
        handler = get_platform_handler()
        
        # Handle different function signatures across platforms
        if hasattr(handler, 'unregister_protocol'):
            # Check if the handler supports system_wide parameter
            import inspect
            sig = inspect.signature(handler.unregister_protocol)
            if 'system_wide' in sig.parameters:
                return handler.unregister_protocol(system_wide=system_wide)
            else:
                return handler.unregister_protocol()
        else:
            raise ProtocolHandlerError("Handler does not support protocol unregistration")
    
    except ImportError as e:
        raise ProtocolHandlerError(f"Failed to import platform handler: {e}")

def get_protocol_status(system_wide: bool = False) -> Dict[str, Any]:
    """Get protocol registration status (cross-platform)"""
    platform_name = get_platform()

    base_status = {
        "platform": platform_name,
        "supported": is_protocol_supported()
    }

    if not is_protocol_supported():
        base_status.update({
            "registered": False,
            "user_registered": False,
            "system_registered": False,
            "message": f"Protocol registration is not supported on {platform_name}"
        })
        return base_status

    try:
        handler = get_platform_handler()

        if hasattr(handler, 'get_protocol_status'):
            # Check if the handler supports system_wide parameter
            import inspect
            sig = inspect.signature(handler.get_protocol_status)
            if 'system_wide' in sig.parameters:
                # Platform handler supports system_wide parameter
                user_status = handler.get_protocol_status(system_wide=False)
                system_status = handler.get_protocol_status(system_wide=True)

                # Merge with base status and map to expected format
                base_status.update(user_status)
                base_status["user_registered"] = user_status.get("registered", False)
                base_status["system_registered"] = system_status.get("registered", False)
                base_status["registered"] = base_status["user_registered"] or base_status["system_registered"]
            else:
                # Platform handler doesn't support system_wide parameter
                status = handler.get_protocol_status()
                base_status.update(status)
                # For platforms that don't distinguish between user/system, treat as user-level
                is_registered = status.get("registered", False)
                base_status["user_registered"] = is_registered
                base_status["system_registered"] = False
                base_status["registered"] = is_registered

            return base_status
        else:
            base_status.update({
                "registered": False,
                "user_registered": False,
                "system_registered": False,
                "message": "Handler does not support status checking"
            })
            return base_status

    except ImportError as e:
        base_status.update({
            "registered": False,
            "user_registered": False,
            "system_registered": False,
            "error": f"Failed to import platform handler: {e}"
        })
        return base_status
    except Exception as e:
        base_status.update({
            "registered": False,
            "user_registered": False,
            "system_registered": False,
            "error": f"Error checking protocol status: {e}"
        })
        return base_status

def get_install_instructions() -> List[str]:
    """Get platform-specific installation instructions"""
    platform_name = get_platform()
    
    if not is_protocol_supported():
        return [
            f"Protocol registration is not supported on {platform_name}",
            "Supported platforms: Windows, Linux, macOS"
        ]
    
    try:
        handler = get_platform_handler()
        
        if hasattr(handler, 'get_install_instructions'):
            return handler.get_install_instructions()
        else:
            # Generic instructions based on platform
            if platform_name == "windows":
                return [
                    "Register protocol using batch file:",
                    "  rediacc.bat protocol register",
                    "  # or for system-wide:",
                    "  rediacc.bat protocol register --system-wide"
                ]
            elif platform_name == "linux":
                return [
                    "Install xdg-utils if not available:",
                    "  sudo apt install xdg-utils  # Ubuntu/Debian",
                    "  sudo dnf install xdg-utils  # Fedora/RHEL",
                    "",
                    "Register protocol:",
                    "  ./rediacc --register-protocol"
                ]
            elif platform_name == "macos":
                return [
                    "Optional: Install duti for enhanced support:",
                    "  brew install duti",
                    "",
                    "Register protocol:",
                    "  ./rediacc --register-protocol"
                ]
    
    except Exception as e:
        return [
            f"Error getting instructions for {platform_name}: {e}",
            "",
            "Generic instructions:",
            "  ./rediacc --register-protocol"
        ]
    
    return ["No specific instructions available"]