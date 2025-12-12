#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rediacc CLI - Complete command-line interface for Rediacc Middleware API
Includes all functionality from both CLI and test suite with enhanced queue support
"""

import argparse
import getpass
import hashlib
import json
import os
import sys
import base64
from typing import Dict, Any, Optional, List, Union
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli._version import __version__
from cli.core.config import (
    load_config, get_required, get, get_path, ConfigError,
    TokenManager, api_mutex, setup_logging, get_logger
)

from cli.core.shared import colorize, COLORS
from cli.core.api_client import client
from cli.core.telemetry import track_command, initialize_telemetry, shutdown_telemetry
# Note: WorkflowHandler import removed - workflow is now a standalone module

import time
import datetime

try:
    load_config()
except ConfigError as e:
    print(f"Configuration error: {e}", file=sys.stderr)
    sys.exit(1)

from cli.core.config import get_config_dir

HTTP_PORT = get_required('SYSTEM_HTTP_PORT')
BASE_URL = get_required('SYSTEM_API_URL')
API_PREFIX = '/StoredProcedure'
CONFIG_DIR = str(get_config_dir())
REQUEST_TIMEOUT = 30
TEST_ACTIVATION_CODE = get('REDIACC_TEST_ACTIVATION_CODE') or '111111'

from cli.config import CLI_CONFIG_FILE

CLI_CONFIG_PATH = CLI_CONFIG_FILE
try:
    with open(CLI_CONFIG_PATH, 'r', encoding='utf-8') as f:
        cli_config = json.load(f)
        API_ENDPOINTS_JSON = cli_config['API_ENDPOINTS']
        CLI_COMMANDS_JSON = cli_config['CLI_COMMANDS']
except Exception as e:
    print(colorize(f"Error loading CLI configuration from {CLI_CONFIG_PATH}: {e}", 'RED'))
    sys.exit(1)

def reconstruct_cmd_config():
    def process_value(value):
        if not isinstance(value, dict): return value
        if 'params' in value and isinstance(value['params'], str) and value['params'].startswith('lambda'):
            value = value.copy(); value['params'] = eval(value['params']); return value
        return {k: process_value(v) if isinstance(v, dict) else v for k, v in value.items()}
    return {key: process_value(value) for key, value in API_ENDPOINTS_JSON.items()}

def reconstruct_arg_defs():
    def process_arg(arg):
        if not isinstance(arg, dict) or 'type' not in arg: return arg
        arg = arg.copy()
        if isinstance(arg['type'], str):
            arg['type'] = eval(arg['type']) if arg['type'].startswith('lambda') else int if arg['type'] == 'int' else arg['type']
        return arg
    
    def process_value(value):
        return [process_arg(arg) for arg in value] if isinstance(value, list) else \
               {k: process_value(v) if isinstance(v, (list, dict)) else v for k, v in value.items()} if isinstance(value, dict) else value
    
    return {key: process_value(value) for key, value in CLI_COMMANDS_JSON.items()}

API_ENDPOINTS = reconstruct_cmd_config()
CLI_COMMANDS = reconstruct_arg_defs()

def APIClient(config_manager):
    """Create CLI client instance by setting config manager on singleton"""
    client.set_config_manager(config_manager)
    return client

def format_output(data, format_type, message=None, error=None):
    if format_type in ['json', 'json-full']:
        output = {'success': error is None, 'data': data}
        if message: output['message'] = message
        if error: output['error'] = error
        return json.dumps(output, indent=2)
    return colorize(f"Error: {error}", 'RED') if error else data if data else colorize(message, 'GREEN') if message else "No data available"

STATIC_SALT = 'Rd!@cc111$ecur3P@$$w0rd$@lt#H@$h'

def pwd_hash(pwd):
    salted_password = pwd + STATIC_SALT
    return "0x" + hashlib.sha256(salted_password.encode()).digest().hex()

def extract_table_data(response, table_index=0):
    return response.get('resultSets', [])[table_index].get('data', []) if response and len(response.get('resultSets', [])) > table_index else []


def camel_to_title(name):
    special_cases = {
        'vaultVersion': 'Vault Version', 'vaultContent': 'Vault Content',
        'memberCount': 'Members', 'machineCount': 'Machines',
        'bridgeCount': 'Bridges', 'repoCount': 'Repos',
        'storageCount': 'Storage', 'scheduleCount': 'Schedules',
        'queueCount': 'Queue Items', 'teamName': 'Team',
        'regionName': 'Region', 'bridgeName': 'Bridge',
        'machineName': 'Machine', 'repoName': 'Repository',
        'storageName': 'Storage', 'scheduleName': 'Schedule',
        'userEmail': 'Email', 'companyName': 'Company',
        'hasAccess': 'Access', 'isMember': 'Member',
        'activated': 'Active', 'taskId': 'Task ID',
        'itemCount': 'Count', 'newUserEmail': 'Email',
        'permissionGroupName': 'Permission Group',
        'permissionName': 'Permission', 'subscriptionPlan': 'Plan',
        'maxTeams': 'Max Teams', 'maxRegions': 'Max Regions',
        'maxMachines': 'Max Machines', 'maxStorage': 'Max Storage',
        'sessionName': 'Session', 'createdAt': 'Created',
        'updatedAt': 'Updated', 'lastActive': 'Last Active',
        'auditId': 'Audit ID', 'entityName': 'Entity Name',
        'actionByUser': 'Action By', 'timestamp': 'Timestamp',
        'details': 'Details', 'action': 'Action',
        'entity': 'Entity', 'entityId': 'Entity ID',
        'userId': 'User ID', 'changeType': 'Change Type',
        'previousValue': 'Previous Value', 'newValue': 'New Value',
        'propertyName': 'Property', 'changeDetails': 'Change Details',
        'bridgeCredentialsVersion': 'Bridge Credentials Version',
        'bridgeCredentials': 'Bridge Credentials',
        'bridgeUserEmail': 'Bridge User Email'
    }
    
    return special_cases.get(name, ''.join(' ' + char if char.isupper() and i > 0 else char 
                                          for i, char in enumerate(name)).strip().title())

def format_table(headers, rows):
    if not rows:
        return "No items found"
    
    widths = [max(len(h), max(len(str(row[i])) for row in rows if i < len(row))) for i, h in enumerate(headers)]
    
    header_line = '  '.join(h.ljust(w) for h, w in zip(headers, widths))
    separator = '-' * len(header_line)
    formatted_rows = ['  '.join(str(cell).ljust(w) for cell, w in zip(row, widths)) for row in rows]
    
    return '\n'.join([header_line, separator] + formatted_rows)

def format_dynamic_tables(response, output_format='text', skip_fields=None):
    if not response or 'resultSets' not in response:
        return format_output("No data available", output_format)
    
    resultSets = response.get('resultSets', [])
    if len(resultSets) <= 1:
        return format_output("No records found", output_format)
    
    skip_fields = skip_fields or ['nextRequestToken', 'newUserHash']
    
    def process_table_data(table):
        data = table.get('data', [])
        if not data:
            return None
            
        processed_data = [{k: v for k, v in record.items() if k not in skip_fields} for record in data]
        return processed_data if any(processed_data) else None
    
    if output_format == 'json':
        result = []
        for table in resultSets[1:]:
            processed = process_table_data(table)
            if processed:
                result.extend(processed)
        return format_output(result, output_format)
    
    if output_format == 'json-full':
        # Return the complete response with all resultSets for json-full
        return format_output({'resultSets': resultSets}, output_format)
    
    output_parts = []
    for table in resultSets[1:]:
        data = table.get('data', [])
        if not data:
            continue
        
        all_keys = set().union(*(record.keys() for record in data))
        display_keys = sorted(k for k in all_keys if k not in skip_fields)
        
        if not display_keys:
            continue
        
        headers = [camel_to_title(key) for key in display_keys]
        rows = [[str(record.get(key, '')) for key in display_keys] for record in data]
        
        if rows:
            output_parts.append(format_table(headers, rows))
    
    return format_output('\n\n'.join(output_parts) if output_parts else "No records found", output_format)



class CommandHandler:
    def __init__(self, config_manager, output_format='text'):
        self.config = config_manager.config
        self.config_manager = config_manager
        self.client = APIClient(config_manager)
        self.output_format = output_format
    
    def handle_response(self, response, success_message=None, format_args=None):
        if response.get('error'): print(format_output(None, self.output_format, None, response['error'])); return False
        
        # Debug: Check if response indicates failure
        if response.get('failure') or response.get('success') == False:
            errors = response.get('errors', [])
            if errors:
                error_msg = '; '.join(errors)
                print(format_output(None, self.output_format, None, f"Operation failed: {error_msg}"))
                return False
        
        if success_message and format_args and '{task_id}' in success_message:
            resultSets = response.get('resultSets', [])
            if resultSets and len(resultSets) > 1 and resultSets[1].get('data'):
                task_id = resultSets[1]['data'][0].get('taskId') or resultSets[1]['data'][0].get('TaskId')
                if task_id:
                    setattr(format_args, 'task_id', task_id)
        
        if not success_message: return True
        
        if format_args:
            format_dict = {k: getattr(format_args, k, '') for k in dir(format_args) if not k.startswith('_')}
            success_message = success_message.format(**format_dict)
        
        if self.output_format in ['json', 'json-full']:
            data = {'task_id': format_args.task_id} if hasattr(format_args, 'task_id') and format_args.task_id else {}
            
            # For json-full, include the complete response data
            if self.output_format == 'json-full' and response.get('resultSets'):
                data['resultSets'] = response['resultSets']
            
            print(format_output(data, self.output_format, success_message))
        else:
            print(colorize(success_message, 'GREEN'))
        return True
    
    


    
    def generate_dynamic_help(self, cmd_type, resource_type=None):
        """Generate help text dynamically from configuration"""
        if not resource_type:
            # List all resources for command type
            if cmd_type not in API_ENDPOINTS:
                return f"\nNo resources available for command '{cmd_type}'\n"
            
            resources = API_ENDPOINTS.get(cmd_type, {})
            help_text = f"\nAvailable resources for '{colorize(cmd_type, 'BLUE')}':\n\n"
            
            # Calculate max width for alignment
            max_width = max(len(r) for r in resources.keys()) if resources else 0
            
            for resource, config in resources.items():
                help_info = config.get('help', {})
                desc = help_info.get('description', 'No description available')
                help_text += f"  {colorize(resource, 'GREEN'):<{max_width + 10}} {desc}\n"
            
            help_text += f"\nUse '{colorize(f'rediacc {cmd_type} <resource> --help', 'YELLOW')}' for more details on a specific resource.\n"
            return help_text
        
        # Generate help for specific command
        if cmd_type not in API_ENDPOINTS or resource_type not in API_ENDPOINTS[cmd_type]:
            return f"\nNo help available for: {cmd_type} {resource_type}\n"
        
        config = API_ENDPOINTS[cmd_type][resource_type]
        help_info = config.get('help', {})
        
        # Start with command description
        help_text = f"\n{colorize(help_info.get('description', 'No description available'), 'BOLD')}\n"
        
        # Add detailed description
        details = help_info.get('details')
        if details:
            help_text += f"\n{details}\n"
        
        # Add parameters section
        params = help_info.get('parameters')
        if params:
            help_text += f"\n{colorize('Parameters:', 'BLUE')}\n"
            for param_name, param_info in params.items():
                req_text = colorize(" (required)", 'YELLOW') if param_info.get('required') else " (optional)"
                help_text += f"  {colorize(param_name, 'GREEN')}{req_text}: {param_info['description']}\n"
                
                default = param_info.get('default')
                if default:
                    help_text += f"    Default: {default}\n"
                    
                example = param_info.get('example')
                if example:
                    help_text += f"    Example: {example}\n"
        
        # Add examples section
        examples = help_info.get('examples')
        if examples:
            help_text += f"\n{colorize('Examples:', 'BLUE')}\n"
            for ex in examples:
                help_text += f"  $ {colorize(ex['command'], 'GREEN')}\n"
                help_text += f"    {ex['description']}\n\n"
        
        # Add notes section
        notes = help_info.get('notes')
        if notes:
            help_text += f"{colorize('Notes:', 'BLUE')} {notes}\n"
        
        # Add success message info if available
        success_msg = config.get('success_msg')
        if success_msg:
            help_text += f"\n{colorize('Success message:', 'BLUE')} {success_msg}\n"
        
        return help_text
    
    def generic_command(self, cmd_type, resource_type, args):
        special_handlers = {}
        
        handler = special_handlers.get((cmd_type, resource_type))
        if handler:
            return handler(args)
        
        if cmd_type not in API_ENDPOINTS or resource_type not in API_ENDPOINTS[cmd_type]:
            print(format_output(None, self.output_format, None, f"Unsupported command: {cmd_type} {resource_type}"))
            return 1
        
        cmd_config = API_ENDPOINTS[cmd_type][resource_type]
        auth_required = cmd_config.get('auth_required', True)
        
        password_prompts = [
            (cmd_type == 'create' and resource_type == 'user' and not hasattr(args, 'password'),
             lambda: setattr(args, 'password', getpass.getpass("Password for new user: ")))
        ]
        
        for condition, action in password_prompts:
            if condition:
                action()
        
        confirm_msg = cmd_config.get('confirm_msg')
        if confirm_msg and not args.force and self.output_format != 'json':
            confirm_msg = confirm_msg.format(**{k: getattr(args, k, '') 
                                                             for k in dir(args) 
                                                             if not k.startswith('_')})
            confirm = input(f"{confirm_msg} [y/N] ")
            if confirm.lower() != 'y':
                print("Operation cancelled")
                return 0
        
        if cmd_type == 'vault':
            if resource_type == 'set':
                return self.vault_set(args)
            elif resource_type == 'set-password':
                return self.vault_set_password(args)
            elif resource_type == 'clear-password':
                return self.vault_clear_password(args)
            elif resource_type == 'status':
                return self.vault_status(args)
            return 1
        
        params = cmd_config['params'](args) if callable(cmd_config.get('params')) else {}
        
        if cmd_config.get('auth_type') == 'credentials' and hasattr(args, 'email'):
            email = args.email or input("Admin Email: ")
            password = args.password
            if not password:
                password = getpass.getpass("Admin Password: ")
                confirm = getpass.getpass("Confirm Password: ")
                if password != confirm:
                    error = "Passwords do not match"
                    output = format_output(None, self.output_format, None, error)
                    print(output)
                    return 1
            
            response = self.client.auth_request(
                cmd_config['endpoint'], email, pwd_hash(password), params
            )
        elif not auth_required:
            # No authentication required
            response = self.client.request(cmd_config['endpoint'], params)
        else:
            # Use token authentication
            response = self.client.token_request(cmd_config['endpoint'], params)
        
        # For list commands or permission list commands, format the output
        if cmd_type == 'list' or cmd_type == 'inspect' or (cmd_type == 'permission' and resource_type in ['list-groups', 'list-group']) or \
           (cmd_type == 'team-member' and resource_type == 'list') or \
           (cmd_type == 'company' and resource_type == 'get-vaults'):
            if response.get('error'):
                output = format_output(None, self.output_format, None, response['error'])
                print(output)
                return 1

            # Special handling for inspect commands
            if cmd_type == 'inspect':
                # Apply filter for inspect commands
                if 'filter' in cmd_config:
                    # Extract data from response
                    data = extract_table_data(response, 1)  # Data is in table index 1
                    # Apply filter
                    filter_func = eval(cmd_config['filter'])
                    filtered_data = filter_func(data, args)
                    
                    if cmd_config.get('single_result') and filtered_data:
                        # For single result, show just the first match
                        filtered_data = filtered_data[:1]
                    
                    # Create new response with filtered data
                    filtered_response = {
                        'success': True,
                        'resultSets': [
                            response['resultSets'][0],  # Keep credentials table
                            {'data': filtered_data}  # Replace data with filtered results
                        ]
                    }
                    result = format_dynamic_tables(filtered_response, self.output_format)
                else:
                    result = format_dynamic_tables(response, self.output_format)
            else:
                result = format_dynamic_tables(response, self.output_format)
            print(result)
            return 0
        
        # For create queue-item, handle special response
        if cmd_type == 'create' and resource_type == 'queue-item':
            success_msg = cmd_config.get('success_msg')
            # Create a simple object to hold task_id for format_args
            class Args:
                pass
            format_args = Args()
            for k in dir(args):
                if not k.startswith('_'):
                    setattr(format_args, k, getattr(args, k))
            
            if self.handle_response(response, success_msg, format_args):
                # If we have a task ID, print it
                if hasattr(format_args, 'task_id') and format_args.task_id and self.output_format != 'json':
                    print(f"Task ID: {format_args.task_id}")
                return 0
            return 1
        
        # For other commands, handle the response
        success_msg = cmd_config.get('success_msg')
        if self.handle_response(response, success_msg, args):
            return 0
        return 1
    
    def update_resource(self, resource_type, args):
        """Handle update commands"""
        success = True
        result_data = {}
        
        if resource_type == 'team':
            if args.new_name:
                response = self.client.token_request(
                    "UpdateTeamName", 
                    {"currentTeamName": args.name, "newTeamName": args.new_name}
                )
                
                success_msg = f"Successfully renamed team: {args.name} → {args.new_name}"
                if not self.handle_response(response, success_msg):
                    success = False
                else:
                    result_data['team_name'] = args.new_name
            
            if (args.vault or args.vault_file) and success:
                vault_data = get_vault_data(args)
                team_name = args.new_name if args.new_name else args.name
                
                response = self.client.token_request(
                    "UpdateTeamVault", 
                    {
                        "teamName": team_name,
                        "vaultContent": vault_data,
                        "vaultVersion": args.vault_version or 1
                    }
                )
                
                if not self.handle_response(response, "Successfully updated team vault"):
                    success = False
                else:
                    result_data['vault_updated'] = True
                    result_data['vault_version'] = args.vault_version or 1
        
        elif resource_type == 'region':
            if args.new_name:
                # Update region name
                response = self.client.token_request(
                    "UpdateRegionName", 
                    {"currentRegionName": args.name, "newRegionName": args.new_name}
                )
                
                success_msg = f"Successfully renamed region: {args.name} → {args.new_name}"
                if not self.handle_response(response, success_msg):
                    success = False
                else:
                    result_data['region_name'] = args.new_name
            
            if (args.vault or args.vault_file) and success:
                vault_data = get_vault_data(args)
                region_name = args.new_name if args.new_name else args.name
                
                response = self.client.token_request(
                    "UpdateRegionVault", 
                    {
                        "regionName": region_name,
                        "vaultContent": vault_data,
                        "vaultVersion": args.vault_version or 1
                    }
                )
                
                if not self.handle_response(response, "Successfully updated region vault"):
                    success = False
                else:
                    result_data['vault_updated'] = True
                    result_data['vault_version'] = args.vault_version or 1
        
        elif resource_type == 'bridge':
            if args.new_name:
                # Update bridge name
                response = self.client.token_request(
                    "UpdateBridgeName", 
                    {
                        "regionName": args.region,
                        "currentBridgeName": args.name,
                        "newBridgeName": args.new_name
                    }
                )
                
                success_msg = f"Successfully renamed bridge: {args.name} → {args.new_name}"
                if not self.handle_response(response, success_msg):
                    success = False
                else:
                    result_data['bridge_name'] = args.new_name
            
            if (args.vault or args.vault_file) and success:
                vault_data = get_vault_data(args)
                bridge_name = args.new_name if args.new_name else args.name
                
                response = self.client.token_request(
                    "UpdateBridgeVault", 
                    {
                        "regionName": args.region,
                        "bridgeName": bridge_name,
                        "vaultContent": vault_data,
                        "vaultVersion": args.vault_version or 1
                    }
                )
                
                if not self.handle_response(response, "Successfully updated bridge vault"):
                    success = False
                else:
                    result_data['vault_updated'] = True
                    result_data['vault_version'] = args.vault_version or 1
        
        elif resource_type == 'machine':
            team_name = args.team
            result_data['team'] = team_name
            
            if args.new_name:
                # Update machine name
                response = self.client.token_request(
                    "UpdateMachineName", 
                    {
                        "teamName": team_name,
                        "currentMachineName": args.name,
                        "newMachineName": args.new_name
                    }
                )
                
                success_msg = f"Successfully renamed machine: {args.name} → {args.new_name}"
                if not self.handle_response(response, success_msg):
                    success = False
                else:
                    result_data['machine_name'] = args.new_name
            
            # Update bridge if provided
            if args.new_bridge and success:
                machine_name = args.new_name if args.new_name else args.name
                
                response = self.client.token_request(
                    "UpdateMachineAssignedBridge", 
                    {
                        "teamName": team_name,
                        "machineName": machine_name,
                        "newBridgeName": args.new_bridge
                    }
                )
                
                success_msg = f"Successfully updated machine bridge: → {args.new_bridge}"
                if not self.handle_response(response, success_msg):
                    success = False
                else:
                    result_data['bridge'] = args.new_bridge
            
            if (args.vault or args.vault_file) and success:
                vault_data = get_vault_data(args)
                machine_name = args.new_name if args.new_name else args.name
                
                response = self.client.token_request(
                    "UpdateMachineVault", 
                    {
                        "teamName": team_name,
                        "machineName": machine_name,
                        "vaultContent": vault_data,
                        "vaultVersion": args.vault_version or 1
                    }
                )
                
                if not self.handle_response(response, "Successfully updated machine vault"):
                    success = False
                else:
                    result_data['vault_updated'] = True
                    result_data['vault_version'] = args.vault_version or 1
        
        elif resource_type == 'repository':
            if args.new_name:
                # Update repository name
                response = self.client.token_request(
                    "UpdateRepositoryName", 
                    {
                        "teamName": args.team,
                        "currentRepoName": args.name,
                        "newRepoName": args.new_name
                    }
                )
                
                success_msg = f"Successfully renamed repository: {args.name} → {args.new_name}"
                if not self.handle_response(response, success_msg):
                    success = False
                else:
                    result_data['repository_name'] = args.new_name
            
            if (args.vault or args.vault_file) and success:
                vault_data = get_vault_data(args)
                repo_name = args.new_name if args.new_name else args.name

                response = self.client.token_request(
                    "UpdateRepositoryVault",
                    {
                        "teamName": args.team,
                        "repoName": repo_name,
                        "repositoryTag": args.tag,
                        "vaultContent": vault_data,
                        "vaultVersion": args.vault_version or 1
                    }
                )
                
                if not self.handle_response(response, "Successfully updated repository vault"):
                    success = False
                else:
                    result_data['vault_updated'] = True
                    result_data['vault_version'] = args.vault_version or 1
        
        elif resource_type == 'storage':
            if args.new_name:
                # Update storage name
                response = self.client.token_request(
                    "UpdateStorageName", 
                    {
                        "teamName": args.team,
                        "currentStorageName": args.name,
                        "newStorageName": args.new_name
                    }
                )
                
                success_msg = f"Successfully renamed storage: {args.name} → {args.new_name}"
                if not self.handle_response(response, success_msg):
                    success = False
                else:
                    result_data['storage_name'] = args.new_name
            
            if (args.vault or args.vault_file) and success:
                vault_data = get_vault_data(args)
                storage_name = args.new_name if args.new_name else args.name
                
                response = self.client.token_request(
                    "UpdateStorageVault", 
                    {
                        "teamName": args.team,
                        "storageName": storage_name,
                        "vaultContent": vault_data,
                        "vaultVersion": args.vault_version or 1
                    }
                )
                
                if not self.handle_response(response, "Successfully updated storage vault"):
                    success = False
                else:
                    result_data['vault_updated'] = True
                    result_data['vault_version'] = args.vault_version or 1
        
        elif resource_type == 'schedule':
            if args.new_name:
                # Update schedule name
                response = self.client.token_request(
                    "UpdateScheduleName", 
                    {
                        "teamName": args.team,
                        "currentScheduleName": args.name,
                        "newScheduleName": args.new_name
                    }
                )
                
                success_msg = f"Successfully renamed schedule: {args.name} → {args.new_name}"
                if not self.handle_response(response, success_msg):
                    success = False
                else:
                    result_data['schedule_name'] = args.new_name
            
            if (args.vault or args.vault_file) and success:
                vault_data = get_vault_data(args)
                schedule_name = args.new_name if args.new_name else args.name
                
                response = self.client.token_request(
                    "UpdateScheduleVault", 
                    {
                        "teamName": args.team,
                        "scheduleName": schedule_name,
                        "vaultContent": vault_data,
                        "vaultVersion": args.vault_version or 1
                    }
                )
                
                if not self.handle_response(response, "Successfully updated schedule vault"):
                    success = False
                else:
                    result_data['vault_updated'] = True
                    result_data['vault_version'] = args.vault_version or 1
        
        else:
            error = f"Unsupported resource type: {resource_type}"
            output = format_output(None, self.output_format, None, error)
            print(output)
            return 1
        
        # If JSON output and operations were successful, show summary
        if self.output_format == 'json' and success and result_data:
            output = format_output(result_data, self.output_format, "Update completed successfully")
            print(output)
        
        return 0 if success else 1
    
    
    def handle_dynamic_endpoint(self, endpoint_name, args):
        """Handle direct endpoint calls without predefined configuration"""
        # Convert CLI args to API parameters
        params = {}
        
        # Get all attributes from args that are not system attributes
        for key in vars(args):
            if key not in ['command', 'output', 'token', 'verbose', 'func', 'help', 'email', 'password']:
                value = getattr(args, key)
                if value is not None:
                    # Handle boolean parameters properly
                    # Check if the value is a string that represents a boolean
                    if isinstance(value, str) and value.lower() in ['true', 'false']:
                        params[key] = value.lower() == 'true'
                    else:
                        params[key] = value
        
        # Check if this endpoint requires special authentication handling
        # Look for it in API_ENDPOINTS to determine auth requirements
        auth_required = True
        auth_type = None
        
        for main_cmd, sub_cmds in API_ENDPOINTS.items():
            if isinstance(sub_cmds, dict):
                # Check top-level commands
                if sub_cmds.get('endpoint') == endpoint_name:
                    auth_required = sub_cmds.get('auth_required', True)
                    auth_type = sub_cmds.get('auth_type')
                    break
                
                # Check sub-commands
                for sub_cmd, config in sub_cmds.items():
                    if isinstance(config, dict) and config.get('endpoint') == endpoint_name:
                        auth_required = config.get('auth_required', True) 
                        auth_type = config.get('auth_type')
                        break
            if not auth_required:
                break
        
        # Debug output if verbose
        if args.verbose:
            print(f"Dynamic endpoint: {endpoint_name}")
            print(f"Parameters: {params}")
            print(f"Auth required: {auth_required}")
            print(f"Auth type: {auth_type}")
        
        # Make API call based on auth requirements
        if not auth_required and auth_type == 'credentials':
            # This endpoint uses email/password authentication
            email = getattr(args, 'email', None)
            password = getattr(args, 'password', None)
            
            if email and password:
                hash_pwd = pwd_hash(password)
                response = self.client.auth_request(endpoint_name, email, hash_pwd, params)
            else:
                print(format_output(None, self.output_format, None, "Email and password required for this endpoint"))
                return 1
        else:
            # Standard token-based authentication
            response = self.client.token_request(endpoint_name, params)
        
        # Handle response
        if response.get('error'):
            print(format_output(None, self.output_format, None, response['error']))
            return 1
        
        # Format success message
        success_msg = f"Successfully executed {endpoint_name}"
        
        # Try to create a more informative success message based on the endpoint name
        if 'Update' in endpoint_name and 'Name' in endpoint_name:
            # Extract what's being updated from the endpoint name
            resource = endpoint_name.replace('Update', '').replace('Name', '')
            if 'currentStorageName' in params and 'newStorageName' in params:
                success_msg = f"Successfully updated {resource.lower()} name: {params['currentStorageName']} → {params['newStorageName']}"
            elif 'current' + resource + 'Name' in params and 'new' + resource + 'Name' in params:
                current_key = 'current' + resource + 'Name'
                new_key = 'new' + resource + 'Name'
                success_msg = f"Successfully updated {resource.lower()} name: {params[current_key]} → {params[new_key]}"
        
        if self.output_format in ['json', 'json-full']:
            # Extract meaningful data from response for JSON output
            result_data = {'endpoint': endpoint_name, 'parameters': params}
            
            # If there's data in the response, include it
            if 'resultSets' in response and len(response['resultSets']) > 1:
                for table in response['resultSets'][1:]:
                    if table.get('data'):
                        result_data['result'] = table['data']
                        break
            
            print(format_output(result_data, self.output_format, success_msg))
        else:
            print(colorize(success_msg, 'GREEN'))
        
        return 0

    # Note: Workflow delegate methods removed - workflow is now a standalone module


def show_version():
    """Print version information - single source of truth for version display"""
    print(f'Rediacc CLI v{__version__}')


def show_help():
    """Print comprehensive help - single source of truth for help display"""
    from cli.core.format_help import main as format_help_main
    format_help_main()


def handle_special_flags():
    """
    Handle special flags that should work consistently in both wrapper and PyPI package.
    Returns True if a special flag was handled (caller should exit), False otherwise.

    This function provides DRY principle for:
    - --version: Show version and exit
    - --help/-h: Show comprehensive help and exit (only if no command specified)
    - No arguments: Show comprehensive help and exit
    """
    # Handle version (global flag)
    if '--version' in sys.argv:
        show_version()
        return True

    # Handle help - only if it appears before any command
    # This allows subcommands to handle their own --help
    if '--help' in sys.argv or '-h' in sys.argv:
        # Check if there's a command before the help flag
        has_command_before_help = False
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg in ['--help', '-h']:
                break
            # If we find a non-flag argument before --help, it's a command
            if not arg.startswith('-'):
                has_command_before_help = True
                break

        # Only show global help if no command was specified before --help
        if not has_command_before_help:
            show_help()
            return True

    # Handle no arguments
    if len(sys.argv) == 1:
        show_help()
        return True

    return False


def setup_parser():
    parser = argparse.ArgumentParser(
        prog='rediacc cli',
        description='Rediacc CLI - Complete interface for Rediacc Middleware API with enhanced queue support',
        add_help=False  # We handle help manually for consistent UX across wrapper and direct Python
    )
    # Note: --version and --help are handled early in main() for consistent behavior
    parser.add_argument('--output', '-o', choices=['text', 'json', 'json-full'], default='text',
                       help='Output format: text, json (concise), or json-full (comprehensive)')
    parser.add_argument('--token', '-t', help='Authentication token (overrides saved token)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging output')
    parser.add_argument('--sandbox', action='store_true',
                       help='Use sandbox API (https://sandbox.rediacc.com)')
    
    
    subparsers = parser.add_subparsers(dest='command', help='Command')
    
    for cmd_name, cmd_def in CLI_COMMANDS.items():
        # Skip individual parameter definitions (they have 'type' and 'help' but no subcommands)
        if isinstance(cmd_def, dict) and 'type' in cmd_def and 'help' in cmd_def and len(cmd_def) <= 3:
            continue
        
        # Skip commands that have subcommands (they're handled in the CLI_COMMANDS section above)
        if isinstance(cmd_def, dict) and 'subcommands' in cmd_def:
            continue
            
        if isinstance(cmd_def, list):
            cmd_parser = subparsers.add_parser(cmd_name, help=f"{cmd_name} command")
            for arg in cmd_def:
                kwargs = {k: v for k, v in arg.items() if k != 'name'}
                cmd_parser.add_argument(arg['name'], **kwargs)
        else:
            cmd_parser = subparsers.add_parser(cmd_name, help=f"{cmd_name} command")
            subcmd_parsers = cmd_parser.add_subparsers(dest='resource', help='Resource')
            
            for subcmd_name, subcmd_def in cmd_def.items():
                subcmd_parser = subcmd_parsers.add_parser(subcmd_name, help=f"{subcmd_name} resource")

                if isinstance(subcmd_def, list):
                    for arg in subcmd_def:
                        if isinstance(arg, dict):
                            kwargs = {k: v for k, v in arg.items() if k != 'name'}
                            subcmd_parser.add_argument(arg['name'], **kwargs)
                        else:
                            # Handle string arguments
                            subcmd_parser.add_argument(arg)
                elif isinstance(subcmd_def, dict):
                    for arg_name, arg_def in subcmd_def.items():
                        if isinstance(arg_def, dict):
                            kwargs = {k: v for k, v in arg_def.items() if k != 'name'}
                            subcmd_parser.add_argument(arg_name, **kwargs)
                        else:
                            subcmd_parser.add_argument(arg_name, help=str(arg_def))

                if cmd_name == 'update' and subcmd_name in ['team', 'region', 'bridge', 'machine', 'repository', 'storage', 'schedule']:
                    subcmd_parser.add_argument('--vault', help='JSON vault data')
                    subcmd_parser.add_argument('--vault-file', help='File containing JSON vault data')
                    subcmd_parser.add_argument('--vault-version', type=int, help='Vault version')

                    if subcmd_name == 'machine':
                        subcmd_parser.add_argument('--new-bridge', help='New bridge name for machine')
    
    # Add CLI commands from JSON configuration
    if 'CLI_COMMANDS' in cli_config:
        for cmd_name, cmd_def in cli_config['CLI_COMMANDS'].items():
            # Skip license, vault, and user - now have dedicated modules
            if cmd_name in ('license', 'vault', 'user'):
                continue

            # Only process commands with subcommands structure
            if isinstance(cmd_def, dict) and 'subcommands' in cmd_def:
                cmd_parser = subparsers.add_parser(cmd_name, help=cmd_def.get('description', f'{cmd_name} commands'))

                cmd_subparsers = cmd_parser.add_subparsers(
                    dest=f'{cmd_name}_type',
                    help=f'{cmd_name.title()} commands'
                )
                
                for subcmd_name, subcmd_def in cmd_def['subcommands'].items():
                    subcmd_parser = cmd_subparsers.add_parser(
                        subcmd_name, 
                        help=subcmd_def.get('description', f'{subcmd_name} command')
                    )
                    
                    # Add parameters for this subcommand
                    if 'parameters' in subcmd_def:
                        for param_name, param_def in subcmd_def['parameters'].items():
                            # Convert parameter name to CLI format
                            cli_param_name = f'--{param_name}'
                            
                            # Build argument kwargs
                            kwargs = {}
                            
                            # Add short form if specified
                            if 'short' in param_def:
                                args = [param_def['short'], cli_param_name]
                            else:
                                args = [cli_param_name]
                            
                            # Convert parameter definition to argparse kwargs
                            if 'help' in param_def:
                                kwargs['help'] = param_def['help']
                            if 'required' in param_def:
                                kwargs['required'] = param_def['required']
                            if 'default' in param_def:
                                kwargs['default'] = param_def['default']
                            if 'type' in param_def:
                                if param_def['type'] == 'int':
                                    kwargs['type'] = int
                            if 'action' in param_def:
                                kwargs['action'] = param_def['action']
                            if 'choices' in param_def:
                                kwargs['choices'] = param_def['choices']
                            if 'nargs' in param_def:
                                kwargs['nargs'] = param_def['nargs']
                            
                            # Set destination to replace hyphens with underscores
                            kwargs['dest'] = param_name.replace('-', '_')
                            
                            subcmd_parser.add_argument(*args, **kwargs)

    return parser

def reorder_args(argv):
    """Move global options after the command to handle argparse limitations"""
    if len(argv) < 2:
        return argv

    # Global options that should be moved
    global_opts = {'--output', '-o', '--token', '-t', '--verbose', '-v', '--sandbox'}
    
    # Commands that have subcommands
    # Note: workflow removed - now routed via dispatcher
    subcommand_cmds = {'create', 'list', 'update', 'rm', 'permission',
                       'team-member', 'bridge', 'company', 'audit', 'inspect',
                       'distributed-storage', 'auth'}
    
    # Separate script name, global options, and command/args
    script_name = argv[0]
    global_args = []
    command = None
    command_args = []
    
    i = 1
    skip_next = False
    
    while i < len(argv):
        if skip_next:
            skip_next = False
            i += 1
            continue
            
        arg = argv[i]
        
        # Check if this is a global option
        if arg in global_opts:
            global_args.append(arg)
            # Check if the option has a value
            if i + 1 < len(argv) and not argv[i + 1].startswith('-'):
                if arg not in ['--verbose', '-v']:  # verbose is a flag, no value
                    global_args.append(argv[i + 1])
                    skip_next = True
        elif not arg.startswith('-') and command is None:
            # This is the command
            command = arg
        elif command is not None:
            # Everything after the command goes to command_args
            command_args.append(arg)
        
        i += 1
    
    # Reconstruct the arguments in the correct order
    result = [script_name]
    
    # Add global options first (they go at the root level)
    result.extend(global_args)
    
    # Then add command
    if command:
        result.append(command)
    
    # Then all command args
    result.extend(command_args)
    
    return result

def parse_dynamic_command(argv):
    """Parse command line for dynamic endpoint calls"""
    # Create a simple parser for global options
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--output', '-o', choices=['text', 'json', 'json-full'], default='text')
    parser.add_argument('--token', '-t')
    parser.add_argument('--verbose', '-v', action='store_true')
    
    # Find the command (first non-option argument)
    command = None
    remaining_args = []
    i = 1  # Skip script name
    while i < len(argv):
        arg = argv[i]
        if not arg.startswith('-'):
            command = arg
            # Collect remaining arguments after command
            remaining_args = argv[i+1:]
            break
        else:
            # Skip option and its value if needed
            if arg in ['--output', '-o', '--token', '-t'] and i + 1 < len(argv):
                i += 2
            else:
                i += 1
    
    # Parse global options from original argv
    global_args, _ = parser.parse_known_args(argv[1:])
    
    # Create dynamic args object
    class DynamicArgs:
        def __init__(self):
            self.command = command
            self.output = global_args.output
            self.token = global_args.token
            self.verbose = global_args.verbose
    
    args = DynamicArgs()
    
    # Parse remaining arguments as key-value pairs
    i = 0
    while i < len(remaining_args):
        arg = remaining_args[i]
        if arg.startswith('--'):
            key = arg[2:].replace('-', '_')
            # Check if next arg is a value or another option
            if i + 1 < len(remaining_args) and not remaining_args[i + 1].startswith('--'):
                value = remaining_args[i + 1]
                # Try to parse as integer if it looks like one
                if value.isdigit() or (value.startswith('-') and value[1:].isdigit()):
                    try:
                        value = int(value)
                    except ValueError:
                        pass  # Keep as string
                # Handle boolean values explicitly
                elif value.lower() in ['true', 'false']:
                    value = value.lower() == 'true'
                setattr(args, key, value)
                i += 2
            else:
                # Boolean flag
                setattr(args, key, True)
                i += 1
        else:
            i += 1
    
    return args, command

@track_command('cli')
def main():
    # Initialize telemetry
    initialize_telemetry()

    # Debug output
    if os.environ.get('REDIACC_DEBUG_ARGS'):
        print(f"DEBUG: sys.argv = {sys.argv}", file=sys.stderr)

    # Handle special flags (--version, --help, no args) using DRY approach
    if handle_special_flags():
        return 0

    # Handle local commands that don't require authentication
    if len(sys.argv) > 1:
        command = sys.argv[1]

        # Command dispatcher - route dedicated commands to their modules (Docker-style UX)
        # This allows both 'rediacc sync' and 'rediacc-sync' to work
        command_modules = {
            'auth': ('cli.commands.auth_main', 'Auth'),
            'sync': ('cli.commands.sync_main', 'Sync'),
            'term': ('cli.commands.term_main', 'Term'),
            'plugin': ('cli.commands.plugin_main', 'Plugin'),
            'vscode': ('cli.commands.vscode_main', 'VSCode'),
            'compose': ('cli.commands.compose_main', 'Compose'),
            'protocol': ('cli.commands.protocol_main', 'Protocol'),
            'vault': ('cli.commands.vault_main', 'Vault'),
            'user': ('cli.commands.user_main', 'User'),
            'desktop': ('cli.gui.main', 'Desktop'),
            'gui': ('cli.gui.main', 'GUI'),  # Alias for desktop
        }

        if command in command_modules:
            try:
                module_path, cmd_name = command_modules[command]
                module = __import__(module_path, fromlist=['main'])
                # Adjust sys.argv to remove the subcommand
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                return module.main()
            except Exception as e:
                print(f"Error running {cmd_name}: {e}", file=sys.stderr)
                if os.environ.get('REDIACC_DEBUG'):
                    import traceback
                    traceback.print_exc()
                return 1

        # Setup command - show setup instructions
        if command == 'setup':
            print("Rediacc CLI Setup")
            print("\nThe package is already installed via pip/pipx.")
            print("\nAvailable commands:")
            print("  rediacc login          - Authenticate with Rediacc API")
            print("  rediacc protocol       - Manage protocol handlers")
            print("  rediacc --help         - Show all available commands")
            return 0

    # Check if this might be a dynamic command
    if len(sys.argv) > 1:
        # Get the first non-option argument (skip option values)
        potential_command = None
        skip_next = False
        for i, arg in enumerate(sys.argv[1:], 1):
            if skip_next:
                skip_next = False
                continue
            if arg.startswith('-'):
                # If this is an option that takes a value, skip the next arg
                if arg in ['--output', '-o', '--token', '-t'] and i < len(sys.argv) - 1:
                    skip_next = True
            else:
                # This is the command
                potential_command = arg
                break
        
        # Check if it's a known command
        # Note: workflow and auth are now routed via dispatcher, not here
        known_commands = set(API_ENDPOINTS.keys())
        
        if potential_command and potential_command not in known_commands and potential_command not in CLI_COMMANDS:
            # This might be a dynamic endpoint
            args, command = parse_dynamic_command(sys.argv)
            
            if command:
                # Set up logging
                setup_logging(verbose=args.verbose)
                logger = get_logger(__name__)
                
                if args.verbose:
                    logger.debug("Dynamic endpoint detected")
                    logger.debug(f"Command: {command}")
                    logger.debug(f"Arguments: {vars(args)}")
                
                # Set up config manager
                config_manager = TokenManager()
                config_manager.load_vault_info_from_config()
                
                if args.token:
                    if not TokenManager.validate_token(args.token):
                        error = f"Invalid token format: {TokenManager.mask_token(args.token)}"
                        print(format_output(None, args.output, None, error))
                        return 1
                    # Store token directly in config file for proper rotation
                    TokenManager.set_token(args.token)
                
                handler = CommandHandler(config_manager, args.output)
                
                # Handle the dynamic endpoint (it will check auth requirements internally)
                return handler.handle_dynamic_endpoint(command, args)
    
    # Normal flow for known commands
    # Reorder arguments to handle global options before command
    sys.argv = reorder_args(sys.argv)
    
    parser = setup_parser()
    args = parser.parse_args()
    
    setup_logging(verbose=args.verbose)
    logger = get_logger(__name__)
    
    if args.verbose:
        logger.debug("Rediacc CLI starting up")
        logger.debug(f"Command: {args.command}")
        logger.debug(f"Arguments: {vars(args)}")
    
    if not args.command:
        parser.print_help()
        return 1
    
    output_format = args.output
    
    # Set sandbox mode if requested
    if args.sandbox:
        os.environ['REDIACC_SANDBOX_MODE'] = 'true'
        # Initialize SuperClient with sandbox mode
        from ..core.api_client import SuperClient
        client = SuperClient()
        client.set_sandbox_mode(True)
        if args.verbose:
            logger.debug("Sandbox mode enabled - using https://sandbox.rediacc.com/api")
    
    config_manager = TokenManager()
    config_manager.load_vault_info_from_config()
    
    if args.token:
        if not TokenManager.validate_token(args.token):
            error = f"Invalid token format: {TokenManager.mask_token(args.token)}"
            output = format_output(None, output_format, None, error)
            print(output)
            return 1
        # Store token directly in config file for proper rotation
        TokenManager.set_token(args.token)
    
    handler = CommandHandler(config_manager, output_format)
    
    # Check if user is requesting help for a generic command
    if hasattr(args, 'help') and args.help and args.command in API_ENDPOINTS:
        # Show help for command or resource
        resource = getattr(args, 'resource', None)
        help_text = handler.generate_dynamic_help(args.command, resource)
        print(help_text)
        return 0

    # Note: workflow and auth are now handled via dispatcher, not here

    auth_not_required_commands = {
        ('user', 'activate'),
        ('create', 'company')
    }
    
    standalone_commands = ['bridge']
    
    if (args.command, getattr(args, 'resource', None)) not in auth_not_required_commands:
        if not config_manager.is_authenticated():
            error = "Not authenticated. Please login first."
            output = format_output(None, output_format, None, error)
            print(output)
            return 1
    
    if not hasattr(args, 'resource') or not args.resource:
        # Show available resources for the command if no resource specified
        if args.command in API_ENDPOINTS:
            help_text = handler.generate_dynamic_help(args.command)
            print(help_text)
            return 0
        else:
            error = f"No resource specified for command: {args.command}"
            output = format_output(None, output_format, None, error)
            print(output)
            return 1
    
    if args.command == 'update':
        return handler.update_resource(args.resource, args)
    elif args.command in standalone_commands:
        return handler.generic_command(args.command, args.resource, args)
    elif args.command in API_ENDPOINTS:
        return handler.generic_command(args.command, args.resource, args)
    else:
        # Check if this could be a direct endpoint call
        # If command is not in API_ENDPOINTS and doesn't have a resource, treat as endpoint
        if not hasattr(args, 'resource') or not args.resource:
            return handler.handle_dynamic_endpoint(args.command, args)
        else:
            return handler.generic_command(args.command, args.resource, args)

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(130)
    finally:
        # Shutdown telemetry
        shutdown_telemetry()