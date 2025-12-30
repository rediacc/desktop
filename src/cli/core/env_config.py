#!/usr/bin/env python3
"""
Centralized environment configuration module for Rediacc CLI.
Handles all environment variable parsing and provides defaults.
"""

import os
import json
from typing import Tuple, Optional, Dict, Any


class EnvironmentConfig:
    """Centralized environment configuration manager"""
    
    # Default values from typical .env file
    ENV_DEFAULTS = {
        'SYSTEM_DOMAIN': 'localhost',
        'SYSTEM_ORGANIZATION_NAME': 'REDIACC.IO',
        'SYSTEM_ADMIN_EMAIL': 'admin@rediacc.io',
        'SYSTEM_ADMIN_PASSWORD': 'admin',
        'SYSTEM_DEFAULT_TEAM_NAME': 'Private Team',
        'SYSTEM_DEFAULT_REGION_NAME': 'Default Region',
        'SYSTEM_DEFAULT_BRIDGE_NAME': 'Global Bridges',
        'SYSTEM_SELF_MANAGED_BRIDGE_NAME': 'My Bridge',
        'SYSTEM_HTTP_PORT': '7322',
        'SYSTEM_SQL_PORT': '1433',
        'SYSTEM_API_URL': 'http://localhost:7322/api',
        'PUBLIC_API_URL': 'https://www.rediacc.com/api',
        'SANDBOX_API_URL': 'https://sandbox.rediacc.com/api',
        'REDIACC_BUILD_TYPE': 'DEBUG',
        'REDIACC_SANDBOX_MODE': 'false',
        'SYSTEM_BASE_IMAGE': 'ubuntu:24.04',
        'DOCKER_REGISTRY': '192.168.111.1:5000',
        'PROVISION_CEPH_CLUSTER': 'false',
        'PROVISION_KVM_MACHINES': 'true',
        'EMAIL_SERVICE_TYPE': 'EXCHANGE',
        'SYSTEM_ORGANIZATION_VAULT_DEFAULTS': '{"UNIVERSAL_USER_ID":"7111","UNIVERSAL_USER_NAME":"rediacc","PLUGINS":{},"DOCKER_JSON_CONF":{}}',
    }
    
    # Default organization vault structure
    DEFAULT_ORGANIZATION_VAULT = {
        'UNIVERSAL_USER_ID': '7111',
        'UNIVERSAL_USER_NAME': 'rediacc',
        'PLUGINS': {
            'Terminal': {
                'image': '${DOCKER_REGISTRY}/rediacc/plugin-terminal:latest',
                'active': True
            },
            'Browser': {
                'image': '${DOCKER_REGISTRY}/rediacc/plugin-browser:latest',
                'active': True
            }
        },
        'DOCKER_JSON_CONF': {
            'insecure-registries': ['${DOCKER_REGISTRY}'],
            'registry-mirrors': ['http://${DOCKER_REGISTRY}']
        }
    }
    
    @classmethod
    def get_env(cls, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get environment variable with fallback to defaults"""
        return os.environ.get(key, cls.ENV_DEFAULTS.get(key, default))
    
    @classmethod
    def get_organization_vault_defaults(cls) -> Dict[str, Any]:
        """Parse SYSTEM_ORGANIZATION_VAULT_DEFAULTS from environment or use defaults"""
        vault_json = cls.get_env('SYSTEM_ORGANIZATION_VAULT_DEFAULTS')

        if not vault_json:
            return cls.DEFAULT_ORGANIZATION_VAULT.copy()

        try:
            # Handle escaped JSON strings from shell
            if vault_json.startswith('{') and '\\' in vault_json:
                vault_json = vault_json.replace('\\"', '"').replace('\\\\', '\\')

            vault_data = json.loads(vault_json)

            # Ensure essential fields with defaults
            for key in ['UNIVERSAL_USER_ID', 'UNIVERSAL_USER_NAME']:
                vault_data.setdefault(key, cls.DEFAULT_ORGANIZATION_VAULT[key])

            # Variable substitution for ${DOCKER_REGISTRY}
            docker_registry = cls.get_env('DOCKER_REGISTRY', '192.168.111.1:5000')
            vault_str = json.dumps(vault_data).replace('${DOCKER_REGISTRY}', docker_registry)
            return json.loads(vault_str)
        except (json.JSONDecodeError, TypeError) as e:
            import sys
            print(f"Warning: Failed to parse SYSTEM_ORGANIZATION_VAULT_DEFAULTS: {e}\n"
                  f"Debug: The string was: {repr(vault_json)}", file=sys.stderr)
            return cls.DEFAULT_ORGANIZATION_VAULT.copy()
    
    @classmethod
    def get_universal_user_info(cls) -> Tuple[str, str, Optional[str]]:
        """Get universal user info from environment or defaults.
        Returns: (universal_user_name, universal_user_id, organization_id)
        """
        vault = cls.get_organization_vault_defaults()
        return (vault.get('UNIVERSAL_USER_NAME', 'rediacc'),
                vault.get('UNIVERSAL_USER_ID', '7111'),
                vault.get('ORGANIZATION_ID'))
    
    @classmethod
    def get_universal_user_name(cls) -> str:
        """Get universal user name with guaranteed fallback"""
        return cls.get_universal_user_info()[0] or 'rediacc'
    
    @classmethod
    def get_universal_user_id(cls) -> str:
        """Get universal user ID with guaranteed fallback"""
        return cls.get_universal_user_info()[1] or '7111'
    
    @classmethod
    def get_system_defaults(cls) -> Dict[str, str]:
        """Get all system default values"""
        return {key: cls.get_env(key) for key in cls.ENV_DEFAULTS}
    
    @classmethod
    def get_important_env_vars(cls) -> Dict[str, str]:
        """Get environment variables that should be exported to subprocesses"""
        important_vars = [
            'SYSTEM_API_URL', 'PUBLIC_API_URL', 'SANDBOX_API_URL',
            'REDIACC_BUILD_TYPE', 'REDIACC_SANDBOX_MODE',
            'SYSTEM_ADMIN_EMAIL', 'SYSTEM_ADMIN_PASSWORD',
            'SYSTEM_MASTER_PASSWORD', 'SYSTEM_HTTP_PORT', 'SYSTEM_ORGANIZATION_ID',
            'SYSTEM_ORGANIZATION_VAULT_DEFAULTS', 'SYSTEM_ORGANIZATION_NAME',
            'SYSTEM_DEFAULT_TEAM_NAME', 'SYSTEM_DEFAULT_REGION_NAME',
            'SYSTEM_DEFAULT_BRIDGE_NAME', 'DOCKER_REGISTRY'
        ]
        result = {}
        for var in important_vars:
            value = cls.get_env(var)
            if value:
                result[var] = value
        return result


# Convenience functions for backward compatibility
def get_universal_user_info() -> Tuple[str, str, Optional[str]]:
    """Get universal user info from environment"""
    return EnvironmentConfig.get_universal_user_info()


def get_universal_user_name() -> str:
    """Get universal user name with fallback"""
    return EnvironmentConfig.get_universal_user_name()


def get_universal_user_id() -> str:
    """Get universal user ID with fallback"""
    return EnvironmentConfig.get_universal_user_id()


def get_organization_vault_defaults() -> Dict[str, Any]:
    """Get organization vault defaults from environment"""
    return EnvironmentConfig.get_organization_vault_defaults()