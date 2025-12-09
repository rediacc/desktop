#!/usr/bin/env python3
"""
Dynamic Help Generator for Rediacc CLI
Automatically discovers all commands and generates comprehensive help
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any

from cli.config import CLI_CONFIG_FILE

# Get paths - simple and consistent in both dev and installed
CLI_PACKAGE_DIR = Path(__file__).parent.parent  # .../cli/core -> .../cli
COMMANDS_DIR = CLI_PACKAGE_DIR / "commands"
CONFIG_FILE = CLI_CONFIG_FILE


def get_module_description(module_path: Path) -> str:
    """Extract description from module docstring"""
    try:
        with open(module_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Look for docstring in first 10 lines
        in_docstring = False
        docstring_lines = []

        for line in lines[:15]:
            stripped = line.strip()

            if '"""' in stripped or "'''" in stripped:
                if not in_docstring:
                    in_docstring = True
                    # Get text after opening quotes
                    text = stripped.split('"""')[1] if '"""' in stripped else stripped.split("'''")[1]
                    if text and text != '"""' and text != "'''":
                        docstring_lines.append(text.strip())
                    continue
                else:
                    # Closing quotes found
                    break

            if in_docstring:
                if stripped:
                    docstring_lines.append(stripped)

        # Return first meaningful line
        for line in docstring_lines:
            if line and not line.startswith('#') and len(line) > 10:
                return line

        return ""
    except:
        return ""


def get_dedicated_commands() -> List[Dict[str, str]]:
    """Scan for dedicated command modules (*_main.py)"""
    commands = []

    # Dedicated modules we know about
    modules = {
        'sync': 'File synchronization operations',
        'term': 'Terminal access to repositories',
        'plugin': 'Plugin connection management (SSH tunnels)',
        'protocol': 'Protocol handler registration',
        'license': 'License management',
        'vscode': 'VSCode remote integration',
        'compose': 'Repository environment management',
        'workflow': 'High-level workflow automation'
    }

    for module_name, default_desc in modules.items():
        module_file = COMMANDS_DIR / f"{module_name}_main.py"
        if module_file.exists():
            # Try to extract from docstring
            desc = get_module_description(module_file)
            if not desc:
                desc = default_desc

            commands.append({
                'name': module_name,
                'description': desc
            })

    return commands


def get_api_commands() -> List[Dict[str, str]]:
    """Read API commands from cli-config.json"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)

        api_endpoints = config.get('API_ENDPOINTS', {})
        commands = []

        # Generic API command descriptions
        generic_descriptions = {
            'create': 'Create new resources',
            'list': 'List and query resources',
            'update': 'Update resource configuration',
            'rm': 'Remove resources',
            'vault': 'Manage encrypted vault data',
            'permission': 'Manage access permissions',
            'user': 'User account management',
            'team-member': 'Team membership management',
            'bridge': 'Bridge management',
            'company': 'Company administration',
            'audit': 'Audit log queries',
            'inspect': 'Inspect resource details',
            'distributed-storage': 'Ceph storage management',
            'auth': 'Authentication operations'
        }

        for cmd_name in api_endpoints.keys():
            # Skip internal/dynamic commands
            if cmd_name in ['misc', 'machine', 'clone', 'region', 'team', 'login', 'logout']:
                continue

            desc = generic_descriptions.get(cmd_name, f'{cmd_name} operations')
            commands.append({
                'name': cmd_name,
                'description': desc
            })

        return sorted(commands, key=lambda x: x['name'])
    except:
        return []


def get_cli_commands() -> List[Dict[str, str]]:
    """Read CLI commands from cli-config.json (like workflow)"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)

        cli_commands = config.get('CLI_COMMANDS', {})
        commands = []

        for cmd_name, cmd_def in cli_commands.items():
            # Skip if already in dedicated commands
            if cmd_name in ['license', 'workflow']:
                continue

            if isinstance(cmd_def, dict):
                desc = cmd_def.get('description', f'{cmd_name} commands')
                commands.append({
                    'name': cmd_name,
                    'description': desc
                })

        return commands
    except:
        return []


def get_wrapper_commands() -> List[Dict[str, str]]:
    """Return utility commands that actually work in the Python CLI"""
    return [
        {'name': 'setup', 'description': 'Install dependencies and configure environment'},
        {'name': 'version', 'description': 'Show version information'},
        {'name': 'help', 'description': 'Show this help message'},
        {'name': 'desktop', 'description': 'Launch Rediacc Desktop application'},
    ]


def get_auth_commands() -> List[Dict[str, str]]:
    """Return authentication commands"""
    return [
        {'name': 'login', 'description': 'Authenticate with Rediacc API'},
        {'name': 'logout', 'description': 'End current session'},
    ]


def generate_help_data() -> Dict[str, Any]:
    """Generate comprehensive help data"""
    dedicated = get_dedicated_commands()
    api = get_api_commands()
    cli = get_cli_commands()
    wrapper = get_wrapper_commands()
    auth = get_auth_commands()

    # Organize by category
    return {
        'core_commands': auth + dedicated,
        'management_commands': api,
        'utility_commands': wrapper
    }


def main():
    """Main entry point - output JSON"""
    help_data = generate_help_data()
    print(json.dumps(help_data, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
