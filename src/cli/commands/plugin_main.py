#!/usr/bin/env python3
"""
Rediacc CLI Plugin - Plugin management for repositories
"""

import argparse
import os
import subprocess
import sys
import json
import signal
import socket
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli._version import __version__
from cli.core.shared import (
    colorize,
    add_common_arguments,
    error_exit,
    initialize_cli_command,
    RepositoryConnection,
    SSHTunnelConnection,
    is_windows,
    safe_error_message,
    get_ssh_key_from_vault
)

from cli.core.config import (
    get_config_dir, get_plugin_connections_file, get_ssh_control_dir
)
from cli.core.telemetry import track_command, initialize_telemetry, shutdown_telemetry

LOCAL_CONFIG_DIR = get_config_dir()
CONNECTIONS_FILE = str(get_plugin_connections_file())
DEFAULT_PORT_RANGE = (7111, 9111)
SSH_CONTROL_DIR = str(get_ssh_control_dir())

def ensure_directories():
    for directory in [os.path.dirname(CONNECTIONS_FILE), SSH_CONTROL_DIR]:
        os.makedirs(directory, exist_ok=True)

def load_connections() -> Dict[str, Any]:
    try:
        with open(CONNECTIONS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_connections(connections: Dict[str, Any]):
    ensure_directories()
    with open(CONNECTIONS_FILE, 'w') as f:
        json.dump(connections, f, indent=2)

def is_port_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('localhost', port)); return True
    except OSError: return False

def find_available_port(start: int = DEFAULT_PORT_RANGE[0], end: int = DEFAULT_PORT_RANGE[1]) -> Optional[int]:
    return next((port for port in range(start, end + 1) if is_port_available(port)), None)

def is_process_running(pid: int) -> bool:
    try: os.kill(pid, 0); return True
    except OSError: return False

def clean_stale_connections():
    connections = load_connections()
    active_connections = {}
    for conn_id, conn_info in connections.items():
        pid = conn_info.get('ssh_pid')
        if pid and is_process_running(pid):
            active_connections[conn_id] = conn_info
    
    stale_connections = set(connections) - set(active_connections)
    if stale_connections:
        for conn_id in stale_connections:
            print(colorize(f"Cleaning up stale connection: {conn_id}", 'YELLOW'))
        save_connections(active_connections)

def generate_connection_id(team: str, machine: str, repository: str, plugin: str) -> str:
    from hashlib import md5
    data = f"{team}:{machine}:{repository}:{plugin}:{time.time()}"
    return md5(data.encode()).hexdigest()[:8]

def list_plugins(args):
    print(colorize(f"Listing plugins for repository '{args.repository}' on machine '{args.machine}'...", 'HEADER'))
    
    conn = RepositoryConnection(args.team, args.machine, args.repository); conn.connect()

    with conn.ssh_context() as ssh_conn:
        universal_user = conn.connection_info.get('universal_user', 'rediacc')
        
        # Use the new plugin_socket_dir for listing sockets
        plugin_socket_dir = conn.repo_paths.get('plugin_socket_dir', conn.repo_paths['mount_path'])
        ssh_cmd = ['ssh', *ssh_conn.ssh_opts.split(), conn.ssh_destination,
                   f"sudo -u {universal_user} bash -c 'cd {plugin_socket_dir} && ls -la *.sock 2>/dev/null || true'"]
        
        result = subprocess.run(ssh_cmd, capture_output=True, text=True)
        
        if result.returncode == 0 and result.stdout.strip():
            print(colorize("\nAvailable plugins:", 'BLUE'))
            print(colorize("=" * 60, 'BLUE'))
            
            plugins = []
            for line in result.stdout.strip().split('\n'):
                parts = line.split()
                if '.sock' in line and parts and len(parts) >= 9:
                    socket_file = parts[-1]
                    plugin_name = socket_file.replace('.sock', '')
                    plugins.append(plugin_name)
                    print(f"  • {colorize(plugin_name, 'GREEN')} ({socket_file})")
            
            if not plugins: print(colorize("  No plugin sockets found", 'YELLOW'))
            else:
                print(colorize("\nPlugin container status:", 'BLUE'))
                docker_cmd = f"sudo -u {universal_user} bash -c 'export DOCKER_HOST=\"unix://{conn.repo_paths['docker_socket']}\" && docker ps --format \"table {{{{.Names}}}}\\t{{{{.Image}}}}\\t{{{{.Status}}}}\" | grep plugin || true'"
                
                ssh_cmd = ['ssh', *ssh_conn.ssh_opts.split(), conn.ssh_destination, docker_cmd]
                
                docker_result = subprocess.run(ssh_cmd, capture_output=True, text=True)
                if docker_result.returncode == 0 and docker_result.stdout.strip():
                    print(docker_result.stdout.strip())
                else:
                    print(colorize("  No plugin containers running", 'YELLOW'))
                
                connections = load_connections()
                active_for_repo = [conn_info for conn_info in connections.values() if all([conn_info.get('team') == args.team, conn_info.get('machine') == args.machine, conn_info.get('repository') == args.repository])]
                
                if active_for_repo:
                    print(colorize("\nActive local connections:", 'BLUE'))
                    for conn_info in active_for_repo:
                        print(f"  • {conn_info['plugin']} → localhost:{conn_info['local_port']}")
        else:
            print(colorize("No plugins found or repository not accessible", 'YELLOW'))
            if result.stderr:
                print(colorize(f"Error: {safe_error_message(result.stderr)}", 'RED'))

def connect_plugin(args):
    print(colorize(f"Connecting to plugin '{args.plugin}' in repository '{args.repository}'...", 'HEADER'))
    
    clean_stale_connections()
    
    connections = load_connections()
    existing_conn = next(
        ((conn_id, conn_info) for conn_id, conn_info in connections.items()
         if all([
             conn_info.get('team') == args.team,
             conn_info.get('machine') == args.machine,
             conn_info.get('repository') == args.repository,
             conn_info.get('plugin') == args.plugin
         ])),
        None
    )
    
    if existing_conn:
        conn_id, conn_info = existing_conn
        print(colorize(f"Plugin already connected on port {conn_info['local_port']}", 'YELLOW'))
        print(f"Connection ID: {conn_id}")
        return
    
    if args.port:
        if not is_port_available(args.port): 
            error_exit(f"Port {args.port} is not available")
        local_port = args.port
    else:
        local_port = find_available_port()
        if not local_port:
            error_exit("No available ports in range 7111-9111")
    
    conn = RepositoryConnection(args.team, args.machine, args.repository); conn.connect()

    # Get SSH key for tunnel connection
    ssh_key = get_ssh_key_from_vault(args.team)
    if not ssh_key:
        error_exit(f"SSH key not found for team '{args.team}'")

    # Use SSHTunnelConnection for persistent tunnels
    host_entry = conn.connection_info.get('host_entry')
    if not host_entry:
        error_exit("Security Error: No host key found in machine vault. Contact your administrator to add the host key.")
    ssh_tunnel_conn = SSHTunnelConnection(ssh_key, host_entry)
    ssh_tunnel_conn.__enter__()  # Setup connection
    ssh_tunnel_conn.disable_auto_cleanup()  # Prevent auto cleanup for persistent tunnel
    
    try:
        # Verify plugin socket exists
        universal_user = conn.connection_info.get('universal_user', 'rediacc')
        plugin_socket_dir = conn.repo_paths.get('plugin_socket_dir', conn.repo_paths['mount_path'])
        socket_path = f"{plugin_socket_dir}/{args.plugin}.sock"
        
        check_cmd = ['ssh', *ssh_tunnel_conn.ssh_opts.split(), conn.ssh_destination,
                     f"sudo -u {universal_user} test -S {socket_path} && echo 'exists' || echo 'not found'"]
        
        result = subprocess.run(check_cmd, capture_output=True, text=True)
        if result.returncode != 0 or 'not found' in result.stdout:
            print(colorize(f"Plugin socket '{args.plugin}.sock' not found", 'RED'))
            print("Use 'list' command to see available plugins")
            sys.exit(1)
        
        # Generate connection ID
        conn_id = generate_connection_id(args.team, args.machine, args.repository, args.plugin)
        control_path = os.path.join(SSH_CONTROL_DIR, f"plugin-{conn_id}")
        
        def check_ssh_unix_support() -> bool:
            result = subprocess.run(['ssh', '-V'], capture_output=True, text=True)
            ssh_version_output = (result.stdout + result.stderr).lower()
            if 'openssh' not in ssh_version_output: return False
            try:
                import re
                match = re.search(r'openssh[_\s]+(\d+)\.(\d+)', ssh_version_output)
                if match:
                    major, minor = map(int, match.groups())
                    return major > 6 or (major == 6 and minor >= 7)
            except: return False
            return False
        
        supports_unix_forwarding = check_ssh_unix_support()
        
        if supports_unix_forwarding:
            # Use native Unix socket forwarding
            ssh_tunnel_cmd = [
                'ssh', '-N', '-f',
                '-o', 'ControlMaster=auto',
                '-o', f'ControlPath={control_path}',
                '-o', 'ControlPersist=10m',
                '-o', 'ExitOnForwardFailure=yes',
                '-L', f'localhost:{local_port}:{socket_path}',
                *ssh_tunnel_conn.ssh_opts.split(),
                conn.ssh_destination,
            ]
            
            print(f"Establishing tunnel on port {local_port} (using native Unix socket forwarding)...")
            
            # Start SSH tunnel
            result = subprocess.run(ssh_tunnel_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(colorize(f"Failed to establish tunnel: {safe_error_message(result.stderr)}", 'RED'))
                ssh_tunnel_conn.manual_cleanup()
                sys.exit(1)
            
            def get_ssh_pid(control_path: str) -> Optional[int]:
                try:
                    result = subprocess.run(['ssh', '-O', 'check', '-o', f'ControlPath={control_path}', 'dummy'], capture_output=True, text=True)
                    if 'pid=' in result.stderr: return int(result.stderr.split('pid=')[1].split()[0].rstrip(')'))
                except: return None
                return None
            
            ssh_pid = get_ssh_pid(control_path)
            process = type('Process', (), {'pid': ssh_pid})()
        else:
            # Fallback: Use socat if available
            # First, check if socat is available on remote
            check_socat_cmd = ['ssh', *ssh_tunnel_conn.ssh_opts.split(), conn.ssh_destination,
                              "which socat >/dev/null 2>&1 && echo 'available' || echo 'missing'"]
            
            socat_check = subprocess.run(check_socat_cmd, capture_output=True, text=True)
            if 'missing' in socat_check.stdout:
                print(colorize("Error: Your SSH client doesn't support Unix socket forwarding", 'RED'))
                print("Please upgrade to OpenSSH 6.7+ or install socat on the remote machine")
                ssh_tunnel_conn.manual_cleanup()
                sys.exit(1)
            
            # Build SSH command with remote socat forwarding
            ssh_tunnel_cmd = [
                'ssh', '-N',
                '-L', f'{local_port}:localhost:{local_port}',
                '-o', 'ControlMaster=auto',
                '-o', f'ControlPath={control_path}',
                '-o', 'ControlPersist=10m',
                *ssh_tunnel_conn.ssh_opts.split(),
                conn.ssh_destination,
                f"sudo -u {universal_user} socat TCP-LISTEN:{local_port},bind=localhost,reuseaddr,fork UNIX-CONNECT:{socket_path}"
            ]
            
            print(f"Establishing tunnel on port {local_port} (using socat bridge)...")
            
            # Start SSH tunnel in background
            process = subprocess.Popen(ssh_tunnel_cmd, 
                                     stdout=subprocess.PIPE, 
                                     stderr=subprocess.PIPE)
            
            # Give it a moment to establish
            time.sleep(2)
            
            # Check if process is still running
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                print(colorize(f"Failed to establish tunnel: {safe_error_message(stderr.decode())}", 'RED'))
                ssh_tunnel_conn.manual_cleanup()
                sys.exit(1)
        
        # Save connection info
        connection_info = {
            'connection_id': conn_id,
            'team': args.team,
            'machine': args.machine,
            'repository': args.repository,
            'plugin': args.plugin,
            'local_port': local_port,
            'ssh_pid': process.pid,
            'control_path': control_path,
            'ssh_key_file': ssh_tunnel_conn.ssh_key_file,
            'known_hosts_file': ssh_tunnel_conn.known_hosts_file,
            'created_at': datetime.now().isoformat()
        }
        
        connections = load_connections()
        connections[conn_id] = connection_info
        save_connections(connections)
        
        print(colorize(f"\n✓ Plugin '{args.plugin}' connected successfully!", 'GREEN'))
        print(colorize("=" * 60, 'BLUE'))
        print(f"Connection ID: {colorize(conn_id, 'YELLOW')}")
        print(f"Local URL: {colorize(f'http://localhost:{local_port}', 'GREEN')}")
        print(colorize("=" * 60, 'BLUE'))
        print(f"\nTo disconnect, run: {colorize(f'rediacc plugin disconnect --connection-id {conn_id}', 'YELLOW')}")
        
    except Exception as e:
        print(colorize(f"Error: {e}", 'RED'))
        ssh_tunnel_conn.manual_cleanup()
        sys.exit(1)

def disconnect_plugin(args):
    connections = load_connections()
    
    if args.connection_id:
        if args.connection_id not in connections: 
            error_exit(f"Connection ID '{args.connection_id}' not found")
        to_disconnect = [args.connection_id]
    else:
        to_disconnect = [conn_id for conn_id, conn_info in connections.items() if all([conn_info.get('team') == args.team, conn_info.get('machine') == args.machine, conn_info.get('repository') == args.repository, not args.plugin or conn_info.get('plugin') == args.plugin])]
    
    if not to_disconnect: print(colorize("No matching connections found", 'YELLOW')); return
    
    for conn_id in to_disconnect:
        conn_info = connections[conn_id]
        print(colorize(f"Disconnecting {conn_info['plugin']} (port {conn_info['local_port']})...", 'BLUE'))
        
        def stop_ssh_connection(conn_info: Dict[str, Any]):
            control_path = conn_info.get('control_path')
            if control_path:
                try: subprocess.run(['ssh', '-O', 'stop', '-o', f'ControlPath={control_path}', 'dummy'], capture_output=True, stderr=subprocess.DEVNULL)
                except: pass
            
            pid = conn_info.get('ssh_pid')
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM); time.sleep(0.5)
                    if is_process_running(pid): os.kill(pid, signal.SIGKILL)
                except: pass
        
        stop_ssh_connection(conn_info)
        
        for file_key in ['ssh_key_file', 'known_hosts_file']:
            file_path = conn_info.get(file_key)
            if file_path:
                try: os.remove(file_path)
                except: pass
        
        del connections[conn_id]
        print(colorize(f"✓ Disconnected {conn_info['plugin']}", 'GREEN'))
    
    save_connections(connections)

def show_status(args):
    clean_stale_connections()
    connections = load_connections()
    if not connections: print(colorize("No active plugin connections", 'YELLOW')); return
    
    print(colorize("Active Plugin Connections", 'HEADER'))
    print(colorize("=" * 80, 'BLUE'))
    print(f"{'ID':<10} {'Plugin':<15} {'Repository':<15} {'Machine':<15} {'Port':<8} {'Status'}")
    print(colorize("-" * 80, 'BLUE'))
    
    for conn_id, conn_info in connections.items():
        port_status = 'Active' if not is_port_available(conn_info['local_port']) else 'Error'
        status_color = 'GREEN' if port_status == 'Active' else 'RED'
        
        print(f"{conn_id:<10} {conn_info['plugin']:<15} {conn_info['repository']:<15} "
              f"{conn_info['machine']:<15} {conn_info['local_port']:<8} "
              f"{colorize(port_status, status_color)}")
    
    print(colorize("-" * 80, 'BLUE'))
    print(f"Total connections: {len(connections)}")

@track_command('plugin')
def main():
    # Initialize telemetry
    initialize_telemetry()

    parser = argparse.ArgumentParser(
        prog='rediacc plugin',
        description='Rediacc CLI Plugin - SSH tunnel management for repository plugins',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  List available plugins:
    %(prog)s list --team="Private Team" --machine=server1 --repository = myrepo
    
  Connect to a plugin:
    %(prog)s connect --team="Private Team" --machine=server1 --repository = myrepo --plugin=browser
    %(prog)s connect --team="Private Team" --machine=server1 --repository = myrepo --plugin=terminal --port=9001
    
  Show connection status:
    %(prog)s status
    
  Disconnect a plugin:
    %(prog)s disconnect --connection-id=abc123
    %(prog)s disconnect --team="Private Team" --machine=server1 --repository = myrepo --plugin=browser

Plugin Access:
  Once connected, access plugins via local URLs:
    Browser: http://localhost:9000
    Terminal: http://localhost:9001
    
  The local port forwards to the plugin's Unix socket on the remote repository.
"""
    )

    # Note: --version is only available at root level (rediacc --version)

    # Add verbose to main parser (applies to all subcommands)
    add_common_arguments(parser, include_args=['verbose'])

    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List available plugins in a repository')
    add_common_arguments(list_parser, include_args=['token', 'team', 'machine', 'repository'])
    list_parser.set_defaults(func=list_plugins)
    
    # Connect command
    connect_parser = subparsers.add_parser('connect', help='Connect to a plugin')
    add_common_arguments(connect_parser, include_args=['token', 'team', 'machine', 'repository'])
    connect_parser.add_argument('--plugin', required=True, help='Plugin name (e.g., browser, terminal)')
    connect_parser.add_argument('--port', type=int, help='Local port to use (auto-assigned if not specified)')
    connect_parser.set_defaults(func=connect_plugin)
    
    # Disconnect command
    disconnect_parser = subparsers.add_parser('disconnect', help='Disconnect plugin connection(s)')
    disconnect_parser.add_argument('--connection-id', help='Connection ID to disconnect')
    add_common_arguments(disconnect_parser, include_args=['team', 'machine', 'repository'], 
                        required_overrides={'team': False, 'machine': False, 'repository': False})
    disconnect_parser.add_argument('--plugin', help='Plugin name (disconnect all if not specified)')
    disconnect_parser.set_defaults(func=disconnect_plugin)
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show status of all plugin connections')
    status_parser.set_defaults(func=show_status)
    
    args = parser.parse_args()
    if not args.command: parser.print_help(); sys.exit(1)
    
    if args.command in ['list', 'connect']:
        initialize_cli_command(args, parser)
    
    try:
        args.func(args)
    finally:
        # Shutdown telemetry
        shutdown_telemetry()

if __name__ == '__main__':
    main()