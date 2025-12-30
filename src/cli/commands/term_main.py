#!/usr/bin/env python3
"""
Rediacc CLI Term - SSH terminal access to repositories and machines
"""

import argparse
import subprocess
import sys
import os
import json
import shlex
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli._version import __version__
from cli.core.shared import (
    colorize, add_common_arguments,
    error_exit, initialize_cli_command, RepositoryConnection, INTERIM_FOLDER_NAME, 
    get_ssh_key_from_vault, SSHConnection
)

from cli.core.config import setup_logging, get_logger
from cli.core.telemetry import track_command, initialize_telemetry, shutdown_telemetry
from cli.core.env_bootstrap import compose_sudo_env_command
from cli.config import TERM_CONFIG_FILE

# Load configuration
def load_config():
    """Load configuration from JSON file"""
    try:
        with open(TERM_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load config file: {e}")
        return {"terminal_commands": {}, "messages": {}, "help_text": {}}
    except UnicodeDecodeError as e:
        print(f"Warning: Config file encoding error at position {e.start}: {e}")
        print("Attempting to read with fallback encoding...")
        try:
            with open(config_path, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        except Exception as fallback_error:
            print(f"Failed to load config with fallback: {fallback_error}")
            return {"terminal_commands": {}, "messages": {}, "help_text": {}}

# Global config
CONFIG = load_config()
MESSAGES = CONFIG.get('messages', {})
def print_message(key, color='BLUE', **kwargs):
    """Print a message from config with color and formatting"""
    msg = MESSAGES.get(key, key)
    if kwargs: msg = msg.format(**kwargs)
    print(colorize(msg, color))


def get_config_value(*keys, default=''):
    """Get nested config value with default"""
    result = CONFIG
    for key in keys:
        if not isinstance(result, dict) or key not in result: return default
        result = result[key]
    return result


def connect_to_machine(args):
    print_message('connecting_machine', 'HEADER', machine=args.machine)

    from cli.core.shared import get_machine_info_with_team, get_machine_connection_info, validate_machine_accessibility, handle_ssh_exit_code

    print(MESSAGES.get('fetching_info', 'Fetching machine information...'))
    machine_info = get_machine_info_with_team(args.team, args.machine)
    connection_info = get_machine_connection_info(machine_info)
    port = connection_info.get('port', 22)
    validate_machine_accessibility(args.machine, args.team, connection_info['ip'], port)

    print(MESSAGES.get('retrieving_ssh_key', 'Retrieving SSH key...'))
    ssh_key = get_ssh_key_from_vault(args.team)
    if not ssh_key:
        error_exit(MESSAGES.get('ssh_key_not_found', 'SSH key not found').format(team=args.team))

    host_entry = connection_info.get('host_entry')

    if not host_entry:
        error_exit("Security Error: No host key found in machine vault. Contact your administrator to add the host key.")

    with SSHConnection(ssh_key, host_entry, port) as ssh_conn:
        if ssh_conn.is_using_agent:
            print_message('ssh_agent_setup', pid=ssh_conn.agent_pid)
        
        ssh_cmd = ['ssh', '-tt', *ssh_conn.ssh_opts.split(), f"{connection_info['user']}@{connection_info['ip']}"]
        universal_user = connection_info.get('universal_user', 'rediacc')
        # Datastore path is now direct (no user/organization isolation)
        datastore_path = connection_info['datastore']
        
        if args.command:
            full_command = f"sudo -u {universal_user} bash -c 'cd {datastore_path} 2>/dev/null; {args.command}'"
            ssh_cmd.append(full_command)
            print_message('executing_as_user', user=universal_user, command=args.command)
            print_message('working_directory', path=datastore_path)
        else:
            commands = CONFIG.get('machine_welcome', {}).get('commands', [])
            format_vars = {'machine': args.machine, 'ip': connection_info["ip"], 'user': connection_info["user"], 'universal_user': universal_user, 'datastore_path': datastore_path}
            welcome_lines = [cmd.format(**format_vars) for cmd in commands]
            ssh_cmd.append(f"sudo -u {universal_user} bash -c '{' && '.join(welcome_lines)}'")
            print_message('opening_terminal'); print_message('exit_instruction', 'YELLOW')

        result = subprocess.run(ssh_cmd)
        handle_ssh_exit_code(result.returncode, "machine")


def connect_to_terminal(args):
    print_message('connecting_repository', 'HEADER', repository=args.repository, machine=args.machine)

    from cli.core.shared import validate_machine_accessibility, handle_ssh_exit_code
    from cli.core.config import get_logger
    logger = get_logger(__name__)

    conn = RepositoryConnection(args.team, args.machine, args.repository); conn.connect()
    port = conn.connection_info.get('port', 22)
    validate_machine_accessibility(args.machine, args.team, conn.connection_info['ip'], port, args.repository)

    # DEBUG: Log terminal connection details
    logger.debug(f"[connect_to_terminal] Terminal connection details:")
    logger.debug(f"  - Team: {args.team}")
    logger.debug(f"  - Machine: {args.machine}")
    logger.debug(f"  - Repository: {args.repository}")
    logger.debug(f"  - repo_guid: {conn.repo_guid}")
    logger.debug(f"  - mount_path: {conn.repo_paths['mount_path']}")

    ssh_key = get_ssh_key_from_vault(args.team)
    if not ssh_key:
        error_exit(MESSAGES.get('ssh_key_not_found', 'SSH key not found').format(team=args.team))

    host_entry = conn.connection_info.get('host_entry')

    if not host_entry:
        error_exit("Security Error: No host key found in repository machine vault. Contact your administrator to add the host key.")

    with SSHConnection(ssh_key, host_entry, port) as ssh_conn:
        if ssh_conn.is_using_agent:
            print_message('ssh_agent_setup', pid=ssh_conn.agent_pid)
        # Get environment variables using shared module (DRY principle)
        from cli.core.repository_env import get_repository_environment

        env_vars = get_repository_environment(args.team, args.machine, args.repository,
                                              connection_info=conn.connection_info,
                                              repository_paths=conn.repo_paths,
                                              repository_info=conn.repo_info)

        cd_logic = get_config_value('cd_logic', 'basic')
        
        universal_user = conn.connection_info.get('universal_user', 'rediacc')
        ssh_cmd = ['ssh', '-tt', *ssh_conn.ssh_opts.split(), conn.ssh_destination]

        if args.command:
            # Simplified approach: execute command in a basic environment without complex setup
            print_message('executing_command', command=args.command)
            sudo_command = compose_sudo_env_command(
                universal_user,
                env_vars,
                [cd_logic, args.command],
                preserve_home=False,
            )
            ssh_cmd.append(sudo_command)
        else:
            # For interactive terminal, use the existing complex setup that works
            print_message('opening_terminal'); print_message('exit_instruction', 'YELLOW')
            extended_cd_logic = get_config_value('cd_logic', 'extended')
            bash_funcs = CONFIG.get('bash_functions', {})
            format_vars = {
                'repository': args.repository,
                'team': args.team,
                'machine': args.machine,
                'bridge': getattr(args, 'bridge', 'N/A')
            }
            ps1_prompt = CONFIG.get('ps1_prompt', '').format(**format_vars)
            commands = CONFIG.get('repository_welcome', {}).get('commands', [])
            welcome_lines = [cmd.format(**format_vars) for cmd in commands]
            functions = '\n\n'.join(bash_funcs.values())
            exports = 'export -f enter_container\nexport -f logs\nexport -f status\nexport -f rediacc_prompt'

            script_sections = [extended_cd_logic]
            if functions:
                script_sections.extend(['', functions])
            if exports:
                script_sections.extend(['', exports])
            if welcome_lines:
                script_sections.append('')
                script_sections.extend(welcome_lines)

            # Write rediacc_prompt function and PROMPT_COMMAND to ~/.bashrc-rediacc
            # This file is sourced at the END of ~/.bashrc, so it overrides PS1
            rediacc_prompt_func = bash_funcs.get('rediacc_prompt', '')
            bashrc_rediacc_content = f'''# Rediacc prompt configuration - auto-generated
{rediacc_prompt_func}

# Initialize direnv hook if direnv is available
if command -v direnv &> /dev/null; then
    eval "$(direnv hook bash)"
fi

export PROMPT_COMMAND='_direnv_hook 2>/dev/null; rediacc_prompt'
rediacc_prompt  # Set initial prompt
'''
            # Escape for shell and write to file
            escaped_content = bashrc_rediacc_content.replace("'", "'\"'\"'")
            script_sections.append('')
            script_sections.append(f"echo '{escaped_content}' > ~/.bashrc-rediacc")
            script_sections.append('')
            script_sections.append(f"export PS1='{ps1_prompt}'")
            script_sections.append('exec bash')

            sudo_command = compose_sudo_env_command(
                universal_user,
                env_vars,
                script_sections,
                preserve_home=False,
            )
            ssh_cmd.append(sudo_command)
        result = subprocess.run(ssh_cmd)
        handle_ssh_exit_code(result.returncode, "repository terminal")


def connect_to_container(args):
    print_message('connecting_container', 'HEADER', container=args.container, repository=args.repository, machine=args.machine)

    from cli.core.shared import validate_machine_accessibility, handle_ssh_exit_code

    conn = RepositoryConnection(args.team, args.machine, args.repository); conn.connect()
    port = conn.connection_info.get('port', 22)
    validate_machine_accessibility(args.machine, args.team, conn.connection_info['ip'], port, args.repository)

    ssh_key = get_ssh_key_from_vault(args.team)
    if not ssh_key:
        error_exit(MESSAGES.get('ssh_key_not_found', 'SSH key not found').format(team=args.team))

    host_entry = conn.connection_info.get('host_entry')

    if not host_entry:
        error_exit("Security Error: No host key found in repository machine vault. Contact your administrator to add the host key.")

    with SSHConnection(ssh_key, host_entry, port) as ssh_conn:
        if ssh_conn.is_using_agent:
            print_message('ssh_agent_setup', pid=ssh_conn.agent_pid)
        # Get environment variables using shared module (DRY principle)
        from cli.core.repository_env import get_repository_environment

        env_vars = get_repository_environment(args.team, args.machine, args.repository,
                                              connection_info=conn.connection_info,
                                              repository_paths=conn.repo_paths,
                                              repository_info=conn.repo_info)

        universal_user = conn.connection_info.get('universal_user', 'rediacc')
        ssh_cmd = ['ssh', '-tt', *ssh_conn.ssh_opts.split(), conn.ssh_destination]

        if args.command:
            # Execute command inside container
            container_command = (
                f"docker exec -it {args.container} bash -c {shlex.quote(args.command)}"
            )
            script_sections = [container_command]
            print_message('executing_container_command', container=args.container, command=args.command)
        else:
            # Interactive container access - use the same pattern as existing enter_container function
            print_message('entering_container', container=args.container)
            print_message('exit_instruction', 'YELLOW')
            script_sections = [
                f"docker exec -it {args.container} bash || docker exec -it {args.container} sh"
            ]

        sudo_command = compose_sudo_env_command(
            universal_user,
            env_vars,
            script_sections,
            preserve_home=False,
        )
        ssh_cmd.append(sudo_command)
        result = subprocess.run(ssh_cmd)
        handle_ssh_exit_code(result.returncode, "container terminal")

@track_command('term')
def main():
    # Initialize telemetry
    initialize_telemetry()

    help_config = CONFIG.get('help_text', {})
    sections = []
    
    examples = ["Examples:"]
    for example in help_config.get('examples', {}).values():
        examples.extend([f"  {example.get('title', '')}", f"    {example.get('command', '')}", ""])
    sections.append('\n'.join(examples))
    
    repo_env = help_config.get('repository_env_vars', {})
    if repo_env:
        env_section = [repo_env.get('title', ''), f"  {repo_env.get('subtitle', '')}"]
        env_section.extend(f"    {var:<15} - {desc}" for var, desc in repo_env.get('vars', {}).items())
        sections.append('\n'.join(env_section))
    
    machine_info = help_config.get('machine_only_info', {})
    if machine_info:
        machine_section = [machine_info.get('title', '')]
        machine_section.extend(f"  {point}" for point in machine_info.get('points', []))
        sections.append('\n'.join(machine_section))
    
    epilog_text = '\n\n'.join(sections)
    
    parser = argparse.ArgumentParser(
        prog='rediacc term',
        description=help_config.get('description', 'Rediacc CLI Terminal'),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog_text
    )
    # Note: --version is only available at root level (rediacc --version)
    # Add common arguments (standard order: token, team, machine, verbose)
    add_common_arguments(parser, include_args=['token', 'team', 'machine', 'verbose'])
    
    # Add repository separately since it has different requirements
    parser.add_argument('--repository', help='Target repository name (optional - if not specified, connects to machine only)')
    parser.add_argument('--container', help='Container name to connect to directly (requires --repository)')
    parser.add_argument('--command', help='Command to execute (interactive shell if not specified)')

    args = parser.parse_args()
    
    setup_logging(verbose=args.verbose)
    logger = get_logger(__name__)
    
    if args.verbose: logger.debug("Rediacc CLI Term starting up"); logger.debug(f"Arguments: {vars(args)}")
    if not (args.team and args.machine): parser.error("--team and --machine are required in CLI mode")
    if args.container and not args.repository: parser.error("--container requires --repository to be specified")
    
    initialize_cli_command(args, parser)

    try:
        if args.container:
            connect_to_container(args)
        elif args.repository:
            connect_to_terminal(args)
        else:
            connect_to_machine(args)
        return 0  # Successful completion
    except Exception as e:
        logger.error(f"Terminal operation failed: {e}")
        return 1  # Failure
    finally:
        # Shutdown telemetry
        shutdown_telemetry()

if __name__ == '__main__':
    main()
