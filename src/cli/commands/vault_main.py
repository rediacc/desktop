#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rediacc CLI Vault Module - Vault management and encryption operations
"""

import argparse
import getpass
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

from cli.core.shared import colorize
from cli.core.api_client import client
from cli.core.config import TokenManager, setup_logging, get_logger
from cli.core.telemetry import track_command
from cli.config import CLI_CONFIG_FILE

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


# Encryption constants
ITERATIONS = 100000
SALT_SIZE = 16
IV_SIZE = 12
TAG_SIZE = 16
KEY_SIZE = 32


def derive_key(password: str, salt: bytes) -> bytes:
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("Cryptography library not available")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=salt,
        iterations=ITERATIONS,
    )
    return kdf.derive(password.encode('utf-8'))


def encrypt_string(plaintext: str, password: str) -> str:
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("Cryptography library not available")
    salt = os.urandom(SALT_SIZE)
    iv = os.urandom(IV_SIZE)
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext.encode('utf-8'), None)
    import base64
    return base64.b64encode(salt + iv + ciphertext).decode('utf-8')


def decrypt_string(ciphertext: str, password: str) -> str:
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("Cryptography library not available")
    import base64
    data = base64.b64decode(ciphertext.encode('utf-8'))
    salt = data[:SALT_SIZE]
    iv = data[SALT_SIZE:SALT_SIZE + IV_SIZE]
    encrypted_data = data[SALT_SIZE + IV_SIZE:]
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, encrypted_data, None)
    return plaintext.decode('utf-8')


def is_encrypted(value: str) -> bool:
    """Check if a value looks like it's encrypted"""
    if not value or len(value) < 40:
        return False
    try:
        import base64
        base64.b64decode(value.encode('utf-8'))
        return True
    except:
        import re
        return bool(re.match(r'^[A-Za-z0-9+/]+=*$', value) and len(value) >= 40)


def encrypt_vault_fields(obj: dict, password: str) -> dict:
    """Recursively encrypt vault fields in a dictionary"""
    if not password or not obj:
        return obj

    def encrypt_field(key: str, value: Any) -> Any:
        if 'vault' in key.lower() and isinstance(value, str) and value and not is_encrypted(value):
            try:
                return encrypt_string(value, password)
            except Exception as e:
                print(colorize(f"Warning: Failed to encrypt field {key}: {e}", 'YELLOW'))
        return value

    return {
        key: encrypt_field(key, value) if isinstance(value, str)
        else encrypt_vault_fields(value, password) if isinstance(value, dict)
        else [encrypt_vault_fields(item, password) if isinstance(item, dict) else item for item in value] if isinstance(value, list)
        else value
        for key, value in obj.items()
    }


def decrypt_vault_fields(obj: dict, password: str) -> dict:
    """Recursively decrypt vault fields in a dictionary"""
    if not password or not obj:
        return obj

    def decrypt_field(key: str, value: Any) -> Any:
        if 'vault' in key.lower() and isinstance(value, str) and value and is_encrypted(value):
            try:
                return decrypt_string(value, password)
            except Exception as e:
                print(colorize(f"Warning: Failed to decrypt field {key}: {e}", 'YELLOW'))
        return value

    return {
        key: decrypt_field(key, value) if isinstance(value, str)
        else decrypt_vault_fields(value, password) if isinstance(value, dict)
        else [decrypt_vault_fields(item, password) if isinstance(item, dict) else item for item in value] if isinstance(value, list)
        else value
        for key, value in obj.items()
    }


def format_output(data, format_type, message=None, error=None):
    """Format output based on format type"""
    if format_type in ['json', 'json-full']:
        output = {'success': error is None, 'data': data}
        if message: output['message'] = message
        if error: output['error'] = error
        return json.dumps(output, indent=2)
    return colorize(f"Error: {error}", 'RED') if error else data if data else colorize(message, 'GREEN') if message else "No data available"


def get_vault_data(args):
    """Get vault data from arguments or file"""
    if not (hasattr(args, 'vault_file') and args.vault_file):
        return getattr(args, 'vault', '{}') or '{}'
    try:
        if args.vault_file == '-':
            return json.dumps(json.loads(sys.stdin.read()))
        else:
            with open(args.vault_file, 'r', encoding='utf-8') as f:
                return json.dumps(json.load(f))
    except (IOError, json.JSONDecodeError) as e:
        print(colorize(f"Warning: Could not load vault data: {e}", 'YELLOW'))
        return '{}'


def get_vault_set_params(args, config_manager=None):
    """Build parameters for vault set command from arguments"""
    if args.file and args.file != '-':
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                vault_data = f.read()
        except IOError:
            print(colorize(f"Error: Could not read file: {args.file}", 'RED'))
            return None
    else:
        print("Enter JSON vault data (press Ctrl+D when finished):")
        vault_data = sys.stdin.read()

    try:
        json.loads(vault_data)
    except json.JSONDecodeError as e:
        print(colorize(f"Error: Invalid JSON: {str(e)}", 'RED'))
        return None

    params = {'vaultVersion': args.vault_version or 1}

    resource_mappings = {
        'team': {'teamName': args.name, 'vaultContent': vault_data},
        'machine': {'teamName': args.team, 'machineName': args.name, 'vaultContent': vault_data},
        'region': {'regionName': args.name, 'vaultContent': vault_data},
        'bridge': {'regionName': args.region, 'bridgeName': args.name, 'vaultContent': vault_data},
        'repository': {'teamName': args.team, 'repositoryName': args.name, 'repositoryTag': args.tag, 'vaultContent': vault_data},
        'storage': {'teamName': args.team, 'storageName': args.name, 'vaultContent': vault_data},
        'schedule': {'teamName': args.team, 'scheduleName': args.name, 'vaultContent': vault_data},
        'company': {'vaultContent': vault_data}
    }

    if args.resource_type in resource_mappings:
        params.update(resource_mappings[args.resource_type])

    return params


# Load CLI configuration for endpoints
CLI_CONFIG_PATH = CLI_CONFIG_FILE
try:
    with open(CLI_CONFIG_PATH, 'r', encoding='utf-8') as f:
        cli_config = json.load(f)
        API_ENDPOINTS = cli_config.get('API_ENDPOINTS', {})
except Exception as e:
    print(colorize(f"Error loading CLI configuration from {CLI_CONFIG_PATH}: {e}", 'RED'))
    sys.exit(1)


class VaultHandler:
    """Handler for vault commands"""

    def __init__(self, client_instance, config_manager, output_format='text'):
        self.client = client_instance
        self.config_manager = config_manager
        self.output_format = output_format

    def set_command(self, args):
        """Set vault data for a resource"""
        resource_type = args.resource_type
        endpoints = API_ENDPOINTS.get('vault', {}).get('set', {}).get('endpoints', {})

        if resource_type not in endpoints:
            print(format_output(None, self.output_format, None, f"Unsupported resource type: {resource_type}"))
            return 1

        params = get_vault_set_params(args, self.config_manager)
        if not params:
            return 1

        response = self.client.token_request(endpoints[resource_type], params)

        if response.get('error'):
            print(format_output(None, self.output_format, None, response['error']))
            return 1

        success_msg = f"Successfully updated {resource_type} vault"
        if self.output_format == 'json':
            result = {
                'resource_type': resource_type,
                'vault_version': params.get('vaultVersion', 1)
            }
            if resource_type != 'company':
                result['name'] = args.name
            if resource_type in ['machine', 'repository', 'storage', 'schedule']:
                result['team'] = args.team
            if resource_type == 'bridge':
                result['region'] = args.region

            print(format_output(result, self.output_format, success_msg))
        else:
            print(colorize(success_msg, 'GREEN'))
        return 0

    def set_password_command(self, args):
        """Set master password for vault encryption"""
        if not CRYPTO_AVAILABLE:
            print(format_output(None, self.output_format, None,
                "Cryptography library not available. Install with: pip install cryptography"))
            return 1

        self.client._ensure_vault_info()

        if not self.config_manager.has_vault_encryption():
            print(format_output(None, self.output_format, None,
                "Your company has not enabled vault encryption. Contact your administrator to enable it."))
            return 1

        master_password = getpass.getpass("Enter master password: ")
        confirm_password = getpass.getpass("Confirm master password: ")

        if master_password != confirm_password:
            print(format_output(None, self.output_format, None, "Passwords do not match"))
            return 1

        if self.config_manager.validate_master_password(master_password):
            self.config_manager.set_master_password(master_password)
            success_msg = "Master password set successfully"
            print(format_output({'success': True}, self.output_format, success_msg) if self.output_format == 'json'
                  else colorize(success_msg, 'GREEN'))
            return 0
        else:
            print(format_output(None, self.output_format, None,
                "Invalid master password. Please check with your administrator for the correct company master password."))
            return 1

    def clear_password_command(self, args):
        """Clear master password from memory"""
        self.config_manager.clear_master_password()
        success_msg = "Master password cleared from memory"
        print(format_output({'success': True}, self.output_format, success_msg) if self.output_format == 'json'
              else colorize(success_msg, 'GREEN'))
        return 0

    def status_command(self, args):
        """Show vault encryption status"""
        self.client._ensure_vault_info()
        vault_company = self.config_manager.get_vault_company()

        status_data = {
            'crypto_available': CRYPTO_AVAILABLE,
            'company': self.config_manager.config.get('company'),
            'vault_encryption_enabled': self.config_manager.has_vault_encryption(),
            'master_password_set': bool(self.config_manager.get_master_password()),
            'vault_company_present': bool(vault_company),
            'vault_company_encrypted': is_encrypted(vault_company) if vault_company else False
        }

        if self.output_format == 'json':
            print(format_output(status_data, self.output_format))
        else:
            print(colorize("VAULT ENCRYPTION STATUS", 'HEADER'))
            print("=" * 40)
            print(f"Cryptography Library: {'Available' if status_data['crypto_available'] else 'Not Available'}")
            print(f"Company: {status_data['company'] or 'Not set'}")
            print(f"Vault Company Data: {'Present' if status_data['vault_company_present'] else 'Not fetched'}")
            print(f"Vault Encryption: {'Required' if status_data['vault_encryption_enabled'] else 'Not Required'}")
            print(f"Master Password: {'Set' if status_data['master_password_set'] else 'Not Set'}")

            if not status_data['crypto_available']:
                print("\n" + colorize("To enable vault encryption, install the cryptography library:", 'YELLOW'))
                print("  pip install cryptography")
            elif status_data['vault_encryption_enabled'] and not status_data['master_password_set']:
                print("\n" + colorize("Your company requires a master password for vault encryption.", 'YELLOW'))
                print("Use 'rediacc vault set-password' to set it.")
            elif not status_data['vault_company_present']:
                print("\n" + colorize("Note: Vault company information will be fetched on next command.", 'BLUE'))

        return 0


def add_common_arguments(parser):
    """Add common arguments to parser"""
    parser.add_argument('--output', choices=['text', 'json', 'json-full'], default='text',
                       help='Output format (default: text)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose output')


@track_command('vault')
def main():
    """Main entry point for vault commands"""
    parser = argparse.ArgumentParser(
        description='Rediacc Vault Management - Manage vault data and encryption',
        prog='rediacc vault'
    )

    add_common_arguments(parser)

    subparsers = parser.add_subparsers(dest='subcommand', help='Vault subcommands')
    subparsers.required = True

    # Set subcommand
    set_parser = subparsers.add_parser('set', help='Set vault data for a resource')
    set_parser.add_argument('resource_type', choices=['team', 'machine', 'region', 'bridge', 'repository', 'storage', 'schedule', 'company'],
                           help='Resource type to set vault data for')
    set_parser.add_argument('--name', help='Resource name (not needed for company)')
    set_parser.add_argument('--team', help='Team name (for machine, repository, storage, schedule)')
    set_parser.add_argument('--region', help='Region name (for bridge)')
    set_parser.add_argument('--file', help='File containing JSON vault data (use - for stdin)')
    set_parser.add_argument('--vault-version', type=int, default=1, help='Vault version (default: 1)')

    # Set password subcommand
    set_password_parser = subparsers.add_parser('set-password', help='Set master password for vault encryption')

    # Clear password subcommand
    clear_password_parser = subparsers.add_parser('clear-password', help='Clear master password from memory')

    # Status subcommand
    status_parser = subparsers.add_parser('status', help='Show vault encryption status')

    args = parser.parse_args()

    # Initialize logging
    if args.verbose:
        os.environ['REDIACC_VERBOSE'] = '1'
    setup_logging(verbose=args.verbose)

    # Initialize token manager
    token_mgr = TokenManager()
    token_mgr.load_vault_info_from_config()

    # Client is a singleton - just use it directly
    client_instance = client

    # Create handler
    handler = VaultHandler(client_instance, token_mgr, args.output)

    # Route to appropriate command
    if args.subcommand == 'set':
        return handler.set_command(args)
    elif args.subcommand == 'set-password':
        return handler.set_password_command(args)
    elif args.subcommand == 'clear-password':
        return handler.clear_password_command(args)
    elif args.subcommand == 'status':
        return handler.status_command(args)
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
