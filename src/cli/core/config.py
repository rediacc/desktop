#!/usr/bin/env python3
"""
Rediacc CLI Core Utilities - Consolidated module containing all core functionality
This module combines all the utility modules that were previously separate files.
"""

import os
import sys
import json
import time
import errno
import threading
import subprocess
import tempfile
import platform
import base64
import re
import logging
import contextlib
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

from cli.config import GUI_TRANSLATIONS_FILE

# ============================================================================
# CONFIG PATH MODULE (from config_path.py)
# ============================================================================

def get_cli_root() -> Path:
    """
    Get the CLI root directory (where src, scripts, tests, etc. are located)
    
    Returns:
        Path: The absolute path to the CLI root directory
    """
    # This module is in cli/src/cli, so go up 2 levels
    return Path(__file__).resolve().parent.parent.parent  # cli -> src -> cli


def get_config_dir() -> Path:
    """
    Get the configuration directory path (.rediacc)

    Checks in order:
    1. REDIACC_CONFIG_DIR environment variable (for Docker containers)
    2. User's home directory (~/.rediacc)

    The directory is created if it doesn't exist.

    Returns:
        Path: The absolute path to the configuration directory
    """
    config_dir = (
        Path(os.environ['REDIACC_CONFIG_DIR']).resolve()
        if 'REDIACC_CONFIG_DIR' in os.environ
        else Path.home() / '.rediacc'
    )
    config_dir.mkdir(exist_ok=True)
    return config_dir


def get_config_file(filename: str) -> Path:
    """
    Get the full path to a configuration file
    
    Args:
        filename: The name of the config file (e.g., 'config.json', 'language_preference.json')
    
    Returns:
        Path: The absolute path to the configuration file
    """
    return get_config_dir() / filename


# Convenience functions for common config files
def get_main_config_file() -> Path:
    """Get the path to the main config.json file"""
    return get_config_file('config.json')


def get_language_config_file() -> Path:
    """Get the path to the language preference file"""
    return get_config_file('language_preference.json')


def get_plugin_connections_file() -> Path:
    """Get the path to the plugin connections file"""
    return get_config_file('plugin-connections.json')


def get_terminal_cache_file() -> Path:
    """Get the path to the terminal cache file"""
    return get_config_file('terminal_cache.json')


def get_terminal_detector_cache_file() -> Path:
    """Get the path to the terminal detector cache file"""
    return get_config_file('terminal_detector_cache.json')


def get_api_lock_file() -> Path:
    """Get the path to the API mutex lock file"""
    return get_config_file('api_call.lock')


def get_token_lock_file() -> Path:
    """Get the path to the token manager lock file"""
    return get_config_file('.config.lock')


def get_ssh_control_dir() -> Path:
    """Get the SSH control directory for plugin connections"""
    ssh_dir = get_config_dir() / 'ssh-control'
    ssh_dir.mkdir(exist_ok=True)
    return ssh_dir


# ============================================================================
# LOGGING CONFIG MODULE (from logging_config.py)
# ============================================================================

def setup_logging(verbose: bool = False, log_file: Optional[str] = None) -> None:
    """
    Configure logging for the CLI application.
    
    Args:
        verbose: Enable verbose (DEBUG) logging
        log_file: Optional file path to write logs to
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = (
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        if verbose else
        '%(levelname)s: %(message)s'
    )
    
    # Configure handlers
    handlers = [
        logging.StreamHandler(sys.stderr)
    ]
    handlers[0].setFormatter(logging.Formatter(log_format))
    
    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        ))
        handlers.append(file_handler)
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        force=True  # Force reconfiguration if already configured
    )
    
    # Set specific loggers that might be too verbose
    if not verbose:
        # Suppress verbose output from third-party libraries
        for logger_name in ('urllib3', 'requests'):
            logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for the specified module.
    
    Args:
        name: Name of the logger (typically __name__)
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def is_verbose_enabled() -> bool:
    """
    Check if verbose logging is enabled.
    
    Returns:
        True if root logger is set to DEBUG level
    """
    return logging.getLogger().isEnabledFor(logging.DEBUG)


# ============================================================================
# CONFIG LOADER MODULE (from config_loader.py)
# ============================================================================

class ConfigError(Exception):
    """Raised when required configuration is missing"""
    pass

class Config:
    """Configuration manager for Rediacc CLI"""
    
    # Default configuration values
    DEFAULTS = {
        'SYSTEM_HTTP_PORT': '443',
        'SYSTEM_API_URL': 'https://www.rediacc.com/api',
        'SYSTEM_ORGANIZATION_NAME': 'REDIACC.IO',
        'SYSTEM_DEFAULT_TEAM_NAME': 'Private Team',
        'SYSTEM_DEFAULT_REGION_NAME': 'Default Region',
        'SYSTEM_DEFAULT_BRIDGE_NAME': 'Global Bridges',
        'SYSTEM_ORGANIZATION_VAULT_DEFAULTS': '{"UNIVERSAL_USER_ID":"7111","UNIVERSAL_USER_NAME":"rediacc","PLUGINS":{},"DOCKER_JSON_CONF":{}}',
        'DOCKER_REGISTRY': '192.168.111.1:5000',
        'REDIACC_LINUX_USER': 'rediacc',
        'REDIACC_LINUX_GROUP': 'rediacc',
        'REDIACC_USER_UID': '7111',
        'REDIACC_USER_GID': '7111',
        'REDIACC_TEST_ACTIVATION_CODE': '111111',
        'REDIACC_DEFAULT_THEME': 'dark',
        'REDIACC_TEMP_DIR': 'C:\\Windows\\Temp' if platform.system() == 'Windows' else '/tmp',
        'REDIACC_MSYS2_ROOT': 'C:\\msys64' if platform.system() == 'Windows' else None,
        'REDIACC_PYTHON_PATH': None,  # Will use system default if not set
        'REDIACC_CONFIG_DIR': None,  # Will use default path logic if not set
    }
    
    # Required configuration keys (must have valid values)
    REQUIRED_KEYS = {
        'SYSTEM_HTTP_PORT': 'Port for the Rediacc API server',
        'SYSTEM_API_URL': 'Full URL to the Rediacc API endpoint',
    }
    
    def __init__(self):
        self._config = {}
        self._loaded = False
        self.logger = get_logger(__name__)
    
    def load(self, env_file: Optional[str] = None):
        """Load configuration from defaults and environment variables"""
        if self._loaded: return
        self._load_defaults()
        self._load_from_environment()
        self._validate()
        self._loaded = True
    
    def _load_defaults(self):
        self._config = {k: v for k, v in self.DEFAULTS.items() if v is not None}
    
    def _load_from_environment(self):
        self._config.update({k: v for k, v in os.environ.items() if k in self.DEFAULTS})
        
        api_url = self._load_api_url_from_shared_config()
        if 'SYSTEM_API_URL' not in os.environ and api_url:
            self._config['SYSTEM_API_URL'] = api_url
    
    def _load_api_url_from_shared_config(self) -> Optional[str]:
        try:
            config_path = get_config_dir() / 'config.json'
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    return config.get('api_url') or config.get('apiUrl')
        except Exception:
            pass
        return None
    
    def _validate(self):
        missing = [f"  {key}: {description}" for key, description in self.REQUIRED_KEYS.items() if key not in self._config]
        if missing:
            raise ConfigError(f"Missing required configuration:\n{chr(10).join(missing)}\n\nPlease set these environment variables.")
    
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a configuration value"""
        if not self._loaded: self.load()
        return self._config.get(key, default)
    
    def get_required(self, key: str) -> str:
        value = self.get(key)
        if value is None: 
            raise ConfigError(f"Required configuration '{key}' is not set")
        return value
    
    def get_int(self, key: str, default: Optional[int] = None) -> Optional[int]:
        value = self.get(key)
        if value is None: return default
        try: return int(value)
        except ValueError: raise ConfigError(f"Configuration '{key}' must be an integer, got: {value}")
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key)
        return value.lower() in ('true', '1', 'yes', 'on') if value is not None else default
    
    def get_path(self, key: str, default: Optional[str] = None) -> Optional[Path]:
        value = self.get(key, default)
        return Path(os.path.expandvars(os.path.expanduser(value))) if value else None
    
    def print_config(self):
        """Print current configuration (for debugging)"""
        if not self._loaded: self.load()
        
        self.logger.debug("Current configuration:")
        self.logger.debug("-" * 40)
        self.logger.debug("Required:")
        for key in self.REQUIRED_KEYS:
            self.logger.debug(f"  {key}={self._config.get(key, '<NOT SET>')}")
        
        self.logger.debug("\nOptional (set):")
        for key in getattr(self, 'OPTIONAL_KEYS', []):
            if key in self._config:
                self.logger.debug(f"  {key}={self._config[key]}")
        
        if hasattr(self, 'OPTIONAL_KEYS'):
            unset = [k for k in self.OPTIONAL_KEYS if k not in self._config]
            if unset:
                self.logger.debug("\nOptional (not set):")
                for key in unset:
                    self.logger.debug(f"  {key}")

# Global config instance
_config = Config()

def get_config() -> Config:
    """Get the global configuration instance"""
    return _config

def load_config(env_file: Optional[str] = None):
    """Load configuration (safe to call multiple times)"""
    _config.load(env_file)

# Convenience functions
def get(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get a configuration value"""
    return _config.get(key, default)

def get_required(key: str) -> str:
    return _config.get_required(key)

def get_int(key: str, default: Optional[int] = None) -> Optional[int]:
    return _config.get_int(key, default)

def get_bool(key: str, default: bool = False) -> bool:
    return _config.get_bool(key, default)

def get_path(key: str, default: Optional[str] = None) -> Optional[Path]:
    return _config.get_path(key, default)


# API MUTEX MODULE

try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

class APIMutex:
    def __init__(self, lock_file: Path = None):
        if lock_file is None:
            lock_file = get_api_lock_file()
        
        self.lock_file = str(lock_file)
    
    @contextmanager
    def acquire(self, timeout: float = 30.0):
        start_time = time.time()
        lock_fd = None
        
        try:
            lock_fd = os.open(self.lock_file, os.O_CREAT | os.O_WRONLY)
            
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except IOError as e:
                    if e.errno != errno.EAGAIN:
                        raise
                    if time.time() - start_time > timeout:
                        raise TimeoutError(f"Could not acquire API lock after {timeout}s")
                    time.sleep(0.05)
            
            yield
            
        finally:
            if lock_fd is not None:
                with contextlib.suppress(Exception):
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                with contextlib.suppress(Exception):
                    os.close(lock_fd)

if not HAS_FCNTL and HAS_MSVCRT:
    class APIMutexWindows:
        def __init__(self, lock_file: Path = None):
            if lock_file is None:
                lock_file = get_api_lock_file()
            
            self.lock_file = str(lock_file)
        
        @contextmanager
        def acquire(self, timeout: float = 30.0):
            start_time = time.time()
            file_handle = None
            
            try:
                os.makedirs(os.path.dirname(self.lock_file), exist_ok=True)
                
                while True:
                    try:
                        file_handle = open(self.lock_file, 'wb')
                        msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except IOError:
                        if file_handle:
                            file_handle.close()
                            file_handle = None
                        if time.time() - start_time > timeout:
                            raise TimeoutError(f"Could not acquire API lock after {timeout}s")
                        time.sleep(0.05)
                
                yield
                
            finally:
                if file_handle:
                    with contextlib.suppress(Exception):
                        msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                    with contextlib.suppress(Exception):
                        file_handle.close()

if HAS_FCNTL:
    api_mutex = APIMutex()
elif HAS_MSVCRT:
    api_mutex = APIMutexWindows()
else:
    class APIMutexNoOp:
        def __init__(self, lock_file: Path = None):
            pass
        
        @contextmanager
        def acquire(self, timeout: float = 30.0):
            yield
    
    api_mutex = APIMutexNoOp()
    print("Warning: No file locking mechanism available", file=sys.stderr)


def _clean_environment():
    """Get environment copy without token variables to prevent stale token propagation"""
    return {k: v for k, v in os.environ.items() if not k.startswith('REDIACC_TOKEN')}

# TOKEN MANAGER MODULE

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = get_logger(__name__)


def is_encrypted(value: str) -> bool:
    if not value or len(value) < 20: return False
    # Check if it's valid JSON first - if so, it's not encrypted
    try:
        json.loads(value)
        return False  # It's JSON, not encrypted
    except (json.JSONDecodeError, ValueError):
        pass  # Not JSON, could be encrypted
    # Now check if it's base64-encoded binary data
    try: return len(base64.b64decode(value)) >= 32
    except Exception: return False


def decrypt_string(encrypted: str, password: str) -> str:
    if not CRYPTO_AVAILABLE: raise RuntimeError("Cryptography library not available")
    
    combined = base64.b64decode(encrypted)
    salt, iv, ciphertext_and_tag = combined[:16], combined[16:28], combined[28:]
    
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000, backend=default_backend())
    key = kdf.derive(password.encode('utf-8'))
    
    aesgcm = AESGCM(key)
    try: return aesgcm.decrypt(iv, ciphertext_and_tag, None).decode('utf-8')
    except Exception as e: raise ValueError(f"Decryption failed: {e}")


class TokenManager:
    """Centralized token management with secure storage - Singleton implementation"""
    
    # Class-level attributes for singleton
    _instance = None
    _lock = threading.Lock()
    _initialized = False
    
    # Static attributes
    _config_dir: Optional[Path] = None
    _config_file: Optional[Path] = None
    _lock_file: Optional[Path] = None
    
    def __new__(cls):
        """Ensure only one instance exists"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not TokenManager._initialized:
            with TokenManager._lock:
                if not TokenManager._initialized:
                    self._initialize()
                    self._master_password = None
                    self._vault_organization = None
                    self._organization_name = None
                    self._vault_info_fetched = False
                    TokenManager._initialized = True
    
    @classmethod
    def _initialize(cls):
        config_dir = get_config_dir()
        
        if 'MSYSTEM' in os.environ:
            config_dir_str = str(config_dir)
            
            if not config_dir.exists():
                if config_dir_str.startswith(('C:', 'c:')):
                    drive = config_dir_str[0].lower()
                    rest = config_dir_str[2:].replace('\\', '/')
                    
                    msys2_path = f'/{drive}{rest}'
                    if Path(msys2_path).exists():
                        config_dir = Path(msys2_path)
                        logger.debug(f"MSYS2: Using converted path: {msys2_path}")
                    else:
                        wsl_path = f'/mnt/{drive}{rest}'
                        if Path(wsl_path).exists():
                            config_dir = Path(wsl_path)
                            logger.debug(f"MSYS2: Using WSL fallback path: {wsl_path}")
            
        logger.debug(f"TokenManager using local config: {config_dir}")
        
        cls._config_dir = Path(config_dir)
        cls._config_file = get_main_config_file()
        cls._lock_file = get_token_lock_file()
        cls._ensure_secure_config()
    
    @classmethod
    def _ensure_secure_config(cls):
        try:
            cls._config_dir.mkdir(mode=0o700, exist_ok=True)
        except OSError:
            cls._config_dir.mkdir(exist_ok=True)
        
        if cls._config_file.exists():
            with contextlib.suppress(OSError, NotImplementedError):
                cls._config_file.chmod(0o600)
    
    @classmethod
    def _load_from_config(cls) -> Dict[str, Any]:
        # Create a file lock for config operations
        config_lock_file = cls._config_dir / '.config.lock'
        config_mutex = APIMutex(lock_file=config_lock_file) if HAS_FCNTL else APIMutexWindows(lock_file=config_lock_file) if HAS_MSVCRT else APIMutexNoOp()
        
        try:
            with config_mutex.acquire(timeout=10.0):
                with cls._lock:  # Keep threading lock for backward compatibility
                    if not cls._config_file.exists():
                        return {}
                    
                    try:
                        with open(cls._config_file, 'r') as f:
                            return json.load(f)
                    except (json.JSONDecodeError, IOError) as e:
                        logger.error(f"Failed to load config: {e}")
                        return {}
        except TimeoutError:
            logger.error("Timeout acquiring config lock for read - another process may be updating the config")
            return {}
    
    @classmethod
    def _save_config(cls, config: Dict[str, Any]):
        import platform
        import shutil
        
        # Create a file lock for config operations
        config_lock_file = cls._config_dir / '.config.lock'
        config_mutex = APIMutex(lock_file=config_lock_file) if HAS_FCNTL else APIMutexWindows(lock_file=config_lock_file) if HAS_MSVCRT else APIMutexNoOp()
        
        try:
            with config_mutex.acquire(timeout=10.0):
                with cls._lock:  # Keep threading lock for backward compatibility
                    cls._config_dir.mkdir(mode=0o700, exist_ok=True)
                    
                    is_windows = platform.system() == 'Windows' or 'MSYSTEM' in os.environ
                    max_retries = 3 if is_windows else 1
                    
                    for attempt in range(max_retries):
                        temp_file = cls._config_file.with_suffix(f'.tmp.{attempt}.{int(time.time())}')
                        try:
                            with open(temp_file, 'w') as f: json.dump(config, f, indent=2)
                            if not is_windows: temp_file.chmod(0o600)
                            
                            if is_windows and cls._config_file.exists():
                                with contextlib.suppress(OSError): cls._config_file.unlink()
                            
                            shutil.move(str(temp_file), str(cls._config_file)) if is_windows else temp_file.replace(cls._config_file)
                            if not is_windows: cls._config_file.chmod(0o600)
                            return
                            
                        except OSError as e:
                            logger.warning(f"Config save attempt {attempt + 1} failed: {e}")
                            if temp_file.exists():
                                with contextlib.suppress(OSError): temp_file.unlink()
                            if attempt < max_retries - 1: time.sleep(0.1 * (attempt + 1))
                            else: logger.error(f"Failed to save config after {max_retries} attempts: {e}"); raise
                        except Exception as e:
                            logger.error(f"Failed to save config: {e}")
                            if temp_file.exists():
                                with contextlib.suppress(OSError): temp_file.unlink()
                            raise
        except TimeoutError:
            logger.error("Timeout acquiring config lock - another process may be updating the config")
            raise
    
    @classmethod
    def get_token(cls, override_token: Optional[str] = None) -> Optional[str]:
        if not cls._initialized:
            TokenManager()

        if override_token:
            if cls.validate_token(override_token):
                if os.environ.get('REDIACC_DEBUG'):
                    print(f"DEBUG: Using override token: {override_token[:16]}...{override_token[-8:] if len(override_token) > 24 else override_token}", file=sys.stderr)
                return override_token
            if os.environ.get('REDIACC_DEBUG'):
                print("DEBUG: Override token provided but invalid format", file=sys.stderr)
            logger.warning("Invalid override token format")
            return None

        # Use config file token
        try:
            config = cls._load_from_config()
            token = config.get('token')
            if token and cls.validate_token(token):
                if os.environ.get('REDIACC_DEBUG'):
                    print(f"DEBUG: Using token from config file: {token[:16]}...{token[-8:] if len(token) > 24 else token}", file=sys.stderr)
                return token

            if os.environ.get('REDIACC_DEBUG'):
                if token:
                    print(f"DEBUG: Token in config file is invalid format: {token[:16]}...{token[-8:] if len(token) > 24 else token}", file=sys.stderr)
                else:
                    print("DEBUG: No token found in config file", file=sys.stderr)
        except Exception as e:
            if os.environ.get('REDIACC_DEBUG'):
                print(f"DEBUG: Error loading config: {e}", file=sys.stderr)

        if os.environ.get('REDIACC_DEBUG'):
            print("DEBUG: No valid token found from any source", file=sys.stderr)
        return None
    
    @classmethod
    def set_token(cls, token: str, email: Optional[str] = None, organization: Optional[str] = None, vault_organization: Optional[str] = None, endpoint: Optional[str] = None):
        if not cls._initialized: TokenManager()
        if not cls.validate_token(token): raise ValueError("Invalid token format")

        config = cls._load_from_config()

        config['token'] = token
        config['token_updated_at'] = datetime.now(timezone.utc).isoformat()

        if email:
            config['email'] = email
        if organization:
            config['organization'] = organization
        if vault_organization is not None:
            config['vault_organization'] = vault_organization
        if endpoint:
            config['endpoint'] = endpoint

        cls._save_config(config)
    
    @classmethod
    def clear_token(cls):
        """Clear token and authentication information"""
        # Ensure initialization
        if not cls._initialized:
            TokenManager()
            
        config = cls._load_from_config()

        # Remove auth-related fields
        auth_fields = ['token', 'token_updated_at', 'email', 'organization', 'vault_organization', 'endpoint']
        for field in auth_fields:
            config.pop(field, None)

        cls._save_config(config)
    
    @classmethod
    def get_auth_info(cls) -> Dict[str, Any]:
        """Get all authentication-related information"""
        # Ensure initialization
        if not cls._initialized:
            TokenManager()

        config = cls._load_from_config()
        return {
            'token': cls.mask_token(config.get('token')),
            'email': config.get('email'),
            'organization': config.get('organization'),
            'vault_organization': config.get('vault_organization'),
            'has_vault': bool(config.get('vault_organization')),
            'endpoint': config.get('endpoint'),
            'token_updated_at': config.get('token_updated_at')
        }
    
    @staticmethod
    def validate_token(token: Optional[str]) -> bool:
        """Validate token format (UUID/GUID)"""
        if not token:
            return False
        
        # GUID pattern: 8-4-4-4-12 hexadecimal digits
        guid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        return bool(re.match(guid_pattern, token, re.IGNORECASE))
    
    @staticmethod
    def mask_token(token: Optional[str]) -> Optional[str]:
        """Mask token for display (show only first 8 chars)"""
        return f"{token[:8]}..." if token and len(token) >= 12 else None
    
    @classmethod
    def is_authenticated(cls) -> bool:
        """Check if a valid token is available"""
        return cls.get_token() is not None
    
    @classmethod
    def get_config_value(cls, key: str) -> Any:
        """Get any config value"""
        # Ensure initialization
        if not cls._initialized:
            TokenManager()
            
        return cls._load_from_config().get(key)
    
    @classmethod
    def set_config_value(cls, key: str, value: Any):
        """Set any config value"""
        # Ensure initialization
        if not cls._initialized:
            TokenManager()
            
        config = cls._load_from_config()
        config[key] = value
        cls._save_config(config)
    
    @classmethod
    def set_api_url(cls, api_url: str):
        """Set API URL in config (compatible with desktop app)"""
        # Ensure initialization
        if not cls._initialized:
            TokenManager()
            
        config = cls._load_from_config()
        # Save in snake_case for CLI compatibility
        config['api_url'] = api_url
        cls._save_config(config)
    
    @classmethod
    def get_api_url(cls) -> Optional[str]:
        """Get API URL from config"""
        # Ensure initialization
        if not cls._initialized:
            TokenManager()
            
        config = cls._load_from_config()
        # Support both snake_case and camelCase
        return config.get('api_url') or config.get('apiUrl')
    
    # Master Password Management (in-memory only)
    def set_master_password(self, password: str):
        """Set master password in memory only"""
        self._master_password = password
    
    def get_master_password(self) -> Optional[str]:
        """Get master password from memory"""
        return self._master_password
    
    def clear_master_password(self):
        """Clear master password from memory"""
        self._master_password = None
    
    # Vault Management
    def has_vault_encryption(self) -> bool:
        """Check if organization has vault encryption enabled"""
        # Try to get vault organization from memory first, then config
        vault_organization = self._vault_organization or self.get_config_value('vault_organization')
        return bool(vault_organization and is_encrypted(vault_organization))
    
    def get_vault_organization(self) -> Optional[str]:
        """Get vault organization value"""
        return self._vault_organization or self.get_config_value('vault_organization')
    
    def validate_master_password(self, password: str) -> bool:
        """Validate master password against VaultOrganization"""
        vault_organization = self.get_vault_organization()
        
        if not vault_organization:
            return False
        
        if not is_encrypted(vault_organization):
            return True  # No encryption required
        
        try:
            # Try to decrypt the vault content
            decrypted = decrypt_string(vault_organization, password)
            # If decryption succeeds, the password is valid
            # The decrypted content should be valid JSON (even if it's just {})
            json.loads(decrypted)
            return True
        except Exception:
            # Decryption failed or result is not valid JSON - wrong password
            return False
    
    # Session State Management
    def needs_vault_info_fetch(self) -> bool:
        """Check if we need to fetch vault info"""
        # Need to fetch if authenticated but don't have vault info
        return self.is_authenticated() and not self._vault_info_fetched and not self.get_vault_organization()
    
    def mark_vault_info_fetched(self):
        """Mark that we've attempted to fetch vault info this session"""
        self._vault_info_fetched = True
    
    def load_vault_info_from_config(self):
        """Load vault info from saved config"""
        config = self._load_from_config()
        self._vault_organization = config.get('vault_organization')
        self._organization_name = config.get('organization')
    
    
    # Enhanced set_token to update internal state
    @classmethod
    def set_token_with_auth(cls, token: str, email: Optional[str] = None,
                           organization: Optional[str] = None, vault_organization: Optional[str] = None, endpoint: Optional[str] = None):
        """Set token and authentication information (ConfigManager compatibility)"""
        instance = cls()
        cls.set_token(token, email, organization, vault_organization, endpoint)

        # Update instance state
        if organization:
            instance._organization_name = organization
        if vault_organization:
            instance._vault_organization = vault_organization
    
    # Enhanced clear method
    @classmethod 
    def clear_auth(cls):
        """Clear all authentication information (ConfigManager compatibility)"""
        instance = cls()
        cls.clear_token()
        
        # Clear instance state
        instance._master_password = None
        instance._vault_organization = None
        instance._organization_name = None
        instance._vault_info_fetched = False
    
    # ConfigManager compatibility property
    @property
    def config(self) -> Dict[str, Any]:
        """Get current configuration dict (ConfigManager compatibility)"""
        return self._load_from_config()


# For backward compatibility - these functions now use the singleton
def get_default_token_manager() -> TokenManager:
    """Get the default token manager instance"""
    return TokenManager()

def get_default_config_manager() -> TokenManager:
    """Get the default config manager instance (TokenManager implements config manager interface)"""
    config_manager = TokenManager()
    config_manager.load_vault_info_from_config()
    return config_manager


# ============================================================================
# I18N MODULE (from i18n.py)
# ============================================================================

class I18n:
    """Internationalization manager for GUI application"""
    
    def __init__(self):
        # Load configuration from JSON file
        self._load_config()
        self.current_language = self.load_language_preference()
        self._observers = []
    
    def _load_config(self):
        """Load languages and translations from JSON configuration file"""
        if not GUI_TRANSLATIONS_FILE.exists():
            raise FileNotFoundError(f"Translation configuration file not found: {GUI_TRANSLATIONS_FILE}")

        try:
            with open(GUI_TRANSLATIONS_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            self.LANGUAGES = config.get('languages', {})
            self.DEFAULT_LANGUAGE = config.get('default_language', 'en')
            self.translations = config.get('translations', {})
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in translation configuration: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to load translation configuration: {e}")
    
    
    def get_language_config_path(self) -> Path:
        """Get the path to the language configuration file"""
        # Use centralized config directory
        return get_config_dir() / 'language_preference.json'
    
    def load_language_preference(self) -> str:
        """Load the saved language preference"""
        config_path = self.get_language_config_path()
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    lang = data.get('language', self.DEFAULT_LANGUAGE)
                    if lang in self.LANGUAGES:
                        return lang
            except Exception:
                pass
        return self.DEFAULT_LANGUAGE
    
    def save_language_preference(self, language: str):
        """Save the language preference"""
        if language not in self.LANGUAGES:
            return
        
        config_path = self.get_language_config_path()
        with contextlib.suppress(Exception):
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump({'language': language}, f, ensure_ascii=False, indent=2)
    
    def set_language(self, language: str):
        """Set the current language"""
        logger = get_logger(__name__)
        logger.debug(f"Setting language from {self.current_language} to {language}")
        
        if language in self.LANGUAGES:
            self.current_language = language
            self.save_language_preference(language)
            logger.debug(f"Language changed successfully to {language}")
            self._notify_observers()
        else:
            logger.warning(f"Attempted to set invalid language: {language}")
    
    def get(self, key: str, fallback: str = None, **kwargs) -> str:
        """Get a translated string for the current language
        
        Args:
            key: The translation key
            fallback: Optional fallback value if key not found
            **kwargs: Format arguments for the translation string
        """
        translation = (
            self.translations.get(self.current_language, {}).get(key) or
            self.translations.get('en', {}).get(key) or
            (fallback if fallback is not None else key)
        )
        
        # Format with provided arguments
        if kwargs:
            with contextlib.suppress(Exception):
                translation = translation.format(**kwargs)
        
        return translation
    
    def register_observer(self, callback):
        """Register a callback to be called when language changes"""
        self._observers.append(callback)
    
    def unregister_observer(self, callback):
        """Unregister a language change callback"""
        if callback in self._observers:
            self._observers.remove(callback)
    
    def _notify_observers(self):
        """Notify all observers of language change"""
        logger = get_logger(__name__)
        logger.debug(f"Notifying {len(self._observers)} observers of language change to {self.current_language}")
        
        for callback in self._observers:
            try:
                callback()
                logger.debug(f"Successfully called observer: {callback.__name__ if hasattr(callback, '__name__') else callback}")
            except Exception as e:
                logger.error(f"Error calling language observer {callback}: {e}", exc_info=True)
    
    def get_language_name(self, code: str) -> str:
        """Get the display name for a language code"""
        return self.LANGUAGES.get(code, code)
    
    def get_language_codes(self) -> list:
        """Get list of available language codes"""
        return list(self.LANGUAGES.keys())
    
    def get_language_names(self) -> list:
        """Get list of language display names"""
        return list(self.LANGUAGES.values())


# Singleton instance
i18n = I18n()


# ============================================================================
# SUBPROCESS RUNNER MODULE (from subprocess_runner.py)
# ============================================================================

class SubprocessRunner:
    """Runs CLI commands and captures output"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        # Store original paths (works on both Windows and Linux)
        # Current file: src/cli/core/config.py
        # We want to get to: src/cli/commands/
        current_dir = os.path.dirname(os.path.abspath(__file__))  # src/cli/core
        cli_dir = os.path.dirname(current_dir)  # src/cli
        self.cli_dir = cli_dir
        
        # All command files are in src/cli/commands/
        commands_dir = os.path.join(cli_dir, 'commands')
        self.cli_path = os.path.join(commands_dir, 'cli_main.py')
        self.sync_path = os.path.join(commands_dir, 'sync_main.py')
        self.term_path = os.path.join(commands_dir, 'term_main.py')
        self.plugin_path = os.path.join(commands_dir, 'plugin_main.py')
        
        # Wrapper is at the root level (src/../rediacc)
        root_dir = os.path.dirname(os.path.dirname(cli_dir))  # Go up from src/cli to root
        self.wrapper_path = os.path.join(root_dir, 'rediacc')
        
        # Debug: Log the constructed paths
        if os.environ.get('REDIACC_DEBUG'):
            self.logger.debug(f"SubprocessRunner paths:")
            self.logger.debug(f"  cli_dir: {self.cli_dir}")
            self.logger.debug(f"  plugin_path: {self.plugin_path} (exists: {os.path.exists(self.plugin_path)})")
            self.logger.debug(f"  cli_path: {self.cli_path} (exists: {os.path.exists(self.cli_path)})")
            self.logger.debug(f"  sync_path: {self.sync_path} (exists: {os.path.exists(self.sync_path)})")
            self.logger.debug(f"  term_path: {self.term_path} (exists: {os.path.exists(self.term_path)})")
        
        # Check for MSYS2 on Windows for better compatibility
        self.msys2_path = self._find_msys2_installation() if platform.system().lower() == 'windows' else None
        self.use_msys2_python = False
            
        self.python_cmd = self._find_python()
        
        # If using MSYS2 Python, convert paths to MSYS2 format
        if self.use_msys2_python:
            convert = self._windows_to_msys2_path
            self.cli_dir_msys2 = convert(self.cli_dir)
            self.cli_path_msys2 = convert(self.cli_path)
            self.sync_path_msys2 = convert(self.sync_path)
            self.term_path_msys2 = convert(self.term_path)
            self.plugin_path_msys2 = convert(self.plugin_path)
        else:
            # Use original paths
            self.cli_dir_msys2 = self.cli_dir
            self.cli_path_msys2 = self.cli_path
            self.sync_path_msys2 = self.sync_path
            self.term_path_msys2 = self.term_path
            self.plugin_path_msys2 = self.plugin_path
    
    def _find_msys2_installation(self):
        """Find MSYS2 installation path on Windows"""
        msys2_paths = [
            'C:\\msys64',
            'C:\\msys2',
            os.path.expanduser('~\\msys64'),
            os.path.expanduser('~\\msys2'),
        ]
        
        # Check MSYS2_ROOT environment variable
        msys2_root = os.environ.get('MSYS2_ROOT')
        if msys2_root:
            msys2_paths.insert(0, msys2_root)
        
        return next((path for path in msys2_paths if os.path.exists(path)), None)

    def _windows_to_msys2_path(self, windows_path):
        """Convert Windows path to MSYS2 format"""
        if not windows_path:
            return windows_path
            
        # Convert C:\path\to\file to /c/path/to/file
        if len(windows_path) >= 2 and windows_path[1] == ':':
            drive = windows_path[0].lower()
            rest = windows_path[2:].replace('\\', '/')
            return f'/{drive}{rest}'
        return windows_path.replace('\\', '/')

    def _find_python(self) -> str:
        """Find the correct Python command to use"""
        import shutil
        
        self.logger.debug("Finding Python command...")
        self.logger.debug(f"MSYS2 path: {self.msys2_path}")
        
        # Try different Python commands in order of preference
        # On Windows, try 'python' first since 'python3' usually doesn't exist
        python_commands = ['python', 'python3', 'py'] if platform.system().lower() == 'windows' else ['python3', 'python', 'py']
        self.logger.debug(f"Trying Python commands: {python_commands}")
        
        for cmd in python_commands:
            self.logger.debug(f"Testing command: {cmd}")
            if not shutil.which(cmd):
                self.logger.debug(f"{cmd} not found in PATH")
                continue
                
            try:
                # Test if it actually works and is Python 3+
                result = subprocess.run([cmd, '--version'], 
                                      capture_output=True, text=True, timeout=5)
                self.logger.debug(f"{cmd} version check: returncode={result.returncode}, stdout='{result.stdout.strip()}'")
                if result.returncode == 0 and 'Python 3' in result.stdout:
                    self.logger.debug(f"Using Python command: {cmd}")
                    return cmd
            except Exception as e:
                self.logger.debug(f"Error testing {cmd}: {e}")
        
        # Fallback to python3 on Unix, python on Windows if nothing found (will fail gracefully)
        fallback = 'python' if platform.system().lower() == 'windows' else 'python3'
        self.logger.debug(f"No suitable Python found, falling back to '{fallback}'")
        return fallback
    
    def run_command(self, args: List[str], timeout: Optional[int] = None) -> Dict[str, Any]:
        """Run a command and return output"""
        try:
            # Set up environment for MSYS2 if available
            env = os.environ.copy()
            if self.msys2_path and platform.system().lower() == 'windows':
                # Add MSYS2 paths to environment
                msys2_bin = os.path.join(self.msys2_path, 'usr', 'bin')
                mingw64_bin = os.path.join(self.msys2_path, 'mingw64', 'bin')
                env['PATH'] = f"{msys2_bin};{mingw64_bin};{env.get('PATH', '')}"
            
            # Build command based on first argument
            cmd_map = {
                'sync': (self.sync_path_msys2, 'Sync command'),
                'term': (self.term_path_msys2, 'Term command'),
                'plugin': (self.plugin_path_msys2, 'Plugin command')
            }
            
            if args[0] in cmd_map:
                script_path, log_msg = cmd_map[args[0]]
                cmd = [self.python_cmd, script_path] + args[1:]
                self.logger.debug(f"{log_msg}: {cmd}")
            else:
                cmd = [self.wrapper_path] + args
                self.logger.debug(f"Wrapper command: {cmd}")
            
            self.logger.debug(f"Executing command in directory: {self.cli_dir}")
            self.logger.debug(f"Environment PATH includes: {env.get('PATH', 'Not set')[:200]}...")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=self.cli_dir, env=env)
            
            self.logger.debug(f"Command completed with return code: {result.returncode}")
            if result.stdout:
                self.logger.debug(f"STDOUT: {result.stdout[:500]}...")
            if result.stderr:
                self.logger.debug(f"STDERR: {result.stderr[:500]}...")
            
            return {
                'success': result.returncode == 0,
                'output': result.stdout,
                'error': result.stderr,
                'returncode': result.returncode
            }
        except subprocess.TimeoutExpired:
            self.logger.error(f"Command timed out: {cmd}")
            return {'success': False, 'output': '', 'error': 'Command timed out', 'returncode': -1}
        except Exception as e:
            self.logger.error(f"Error executing command: {cmd}")
            self.logger.error(f"Exception: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'output': '', 'error': str(e), 'returncode': -1}
    
    def run_cli_command(self, args: List[str], timeout: Optional[int] = None) -> Dict[str, Any]:
        """DEPRECATED: Use direct API calls instead.
        This method is kept for backward compatibility with plugin operations.
        For API operations, use the APIClient class directly."""
        self.logger.warning("run_cli_command is deprecated. Use direct API calls for better performance.")
        try:
            # Don't pass token via command line - let rediacc read it from TokenManager
            # This avoids issues with token rotation and ensures fresh tokens are always used
            
            cli_cmd = [self.python_cmd, self.cli_path_msys2] + args
            self.logger.debug(f"Executing CLI command: {cli_cmd}")
            self.logger.debug(f"Working directory: {self.cli_dir}")
            
            result = subprocess.run(cli_cmd, capture_output=True, text=True, timeout=timeout, cwd=self.cli_dir)
            
            self.logger.debug(f"CLI command completed with return code: {result.returncode}")
            if result.stdout:
                self.logger.debug(f"CLI STDOUT: {result.stdout[:500]}...")
            if result.stderr:
                self.logger.debug(f"CLI STDERR: {result.stderr[:500]}...")
            output = result.stdout.strip()
            
            if '--output' in args and 'json' in args:
                try:
                    data = json.loads(output) if output else {}
                    
                    # Extract data from resultSets format
                    response_data = data.get('data')
                    if not response_data and data.get('resultSets'):
                        response_data = next(
                            (table['data'] for table in data['resultSets']
                             if table.get('data') and not any('nextRequestToken' in row for row in table['data'])),
                            None
                        )
                    
                    return {
                        'success': result.returncode == 0 and data.get('success', False),
                        'data': response_data,
                        'error': data.get('error', result.stderr),
                        'raw_output': output
                    }
                except json.JSONDecodeError:
                    pass
            
            return {
                'success': result.returncode == 0,
                'output': output,
                'error': result.stderr,
                'returncode': result.returncode
            }
        except Exception as e:
            self.logger.error(f"Error executing CLI command: {[self.python_cmd, self.cli_path_msys2] + args}")
            self.logger.error(f"Exception: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'output': '', 'error': str(e), 'returncode': -1}
    
    def run_command_streaming(self, args: List[str], output_callback=None) -> Dict[str, Any]:
        """Run a command and stream output line by line"""
        # Choose the appropriate CLI script based on command
        script_map = {
            'sync': self.sync_path_msys2,
            'term': self.term_path_msys2,
            'plugin': self.plugin_path_msys2
        }
        
        if args[0] in script_map:
            cli_script = script_map[args[0]]
            args = args[1:]  # Remove command from args
        else:
            cli_script = self.cli_path_msys2
        
        cmd = [self.python_cmd, cli_script] + args
        self.logger.debug(f"Streaming command: {cmd}")
        
        try:
            # Start process with pipes
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True,
                env=os.environ.copy()
            )
            
            output_lines = []
            
            # Read output line by line
            for line in iter(process.stdout.readline, ''):
                if line:
                    output_lines.append(line)
                    if output_callback:
                        output_callback(line)
            
            # Wait for process to complete
            process.wait()
            
            # Join all output
            full_output = ''.join(output_lines)
            
            return {
                'success': process.returncode == 0,
                'output': full_output,
                'error': '' if process.returncode == 0 else full_output,
                'returncode': process.returncode
            }
            
        except Exception as e:
            self.logger.error(f"Error in streaming command: {e}")
            return {
                'success': False,
                'output': '',
                'error': str(e),
                'returncode': -1
            }


# ============================================================================
# TERMINAL DETECTOR MODULE (from terminal_detector.py)
# ============================================================================

class TerminalDetector:
    """Detects and caches working terminal launch methods for the current system"""
    
    # Use centralized config directory
    CACHE_FILE = str(get_config_file("terminal_detector_cache.json"))
    CACHE_DURATION = timedelta(days=7)  # Re-test methods after a week
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.cache_dir = os.path.dirname(self.CACHE_FILE)
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Check if running in WSL
        is_wsl = self._is_wsl()
        
        # Define common Linux methods
        linux_methods = [
            ('gnome_terminal', self._test_gnome_terminal),
            ('konsole', self._test_konsole),
            ('xfce4_terminal', self._test_xfce4_terminal),
            ('mate_terminal', self._test_mate_terminal),
            ('terminator', self._test_terminator),
            ('xterm', self._test_xterm)
        ]
        
        # If in WSL, prioritize Windows terminal methods
        wsl_methods = [
            ('wsl_wt', self._test_wsl_windows_terminal),
            ('wsl_powershell', self._test_wsl_powershell),
            ('wsl_cmd', self._test_wsl_cmd),
        ] + linux_methods
        
        self.methods = {
            'win32': [
                ('windows_terminal', self._test_windows_terminal_openssh),
                ('msys2_mintty', self._test_msys2_mintty),
                ('wsl_wt', self._test_wsl_windows_terminal),
                ('wsl_powershell', self._test_wsl_powershell),
                ('msys2_wt', self._test_msys2_windows_terminal),
                ('msys2_bash', self._test_msys2_bash_direct),
                ('powershell', self._test_powershell_direct),
                ('cmd', self._test_cmd_direct)
            ],
            'darwin': [
                ('terminal_app', self._test_macos_terminal)
            ],
            'linux': wsl_methods if is_wsl else linux_methods
        }
        
        # Load cache
        self.cache = self._load_cache()
    
    def _load_cache(self) -> Dict:
        """Load cached detection results"""
        try:
            if os.path.exists(self.CACHE_FILE):
                with open(self.CACHE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.debug(f"Failed to load cache: {e}")
        return {}
    
    def _save_cache(self):
        """Save detection results to cache"""
        try:
            with open(self.CACHE_FILE, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save cache: {e}")
    
    def _is_cache_valid(self, platform: str) -> bool:
        """Check if cached results are still valid"""
        if platform not in self.cache:
            return False
        cached_time = self.cache[platform].get('timestamp')
        if not cached_time:
            return False
        
        try:
            cached_datetime = datetime.fromisoformat(cached_time)
            return datetime.now() - cached_datetime < self.CACHE_DURATION
        except Exception:
            return False
    
    def _find_msys2_installation(self) -> Optional[str]:
        """Find MSYS2 installation path"""
        msys2_paths = [
            'C:\\msys64', 'C:\\msys2',
            os.path.expanduser('~\\msys64'), os.path.expanduser('~\\msys2')
        ]

        msys2_root = os.environ.get('MSYS2_ROOT')
        if msys2_root:
            msys2_paths.insert(0, msys2_root)
        
        return next((path for path in msys2_paths if os.path.exists(path)), None)
    
    def _is_wsl(self) -> bool:
        """Check if running in WSL"""
        try:
            with open('/proc/version', 'r') as f:
                return 'microsoft' in f.read().lower()
        except Exception:
            return False
    
    def _test_command(self, cmd: List[str], timeout: float = 3.0, 
                     expect_running: bool = True) -> Tuple[bool, str]:
        """Test if a command works
        
        Args:
            cmd: Command to test
            timeout: How long to wait for the command
            expect_running: If True, command should still be running after timeout
                          If False, command should complete successfully
        
        Returns:
            Tuple of (success, method_description)
        """
        try:
            # Create a test script that exits cleanly
            # Use .bat on Windows for methods that don't use bash
            is_bash_method = any(x in str(cmd) for x in ['bash', 'msys', 'wsl'])
            suffix = '.sh' if is_bash_method else ('.bat' if sys.platform == 'win32' else '.sh')
            
            with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False) as f:
                if suffix == '.bat':
                    f.write('@echo off\necho Terminal detection test successful\nexit /b 0\n')
                else:
                    f.write('#!/bin/bash\necho "Terminal detection test successful"\nexit 0\n')
                test_script = f.name
            
            os.chmod(test_script, 0o755)
            
            # Replace placeholder in command with actual test script
            def replace_test_script(arg):
                if 'TEST_SCRIPT' not in arg:
                    return arg
                # Check if this is for MSYS2 and needs path conversion
                if ('msys' in cmd[0].lower() or 
                    (len(cmd) > 2 and 'bash' in cmd[0] and '/msys' in cmd[0])):
                    # Convert to MSYS2 path format
                    return arg.replace('TEST_SCRIPT', self._windows_to_msys2_path(test_script))
                return arg.replace('TEST_SCRIPT', test_script)
            
            test_cmd = [replace_test_script(arg) for arg in cmd]
            
            self.logger.debug(f"Testing command: {' '.join(test_cmd[:3])}...")
            
            process = subprocess.Popen(
                test_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                
                # Clean up test script
                with contextlib.suppress(Exception):
                    os.unlink(test_script)
                
                if expect_running:
                    # Process should have timed out (still running)
                    return (False, "Process completed when it should be running")
                else:
                    # Process should have completed successfully
                    if process.returncode == 0:
                        return (True, "Command executed successfully")
                    else:
                        error_info = f"Command failed with code {process.returncode}"
                        if stderr:
                            error_info += f" - stderr: {stderr.decode()[:100]}"
                        return (False, error_info)
                        
            except subprocess.TimeoutExpired:
                # Kill the process
                process.kill()
                
                # Schedule cleanup for later (in case file is in use)
                self._schedule_cleanup(test_script)
                
                if expect_running:
                    # This is expected - terminal is running
                    return (True, "Terminal launched successfully")
                else:
                    # This is unexpected - command should have completed
                    return (False, "Command timed out unexpectedly")
                    
        except Exception as e:
            # Clean up test script if it exists
            if 'test_script' in locals():
                self._schedule_cleanup(test_script)
            return (False, f"Exception: {str(e)}")
    
    def _schedule_cleanup(self, filepath: str):
        """Schedule file cleanup after a delay"""
        def cleanup():
            time.sleep(5)
            with contextlib.suppress(Exception):
                if os.path.exists(filepath):
                    os.unlink(filepath)
        
        cleanup_thread = threading.Thread(target=cleanup)
        cleanup_thread.daemon = True
        cleanup_thread.start()
    
    # Windows terminal tests
    def _test_windows_terminal_openssh(self) -> Tuple[bool, str]:
        """Test Windows Terminal with Windows OpenSSH for GUI launches"""
        import shutil
        
        # Only use on Windows
        if sys.platform != 'win32':
            return (False, "Not on Windows platform")
        
        # Check if Windows Terminal is available
        wt_path = shutil.which('wt.exe')
        if not wt_path:
            return (False, "Windows Terminal not found")
        
        # Check if Windows OpenSSH is available
        ssh_path = shutil.which('ssh.exe')
        if not ssh_path:
            return (False, "SSH not found")
        
        # Prefer Windows OpenSSH over MSYS2 SSH for GUI launches
        # This ensures proper known_hosts handling
        if 'msys' in ssh_path.lower():
            # Look for Windows OpenSSH specifically
            windows_ssh_paths = [
                'C:\\Windows\\System32\\OpenSSH\\ssh.exe',
                'C:\\Program Files\\OpenSSH\\ssh.exe'
            ]
            windows_ssh_found = False
            for win_ssh in windows_ssh_paths:
                if os.path.exists(win_ssh):
                    windows_ssh_found = True
                    break
            
            if not windows_ssh_found:
                return (False, f"Windows OpenSSH not found (found MSYS2 SSH at {ssh_path})")
        
        return (True, "Windows Terminal with OpenSSH available")
    
    def _test_msys2_mintty(self) -> Tuple[bool, str]:
        """Test MSYS2 mintty terminal"""
        msys2_path = self._find_msys2_installation()
        if not msys2_path:
            return (False, "MSYS2 not found")
        
        mintty_exe = os.path.join(msys2_path, 'usr', 'bin', 'mintty.exe')
        if not os.path.exists(mintty_exe):
            return (False, "mintty.exe not found")
        
        try:
            process = subprocess.Popen(
                [mintty_exe, '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            stdout, stderr = process.communicate(timeout=2)
            return ((True, "mintty is available") if process.returncode == 0
                   else (False, f"mintty test failed with code {process.returncode}"))
        except Exception as e:
            return (False, f"Failed to test mintty: {str(e)}")
    
    def _test_wsl_windows_terminal(self) -> Tuple[bool, str]:
        """Test WSL with Windows Terminal"""
        # Check if Windows Terminal is available
        try:
            test_cmd = ['cmd.exe', '/c', 'where', 'wt.exe']
            process = subprocess.Popen(
                test_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = process.communicate(timeout=2)
            return (
                (True, "Windows Terminal is available in WSL") if process.returncode == 0
                else (False, "Windows Terminal not found in WSL")
            )
        except Exception as e:
            return (False, f"Failed to test Windows Terminal: {str(e)}")
    
    def _test_wsl_powershell(self) -> Tuple[bool, str]:
        """Test WSL with PowerShell"""
        try:
            # Simple test to see if powershell.exe is available
            test_cmd = ['powershell.exe', '-Command', 'echo "test"']
            process = subprocess.Popen(
                test_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = process.communicate(timeout=2)
            return (
                (True, "PowerShell is available in WSL") if process.returncode == 0
                else (False, "PowerShell not accessible from WSL")
            )
        except Exception as e:
            return (False, f"Failed to test PowerShell: {str(e)}")
    
    def _test_wsl_cmd(self) -> Tuple[bool, str]:
        """Test WSL with cmd.exe"""
        try:
            # Simple test to see if cmd.exe is available
            test_cmd = ['cmd.exe', '/c', 'echo test']
            process = subprocess.Popen(
                test_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = process.communicate(timeout=2)
            return (
                (True, "cmd.exe is available in WSL") if process.returncode == 0
                else (False, "cmd.exe not accessible from WSL")
            )
        except Exception as e:
            return (False, f"Failed to test cmd.exe: {str(e)}")
    
    def _test_msys2_windows_terminal(self) -> Tuple[bool, str]:
        """Test MSYS2 with Windows Terminal"""
        msys2_path = self._find_msys2_installation()
        if not msys2_path:
            return (False, "MSYS2 not found")
        
        bash_exe = os.path.join(msys2_path, 'usr', 'bin', 'bash.exe')
        if not os.path.exists(bash_exe):
            return (False, "bash.exe not found")
        
        # Check if Windows Terminal is available
        try:
            # Test if wt.exe exists in PATH
            test_cmd = ['where', 'wt.exe']
            process = subprocess.Popen(
                test_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            stdout, stderr = process.communicate(timeout=2)
            return (
                (True, "Windows Terminal is available") if process.returncode == 0
                else (False, "Windows Terminal (wt.exe) not found in PATH")
            )
        except Exception as e:
            return (False, f"Failed to test Windows Terminal: {str(e)}")
    
    def _test_msys2_bash_direct(self) -> Tuple[bool, str]:
        """Test MSYS2 bash directly"""
        msys2_path = self._find_msys2_installation()
        if not msys2_path:
            return (False, "MSYS2 not found")
        
        bash_exe = os.path.join(msys2_path, 'usr', 'bin', 'bash.exe')
        if not os.path.exists(bash_exe):
            return (False, "bash.exe not found")
        
        # Use -l flag for login shell to ensure proper environment
        cmd = [bash_exe, '-l', '-c', 'TEST_SCRIPT']
        return self._test_command(cmd, expect_running=False)
    
    def _test_powershell_direct(self) -> Tuple[bool, str]:
        """Test PowerShell directly"""
        cmd = ['powershell.exe', '-Command', '& TEST_SCRIPT']
        return self._test_command(cmd, expect_running=False)
    
    def _test_cmd_direct(self) -> Tuple[bool, str]:
        """Test cmd.exe directly"""
        cmd = ['cmd.exe', '/c', 'TEST_SCRIPT']
        return self._test_command(cmd, expect_running=False)
    
    # macOS terminal test
    def _test_macos_terminal(self) -> Tuple[bool, str]:
        """Test macOS Terminal.app"""
        cmd = ['open', '-a', 'Terminal', 'TEST_SCRIPT']
        return self._test_command(cmd, expect_running=True)
    
    # Linux terminal tests
    def _test_gnome_terminal(self) -> Tuple[bool, str]:
        """Test GNOME Terminal"""
        cmd = ['gnome-terminal', '--', 'bash', 'TEST_SCRIPT']
        # Linux terminals spawn window and exit immediately - this is normal
        return self._test_command(cmd, expect_running=False)

    def _test_konsole(self) -> Tuple[bool, str]:
        """Test KDE Konsole"""
        cmd = ['konsole', '-e', 'bash', 'TEST_SCRIPT']
        # Linux terminals spawn window and exit immediately - this is normal
        return self._test_command(cmd, expect_running=False)

    def _test_xfce4_terminal(self) -> Tuple[bool, str]:
        """Test XFCE4 Terminal"""
        # Use -x instead of -e: -x takes remaining args as command (like xterm -e)
        # while -e expects a single string which causes quoting issues
        cmd = ['xfce4-terminal', '-x', 'bash', 'TEST_SCRIPT']
        # Linux terminals spawn window and exit immediately - this is normal
        return self._test_command(cmd, expect_running=False)

    def _test_mate_terminal(self) -> Tuple[bool, str]:
        """Test MATE Terminal"""
        cmd = ['mate-terminal', '-e', 'bash TEST_SCRIPT']
        # Linux terminals spawn window and exit immediately - this is normal
        return self._test_command(cmd, expect_running=False)

    def _test_terminator(self) -> Tuple[bool, str]:
        """Test Terminator"""
        cmd = ['terminator', '-e', 'bash TEST_SCRIPT']
        # Linux terminals spawn window and exit immediately - this is normal
        return self._test_command(cmd, expect_running=False)

    def _test_xterm(self) -> Tuple[bool, str]:
        """Test XTerm"""
        cmd = ['xterm', '-e', 'bash', 'TEST_SCRIPT']
        # Linux terminals spawn window and exit immediately - this is normal
        return self._test_command(cmd, expect_running=False)
    
    def detect(self, force_refresh: bool = False) -> Optional[str]:
        """Detect the best working terminal method
        
        Args:
            force_refresh: Force re-detection even if cache is valid
            
        Returns:
            The name of the best working method, or None if none work
        """
        platform = 'linux' if sys.platform.startswith('linux') else sys.platform
        
        # Check cache
        if not force_refresh and self._is_cache_valid(platform):
            cached_method = self.cache[platform].get('method')
            if cached_method:
                self.logger.debug(f"Using cached method: {cached_method}")
                return cached_method
        
        # Get methods for this platform
        platform_methods = self.methods.get(platform, [])
        if not platform_methods:
            self.logger.warning(f"No methods defined for platform: {platform}")
            return None
        
        self.logger.debug(f"Testing {len(platform_methods)} methods for {platform}...")
        
        # Test each method
        working_methods = []
        for method_name, test_func in platform_methods:
            success, description = test_func()
            self.logger.debug(f"[{'OK' if success else 'FAIL'}] {method_name}: {description}")
            if success:
                working_methods.append(method_name)
        
        # Select the best method (first working one)
        best_method = working_methods[0] if working_methods else None
        
        # Update cache
        self.cache[platform] = {
            'method': best_method,
            'working_methods': working_methods,
            'timestamp': datetime.now().isoformat(),
            'platform': platform
        }
        self._save_cache()
        
        if best_method:
            self.logger.info(f"Selected terminal method: {best_method}")
        else:
            self.logger.warning("No working terminal methods found!")
        
        return best_method
    
    def get_launch_function(self, method_name: str):
        """Get the launch function for a specific method
        
        Returns a function that takes (cli_dir, command, description) and launches a terminal
        """
        launch_functions = {
            # Windows methods
            'windows_terminal': self._launch_windows_terminal_openssh,
            'msys2_mintty': self._launch_msys2_mintty,
            'wsl_wt': self._launch_wsl_windows_terminal,
            'wsl_powershell': self._launch_wsl_powershell,
            'wsl_cmd': self._launch_wsl_cmd,
            'msys2_wt': self._launch_msys2_windows_terminal,
            'msys2_bash': self._launch_msys2_bash_direct,
            'powershell': self._launch_powershell_direct,
            'cmd': self._launch_cmd_direct,
            # macOS methods
            'terminal_app': self._launch_macos_terminal,
            # Linux methods
            'gnome_terminal': self._launch_gnome_terminal,
            'konsole': self._launch_konsole,
            'xfce4_terminal': self._launch_xfce4_terminal,
            'mate_terminal': self._launch_mate_terminal,
            'terminator': self._launch_terminator,
            'xterm': self._launch_xterm
        }
        
        return launch_functions.get(method_name)
    
    def _windows_to_msys2_path(self, windows_path: str) -> str:
        """Convert Windows path to MSYS2 format"""
        if len(windows_path) >= 2 and windows_path[1] == ':':
            drive = windows_path[0].lower()
            rest = windows_path[2:].replace('\\', '/')
            return f'/{drive}{rest}'
        return windows_path.replace('\\', '/')
    
    def _get_env_exports(self):
        """Get environment variable export statements for shell commands"""
        import shlex
        exports = []
        # Only export critical environment variables that are set
        important_vars = [
            'SYSTEM_API_URL',
            'SYSTEM_ADMIN_EMAIL',
            'SYSTEM_ADMIN_PASSWORD',
            'SYSTEM_MASTER_PASSWORD',
            'SYSTEM_HTTP_PORT',
            'SYSTEM_ORGANIZATION_ID',
            'SYSTEM_ORGANIZATION_VAULT_DEFAULTS',
            'SYSTEM_ORGANIZATION_NAME',
            'SYSTEM_DEFAULT_TEAM_NAME',
            'DOCKER_REGISTRY'
        ]
        for var in important_vars:
            value = os.environ.get(var)
            if value:
                # Properly escape the value for shell
                exports.append(f'export {var}={shlex.quote(value)}')
        
        return ' && '.join(exports) + ' && ' if exports else ''
    
    def _get_env_exports_powershell(self):
        """Get environment variable export statements for PowerShell"""
        exports = []
        important_vars = [
            'SYSTEM_API_URL',
            'SYSTEM_ADMIN_EMAIL',
            'SYSTEM_ADMIN_PASSWORD',
            'SYSTEM_MASTER_PASSWORD',
            'SYSTEM_HTTP_PORT',
            'SYSTEM_ORGANIZATION_ID',
            'SYSTEM_ORGANIZATION_VAULT_DEFAULTS',
            'SYSTEM_ORGANIZATION_NAME',
            'SYSTEM_DEFAULT_TEAM_NAME',
            'DOCKER_REGISTRY'
        ]
        for var in important_vars:
            value = os.environ.get(var)
            if value:
                # Escape for PowerShell
                escaped_value = value.replace("'", "''")
                exports.append(f"$env:{var}='{escaped_value}'")
        
        return '; '.join(exports) + '; ' if exports else ''
    
    def _get_env_exports_cmd(self):
        """Get environment variable export statements for CMD"""
        exports = []
        important_vars = [
            'SYSTEM_API_URL',
            'SYSTEM_ADMIN_EMAIL',
            'SYSTEM_ADMIN_PASSWORD',
            'SYSTEM_MASTER_PASSWORD',
            'SYSTEM_HTTP_PORT',
            'SYSTEM_ORGANIZATION_ID',
            'SYSTEM_ORGANIZATION_VAULT_DEFAULTS',
            'SYSTEM_ORGANIZATION_NAME',
            'SYSTEM_DEFAULT_TEAM_NAME',
            'DOCKER_REGISTRY'
        ]
        for var in important_vars:
            value = os.environ.get(var)
            if value:
                # CMD doesn't need much escaping but quotes can be problematic
                escaped_value = value.replace('"', '""')
                exports.append(f'set {var}={escaped_value}')
        
        return ' && '.join(exports) + ' && ' if exports else ''
    
    # Launch functions for each method
    def _launch_windows_terminal_openssh(self, cli_dir: str, command: str, description: str):
        """Launch using Windows Terminal with Windows OpenSSH for proper SSH handling
        
        This implementation prefers the installed rediacc.exe (from pip entry points),
        and falls back to local development scripts if available, without relying on
        a repository-local rediacc.bat which may not exist in installed environments.
        """
        import subprocess
        import sys as _sys
        
        # Determine the most reliable invocation on native Windows
        launcher_cmd = None
        try:
            # 1) Prefer the installed console executable (works with Windows Store Python too)
            try:
                from .protocol_handler import WindowsProtocolHandler  # Lazy import to avoid cycles
                rediacc_exe = WindowsProtocolHandler().get_rediacc_executable_path()
            except Exception:
                rediacc_exe = None
        
            if rediacc_exe and os.path.exists(rediacc_exe):
                # Use the installed executable directly
                launcher_cmd = f'"{rediacc_exe}" {command}'
            else:
                # 2) Fallback to local dev scripts if present
                rediacc_bat = os.path.join(cli_dir, 'rediacc.bat')
                cli_main_py = os.path.join(cli_dir, 'src', 'cli', 'commands', 'cli_main.py')
                if os.path.exists(rediacc_bat):
                    launcher_cmd = f'"{rediacc_bat}" {command}'
                elif os.path.exists(cli_main_py):
                    # Invoke via the current Python interpreter against the repository sources
                    launcher_cmd = f'"{_sys.executable}" "{cli_main_py}" {command}'
                else:
                    # 3) Last resort: module invocation (works for pip-installed package)
                    launcher_cmd = f'"{_sys.executable}" -m cli.commands.cli_main {command}'
        except Exception:
            # As a safety net, use module invocation
            launcher_cmd = f'"{_sys.executable}" -m cli.commands.cli_main {command}'
        
        # Build Windows Terminal command — keep it simple and robust (no fragile cd chaining)
        wt_args = [
            'wt.exe',
            '--maximized',
            '--title', f'Rediacc: {description}',
            'cmd.exe', '/k',  # /k keeps the window open after command completes
            launcher_cmd
        ]
        
        try:
            # Set environment to ensure Windows OpenSSH is prioritized (matches prior behavior)
            env = os.environ.copy()
            windows_ssh_paths = [
                'C:\\Windows\\System32\\OpenSSH',
                'C:\\Program Files\\OpenSSH'
            ]
            current_path = env.get('PATH', '')
            new_path_parts = [p for p in windows_ssh_paths if os.path.exists(p)] + current_path.split(os.pathsep)
            # Remove duplicates while preserving order
            seen, final_path = set(), []
            for p in new_path_parts:
                low = p.lower()
                if low not in seen:
                    seen.add(low)
                    final_path.append(p)
            env['PATH'] = os.pathsep.join(final_path)
            
            # Launch (no cwd requirement since we now use absolute exe/module)
            subprocess.Popen(wt_args, env=env)
            self.logger.info(f"Launched Windows Terminal for: {description}")
        except Exception as e:
            self.logger.error(f"Failed to launch Windows Terminal: {e}")
            # Fall back to PowerShell directly
            self._launch_powershell_direct(cli_dir, command, description)
    
    def _launch_msys2_mintty(self, cli_dir: str, command: str, description: str):
        """Launch using MSYS2 mintty"""
        import shlex
        
        msys2_path = self._find_msys2_installation()
        mintty_exe = os.path.join(msys2_path, 'usr', 'bin', 'mintty.exe')
        bash_exe = os.path.join(msys2_path, 'usr', 'bin', 'bash.exe')
        msys2_cli_dir = self._windows_to_msys2_path(cli_dir)
        
        cmd_parts = shlex.split(command)
        script_map = {
            'term': f'{msys2_cli_dir}/src/cli/commands/term_main.py',
            'sync': f'{msys2_cli_dir}/src/cli/commands/sync_main.py'
        }
        
        if cmd_parts[0] in script_map:
            cli_script = script_map[cmd_parts[0]]
            args = cmd_parts[1:]
        else:
            cli_script = f'{msys2_cli_dir}/src/cli/commands/cli_main.py'
            args = cmd_parts
        
        escaped_args = ' '.join(shlex.quote(arg) for arg in args)
        env_exports = self._get_env_exports()
        bash_cmd = f'{env_exports}cd "{msys2_cli_dir}" && python3 {cli_script} {escaped_args}'
        
        # Launch maximized with -w max option
        subprocess.Popen([mintty_exe, '-w', 'max', '-e', bash_exe, '-l', '-c', bash_cmd], env=_clean_environment())
    
    def _launch_wsl_windows_terminal(self, cli_dir: str, command: str, description: str):
        """Launch using WSL with Windows Terminal"""
        import shlex
        
        # Parse command to determine which CLI script to use
        try:
            cmd_parts = shlex.split(command)
        except Exception:
            # If shlex fails, do simple split
            cmd_parts = command.split()
        
        script_map = {
            'term': 'src/cli/commands/term_main.py',
            'sync': 'src/cli/commands/sync_main.py'
        }
        
        # Determine the correct CLI script based on command
        if cmd_parts and cmd_parts[0] in script_map:
            cli_script = script_map[cmd_parts[0]]
            args = ' '.join(shlex.quote(arg) for arg in cmd_parts[1:])
        else:
            cli_script = './rediacc'
            args = command
        
        # Build the WSL command with environment exports
        env_exports = self._get_env_exports()
        wsl_command = f'{env_exports}cd {cli_dir} && python3 {cli_script} {args}'
        
        # Launch Windows Terminal maximized with WSL command
        wt_cmd = ['wt.exe', '--maximized', 'new-tab', 'wsl.exe', '-e', 'bash', '-c', wsl_command]
        
        try:
            # Launch directly without cmd.exe to avoid UNC path warning
            subprocess.Popen(wt_cmd)
        except Exception:
            # Fallback to cmd.exe method if direct launch fails
            cmd_str = f'wt.exe --maximized new-tab wsl.exe -e bash -c "{wsl_command}"'
            subprocess.Popen(['cmd.exe', '/c', cmd_str], cwd=os.environ.get('WINDIR', 'C:\\Windows'), env=_clean_environment())
    
    def _launch_wsl_powershell(self, cli_dir: str, command: str, description: str):
        """Launch using WSL with PowerShell"""
        import shlex
        
        # Parse command to determine which CLI script to use
        try:
            cmd_parts = shlex.split(command)
        except Exception:
            cmd_parts = command.split()
        
        script_map = {
            'term': 'src/cli/commands/term_main.py',
            'sync': 'src/cli/commands/sync_main.py'
        }
        
        # Determine the correct CLI script
        if cmd_parts and cmd_parts[0] in script_map:
            cli_script = script_map[cmd_parts[0]]
            args = ' '.join(shlex.quote(arg) for arg in cmd_parts[1:])
        else:
            cli_script = './rediacc'
            args = command
        
        # Use PowerShell's Start-Process to avoid UNC path issues, launch maximized
        ps_cmd = f'Start-Process wsl -WindowStyle Maximized -ArgumentList "-e", "bash", "-c", "cd {cli_dir} && {cli_script} {args}"'
        # Set working directory to Windows directory to avoid UNC warning
        subprocess.Popen(['powershell.exe', '-Command', ps_cmd], 
                        cwd=os.environ.get('WINDIR', 'C:\\Windows'), env=os.environ.copy())
    
    def _launch_wsl_cmd(self, cli_dir: str, command: str, description: str):
        """Launch using WSL with cmd.exe"""
        import shlex
        
        # Parse command to determine which CLI script to use
        try:
            cmd_parts = shlex.split(command)
        except Exception:
            cmd_parts = command.split()
        
        script_map = {
            'term': 'src/cli/commands/term_main.py',
            'sync': 'src/cli/commands/sync_main.py'
        }
        
        # Determine the correct CLI script
        cli_script, args = (
            (script_map[cmd_parts[0]], ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd_parts[1:]))
            if cmd_parts and cmd_parts[0] in script_map
            else ('./rediacc', command)
        )
        
        # Use start with /D to set working directory and /max to maximize
        cmd_cmd = f'start /max "WSL Terminal" /D "%WINDIR%" wsl bash -c "cd {cli_dir} && {cli_script} {args}"'
        subprocess.Popen(['cmd.exe', '/c', cmd_cmd], env=_clean_environment())
    
    def _launch_msys2_windows_terminal(self, cli_dir: str, command: str, description: str):
        """Launch using MSYS2 with Windows Terminal"""
        import shlex
        
        msys2_path = self._find_msys2_installation()
        bash_exe = os.path.join(msys2_path, 'usr', 'bin', 'bash.exe')
        msys2_cli_dir = self._windows_to_msys2_path(cli_dir)
        
        cmd_parts = shlex.split(command)
        script_map = {
            'term': f'{msys2_cli_dir}/src/cli/commands/term_main.py',
            'sync': f'{msys2_cli_dir}/src/cli/commands/sync_main.py'
        }
        
        if cmd_parts[0] in script_map:
            cli_script = script_map[cmd_parts[0]]
            args = cmd_parts[1:]
        else:
            cli_script = f'{msys2_cli_dir}/src/cli/commands/cli_main.py'
            args = cmd_parts
        
        escaped_args = ' '.join(shlex.quote(arg) for arg in args)
        env_exports = self._get_env_exports()
        bash_cmd = f'{env_exports}cd "{msys2_cli_dir}" && python3 {cli_script} {escaped_args}'
        wt_cmd = f'wt.exe --maximized new-tab "{bash_exe}" -l -c "{bash_cmd}"'
        
        subprocess.Popen(['cmd.exe', '/c', wt_cmd], env=_clean_environment())
    
    def _launch_msys2_bash_direct(self, cli_dir: str, command: str, description: str):
        """Launch using MSYS2 bash directly (no new window)"""
        import shlex
        
        msys2_path = self._find_msys2_installation()
        bash_exe = os.path.join(msys2_path, 'usr', 'bin', 'bash.exe')
        msys2_cli_dir = self._windows_to_msys2_path(cli_dir)
        
        cmd_parts = shlex.split(command)
        script_map = {
            'term': f'{msys2_cli_dir}/src/cli/commands/term_main.py',
            'sync': f'{msys2_cli_dir}/src/cli/commands/sync_main.py'
        }
        
        if cmd_parts[0] in script_map:
            cli_script = script_map[cmd_parts[0]]
            args = cmd_parts[1:]
        else:
            cli_script = f'{msys2_cli_dir}/src/cli/commands/cli_main.py'
            args = cmd_parts
        
        escaped_args = ' '.join(shlex.quote(arg) for arg in args)
        env_exports = self._get_env_exports()
        bash_cmd = f'{env_exports}cd "{msys2_cli_dir}" && python3 {cli_script} {escaped_args}'
        
        subprocess.Popen([bash_exe, '-l', '-c', bash_cmd], env=_clean_environment())
    
    def _launch_powershell_direct(self, cli_dir: str, command: str, description: str):
        """Launch using PowerShell directly"""
        import shlex
        
        cmd_parts = shlex.split(command)
        script_map = {
            'term': f'{cli_dir}\\src\\cli\\commands\\term_main.py',
            'sync': f'{cli_dir}\\src\\cli\\commands\\sync_main.py'
        }
        
        if cmd_parts[0] in script_map:
            cli_script = script_map[cmd_parts[0]]
            args = cmd_parts[1:]
        else:
            cli_script = f'{cli_dir}\\src\\cli\\commands\\cli_main.py'
            args = cmd_parts
        
        escaped_args = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in args)
        env_exports = self._get_env_exports_powershell()
        ps_cmd = f'Start-Process powershell -WindowStyle Maximized -ArgumentList "-Command", "{env_exports}cd \\"{cli_dir}\\"; python3 {cli_script} {escaped_args}"'
        
        subprocess.Popen(['powershell.exe', '-Command', ps_cmd], env=_clean_environment())
    
    def _launch_cmd_direct(self, cli_dir: str, command: str, description: str):
        """Launch using cmd.exe directly"""
        import shlex
        
        cmd_parts = shlex.split(command)
        script_map = {
            'term': f'{cli_dir}\\src\\cli\\commands\\term_main.py',
            'sync': f'{cli_dir}\\src\\cli\\commands\\sync_main.py'
        }
        
        if cmd_parts[0] in script_map:
            cli_script = script_map[cmd_parts[0]]
            args = cmd_parts[1:]
        else:
            cli_script = f'{cli_dir}\\src\\cli\\commands\\cli_main.py'
            args = cmd_parts
        
        escaped_args = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in args)
        env_exports = self._get_env_exports_cmd()
        cmd_str = f'{env_exports}cd /d "{cli_dir}" && python {cli_script} {escaped_args}'
        
        # Launch maximized
        subprocess.Popen(['cmd.exe', '/c', f'start /max cmd /c {cmd_str}'], env=_clean_environment())
    
    def _get_rediacc_command(self, cli_dir: str, command: str) -> str:
        """Get the best rediacc invocation command with fallback logic.

        This method finds the most reliable way to invoke rediacc on Unix-like systems
        (Linux and macOS), with proper fallback logic similar to Windows implementation.

        Priority order:
        1. Installed 'rediacc' in PATH (pip-installed)
        2. Local development script at cli_dir parent (./rediacc)
        3. Direct Python module invocation (python -m cli.commands.cli_main)

        Args:
            cli_dir: The CLI root directory
            command: The rediacc subcommand and arguments (e.g., "term --token xyz")

        Returns:
            A shell command string that invokes rediacc with the given command
        """
        import shutil

        # 1) Check for pip-installed rediacc in PATH
        rediacc_in_path = shutil.which('rediacc')
        if rediacc_in_path:
            self.logger.debug(f"Using rediacc from PATH: {rediacc_in_path}")
            return f'"{rediacc_in_path}" {command}'

        # 2) Check for local development script (in parent of cli_dir, i.e., repository root)
        repo_root = os.path.dirname(cli_dir)  # cli_dir is typically /path/to/repository/src
        local_rediacc = os.path.join(repo_root, 'rediacc')
        if os.path.exists(local_rediacc) and os.access(local_rediacc, os.X_OK):
            self.logger.debug(f"Using local development rediacc: {local_rediacc}")
            return f'cd "{repo_root}" && ./rediacc {command}'

        # Also check in cli_dir itself (in case structure is different)
        local_rediacc_in_cli = os.path.join(cli_dir, 'rediacc')
        if os.path.exists(local_rediacc_in_cli) and os.access(local_rediacc_in_cli, os.X_OK):
            self.logger.debug(f"Using local rediacc in cli_dir: {local_rediacc_in_cli}")
            return f'cd "{cli_dir}" && ./rediacc {command}'

        # 3) Fall back to Python module invocation
        # This works for both pip-installed packages and development setups
        python_exe = sys.executable
        self.logger.debug(f"Falling back to module invocation with: {python_exe}")

        # Map subcommands to their module paths
        cmd_parts = command.split(None, 1)  # Split into command and rest
        subcommand = cmd_parts[0] if cmd_parts else ''
        rest_args = cmd_parts[1] if len(cmd_parts) > 1 else ''

        module_map = {
            'term': 'cli.commands.term_main',
            'sync': 'cli.commands.sync_main',
            'vscode': 'cli.commands.vscode_main',
            'protocol': 'cli.commands.protocol_main',
        }

        module = module_map.get(subcommand, 'cli.commands.cli_main')

        if subcommand in module_map:
            # Use specific module for known subcommands
            return f'"{python_exe}" -m {module} {rest_args}'
        else:
            # Use main CLI module for unknown commands
            return f'"{python_exe}" -m cli.commands.cli_main {command}'

    def _launch_macos_terminal(self, cli_dir: str, command: str, description: str):
        """Launch using macOS Terminal.app"""
        env_exports = self._get_env_exports()
        rediacc_cmd = self._get_rediacc_command(cli_dir, command)
        cmd_str = f'{env_exports}{rediacc_cmd}'
        # Launch Terminal.app (maximizing is handled by macOS Window Manager)
        # Note: Terminal.app doesn't have a direct maximize flag
        subprocess.Popen(['open', '-a', 'Terminal', '--', 'bash', '-c', cmd_str], env=_clean_environment())
    
    def _launch_gnome_terminal(self, cli_dir: str, command: str, description: str):
        """Launch using GNOME Terminal"""
        env_exports = self._get_env_exports()
        rediacc_cmd = self._get_rediacc_command(cli_dir, command)
        cmd_str = f'{env_exports}{rediacc_cmd}'
        # Launch maximized
        subprocess.Popen(['gnome-terminal', '--maximize', '--', 'bash', '-c', cmd_str], env=_clean_environment())
    
    def _launch_konsole(self, cli_dir: str, command: str, description: str):
        """Launch using KDE Konsole"""
        env_exports = self._get_env_exports()
        rediacc_cmd = self._get_rediacc_command(cli_dir, command)
        cmd_str = f'{env_exports}{rediacc_cmd}'
        # Launch maximized
        subprocess.Popen(['konsole', '--fullscreen', '-e', 'bash', '-c', cmd_str], env=_clean_environment())
    
    def _launch_xfce4_terminal(self, cli_dir: str, command: str, description: str):
        """Launch using XFCE4 Terminal"""
        env_exports = self._get_env_exports()
        rediacc_cmd = self._get_rediacc_command(cli_dir, command)
        cmd_str = f'{env_exports}{rediacc_cmd}'
        # Launch maximized using -x instead of -e
        # -x takes remaining args as command (like xterm -e), avoiding quoting issues
        subprocess.Popen(['xfce4-terminal', '--maximize', '-x', 'bash', '-c', cmd_str], env=_clean_environment())
    
    def _launch_mate_terminal(self, cli_dir: str, command: str, description: str):
        """Launch using MATE Terminal"""
        env_exports = self._get_env_exports()
        rediacc_cmd = self._get_rediacc_command(cli_dir, command)
        cmd_str = f'{env_exports}{rediacc_cmd}'
        # Launch maximized
        subprocess.Popen(['mate-terminal', '--maximize', '-e', f'bash -c "{cmd_str}"'], env=_clean_environment())
    
    def _launch_terminator(self, cli_dir: str, command: str, description: str):
        """Launch using Terminator"""
        env_exports = self._get_env_exports()
        rediacc_cmd = self._get_rediacc_command(cli_dir, command)
        cmd_str = f'{env_exports}{rediacc_cmd}'
        # Launch maximized
        subprocess.Popen(['terminator', '--maximise', '-e', f'bash -c "{cmd_str}"'], env=_clean_environment())
    
    def _launch_xterm(self, cli_dir: str, command: str, description: str):
        """Launch using XTerm"""
        env_exports = self._get_env_exports()
        rediacc_cmd = self._get_rediacc_command(cli_dir, command)
        cmd_str = f'{env_exports}{rediacc_cmd}'
        # Launch maximized with geometry
        subprocess.Popen(['xterm', '-maximized', '-e', 'bash', '-c', cmd_str], env=_clean_environment())


# ============================================================================
# MODULE EXPORTS - All functions and classes available from this module
# ============================================================================

__all__ = [
    # Config path functions
    'get_cli_root',
    'get_config_dir',
    'get_config_file',
    'get_main_config_file',
    'get_language_config_file',
    'get_plugin_connections_file',
    'get_terminal_cache_file',
    'get_terminal_detector_cache_file',
    'get_api_lock_file',
    'get_token_lock_file',
    'get_ssh_control_dir',
    
    # Logging functions
    'setup_logging',
    'get_logger',
    'is_verbose_enabled',
    
    # Config loader
    'ConfigError',
    'Config',
    'get_config',
    'load_config',
    'get',
    'get_required',
    'get_int',
    'get_bool',
    'get_path',
    
    # API mutex
    'api_mutex',
    'APIMutex',
    
    # Token manager
    'TokenManager',
    'get_default_token_manager',
    'get_default_config_manager',
    'is_encrypted',
    'decrypt_string',
    
    # I18n
    'I18n',
    'i18n',
    
    # Subprocess runner
    'SubprocessRunner',
    
    # Terminal detector
    'TerminalDetector',
]