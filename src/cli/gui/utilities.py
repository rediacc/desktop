#!/usr/bin/env python3
"""
GUI Utilities and Configuration

This module provides utility functions, configuration management, and constants
for the Rediacc CLI GUI application.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
import urllib.request
import urllib.parse
import urllib.error

from cli.config import GUI_CONFIG_FILE

# Add parent directory to path for imports if running directly
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import from consolidated core module
from cli.core.config import (
    SubprocessRunner,
    TokenManager,
    get_logger,
    get_required,
    get,
    api_mutex
)
from cli.core.api_client import client, SimpleConfigManager


# ===== UTILITY FUNCTIONS =====

def center_window(window, width: int, height: int) -> None:
    """Center a window on the screen"""
    window.update_idletasks()
    screen_width, screen_height = window.winfo_screenwidth(), window.winfo_screenheight()
    x, y = (screen_width - width) // 2, (screen_height - height) // 2
    window.geometry(f'{width}x{height}+{x}+{y}')


def format_size(size: int) -> str:
    """Format file size for display"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def format_time(timestamp: float) -> str:
    """Format timestamp for display"""
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')


def parse_ls_output(output: str) -> List[Dict[str, Any]]:
    """Parse ls -la output into file information"""
    from cli.core.config import i18n
    
    files = []
    lines = output.strip().split('\n')
    
    for line in lines:
        if not line or line.startswith('total'):
            continue
        
        # Parse ls -la output format
        # Example: drwxr-xr-x 2 user group 4096 Dec 15 10:30 dirname
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        
        perms = parts[0]
        size = int(parts[4]) if parts[4].isdigit() else 0
        name = parts[8]
        
        # Handle symbolic links
        if perms.startswith('l') and ' -> ' in name:
            # Extract link name (before ->)
            name = name.split(' -> ')[0]
        
        # Skip . and ..
        if name in ['.', '..']:
            continue
        
        # Determine if directory or link to directory
        is_dir = perms[0] in 'dl'
        
        # Parse modification time
        try:
            # Try to parse the date
            month = parts[5]
            day = parts[6]
            time_or_year = parts[7]
            
            # Parse date based on format
            current_year = datetime.now().year
            current_time = time.time()
            
            if ':' in time_or_year:
                # Recent file format: "Nov 25 14:23"
                hour, minute = time_or_year.split(':')
                # Create datetime with current year
                date_str = f"{month} {day} {current_year} {hour}:{minute}"
                try:
                    dt = datetime.strptime(date_str, "%b %d %Y %H:%M")
                    # If date is in the future, it's probably from last year
                    if dt.timestamp() > current_time:
                        dt = dt.replace(year=current_year - 1)
                    modified = dt.timestamp()
                except ValueError:
                    modified = current_time
            else:
                # Older file format: "Nov 25  2023"
                year = time_or_year
                date_str = f"{month} {day} {year}"
                try:
                    dt = datetime.strptime(date_str, "%b %d %Y")
                    modified = dt.timestamp()
                except ValueError:
                    modified = current_time
        except (IndexError, ValueError):
            modified = time.time()
        
        files.append({
            'name': name,
            'is_dir': is_dir,
            'size': size,
            'modified': modified,
            'type': i18n.get('folder') if is_dir else i18n.get('file'),
            'perms': perms
        })
    
    return files




def check_token_validity() -> bool:
    """Check if authentication token is valid using direct API call"""
    logger = get_logger(__name__)
    try:
        if not TokenManager.is_authenticated():
            logger.debug("Not authenticated")
            return False
        
        logger.debug("Testing token validity with direct API call...")
        
        # Test token with a simple API call
        # Ensure client has config manager for token rotation
        client.ensure_config_manager()
        response = client.token_request('GetOrganizationTeams', {})
        
        if response.get('error'):
            logger.debug(f"Token validation failed: {response.get('error', 'Unknown error')}")
            TokenManager.clear_token()
            return False
        
        logger.debug("Token is valid")
        return True
    except Exception as e:
        logger.error(f"Error checking authentication: {e}")
        import traceback
        traceback.print_exc()
        return False


# ===== CONFIGURATION =====

class GUIConfig:
    """Configuration loader for GUI settings"""
    _instance = None
    _config = None
    
    def __new__(cls):
        if cls._instance is None: cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._config is None: self.load_config()
    
    def load_config(self):
        """Load configuration from JSON file"""
        try:
            with open(GUI_CONFIG_FILE, 'r') as f: self._config = json.load(f)
        except FileNotFoundError: self._config = self._get_default_config()
        except json.JSONDecodeError as e:
            print(f"Error parsing config file: {e}")
            self._config = self._get_default_config()
    
    def _get_default_config(self):
        """Return default configuration as fallback"""
        return {
            "window_dimensions": {
                "login_window": [450, 500],
                "main_window_default": [1024, 768],
                "progress_dialog": [700, 600],
                "progress_dialog_small": [600, 500],
                "transfer_options_dialog": [700, 700],
                "center_window_default": [800, 600]
            },
            "widget_dimensions": {
                "combo_width": {"small": 15, "medium": 20, "large": 40},
                "entry_width": {"small": 10, "default": 40},
                "button_width": {"tiny": 3, "small": 12, "medium": 15},
                "label_width": {"default": 12},
                "text_height": {"small": 6, "medium": 8, "large": 10, "xlarge": 15}
            },
            "column_widths": {
                "name": 250, "size": 80, "modified": 150, "type": 80,
                "plugin": 120, "url": 200, "status": 80
            },
            "colors": {
                "tooltip_bg": "#ffffe0", "error": "red", "success": "green",
                "info": "blue", "default": "black"
            },
            "time_intervals": {
                "auto_refresh_interval": 5000,
                "status_message_short": 2000,
                "status_message_normal": 3000
            },
            "file_operations": {
                "preview_size_limit": 1048576,
                "preview_line_limit": 1000
            }
        }
    
    def get(self, *keys, default=None):
        """Get a configuration value by key path"""
        result = self._config
        for key in keys:
            if isinstance(result, dict) and key in result: result = result[key]
            else: return default
        return result


# Create global config instance
config = GUIConfig()

# ===== CONSTANTS =====

# Window dimensions
window_dims = config.get('window_dimensions', default={})
LOGIN_WINDOW_SIZE = tuple(window_dims.get('login_window', [480, 520]))
MAIN_WINDOW_DEFAULT_SIZE = tuple(window_dims.get('main_window_default', [1024, 768]))
PROGRESS_DIALOG_SIZE = tuple(window_dims.get('progress_dialog', [700, 600]))
PROGRESS_DIALOG_SIZE_SMALL = tuple(window_dims.get('progress_dialog_small', [600, 500]))
TRANSFER_OPTIONS_DIALOG_SIZE = tuple(window_dims.get('transfer_options_dialog', [700, 700]))
CENTER_WINDOW_DEFAULT_SIZE = tuple(window_dims.get('center_window_default', [800, 600]))

# Minimum window sizes
PROGRESS_DIALOG_MIN_SIZE = tuple(config.get('minimum_sizes', 'progress_dialog', default=[500, 400]))
PROGRESS_DIALOG_MIN_SIZE_SMALL = tuple(config.get('minimum_sizes', 'progress_dialog_small', default=[400, 350]))
TRANSFER_OPTIONS_MIN_SIZE = tuple(config.get('minimum_sizes', 'transfer_options', default=[500, 400]))

# Widget dimensions
widget_dims = config.get('widget_dimensions', default={})
combo_widths = widget_dims.get('combo_width', {})
COMBO_WIDTH_SMALL = combo_widths.get('small', 15)
COMBO_WIDTH_MEDIUM = combo_widths.get('medium', 20)
COMBO_WIDTH_LARGE = combo_widths.get('large', 40)

entry_widths = widget_dims.get('entry_width', {})
ENTRY_WIDTH_SMALL = entry_widths.get('small', 10)
ENTRY_WIDTH_DEFAULT = entry_widths.get('default', 50)

button_widths = widget_dims.get('button_width', {})
BUTTON_WIDTH_TINY = button_widths.get('tiny', 3)
BUTTON_WIDTH_SMALL = button_widths.get('small', 15)
BUTTON_WIDTH_MEDIUM = button_widths.get('medium', 20)

LABEL_WIDTH_DEFAULT = widget_dims.get('label_width', {}).get('default', 12)

text_heights = widget_dims.get('text_height', {})
TEXT_HEIGHT_SMALL = text_heights.get('small', 6)
TEXT_HEIGHT_MEDIUM = text_heights.get('medium', 8)
TEXT_HEIGHT_LARGE = text_heights.get('large', 10)
TEXT_HEIGHT_XLARGE = text_heights.get('xlarge', 15)

# Treeview column widths
column_widths = config.get('column_widths', default={})
COLUMN_WIDTH_NAME = column_widths.get('name', 250)
COLUMN_WIDTH_SIZE = column_widths.get('size', 80)
COLUMN_WIDTH_MODIFIED = column_widths.get('modified', 150)
COLUMN_WIDTH_TYPE = column_widths.get('type', 80)
COLUMN_WIDTH_PLUGIN = column_widths.get('plugin', 120)
COLUMN_WIDTH_URL = column_widths.get('url', 200)
COLUMN_WIDTH_STATUS = column_widths.get('status', 80)

# Layout constraints
PANED_MIN_SIZE_TINY = config.get('layout_constraints', 'paned_min_size', 'tiny', default=120)
PANED_MIN_SIZE_SMALL = config.get('layout_constraints', 'paned_min_size', 'small', default=140)
PANED_MIN_SIZE_MEDIUM = config.get('layout_constraints', 'paned_min_size', 'medium', default=150)
PANED_MIN_SIZE_LARGE = config.get('layout_constraints', 'paned_min_size', 'large', default=200)
PANED_MIN_SIZE_XLARGE = config.get('layout_constraints', 'paned_min_size', 'xlarge', default=300)
PANED_MIN_SIZE_XXLARGE = config.get('layout_constraints', 'paned_min_size', 'xxlarge', default=400)
PREVIEW_HEIGHT_DEFAULT = config.get('layout_constraints', 'preview_height', 'default', default=200)
PREVIEW_HEIGHT_MIN = config.get('layout_constraints', 'preview_height', 'min', default=150)
PREVIEW_HEIGHT_MAX = config.get('layout_constraints', 'preview_height', 'max', default=300)
TRANSFER_FRAME_WIDTH = config.get('layout_constraints', 'transfer_frame_width', 'default', default=140)
TRANSFER_FRAME_WIDTH_MAX = config.get('layout_constraints', 'transfer_frame_width', 'max', default=180)

# Padding values
PADDING_TINY = config.get('padding', 'tiny', default=8)
PADDING_SMALL = config.get('padding', 'small', default=12)
PADDING_MEDIUM = config.get('padding', 'medium', default=20)
PADDING_LARGE = config.get('padding', 'large', default=20)

# Border widths
BORDER_WIDTH_THIN = config.get('border_width', 'thin', default=1)
BORDER_WIDTH_THICK = config.get('border_width', 'thick', default=2)

# Time intervals (milliseconds)
STATUS_MESSAGE_SHORT = config.get('time_intervals', 'status_message_short', default=2000)
STATUS_MESSAGE_NORMAL = config.get('time_intervals', 'status_message_normal', default=3000)
AUTO_REFRESH_INTERVAL = config.get('time_intervals', 'auto_refresh_interval', default=5000)
LOGIN_CHECK_INTERVAL = config.get('time_intervals', 'login_check_interval', default=100)
IMMEDIATE_ACTION = config.get('time_intervals', 'immediate_action', default=0)

# Font configurations
FONT_FAMILY_DEFAULT = config.get('fonts', 'family', 'default', default='Arial')
FONT_FAMILY_MONO = config.get('fonts', 'family', 'mono', default='Consolas')
FONT_SIZE_TINY = config.get('fonts', 'size', 'tiny', default=8)
FONT_SIZE_SMALL = config.get('fonts', 'size', 'small', default=9)
FONT_SIZE_MEDIUM = config.get('fonts', 'size', 'medium', default=10)
FONT_SIZE_LARGE = config.get('fonts', 'size', 'large', default=11)
FONT_SIZE_XLARGE = config.get('fonts', 'size', 'xlarge', default=16)
FONT_STYLE_NORMAL = config.get('fonts', 'style', 'normal', default='normal')
FONT_STYLE_BOLD = config.get('fonts', 'style', 'bold', default='bold')

# Colors
COLOR_TOOLTIP_BG = config.get('colors', 'tooltip_bg', default='#ffffe0')
COLOR_TRANSFER_BG = config.get('colors', 'transfer_bg', default='#f0f0f0')
COLOR_SEPARATOR = config.get('colors', 'separator', default='#d0d0d0')
COLOR_ERROR = config.get('colors', 'error', default='red')
COLOR_ERROR_ALT = config.get('colors', 'error_alt', default='#FF6B35')
COLOR_SUCCESS = config.get('colors', 'success', default='green')
COLOR_INFO = config.get('colors', 'info', default='blue')
COLOR_INFO_GRAY = config.get('colors', 'info_gray', default='gray')
COLOR_INFO_LIGHT = config.get('colors', 'info_light', default='#666666')
COLOR_DEFAULT = config.get('colors', 'default', default='black')

# File operation limits
PREVIEW_SIZE_LIMIT = config.get('file_operations', 'preview_size_limit', default=1048576)
PREVIEW_LINE_LIMIT = config.get('file_operations', 'preview_line_limit', default=1000)
FILE_SIZE_UNIT_THRESHOLD = config.get('file_operations', 'file_size_unit_threshold', default=1024.0)
STATUS_LABEL_WRAP_LENGTH = config.get('file_operations', 'status_label_wrap_length', default=400)
FILE_LABEL_WRAP_LENGTH = config.get('file_operations', 'file_label_wrap_length', default=500)

# Network/Port constraints
DEFAULT_PORT = config.get('network', 'default_port', default=7111)
PORT_MIN = config.get('network', 'port_min', default=1)
PORT_MAX = config.get('network', 'port_max', default=65535)
PORT_USER_MIN = config.get('network', 'port_user_min', default=1024)

# Parsing constants
LS_OUTPUT_SPLIT_PARTS = config.get('parsing', 'ls_output_split_parts', default=8)
SSH_USER_DIR_INDEX = config.get('parsing', 'ssh_user_dir_index', default=2)

# UI text constraints
FILE_PATH_TRUNCATE_LENGTH = config.get('ui_text', 'file_path_truncate_length', default=80)