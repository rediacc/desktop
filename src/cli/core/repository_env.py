#!/usr/bin/env python3
"""
Shared repository environment management module.
Provides centralized logic for calculating repository-specific environment variables.
Used by: rediacc-term, rediacc vscode, GUI integrations.
"""

import sys
from typing import Dict, Optional
from .config import get_logger

logger = get_logger(__name__)


def get_repository_environment(
    team: str,
    machine: str,
    repo: str,
    connection_info: Optional[Dict] = None,
    repo_paths: Optional[Dict] = None,
    repo_info: Optional[Dict] = None
) -> Dict[str, str]:
    """
    Calculate all repository-specific environment variables.

    This is the single source of truth for repository environment variables,
    following DRY principle. Used by terminal, VSCode, and other integrations.

    Args:
        team: Team name
        machine: Machine name
        repo: Repository name
        connection_info: Optional connection info dict (to avoid re-fetching)
        repo_paths: Optional repository paths dict (to avoid re-calculation)
        repo_info: Optional repository info dict (to avoid re-fetching)

    Returns:
        Dictionary of environment variable names and values
    """
    from .shared import RepositoryConnection, _get_universal_user_info

    # Use existing connection info or create new connection
    if connection_info is None or repo_paths is None or repo_info is None:
        conn = RepositoryConnection(team, machine, repo)
        conn.connect()
        repo_paths = conn.repo_paths
        repo_info = conn.repo_info

    # Get universal user info
    universal_user_name, universal_user_id, company_id = _get_universal_user_info()

    # Calculate Docker socket path and host
    docker_socket = repo_paths['docker_socket']
    docker_host = f"unix://{docker_socket}"
    repo_mount_path = repo_paths['mount_path']

    # Get repository network ID (defaults to 0 if not present)
    # Note: API returns 'repoNetworkId' as an integer
    repo_network_id = repo_info.get('repoNetworkId', 0) if repo_info else 0

    # Get repository network mode (defaults to bridge if not present)
    # Valid modes: bridge, host, none, overlay, ipvlan, macvlan
    repo_network_mode = repo_info.get('repoNetworkMode', 'bridge') if repo_info else 'bridge'

    # Get repository tag (defaults to latest if not present)
    repo_tag = repo_info.get('repoTag', 'latest') if repo_info else 'latest'

    # Build environment variables dictionary
    env_vars = {
        'REPO_PATH': repo_mount_path,
        'DOCKER_HOST': docker_host,
        'DOCKER_FOLDER': repo_paths['docker_folder'],
        'DOCKER_SOCKET': docker_socket,
        'DOCKER_DATA': repo_paths['docker_data'],
        'DOCKER_EXEC': repo_paths['docker_exec'],
        'REDIACC_IMMOVABLE': repo_paths['immovable_path'],
        'REPO_NETWORK_ID': str(repo_network_id),
        'REPO_NETWORK_MODE': repo_network_mode,
        'REPO_TAG': repo_tag,
        'REDIACC_REPO': repo,
        'REDIACC_TEAM': team,
        'REDIACC_MACHINE': machine,
        'REDIACC_DESKTOP': sys.executable,
        'UNIVERSAL_USER_NAME': universal_user_name or '',
        'UNIVERSAL_USER_ID': universal_user_id or '',
    }

    logger.debug(f"[get_repository_environment] Generated environment for {team}/{machine}/{repo}:")
    for key, value in env_vars.items():
        logger.debug(f"  {key}={value}")

    return env_vars


def get_machine_environment(
    team: str,
    machine: str,
    connection_info: Optional[Dict] = None
) -> Dict[str, str]:
    """
    Calculate machine-specific environment variables (no repository).

    Args:
        team: Team name
        machine: Machine name
        connection_info: Optional connection info dict (to avoid re-fetching)

    Returns:
        Dictionary of environment variable names and values
    """
    from .shared import get_machine_info_with_team, get_machine_connection_info, _get_universal_user_info

    # Get connection info if not provided
    if connection_info is None:
        machine_info = get_machine_info_with_team(team, machine)
        connection_info = get_machine_connection_info(machine_info)

    # Get universal user info
    universal_user_name, universal_user_id, company_id = _get_universal_user_info()

    # Calculate datastore path
    if universal_user_id:
        datastore_path = f"{connection_info['datastore']}/{universal_user_id}"
    else:
        datastore_path = connection_info['datastore']

    # Build environment variables dictionary
    env_vars = {
        'REDIACC_TEAM': team,
        'REDIACC_MACHINE': machine,
        'REDIACC_DESKTOP': sys.executable,
        'REDIACC_DATASTORE': datastore_path,
    }

    logger.debug(f"[get_machine_environment] Generated environment for {team}/{machine}:")
    for key, value in env_vars.items():
        logger.debug(f"  {key}={value}")

    return env_vars


def format_bash_exports(env_vars: Dict[str, str]) -> str:
    """
    Format environment variables as bash export statements.

    Args:
        env_vars: Dictionary of environment variable names and values

    Returns:
        String containing bash export statements
    """
    exports = []
    for key, value in env_vars.items():
        # Escape single quotes in value
        escaped_value = value.replace("'", "'\"'\"'")
        exports.append(f"export {key}='{escaped_value}'")

    return '\n'.join(exports)


def format_ssh_setenv(env_vars: Dict[str, str]) -> str:
    """
    Format environment variables as SSH SetEnv directives.

    Args:
        env_vars: Dictionary of environment variable names and values

    Returns:
        String containing SSH config SetEnv lines
    """
    setenv_lines = []
    for key, value in env_vars.items():
        # Quote the value if it contains spaces
        if ' ' in value:
            setenv_lines.append(f'    SetEnv {key}="{value}"')
        else:
            setenv_lines.append(f'    SetEnv {key}={value}')

    return '\n'.join(setenv_lines)
