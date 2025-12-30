#!/usr/bin/env python3
"""
Telemetry service for Rediacc CLI

Provides telemetry tracking for CLI operations, similar to the console's
TypeScript telemetry service but adapted for Python CLI usage patterns.
"""

import json
import platform
import sys
import time
import uuid
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
import os

# Try to import requests, fall back to urllib if not available
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.parse
    HAS_REQUESTS = False


class TelemetryService:
    """
    CLI Telemetry service for tracking user interactions and system performance
    """

    def __init__(self,
                 endpoint: str = "https://www.rediacc.com/otlp/v1/traces",
                 service_name: str = "rediacc-cli",
                 service_version: str = "1.0.0",
                 enabled: bool = True):
        self.endpoint = endpoint
        self.service_name = service_name
        self.service_version = service_version
        self.enabled = enabled
        self.session_id = self._generate_session_id()
        self.session_start_time = time.time()
        self.user_context = {}
        self._init_lock = threading.Lock()
        self._initialized = False

        # Environment detection
        self.platform_info = {
            'os': platform.system().lower(),
            'os_version': platform.release(),
            'arch': platform.machine(),
            'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            'platform': platform.platform(),
            'hostname_hash': self._hash_hostname()
        }

    def _generate_session_id(self) -> str:
        """Generate a unique session ID"""
        return f"cli_session_{int(time.time())}_{uuid.uuid4().hex[:8]}"

    def _hash_hostname(self) -> str:
        """Create a privacy-safe hash of hostname for analytics"""
        try:
            import hashlib
            hostname = platform.node() or 'unknown'
            return hashlib.sha256(hostname.encode()).hexdigest()[:16]
        except Exception:
            return 'unknown'

    def initialize(self, user_context: Optional[Dict[str, Any]] = None) -> bool:
        """Initialize telemetry service with user context"""
        with self._init_lock:
            if self._initialized:
                return True

            try:
                if user_context:
                    self.user_context = user_context

                # Track CLI session start
                self.track_event('cli.session_start', {
                    'cli.version': self.service_version,
                    'cli.session_id': self.session_id,
                    **self.platform_info
                })

                self._initialized = True
                return True
            except Exception as e:
                self._log_error(f"Failed to initialize telemetry: {e}")
                return False

    def set_user_context(self, email: Optional[str] = None, organization: Optional[str] = None, **kwargs):
        """Set user context for telemetry"""
        self.user_context.update({
            'email_domain': email.split('@')[1] if email and '@' in email else 'unknown',
            'organization': organization or 'unknown',
            **kwargs
        })

    def track_event(self, event_name: str, attributes: Optional[Dict[str, Any]] = None):
        """Track a telemetry event"""
        if not self.enabled or not self._initialized:
            return

        try:
            # Prepare event data
            event_data = {
                'event_name': event_name,
                'timestamp': int(time.time() * 1000),  # milliseconds
                'session_id': self.session_id,
                'session_duration_ms': int((time.time() - self.session_start_time) * 1000),
                'service_name': self.service_name,
                'service_version': self.service_version,
                **self.platform_info,
                **self.user_context,
                **(attributes or {})
            }

            # Send telemetry data
            self._send_telemetry_data(event_data)

        except Exception as e:
            self._log_error(f"Failed to track event {event_name}: {e}")

    def track_command_execution(self, command: str, args: List[str],
                               duration_ms: float, success: bool,
                               error: Optional[str] = None, **kwargs):
        """Track CLI command execution"""
        self.track_event('cli.command_executed', {
            'command.name': command,
            'command.args_count': len(args),
            'command.duration_ms': duration_ms,
            'command.success': success,
            'command.error': error or '',
            'command.has_flags': any(arg.startswith('-') for arg in args),
            **kwargs
        })

    def track_api_call(self, method: str, endpoint: str, status_code: Optional[int] = None,
                      duration_ms: Optional[float] = None, error: Optional[str] = None):
        """Track API call performance and results"""
        self.track_event('cli.api_call', {
            'api.method': method.upper(),
            'api.endpoint': endpoint,
            'api.status_code': status_code or 0,
            'api.duration_ms': duration_ms or 0,
            'api.success': status_code is not None and 200 <= status_code < 400,
            'api.error': error or ''
        })

    def track_ssh_operation(self, operation: str, host: str, success: bool,
                           duration_ms: Optional[float] = None, error: Optional[str] = None):
        """Track SSH operations (connections, file transfers, etc.)"""
        # Hash host for privacy
        import hashlib
        host_hash = hashlib.sha256(host.encode()).hexdigest()[:16]

        self.track_event('cli.ssh_operation', {
            'ssh.operation': operation,
            'ssh.host_hash': host_hash,
            'ssh.success': success,
            'ssh.duration_ms': duration_ms or 0,
            'ssh.error': error or ''
        })

    def track_file_operation(self, operation: str, file_count: int, total_size_bytes: int,
                            duration_ms: float, success: bool, error: Optional[str] = None):
        """Track file operations (sync, upload, download)"""
        self.track_event('cli.file_operation', {
            'file.operation': operation,
            'file.count': file_count,
            'file.total_size_bytes': total_size_bytes,
            'file.duration_ms': duration_ms,
            'file.success': success,
            'file.error': error or '',
            'file.transfer_rate_bps': total_size_bytes / (duration_ms / 1000) if duration_ms > 0 else 0
        })

    def track_error(self, error_type: str, error_message: str, context: Optional[Dict[str, Any]] = None):
        """Track CLI errors and exceptions"""
        self.track_event('cli.error_occurred', {
            'error.type': error_type,
            'error.message': error_message[:200],  # Limit message length
            'error.context': json.dumps(context or {})[:500],  # Limit context size
        })

    def shutdown(self):
        """Shutdown telemetry service and send final metrics"""
        if not self.enabled or not self._initialized:
            return

        try:
            session_duration = int((time.time() - self.session_start_time) * 1000)
            self.track_event('cli.session_end', {
                'session.total_duration_ms': session_duration
            })
            self._initialized = False
        except Exception as e:
            self._log_error(f"Failed to shutdown telemetry: {e}")

    def _send_telemetry_data(self, data: Dict[str, Any]):
        """Send telemetry data to the endpoint"""
        try:
            # Convert to OpenTelemetry-like format
            trace_data = self._convert_to_otlp_format(data)

            if HAS_REQUESTS:
                self._send_with_requests(trace_data)
            else:
                self._send_with_urllib(trace_data)

        except Exception as e:
            self._log_error(f"Failed to send telemetry data: {e}")

    def _convert_to_otlp_format(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert event data to OpenTelemetry format"""
        return {
            "resourceSpans": [{
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": self.service_name}},
                        {"key": "service.version", "value": {"stringValue": self.service_version}},
                        {"key": "telemetry.sdk.name", "value": {"stringValue": "rediacc-cli-python"}},
                        {"key": "telemetry.sdk.version", "value": {"stringValue": "1.0.0"}}
                    ]
                },
                "scopeSpans": [{
                    "scope": {
                        "name": "rediacc-cli-events",
                        "version": "1.0.0"
                    },
                    "spans": [{
                        "traceId": uuid.uuid4().hex,
                        "spanId": uuid.uuid4().hex[:16],
                        "name": data.get('event_name', 'unknown_event'),
                        "startTimeUnixNano": data.get('timestamp', int(time.time() * 1000)) * 1000000,
                        "endTimeUnixNano": (data.get('timestamp', int(time.time() * 1000)) + 1) * 1000000,
                        "attributes": [
                            {"key": k, "value": {"stringValue": str(v)}}
                            for k, v in data.items()
                        ]
                    }]
                }]
            }]
        }

    def _send_with_requests(self, data: Dict[str, Any]):
        """Send telemetry using requests library"""
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': f'{self.service_name}/{self.service_version}'
        }

        try:
            response = requests.post(
                self.endpoint,
                json=data,
                headers=headers,
                timeout=10
            )
            # Don't raise for HTTP errors - telemetry should be non-blocking
            if response.status_code >= 400:
                self._log_error(f"Telemetry server returned HTTP {response.status_code}: {response.text[:200]}")
        except requests.exceptions.RequestException as e:
            self._log_error(f"Telemetry request failed: {e}")

    def _send_with_urllib(self, data: Dict[str, Any]):
        """Send telemetry using urllib (fallback)"""
        import urllib.request
        import urllib.error

        json_data = json.dumps(data).encode('utf-8')

        req = urllib.request.Request(
            self.endpoint,
            data=json_data,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': f'{self.service_name}/{self.service_version}'
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status >= 400:
                    self._log_error(f"Telemetry server returned HTTP {response.status}")
        except urllib.error.HTTPError as e:
            self._log_error(f"Telemetry HTTP error: {e.code} - {e.reason}")
        except urllib.error.URLError as e:
            self._log_error(f"Telemetry URL error: {e}")
        except Exception as e:
            self._log_error(f"Telemetry request failed: {e}")

    def _log_error(self, message: str):
        """Log telemetry errors (only in debug mode)"""
        if os.environ.get('REDIACC_DEBUG') or os.environ.get('REDIACC_TELEMETRY_DEBUG'):
            print(f"[Telemetry Debug] {message}", file=sys.stderr)


# Global telemetry instance
_telemetry_instance: Optional[TelemetryService] = None


def get_telemetry_service() -> TelemetryService:
    """Get or create the global telemetry service instance"""
    global _telemetry_instance

    if _telemetry_instance is None:
        # Check if telemetry is disabled
        enabled = not (
            os.environ.get('REDIACC_TELEMETRY_DISABLED', '').lower() in ('1', 'true', 'yes') or
            os.environ.get('DO_NOT_TRACK', '').lower() in ('1', 'true', 'yes')
        )

        _telemetry_instance = TelemetryService(enabled=enabled)

    return _telemetry_instance


def initialize_telemetry(user_context: Optional[Dict[str, Any]] = None) -> bool:
    """Initialize the global telemetry service"""
    return get_telemetry_service().initialize(user_context)


def track_event(event_name: str, attributes: Optional[Dict[str, Any]] = None):
    """Track a telemetry event using the global service"""
    get_telemetry_service().track_event(event_name, attributes)


def track_command_execution(command: str, args: List[str], duration_ms: float,
                           success: bool, error: Optional[str] = None, **kwargs):
    """Track CLI command execution using the global service"""
    get_telemetry_service().track_command_execution(command, args, duration_ms, success, error, **kwargs)


def track_api_call(method: str, endpoint: str, status_code: Optional[int] = None,
                  duration_ms: Optional[float] = None, error: Optional[str] = None):
    """Track API call using the global service"""
    get_telemetry_service().track_api_call(method, endpoint, status_code, duration_ms, error)


def shutdown_telemetry():
    """Shutdown the global telemetry service"""
    if _telemetry_instance:
        _telemetry_instance.shutdown()


# Command execution decorator
def track_command(command_name: str):
    """Decorator to automatically track command execution"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            success = False
            error = None

            try:
                result = func(*args, **kwargs)
                success = True
                return result
            except Exception as e:
                error = str(e)
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                track_command_execution(
                    command_name,
                    sys.argv[1:],
                    duration_ms,
                    success,
                    error
                )

        return wrapper
    return decorator


# Context manager for operation tracking
class track_operation:
    """Context manager for tracking operations with automatic timing"""

    def __init__(self, operation_name: str, **attributes):
        self.operation_name = operation_name
        self.attributes = attributes
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.time() - self.start_time) * 1000
        success = exc_type is None
        error = str(exc_val) if exc_val else None

        track_event(f'cli.operation.{self.operation_name}', {
            'operation.duration_ms': duration_ms,
            'operation.success': success,
            'operation.error': error or '',
            **self.attributes
        })