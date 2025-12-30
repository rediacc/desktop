#!/usr/bin/env python3
"""
SuperClient - Universal API Client for Rediacc CLI

This module provides a single, consolidated API client instance that can be used
across all CLI components (main CLI, GUI, tests, etc.) with intelligent
auto-detection of configuration options.
"""

import hashlib
import ipaddress
import json
import os
import sys
import time
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse

# Import from core module
from .config import TokenManager, get_required, api_mutex
# Import environment configuration
from .env_config import EnvironmentConfig
# Import telemetry
from .telemetry import track_api_call, track_event



class SuperClient:
    PASSWORD_SALT = 'Rd!@cc111$ecur3P@$w0rd$@lt#H@$h'
    USER_AGENT = "rediacc/1.0"
    MIDDLEWARE_ERROR_HELP = "\nPlease ensure the middleware is running.\nTry: ./go system up middleware"
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, sandbox_mode=False):
        if SuperClient._initialized:
            return

        SuperClient._initialized = True
        self.sandbox_mode = sandbox_mode
        self.user_agent = SuperClient.USER_AGENT
        self.base_headers = {"Content-Type": "application/json", "User-Agent": self.user_agent}
        self.config_manager = None
        self._vault_warning_shown = False
        self._test_mode_token = None  # Token storage for test mode
        self.use_requests = self._should_use_requests()
        
        if self.use_requests:
            try:
                import requests
                self.requests = requests
                self.session = requests.Session()
            except ImportError:
                self.use_requests = False
        
        
        # Log mode in verbose output
        if os.environ.get('REDIACC_DEBUG'):
            api_url = self.base_url
            print(f"DEBUG: API Client initialized - URL: {api_url}, Sandbox: {sandbox_mode}", file=sys.stderr)
    
    def _should_use_requests(self):
        if any(test_indicator in sys.argv[0] for test_indicator in ['test', 'pytest']):
            return True
        try:
            import requests
            return any(indicator in self.base_url for indicator in ['localhost', '127.0.0.1', ':7322'])
        except ImportError:
            return False

    def _is_lan_ip_address(self, url):
        """Check if URL points to a private/LAN IP address

        Returns True if the URL hostname is a private IP address (LAN),
        False if it's a public IP or domain name.
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or parsed.netloc.split(':')[0]
            ip = ipaddress.ip_address(hostname)
            return ip.is_private or ip.is_loopback or ip.is_link_local
        except (ValueError, AttributeError):
            # Not an IP address (likely a domain name) or parse error
            return False

    def _execute_http_request(self, url, method='POST', data=None, headers=None, timeout=None):
        timeout = timeout or self.request_timeout
        merged_headers = {**self.base_headers, **(headers or {})}
        
        if os.environ.get('REDIACC_DEBUG'):
            prefix = "[REQUESTS]" if self.use_requests else "[URLLIB]"
            print(f"DEBUG: {prefix} {method} {url}", file=sys.stderr)
            print(f"DEBUG: Headers: {merged_headers}", file=sys.stderr)
            if data:
                print(f"DEBUG: Payload: {json.dumps(data, indent=2)}", file=sys.stderr)
        
        return (self._execute_with_requests(url, method, data, merged_headers, timeout) 
               if self.use_requests else 
               self._execute_with_urllib(url, method, data, merged_headers, timeout))
    
    def _execute_with_requests(self, url, method, data, headers, timeout):
        try:
            # Disable SSL verification for LAN/private IP addresses
            verify_ssl = not self._is_lan_ip_address(url)
            response = getattr(self.session, method.lower())(
                url, json=data, headers=headers, timeout=timeout, verify=verify_ssl
            )
            return response.text, response.status_code, dict(response.headers)
        except self.requests.exceptions.RequestException as e:
            raise Exception(f"Request error: {str(e)}")
    
    def _execute_with_urllib(self, url, method, data, headers, timeout):
        import urllib.request, urllib.error
        import ssl

        try:
            req_data = json.dumps(data).encode('utf-8') if data else None
            req = urllib.request.Request(url, data=req_data, headers=headers, method=method.upper())

            # Create SSL context for LAN IPs to allow self-signed certificates
            context = None
            if self._is_lan_ip_address(url):
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE

            with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
                return response.read().decode('utf-8'), response.getcode(), dict(response.info())

        except urllib.error.HTTPError as e:
            raise Exception(f"HTTP {e.code}: {e.read().decode('utf-8') if e.fp else str(e)}")
        except urllib.error.URLError as e:
            raise Exception(f"Connection error: {str(e)}")
        except Exception as e:
            raise Exception(f"Request error: {str(e)}")
    
    def _prepare_request_for_api(self, endpoint, data=None, headers=None):
        url = f"{self.base_url}{self.api_prefix}/{endpoint}"
        prepared_data = data
        merged_headers = {**self.base_headers, **(headers or {})}
        
        master_pwd = self.config_manager.get_master_password() if self.should_use_vault_encryption else None
        if data and self.should_use_vault_encryption and master_pwd:
            try:
                from .config import encrypt_vault_fields
                prepared_data = encrypt_vault_fields(data, master_pwd)
            except Exception as e:
                from .config import colorize
                print(colorize(f"Warning: Failed to encrypt vault fields: {e}", 'YELLOW'))
        
        return url, prepared_data, merged_headers
    
    def _process_api_response(self, response_text, status_code):
        try:
            result = json.loads(response_text) if isinstance(response_text, str) else response_text
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON response: {response_text}", "status_code": 500}
        
        if result.get('failure') and result.get('failure') != 0:
            errors = result.get('errors', [])
            error_msg = f"API Error: {'; '.join(errors) if errors else result.get('message', 'Request failed')}"
            result.update({'error': error_msg, 'status_code': result.get('failure', 400)})
            return result
        
        master_pwd = self.config_manager.get_master_password() if self.should_use_vault_encryption else None
        if self.should_use_vault_encryption and master_pwd:
            try:
                from .config import decrypt_vault_fields
                result = decrypt_vault_fields(result, master_pwd)
            except Exception as e:
                from .config import colorize
                print(colorize(f"Warning: Failed to decrypt vault fields: {e}", 'YELLOW'))
        
        return result
    
    def _handle_http_error(self, error_msg, status_code):
        try:
            error_json = json.loads(error_msg)
            error_text = ('; '.join(error_json.get('errors', [])) or 
                         error_json.get('message') or 
                         error_json.get('error') or 
                         f"API Error: {status_code}")
            error_json.update({'error': error_text, 'status_code': status_code})
            return error_json
        except json.JSONDecodeError:
            return {"error": f"API Error: {status_code} - {error_msg}", "status_code": status_code}
    
    @property
    def base_url(self):
        # Check for saved endpoint from last login first
        from cli.core.config import TokenManager
        auth_info = TokenManager.get_auth_info()
        saved_endpoint = auth_info.get('endpoint')
        if saved_endpoint:
            return saved_endpoint

        # Check for sandbox mode
        sandbox_mode = getattr(self, 'sandbox_mode', False)

        # Check environment variable for sandbox mode
        if not sandbox_mode and 'REDIACC_SANDBOX_MODE' in os.environ:
            sandbox_mode = os.environ.get('REDIACC_SANDBOX_MODE').lower() == 'true'

        if sandbox_mode:
            # Get sandbox URL from environment or use from env_config
            return os.environ.get('SANDBOX_API_URL') or EnvironmentConfig.get_env('SANDBOX_API_URL')

        # Check build type (must be set in environment)
        build_type = os.environ.get('REDIACC_BUILD_TYPE')
        if not build_type:
            # Fall back to env_config
            build_type = EnvironmentConfig.get_env('REDIACC_BUILD_TYPE')

        if build_type and build_type.upper() == 'RELEASE':
            return os.environ.get('PUBLIC_API_URL') or EnvironmentConfig.get_env('PUBLIC_API_URL')
        else:
            return get_required('SYSTEM_API_URL')
    
    @property
    def api_prefix(self):
        base_url = self.base_url
        if base_url.endswith('/api') or '/api/' in base_url:
            return '/StoredProcedure'
        return '/api/StoredProcedure' if self.use_requests or ':7322' in base_url else '/StoredProcedure'
    
    @property
    def request_timeout(self):
        return 30
    
    @property
    def should_use_vault_encryption(self):
        return (self.config_manager and self.config_manager.get_master_password() and
                getattr(self.config_manager, 'has_vault_encryption', lambda: True)())
    
    def set_sandbox_mode(self, enabled=True):
        """Enable or disable sandbox mode for API calls"""
        self.sandbox_mode = enabled
        if os.environ.get('REDIACC_DEBUG'):
            api_url = self.base_url
            print(f"DEBUG: Sandbox mode {'enabled' if enabled else 'disabled'} - URL: {api_url}", file=sys.stderr)
    
    def set_config_manager(self, config_manager):
        self.config_manager = config_manager
        if config_manager and hasattr(config_manager, 'load_vault_info_from_config'):
            config_manager.load_vault_info_from_config()
    
    def ensure_config_manager(self):
        if self.config_manager is None:
            from .config import get_default_config_manager
            self.set_config_manager(get_default_config_manager())
    
    def request(self, endpoint, data=None, headers=None):
        start_time = time.time()
        url, prepared_data, merged_headers = self._prepare_request_for_api(endpoint, data, headers)

        try:
            response_text, status_code, response_headers = self._execute_http_request(
                url, 'POST', prepared_data, merged_headers)

            # Track API call telemetry
            duration_ms = (time.time() - start_time) * 1000
            track_api_call('POST', endpoint, status_code, duration_ms)

            if status_code >= 500:
                if os.environ.get('REDIACC_DEBUG'):
                    print(f"DEBUG: Endpoint URL: {url}\nDEBUG: HTTP Error {status_code} occurred", file=sys.stderr)

            return (self._process_api_response(response_text, status_code)
                   if status_code == 200 else
                   self._handle_http_error(response_text, status_code))

        except Exception as e:
            error_msg = str(e)
            duration_ms = (time.time() - start_time) * 1000

            # Track API error telemetry
            track_api_call('POST', endpoint, None, duration_ms, error_msg)

            if os.environ.get('REDIACC_DEBUG'):
                print(f"DEBUG: Request error for endpoint: {url}\nDEBUG: Error details: {error_msg}", file=sys.stderr)

            if "HTTP " in error_msg and ":" in error_msg:
                try:
                    status_code = int(error_msg.split("HTTP ")[1].split(":")[0])
                    error_body = error_msg.split(":", 1)[1].strip()
                    return self._handle_http_error(error_body, status_code)
                except (ValueError, IndexError):
                    pass

            return {"error": f"Request error: {error_msg}", "status_code": 500}
    
    def auth_request(self, endpoint, email, pwd_hash, data=None):
        """Make an authentication request with email and password hash"""
        # Track authentication attempt
        track_event('cli.auth_attempt', {
            'auth.endpoint': endpoint,
            'auth.email_domain': email.split('@')[1] if '@' in email else 'unknown'
        })

        result = self.request(endpoint, data, {"Rediacc-UserEmail": email, "Rediacc-UserHash": pwd_hash})

        # Track authentication result
        success = result.get('status_code', 500) == 200 and not result.get('error')
        track_event('cli.auth_result', {
            'auth.endpoint': endpoint,
            'auth.success': success,
            'auth.error': result.get('error', '') if not success else ''
        })

        return result
    
    def token_request(self, endpoint, data=None, retry_count=0):
        """Make an authenticated request with token"""
        try:
            with api_mutex.acquire(timeout=30.0):
                return self._token_request_impl(endpoint, data, retry_count)
        except TimeoutError as e:
            return {"error": f"API call timeout: {str(e)}", "status_code": 408}
        except Exception as e:
            return {"error": f"API call error: {str(e)}", "status_code": 500}
    
    def _token_request_impl(self, endpoint, data=None, retry_count=0):
        """Internal implementation of token request with retry logic"""
        token = TokenManager.get_token()
        if not token:
            return {"error": "Not authenticated. Please login first.", "status_code": 401}

        # DEBUG: Print token information for debugging
        if os.environ.get('REDIACC_DEBUG'):
            print(f"DEBUG: Making token request to endpoint '{endpoint}'", file=sys.stderr)
            print(f"DEBUG: Current token: {token[:16]}...{token[-8:] if len(token) > 24 else token}", file=sys.stderr)
            print(f"DEBUG: Token length: {len(token)} characters", file=sys.stderr)
            if retry_count > 0:
                print(f"DEBUG: Retry attempt: {retry_count}", file=sys.stderr)

        # Ensure vault info is loaded (for CLI usage)
        if (endpoint != 'GetOrganizationVault' and self.should_use_vault_encryption and
            self.config_manager and hasattr(self.config_manager, '_ensure_vault_info')):
            self.config_manager._ensure_vault_info()
            self._show_vault_warning_if_needed()

        response = self.request(endpoint, data, {"Rediacc-RequestToken": token})

        # DEBUG: Print response information for debugging
        if os.environ.get('REDIACC_DEBUG'):
            if response:
                print(f"DEBUG: Response status: {response.get('status_code', 'unknown')}", file=sys.stderr)
                if response.get('error'):
                    print(f"DEBUG: Response error: {response.get('error')}", file=sys.stderr)
                if 'nextRequestToken' in response or any('nextRequestToken' in str(rs) for rs in response.get('resultSets', [])):
                    print("DEBUG: New token found in response for rotation", file=sys.stderr)
            else:
                print("DEBUG: No response received from request", file=sys.stderr)

        # Handle token expiration with retry
        if response and response.get('status_code') == 401 and retry_count < 2:
            time.sleep(0.1 * (retry_count + 1))
            if TokenManager.get_token() != token:
                return self._token_request_impl(endpoint, data, retry_count + 1)
        
        self._update_token_if_needed(response, token)
        return response
    
    def _show_vault_warning_if_needed(self):
        """Show vault warning if encryption is required but no password is set"""
        if (self.config_manager and 
            hasattr(self.config_manager, 'has_vault_encryption') and 
            self.config_manager.has_vault_encryption() and 
            not self.config_manager.get_master_password() and 
            not self._vault_warning_shown):
            from .config import colorize
            print(colorize("Warning: Your organization requires vault encryption but no master password is set.", 'YELLOW'))
            print(colorize("Vault fields will not be decrypted. Use 'rediacc vault set-password' to set it.", 'YELLOW'))
            self._vault_warning_shown = True
    
    def _extract_token_from_response(self, response):
        """Extract nextRequestToken from response, prioritizing resultSets[0] for token rotation"""
        # First, check resultSets[0] which contains the main session token rotation
        result_sets = response.get('resultSets', [])
        if result_sets and len(result_sets) > 0:
            first_result_set = result_sets[0]
            if first_result_set and first_result_set.get('data'):
                for data_row in first_result_set['data']:
                    if data_row and isinstance(data_row, dict):
                        token = data_row.get('nextRequestToken') or data_row.get('NextRequestToken')
                        if token:
                            return token

        # Fallback to top-level response token
        return response.get('nextRequestToken') or response.get('NextRequestToken')
    
    def _update_token_if_needed(self, response, current_token):
        """Update authentication token if a new one is provided in the response"""
        if not response: return
        
        if not self.config_manager:
            if os.environ.get('REDIACC_DEBUG'): print("DEBUG: No config manager, initializing default for token rotation", file=sys.stderr)
            self.ensure_config_manager()
        
        new_token = self._extract_token_from_response(response)
        
        if os.environ.get('REDIACC_DEBUG'):
            if new_token: print(f"DEBUG: Found new token in response (length: {len(new_token)})", file=sys.stderr)
            else:
                print("DEBUG: No new token found in response", file=sys.stderr)
                if response:
                    import json
                    print(f"DEBUG: Response structure: {json.dumps(response, indent=2)}", file=sys.stderr)
        
        # Check if token rotation should be skipped
        skip_reasons = []
        if not new_token:
            skip_reasons.append("no new token found")
        if new_token == current_token:
            skip_reasons.append("new token same as current")

        if skip_reasons:
            if os.environ.get('REDIACC_DEBUG'):
                print(f"DEBUG: Token update skipped - {'; '.join(skip_reasons)}", file=sys.stderr)
            return

        # Token rotation is handled via config file
        if os.environ.get('REDIACC_DEBUG'):
            print(f"DEBUG: Token rotation proceeding - updating from {current_token[:8]}... to {new_token[:8]}...", file=sys.stderr)
        
        stored_token = TokenManager.get_token()
        if os.environ.get('REDIACC_DEBUG'):
            print(f"DEBUG: Checking token update condition: stored={stored_token[:8] if stored_token else 'None'}... vs current={current_token[:8] if current_token else 'None'}...", file=sys.stderr)
        
        if stored_token == current_token:
            if os.environ.get('REDIACC_DEBUG'): print(f"DEBUG: Updating token from {current_token[:8]}... to {new_token[:8]}...", file=sys.stderr)
            
            if hasattr(self.config_manager, 'config') and self.config_manager.config:
                config = self.config_manager.config
                TokenManager.set_token(new_token, 
                                     email=config.get('email'),
                                     organization=config.get('organization'),
                                     vault_organization=config.get('vault_organization'))
                if os.environ.get('REDIACC_DEBUG'):
                    print("DEBUG: Token updated via CLI config manager", file=sys.stderr)
            else:
                auth_info = TokenManager.get_auth_info()
                TokenManager.set_token(new_token,
                                     email=auth_info.get('email') if auth_info else None,
                                     organization=auth_info.get('organization') if auth_info else None,
                                     vault_organization=auth_info.get('vault_organization') if auth_info else None)
                if os.environ.get('REDIACC_DEBUG'):
                    print("DEBUG: Token updated via GUI auth info", file=sys.stderr)
        elif os.environ.get('REDIACC_DEBUG'):
            current_stored = TokenManager.get_token()
            print(f"DEBUG: Token not updated - stored token mismatch: {current_stored[:8] if current_stored else 'None'}... vs current: {current_token[:8] if current_token else 'None'}...", file=sys.stderr)
    
    def _ensure_vault_info(self):
        """Ensure vault info is loaded from API if needed (CLI-specific)"""
        if not (self.config_manager and self.config_manager.needs_vault_info_fetch()):
            return

        self.config_manager.mark_vault_info_fetched()
        organization_info = self.get_organization_vault()
        if not organization_info:
            return

        email = self.config_manager.config.get('email')
        token = TokenManager.get_token()
        if email and token:
            self.config_manager.set_auth(
                email, token, organization_info.get('organizationName'), organization_info.get('vaultOrganization'))

    def get_organization_vault(self):
        """Get organization vault information from API (CLI-specific)"""
        response = self.token_request("GetOrganizationVault", {})
        
        if response.get('error'):
            return None
        
        for table in response.get('resultSets', []):
            data = table.get('data', [])
            if not data:
                continue
            
            row = data[0]
            if 'nextRequestToken' in row:
                continue
            
            # Get vault content and organization credential
            vault_content = row.get('vaultContent') or row.get('VaultContent', '{}')
            organization_credential = row.get('organizationCredential') or row.get('OrganizationCredential')

            # Parse vault content and add ORGANIZATION_ID
            try:
                vault_dict = json.loads(vault_content) if vault_content and vault_content != '-' else {}
                if organization_credential:
                    vault_dict['ORGANIZATION_ID'] = organization_credential
                vault_json = json.dumps(vault_dict)
            except (json.JSONDecodeError, TypeError):
                vault_json = vault_content

            return {
                'organizationName': row.get('organizationName') or row.get('OrganizationName', ''),
                'organizationVault': vault_json,
                'vaultOrganization': row.get('vaultOrganization') or row.get('VaultOrganization', ''),
                'organizationCredential': organization_credential
            }
        
        return None
    
    def _make_direct_request(self, url, data=None, method='GET'):
        """Make direct HTTP request (not through stored procedure endpoint) - refactored to use central function"""
        headers = {"User-Agent": self.user_agent}
        if data:
            headers["Content-Type"] = "application/json"
        
        timeout = 30 if data else 5
        
        try:
            response_text, status_code, response_headers = self._execute_http_request(
                url, method, data, headers, timeout)
            
            if status_code >= 400:
                raise Exception(f"HTTP {status_code}: {response_text}")
            
            return json.loads(response_text)
            
        except Exception as e:
            error_msg = str(e)
            
            # Handle specific error messages for license server operations
            if "HTTP " in error_msg and ":" in error_msg:
                # Extract status code and body for license server errors
                try:
                    status_part = error_msg.split("HTTP ")[1].split(":")[0]
                    error_body = error_msg.split(":", 1)[1].strip()
                    raise Exception(f"License server error {status_part}: {error_body}")
                except (ValueError, IndexError):
                    pass
            
            # Provide context-specific error messages
            if data:
                raise Exception(f"Failed to connect to license server: {error_msg}")
            else:
                error_msg = f"Failed to generate hardware ID: {error_msg}"
                error_msg += SuperClient.MIDDLEWARE_ERROR_HELP
                raise Exception(error_msg)
    def hash_password(self, password: str) -> str:
        """Hash password with static salt"""
        salted = password + SuperClient.PASSWORD_SALT
        return '0x' + hashlib.sha256(salted.encode()).hexdigest()
    
    def get_universal_user_info(self) -> Tuple[str, str, Optional[str]]:
        """Get universal user info from environment or config
        Returns: (universal_user_name, universal_user_id, organization_id)
        """
        return EnvironmentConfig.get_universal_user_info()
    
    def get_organization_vault_defaults(self) -> Dict[str, Any]:
        """Get organization vault defaults from environment"""
        return EnvironmentConfig.get_organization_vault_defaults()
    
    def get_universal_user_name(self) -> str:
        """Get universal user name with guaranteed fallback"""
        return EnvironmentConfig.get_universal_user_name()
    
    def get_universal_user_id(self) -> str:
        """Get universal user ID with guaranteed fallback"""
        return EnvironmentConfig.get_universal_user_id()
    
    def execute_command(self, command: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a command through the API (for test compatibility)"""
        endpoint = self._map_command_to_endpoint(command)
        data = self._prepare_request_data(endpoint, args)
        headers = self._get_special_headers(endpoint, args)

        # Unauthenticated endpoints that should NOT send a token
        unauthenticated_endpoints = ['CreateNewOrganization', 'ActivateUserAccount',
                                   'CreateAuthenticationRequest', 'IsRegistered']

        # Use stored token for authenticated endpoints, empty string for unauthenticated
        token = '' if endpoint in unauthenticated_endpoints else (self._test_mode_token or '')
        result = self._make_test_request(endpoint, data, token=token, headers=headers)

        # Extract and store token from successful responses
        if result['success'] and result.get('data'):
            new_token = self._extract_token_from_response(result['data'])
            if new_token:
                self._test_mode_token = new_token

        # Handle logout - clear token
        if endpoint == 'DeleteUserRequest' and result['success']:
            self._test_mode_token = None

        return self._format_response(endpoint, result['data'], args) if result['success'] else result
    
    def _make_test_request(self, endpoint: str, data: Dict[str, Any],
                          token: Optional[str] = None,
                          headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Make API request with automatic token rotation (for testing)"""
        request_headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}

        # Add authentication token if provided (but not empty string)
        if token:  # Simple truthy check - empty string will not add header
            request_headers['Rediacc-RequestToken'] = token

        if headers:
            request_headers.update(headers)

        response = self.request(endpoint, data, request_headers)

        # Handle response for testing
        if 'error' not in response:
            return {'success': True, 'data': response, 'status_code': 200}
        else:
            return {'success': False, 'error': response['error'],
                   'status_code': response.get('status_code', 500)}
    
    def _format_response(self, endpoint: str, raw_response: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
        """Format API response to match test expectations"""
        data_rows = []
        if 'resultSets' in raw_response:
            for i, result_set in enumerate(raw_response['resultSets']):
                if i > 0 and 'data' in result_set:
                    data_rows.extend(result_set['data'])
        
        special_responses = {
            'CreateAuthenticationRequest': {
                'email': args.get('email'),
                'organization': None,
                'vault_encryption_enabled': False,
                'master_password_set': False
            },
            'DeleteUserRequest': {}
        }
        
        return {'success': True, 'data': special_responses.get(endpoint, data_rows)}
    
    def _map_command_to_endpoint(self, command: str) -> str:
        """Map CLI command to API endpoint"""
        if isinstance(command, list):
            command = command[0]
        
        return {'login': 'CreateAuthenticationRequest', 'logout': 'DeleteUserRequest'}.get(command, command)
    
    def _prepare_request_data(self, endpoint: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare request data based on endpoint requirements"""
        endpoint_data = {
            'CreateAuthenticationRequest': {'name': args.get('name', args.get('session_name', 'CLI Session'))},
            'PrivilegeAuthenticationRequest': {'TFACode': args.get('tfaCode', '')},
            'ActivateUserAccount': {'activationCode': args.get('activationCode', '')},
            'CreateNewOrganization': {
                'organizationName': args.get('organizationName', ''),
                **({'subscriptionPlan': args['subscriptionPlan']} if 'subscriptionPlan' in args else {})
            }
        }
        
        return {} if endpoint in ['GetRequestAuthenticationStatus'] else endpoint_data.get(endpoint, args)
    
    def _get_special_headers(self, endpoint: str, args: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Get special headers for certain endpoints"""
        # Endpoints that need email and passwordHash in headers
        auth_endpoints = ['CreateNewOrganization', 'ActivateUserAccount', 'CreateAuthenticationRequest']
        if endpoint in auth_endpoints:
            headers = {
                'Rediacc-UserEmail': args.get('email', ''),
                'Rediacc-UserHash': self.hash_password(args.get('password', ''))
            }
            
            # Special handling for CreateAuthenticationRequest
            # Authentication session setup handled by main CLI
            
            return headers
        
        # Other special cases
        special_headers = {
            'GetRequestAuthenticationStatus': {
                'Rediacc-UserEmail': args.get('email', '')
            },
            'PrivilegeAuthenticationRequest': {
                'Rediacc-UserEmail': args.get('email', ''),
                'totp': args.get('totp', '')
            }
        }
        
        return special_headers.get(endpoint)


class SimpleConfigManager:
    """Minimal config manager for SuperClient compatibility"""
    
    def __init__(self):
        self.config = {}
        self._master_password = None
    
    def get_master_password(self):
        return self._master_password
    
    def set_master_password(self, password):
        self._master_password = password
    
    def has_vault_encryption(self):
        auth_info = TokenManager.get_auth_info()
        return auth_info.get('vault_organization') if auth_info else False
    
    def needs_vault_info_fetch(self):
        return False
    
    
    def load_vault_info_from_config(self):
        pass


# Global singleton instance
client = SuperClient()

def get_client():
    """Get the global SuperClient instance"""
    return client

# Convenience functions for environment access
def get_universal_user_info() -> Tuple[str, str, Optional[str]]:
    """Get universal user info from environment or config"""
    return client.get_universal_user_info()

def get_organization_vault_defaults() -> Dict[str, Any]:
    """Get organization vault defaults from environment"""
    return client.get_organization_vault_defaults()