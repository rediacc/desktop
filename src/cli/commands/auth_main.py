#!/usr/bin/env python3
"""
Rediacc CLI Auth - Authentication management (login, logout, status)
"""

import argparse
import getpass
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli._version import __version__
from cli.core.shared import colorize, add_common_arguments, error_exit, initialize_cli_command
from cli.core.config import (
    TokenManager, setup_logging, get_logger,
    is_encrypted, decrypt_string, load_config
)
from cli.core.telemetry import track_command, initialize_telemetry, shutdown_telemetry
from cli.core.api_client import client

# Load configuration
try:
    load_config()
except Exception as e:
    print(f"Configuration error: {e}", file=sys.stderr)
    sys.exit(1)

# Constants for password hashing (must match server-side)
STATIC_SALT = 'Rd!@cc111$ecur3P@$$w0rd$@lt#H@$h'

def pwd_hash(pwd: str) -> str:
    """Hash password with static salt for API authentication"""
    salted_password = pwd + STATIC_SALT
    return "0x" + hashlib.sha256(salted_password.encode()).digest().hex()

def format_output(data, format_type, message=None, error=None):
    """Format output based on requested format type"""
    if format_type in ['json', 'json-full']:
        output = {'success': error is None, 'data': data}
        if message: output['message'] = message
        if error: output['error'] = error
        return json.dumps(output, indent=2)
    return colorize(f"Error: {error}", 'RED') if error else data if data else colorize(message, 'GREEN') if message else "No data available"

def login_command(args):
    """Handle login command"""
    logger = get_logger(__name__)
    config_manager = TokenManager()
    output_format = getattr(args, 'output', 'text')

    # Check for environment variables and use them as defaults
    env_email = os.environ.get('SYSTEM_ADMIN_EMAIL')
    env_password = os.environ.get('SYSTEM_ADMIN_PASSWORD')

    # Prompt for endpoint with default
    default_endpoint = "https://www.rediacc.com/api"
    if hasattr(args, 'endpoint') and args.endpoint:
        endpoint = args.endpoint
    else:
        if output_format not in ['json', 'json-full']:
            endpoint_input = input(f"API Endpoint (default: {default_endpoint}): ").strip()
            endpoint = endpoint_input if endpoint_input else default_endpoint
        else:
            endpoint = default_endpoint

    # Normalize endpoint - ensure it ends with /api
    if not endpoint.endswith('/api'):
        if endpoint.endswith('/'):
            endpoint = endpoint + 'api'
        else:
            endpoint = endpoint + '/api'

    # Note: Endpoint will be saved to file when we call set_token_with_auth()
    # The api_client.base_url property will read it from the file automatically
    client.set_config_manager(config_manager)

    email = args.email or env_email or input("Email: ")
    password = args.password or env_password or getpass.getpass("Password: ")
    hash_pwd = pwd_hash(password)

    login_params = {'name': args.session_name or "CLI Session"}

    for attr, param in [('tfa_code', 'TFACode'), ('permissions', 'requestedPermissions'), ('expiration', 'tokenExpirationHours'), ('target', 'target')]:
        if hasattr(args, attr):
            value = getattr(args, attr)
            if value:
                login_params[param] = value

    response = client.auth_request("CreateAuthenticationRequest", email, hash_pwd, login_params)

    if response.get('error'):
        print(format_output(None, output_format, None, f"Login failed: {response['error']}"))
        return 1

    resultSets = response.get('resultSets', [])
    if not resultSets or not resultSets[0].get('data'):
        print(format_output(None, output_format, None, "Login failed: Could not get authentication token"))
        return 1

    auth_data = resultSets[0]['data'][0]
    token = auth_data.get('nextRequestToken')
    if not token:
        print(format_output(None, output_format, None, "Login failed: Invalid authentication token"))
        return 1

    is_authorized = auth_data.get('isAuthorized', True)
    authentication_status = auth_data.get('authenticationStatus', '')

    # Handle Two-Factor Authentication
    if authentication_status == 'TFA_REQUIRED' and not is_authorized:
        if not hasattr(args, 'tfa_code') or not args.tfa_code:
            if output_format not in ['json', 'json-full']:
                from cli.core.config import I18n
                i18n = I18n()
                tfa_code = input(i18n.get('enter_tfa_code'))
            else:
                print(format_output(None, output_format, None, "TFA_REQUIRED. Please provide --tfa-code parameter."))
                return 1

            login_params['TFACode'] = tfa_code
            response = client.auth_request("CreateAuthenticationRequest", email, hash_pwd, login_params)

            if response.get('error'):
                print(format_output(None, output_format, None, f"TFA verification failed: {response['error']}"))
                return 1

            resultSets = response.get('resultSets', [])
            if not resultSets or not resultSets[0].get('data'):
                print(format_output(None, output_format, None, "TFA verification failed: Could not get authentication token"))
                return 1

            auth_data = resultSets[0]['data'][0]
            token = auth_data.get('nextRequestToken')
            if not token:
                print(format_output(None, output_format, None, "TFA verification failed: Invalid authentication token"))
                return 1

    organization = auth_data.get('organizationName')
    vault_organization = auth_data.get('vaultOrganization') or auth_data.get('VaultOrganization')

    config_manager.set_token_with_auth(token, email, organization, vault_organization, endpoint)

    # Immediately fetch and update vault_organization with ORGANIZATION_ID after login
    organization_info = client.get_organization_vault()
    if organization_info:
        updated_vault = organization_info.get('vaultOrganization')
        if updated_vault:
            config_manager.set_token_with_auth(token, email, organization, updated_vault, endpoint)

    # Check if organization has vault encryption enabled
    if vault_organization and is_encrypted(vault_organization):
        # Organization requires master password
        master_password = getattr(args, 'master_password', None)
        if not master_password:
            print(colorize("Your organization requires a master password for vault encryption.", 'YELLOW'))
            master_password = getpass.getpass("Master Password: ")

        if config_manager.validate_master_password(master_password):
            config_manager.set_master_password(master_password)
            if output_format not in ['json', 'json-full']:
                print(colorize("Master password validated successfully", 'GREEN'))
        else:
            print(format_output(None, output_format, None,
                "Invalid master password. Please check with your administrator for the correct organization master password."))
            if output_format not in ['json', 'json-full']:
                print(colorize("Warning: Logged in but vault data will not be decrypted", 'YELLOW'))
    elif hasattr(args, 'master_password') and args.master_password and output_format not in ['json', 'json-full']:
        print(colorize("Note: Your organization has not enabled vault encryption. The master password will not be used.", 'YELLOW'))

    # Format output
    if output_format in ['json', 'json-full']:
        result = {
            'email': email,
            'organization': organization,
            'endpoint': endpoint,
            'vault_encryption_enabled': bool(vault_organization and is_encrypted(vault_organization)),
            'master_password_set': bool(config_manager.get_master_password())
        }
        print(format_output(result, output_format, f"Successfully logged in as {email}"))
    else:
        print(colorize(f"Successfully logged in as {email}", 'GREEN'))
        print(f"Endpoint: {endpoint}")
        if organization:
            print(f"Organization: {organization}")
        if vault_organization and is_encrypted(vault_organization):
            print(f"Vault Encryption: Enabled")
            print(f"Master Password: {'Set' if config_manager.get_master_password() else 'Not set (vault data will remain encrypted)'}")

    return 0

def logout_command(args):
    """Handle logout command"""
    logger = get_logger(__name__)
    config_manager = TokenManager()
    output_format = getattr(args, 'output', 'text')

    # Delete the user request if we have a token
    if TokenManager.get_token():
        try:
            client.token_request("DeleteUserRequest")
        except Exception as e:
            logger.debug(f"Error deleting user request: {e}")
            # Continue with logout even if API call fails

    # Clear local auth data
    config_manager.clear_auth()

    print(format_output({}, output_format, "Successfully logged out"))
    return 0

def status_command(args):
    """Show current authentication status"""
    logger = get_logger(__name__)
    output_format = getattr(args, 'output', 'text')

    auth_info = TokenManager.get_auth_info()
    token = auth_info.get('token')
    email = auth_info.get('email')
    organization = auth_info.get('organization')
    vault_organization = auth_info.get('vault_organization')

    is_authenticated = TokenManager.is_authenticated()
    has_master_password = bool(TokenManager().get_master_password())
    vault_encrypted = bool(vault_organization and is_encrypted(vault_organization))

    # Get endpoint information
    api_endpoint = client.base_url
    api_prefix = client.api_prefix
    full_endpoint = f"{api_endpoint}{api_prefix}"
    sandbox_mode = os.environ.get('REDIACC_SANDBOX_MODE', '').lower() == 'true'

    if output_format in ['json', 'json-full']:
        result = {
            'authenticated': is_authenticated,
            'email': email,
            'organization': organization,
            'token': TokenManager.mask_token(token) if token else None,
            'vault_encryption_enabled': vault_encrypted,
            'master_password_set': has_master_password,
            'api_endpoint': api_endpoint,
            'api_prefix': api_prefix,
            'full_endpoint': full_endpoint,
            'sandbox_mode': sandbox_mode
        }
        print(format_output(result, output_format, "Authentication status"))
    else:
        if is_authenticated:
            print(colorize("Authentication Status: Logged In", 'GREEN'))
            print(f"Email: {email}")
            print(f"Organization: {organization}")
            print(f"Token: {TokenManager.mask_token(token)}")
            print(f"API Endpoint: {api_endpoint}")
            print(f"Full Endpoint: {full_endpoint}")
            if sandbox_mode:
                print(colorize("Sandbox Mode: Enabled", 'YELLOW'))
            if vault_encrypted:
                print(f"Vault Encryption: Enabled")
                print(f"Master Password: {'Set' if has_master_password else 'Not Set'}")
            else:
                print(f"Vault Encryption: Disabled")
        else:
            print(colorize("Authentication Status: Not Logged In", 'YELLOW'))
            print(f"API Endpoint: {api_endpoint}")
            print(f"Full Endpoint: {full_endpoint}")
            if sandbox_mode:
                print(colorize("Sandbox Mode: Enabled", 'YELLOW'))
            print("Use 'rediacc auth login' to authenticate")

    return 0

@track_command('auth')
def main():
    """Main entry point for auth command"""
    initialize_telemetry()

    parser = argparse.ArgumentParser(
        prog='rediacc auth',
        description='Rediacc Authentication Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Login with prompts (endpoint, email, password):
    %(prog)s login

  Login with custom endpoint:
    %(prog)s login --endpoint https://custom.rediacc.com/api

  Login with email and password:
    %(prog)s login --email user@organization.com --password myPassword

  Login with TFA code:
    %(prog)s login --email user@organization.com --tfa-code 123456

  Login with master password for vault encryption:
    %(prog)s login --email user@organization.com --master-password myMasterPass

  Check authentication status:
    %(prog)s status

  Logout:
    %(prog)s logout
"""
    )

    add_common_arguments(parser, include_args=['verbose'])
    parser.add_argument('--output', '-o', choices=['text', 'json', 'json-full'], default='text',
                       help='Output format: text, json (concise), or json-full (comprehensive)')

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Login subcommand
    login_parser = subparsers.add_parser('login', help='Authenticate with Rediacc API')
    login_parser.add_argument('--endpoint', help='API endpoint URL (default: https://www.rediacc.com/api)')
    login_parser.add_argument('--email', '-e', help='Email address')
    login_parser.add_argument('--password', '-p', help='Password (will prompt if not provided)')
    login_parser.add_argument('--session-name', help='Name for this session (default: "CLI Session")')
    login_parser.add_argument('--tfa-code', help='Two-factor authentication code')
    login_parser.add_argument('--master-password', help='Master password for vault encryption')
    login_parser.add_argument('--permissions', help='Requested permissions')
    login_parser.add_argument('--expiration', type=int, help='Token expiration in hours')
    login_parser.add_argument('--target', help='Target resource (e.g., bridge name for bridge token)')
    login_parser.set_defaults(func=login_command)

    # Logout subcommand
    logout_parser = subparsers.add_parser('logout', help='Log out from Rediacc API')
    logout_parser.set_defaults(func=logout_command)

    # Status subcommand
    status_parser = subparsers.add_parser('status', help='Show current authentication status')
    status_parser.set_defaults(func=status_command)

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)
    logger = get_logger(__name__)

    if args.verbose:
        logger.debug("Rediacc CLI Auth starting up")
        logger.debug(f"Command: {args.command}")
        logger.debug(f"Arguments: {vars(args)}")

    if not args.command:
        parser.print_help()
        return 1

    # For login command, don't use initialize_cli_command since it checks auth
    # For other commands, we can use it but it won't fail on missing auth
    if args.command != 'login':
        # Initialize CLI but don't require auth for status/logout
        pass

    try:
        return args.func(args) or 0
    finally:
        shutdown_telemetry()

if __name__ == '__main__':
    sys.exit(main())
