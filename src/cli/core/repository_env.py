#!/usr/bin/env python3
"""
Shared repository environment management module.
Provides centralized logic for calculating repository-specific environment variables.
Used by: rediacc-term, rediacc vscode, GUI integrations.
"""

import sys
from typing import Dict, Optional
from .config import get_logger, TokenManager

logger = get_logger(__name__)


def get_repository_environment(
    team: str,
    machine: str,
    repository: str,
    connection_info: Optional[Dict] = None,
    repository_paths: Optional[Dict] = None,
    repository_info: Optional[Dict] = None
) -> Dict[str, str]:
    """
    Calculate all repository-specific environment variables.

    This is the single source of truth for repository environment variables,
    following DRY principle. Used by terminal, VSCode, and other integrations.

    Args:
        team: Team name
        machine: Machine name
        repository: Repository name
        connection_info: Optional connection info dict (to avoid re-fetching)
        repository_paths: Optional repository paths dict (to avoid re-calculation)
        repository_info: Optional repository info dict (to avoid re-fetching)

    Returns:
        Dictionary of environment variable names and values
    """
    from .shared import RepositoryConnection, _get_universal_user_info

    # Use existing connection info or create new connection
    if connection_info is None or repository_paths is None or repository_info is None:
        conn = RepositoryConnection(team, machine, repository)
        conn.connect()
        connection_info = conn.connection_info
        repository_paths = conn.repository_paths
        repository_info = conn.repository_info

    # Get datastore path from connection info
    datastore_path = connection_info.get('datastore', '') if connection_info else ''

    # Get universal user info
    universal_user_name, universal_user_id, organization_id = _get_universal_user_info()

    # Get repository network ID from API
    repository_network_id = repository_info.get('repositoryNetworkId') or repository_info.get('repoNetworkId', 0) if repository_info else 0

    # Docker socket path uses renet format: /var/run/rediacc/docker-{network_id}.sock
    docker_socket = f"/var/run/rediacc/docker-{repository_network_id}.sock"
    docker_exec = f"/var/run/rediacc/docker-{repository_network_id}"
    docker_host = f"unix://{docker_socket}"
    repository_mount_path = repository_paths['mount_path']

    # Get repository network mode (defaults to bridge if not present)
    # Valid modes: bridge, host, none, overlay, ipvlan, macvlan
    repository_network_mode = repository_info.get('repositoryNetworkMode') or repository_info.get('repoNetworkMode', 'bridge') if repository_info else 'bridge'

    # Get repository tag (defaults to latest if not present)
    repository_tag = repository_info.get('repositoryTag') or repository_info.get('repoTag', 'latest') if repository_info else 'latest'

    # Build environment variables dictionary
    env_vars = {
        'DOCKER_DATA': repository_paths['docker_data'],
        'DOCKER_EXEC': docker_exec,
        'DOCKER_FOLDER': repository_paths['docker_folder'],
        'DOCKER_HOST': docker_host,
        'DOCKER_PLUGIN_DIR': '/run/docker/plugins',
        'DOCKER_SOCKET': docker_socket,
        'REDIACC_DATASTORE_USER': datastore_path,
        'REDIACC_DESKTOP': sys.executable,
        'REDIACC_IMMOVABLE': repository_paths['immovable_path'],
        'REDIACC_MACHINE': machine,
        'REDIACC_NETWORK_ID': str(repository_network_id),
        'REDIACC_REPOSITORY': repository,
        'REDIACC_TEAM': team,
        'REPOSITORY_NETWORK_ID': str(repository_network_id),
        'REPOSITORY_NETWORK_MODE': repository_network_mode,
        'REPOSITORY_PATH': repository_mount_path,
        'REPOSITORY_TAG': repository_tag,
        'SYSTEM_API_URL': TokenManager.get_api_url() or '',
        'UNIVERSAL_USER_ID': universal_user_id or '',
        'UNIVERSAL_USER_NAME': universal_user_name or '',
    }

    logger.debug(f"[get_repository_environment] Generated environment for {team}/{machine}/{repository}:")
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

    # Get universal user info (still needed for other purposes, but not for path construction)
    universal_user_name, universal_user_id, organization_id = _get_universal_user_info()

    # Datastore path is now direct (no user/organization isolation)
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
