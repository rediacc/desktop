#!/usr/bin/env python3
"""
Shared utilities for VS Code integration.
Used by both CLI (vscode_main.py) and GUI (main.py).

Platform Requirements:
- Windows: Windows 10+ with OpenSSH client
- macOS: macOS 10.14+ (Mojave) with OpenSSH 7.6+ for RemoteCommand support
- Linux: glibc-based distribution (not Alpine), kernel >= 3.10,
         bash, tar, curl/wget required on remote host

VS Code Installation Support:
- Windows: Standard installer, portable
- macOS: Standard .app, Homebrew (Intel/Apple Silicon)
- Linux: .deb/.rpm packages, Snap, code-oss, codium
"""

import os
import re
import json
import shutil
import stat
import platform
import subprocess

from cli.core.shared import _decode_ssh_key, _decode_host_entry, is_windows


def get_vscode_settings_path():
    """
    Get the VS Code user settings.json path based on the operating system.
    Includes WSL support for better Windows VS Code integration.
    """
    system = platform.system()

    # Check for WSL environment
    is_wsl = False
    if system == "Linux":
        try:
            if os.path.exists('/proc/version'):
                with open('/proc/version', 'r') as f:
                    is_wsl = 'microsoft' in f.read().lower()
        except (IOError, PermissionError):
            pass

    if is_wsl:
        # In WSL, try Windows user profile first for better VS Code integration
        vscode_settings_paths = []

        userprofile = os.environ.get('USERPROFILE')
        if userprofile:
            try:
                # Convert Windows path to WSL path
                wsl_path = subprocess.check_output(['wslpath', userprofile], text=True).strip()
                vscode_settings_paths.append(os.path.join(wsl_path, 'AppData', 'Roaming', 'Code', 'User', 'settings.json'))
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

        # Fallback to WSL paths
        home_dir = os.path.expanduser('~')
        vscode_settings_paths.extend([
            os.path.join(home_dir, '.vscode-server', 'data', 'Machine', 'settings.json'),
            os.path.join(home_dir, '.config', 'Code', 'User', 'settings.json'),
        ])

        # Return first path where directory exists
        for path in vscode_settings_paths:
            if os.path.exists(os.path.dirname(path)):
                return path

        # Default to first path
        return vscode_settings_paths[0] if vscode_settings_paths else os.path.expanduser('~/.config/Code/User/settings.json')

    # Non-WSL paths
    if system == "Windows":
        appdata = os.environ.get('APPDATA', os.path.expanduser('~\\AppData\\Roaming'))
        return os.path.join(appdata, 'Code', 'User', 'settings.json')
    elif system == "Darwin":  # macOS
        return os.path.expanduser('~/Library/Application Support/Code/User/settings.json')
    else:  # Linux - respect XDG Base Directory specification
        xdg_config = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        return os.path.join(xdg_config, 'Code', 'User', 'settings.json')


def get_rediacc_ssh_config_path():
    """Get the path to the rediacc-specific SSH config file."""
    return os.path.expanduser('~/.ssh/config_rediacc')


def find_vscode_executable():
    """
    Find VS Code executable on the system.
    Supports Windows, macOS, Linux, and WSL environments.
    """
    # Check environment variable first
    vscode_path = os.environ.get('REDIACC_VSCODE_PATH')
    if vscode_path:
        if os.path.exists(vscode_path):
            return vscode_path
        if shutil.which(vscode_path):
            return vscode_path

    # Detect WSL environment
    is_wsl = False
    system = platform.system().lower()
    if system == 'linux':
        try:
            if os.path.exists('/proc/version'):
                with open('/proc/version', 'r') as f:
                    is_wsl = 'microsoft' in f.read().lower()
        except (IOError, PermissionError):
            pass

    # Platform-specific candidates
    if system == 'linux':
        if is_wsl:
            # In WSL, prefer Windows VS Code for better integration
            candidates = ['code.exe', 'code', 'code-insiders', 'code-oss', 'codium']
        else:
            # Native Linux (includes Snap installation path)
            candidates = ['code', 'code-insiders', 'code-oss', 'codium', '/snap/bin/code']
    elif system == 'darwin':  # macOS
        candidates = [
            'code',
            'code-insiders',
            '/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code',
            '/usr/local/bin/code',       # Homebrew Intel Mac
            '/opt/homebrew/bin/code',    # Homebrew Apple Silicon Mac
        ]
    elif system == 'windows':
        candidates = ['code.cmd', 'code.exe', 'code', 'code-insiders']
    else:
        candidates = ['code', 'code-insiders', 'code-oss', 'codium']

    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path

    return None


def sanitize_hostname(name: str) -> str:
    """
    Sanitize name for use as SSH hostname (VS Code compatible).
    Removes invalid characters and ensures a valid hostname format.
    """
    if not name:
        return 'default'

    # Replace spaces and other invalid characters with hyphens
    # Keep only alphanumeric characters, hyphens, and dots
    sanitized = re.sub(r'[^a-zA-Z0-9.-]', '-', name)
    # Remove multiple consecutive hyphens
    sanitized = re.sub(r'-+', '-', sanitized)
    # Remove leading/trailing hyphens
    sanitized = sanitized.strip('-')
    # Ensure it's not empty
    return sanitized if sanitized else 'default'


def resolve_universal_user(connection_value: str = None, fallback_value: str = None) -> str:
    """
    Choose the sudo target user, preferring explicit connection metadata.
    Falls back to 'rediacc' if no user is specified.
    """
    for candidate in (connection_value, fallback_value, 'rediacc'):
        if candidate:
            return candidate
    return 'rediacc'


def upsert_ssh_config_entry(ssh_config_path: str, connection_name: str, ssh_config_entry: str) -> str:
    """
    Add or replace the SSH config block for a given connection.
    Returns 'added' or 'updated' to indicate the action taken.
    """
    os.makedirs(os.path.dirname(ssh_config_path), exist_ok=True)

    block = "# Rediacc VS Code connection\n" + ssh_config_entry.rstrip() + "\n\n"
    block_lines = block.splitlines(keepends=True)

    lines = []
    if os.path.exists(ssh_config_path):
        with open(ssh_config_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

    start = end = None
    for idx, line in enumerate(lines):
        if line.strip() == f"Host {connection_name}":
            start = idx
            if idx > 0 and lines[idx - 1].strip() == "# Rediacc VS Code connection":
                start = idx - 1
            end = len(lines)
            for j in range(idx + 1, len(lines)):
                if lines[j].startswith("Host "):
                    end = j
                    break
            break

    if start is not None:
        lines[start:end] = block_lines
        action = "updated"
    else:
        if lines:
            if not lines[-1].endswith('\n'):
                lines[-1] += '\n'
            if lines[-1].strip():
                lines.append('\n')
        lines.extend(block_lines)
        action = "added"

    with open(ssh_config_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    return action


def build_ssh_config_options(ssh_conn, identity_file_path: str, known_hosts_file_path: str = None) -> list:
    """
    Build SSH config options list from SSHConnection object.
    Returns a list of formatted SSH config option lines.
    """
    ssh_opts_lines = [
        f"    IdentityFile {identity_file_path}",
        "    IdentitiesOnly yes",
    ]

    if known_hosts_file_path:
        ssh_opts_lines.append(f"    UserKnownHostsFile {known_hosts_file_path}")

    if ssh_conn.ssh_opts:
        opts = ssh_conn.ssh_opts.split()
        i = 0
        while i < len(opts):
            if opts[i] == '-o' and i + 1 < len(opts):
                option = opts[i + 1]
                if '=' in option:
                    key, value = option.split('=', 1)
                    if key not in ['IdentityFile', 'UserKnownHostsFile']:
                        line = f"    {key} {value}"
                        if line not in ssh_opts_lines:
                            ssh_opts_lines.append(line)
                i += 2
            elif opts[i] == '-i':
                i += 2
            else:
                i += 1

    return ssh_opts_lines


def ensure_persistent_identity_file(team: str, machine: str, repository: str, ssh_key: str) -> str:
    """
    Persist the SSH private key for VS Code connections and return config-safe path.
    Creates a persistent key file in ~/.ssh/ with appropriate permissions.
    """
    ssh_dir = os.path.expanduser('~/.ssh')
    os.makedirs(ssh_dir, exist_ok=True)
    try:
        os.chmod(ssh_dir, 0o700)
    except (PermissionError, NotImplementedError, OSError):
        pass

    parts = [sanitize_hostname(p) for p in (team, machine) if p]
    if repository:
        parts.append(sanitize_hostname(repository))
    key_filename = f"rediacc_{'_'.join(parts)}_key"
    key_path = os.path.join(ssh_dir, key_filename)

    decoded_key = _decode_ssh_key(ssh_key)

    existing_content = None
    try:
        with open(key_path, 'r', encoding='utf-8') as existing_file:
            existing_content = existing_file.read()
    except FileNotFoundError:
        existing_content = None

    if existing_content != decoded_key:
        with open(key_path, 'w', newline='\n', encoding='utf-8') as key_file:
            key_file.write(decoded_key)

    try:
        if is_windows():
            os.chmod(key_path, stat.S_IREAD | stat.S_IWRITE)
        else:
            os.chmod(key_path, 0o600)
    except (PermissionError, NotImplementedError, OSError):
        pass

    return key_path.replace('\\', '/')


def ensure_persistent_known_hosts_file(team: str, machine: str, repository: str, host_entry: str) -> str:
    """
    Persist the host key for VS Code connections and return config-safe path.
    Creates a persistent known_hosts file in ~/.ssh/ with appropriate permissions.
    """
    ssh_dir = os.path.expanduser('~/.ssh')
    os.makedirs(ssh_dir, exist_ok=True)
    try:
        os.chmod(ssh_dir, 0o700)
    except (PermissionError, NotImplementedError, OSError):
        pass

    parts = [sanitize_hostname(p) for p in (team, machine) if p]
    if repository:
        parts.append(sanitize_hostname(repository))
    known_hosts_filename = f"rediacc_{'_'.join(parts)}_known_hosts"
    known_hosts_path = os.path.join(ssh_dir, known_hosts_filename)

    decoded_host_entry = _decode_host_entry(host_entry)

    existing_content = None
    try:
        with open(known_hosts_path, 'r', encoding='utf-8') as existing_file:
            existing_content = existing_file.read().strip()
    except FileNotFoundError:
        existing_content = None

    if existing_content != decoded_host_entry:
        with open(known_hosts_path, 'w', newline='\n', encoding='utf-8') as kh_file:
            kh_file.write(decoded_host_entry + '\n')

    try:
        os.chmod(known_hosts_path, 0o644)
    except (PermissionError, NotImplementedError, OSError):
        pass

    return known_hosts_path.replace('\\', '/')


def ensure_vscode_settings_configured(logger, connection_name: str = None, universal_user: str = None, universal_user_id: str = None, datastore_path: str = None):
    """
    Ensure VS Code settings are properly configured for rediacc.

    Configures:
    - remote.SSH.enableRemoteCommand: true (for RemoteCommand to work)
    - remote.SSH.configFile: ~/.ssh/config_rediacc (use separate config file)
    - remote.SSH.serverInstallPath: shared datastore location for VS Code server
    - remote.SSH.useLocalServer: true
    - remote.SSH.showLoginTerminal: true
    - Terminal profiles for universal user switching

    Note: We do NOT set remotePlatform when using RemoteCommand, as VS Code
    disables RemoteCommand for hosts in remotePlatform.

    Uses REDIACC_DATASTORE_USER env variable if available, otherwise falls back to
    datastore_path directly (no user isolation).

    Requirements:
    - OpenSSH 7.6+ on client for RemoteCommand support
    - Passwordless sudo on remote host for user switching
    """
    settings_path = get_vscode_settings_path()
    rediacc_config_path = get_rediacc_ssh_config_path()

    # Ensure settings directory exists
    settings_dir = os.path.dirname(settings_path)
    os.makedirs(settings_dir, exist_ok=True)

    # Read existing settings
    settings = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    settings = json.loads(content)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not read VS Code settings: {e}")
            settings = {}

    # Track if we need to update
    needs_update = False

    # Enable RemoteCommand support (required for user switching via sudo)
    if not settings.get('remote.SSH.enableRemoteCommand'):
        settings['remote.SSH.enableRemoteCommand'] = True
        needs_update = True

    # Set custom SSH config file path
    if settings.get('remote.SSH.configFile') != rediacc_config_path:
        settings['remote.SSH.configFile'] = rediacc_config_path
        needs_update = True

    # Additional settings for better VS Code remote experience
    if not settings.get('remote.SSH.useLocalServer'):
        settings['remote.SSH.useLocalServer'] = True
        needs_update = True

    if not settings.get('remote.SSH.showLoginTerminal'):
        settings['remote.SSH.showLoginTerminal'] = True
        needs_update = True

    # Configure serverInstallPath to use shared datastore location
    # This allows SCP (running as SSH user) to write to a location accessible by both users
    # The path is: {datastore} directly (VS Code automatically appends .vscode-server)
    # Use REDIACC_DATASTORE_USER env variable if available, otherwise use datastore_path directly
    if connection_name and (datastore_path or os.environ.get('REDIACC_DATASTORE_USER')):
        if 'remote.SSH.serverInstallPath' not in settings:
            settings['remote.SSH.serverInstallPath'] = {}

        # Note: Do NOT include .vscode-server - VS Code appends it automatically
        # Prefer REDIACC_DATASTORE_USER env var, fall back to datastore path directly
        vscode_server_path = os.environ.get('REDIACC_DATASTORE_USER') or datastore_path
        if settings['remote.SSH.serverInstallPath'].get(connection_name) != vscode_server_path:
            settings['remote.SSH.serverInstallPath'][connection_name] = vscode_server_path
            needs_update = True
            logger.info(f"Set serverInstallPath for {connection_name}: {vscode_server_path}")

    # IMPORTANT: Do NOT set remotePlatform for connections that use RemoteCommand
    # VS Code disables RemoteCommand when a host is in remotePlatform setting
    # If the connection is already in remotePlatform, remove it
    if connection_name and 'remote.SSH.remotePlatform' in settings:
        if connection_name in settings['remote.SSH.remotePlatform']:
            del settings['remote.SSH.remotePlatform'][connection_name]
            needs_update = True
            logger.info(f"Removed {connection_name} from remotePlatform to enable RemoteCommand")

    # Configure terminal profile for universal user
    profile_user = universal_user or universal_user_id
    if profile_user and connection_name:
        if 'terminal.integrated.profiles.linux' not in settings:
            settings['terminal.integrated.profiles.linux'] = {}

        profile_name = f"{connection_name}-{sanitize_hostname(profile_user)}"
        profile_config = {
            'path': '/bin/bash',
            'args': ['-c', f'sudo -u {profile_user} bash -l']
        }

        if settings['terminal.integrated.profiles.linux'].get(profile_name) != profile_config:
            settings['terminal.integrated.profiles.linux'][profile_name] = profile_config
            needs_update = True

    if needs_update:
        try:
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
            logger.info(f"Updated VS Code settings: enableRemoteCommand=true, configFile={rediacc_config_path}")
        except IOError as e:
            logger.warning(f"Could not update VS Code settings: {e}")
            logger.warning("Please manually configure VS Code settings")
