#!/usr/bin/env python3
"""
HyperEVM LP Monitor Package
Modular architecture for monitoring LP positions across multiple DEXes

Package Structure:
├── __init__.py              # This file - package initialization
├── main.py                  # Clean entry point (~100 lines)
├── config.py                # Configuration management (~400 lines) 
├── display.py               # Colors, formatting, UI (~300 lines)
├── notifications.py         # All notification methods (~500 lines)
├── blockchain.py            # Web3, DEX interactions (~600 lines)
├── position_monitor.py      # Core monitoring logic (~400 lines)
├── constants.py             # ABIs, mappings, defaults (~300 lines)
└── utils.py                 # Helper functions (~200 lines)

Total: ~2800 lines split into 8 focused modules (was 2000+ in single file)

Version: 1.3.0 (Modular Architecture)
Developer: 8roku8.hl
"""

# Import main components for package-level access
from .main import main
from .position_monitor import LPMonitor
from .blockchain import BlockchainManager
from .notifications import NotificationManager
from .display import DisplayManager
from .config import load_config, save_config, setup_first_run, validate_config
from .constants import VERSION, DEVELOPER, DEFAULT_CONFIG
from .utils import *

# Package metadata
__version__ = VERSION
__author__ = DEVELOPER
__description__ = "Multi-DEX LP position monitoring for HyperEVM"

# Define what gets imported with "from hyperevm_lp_monitor import *"
__all__ = [
    'main',
    'LPMonitor', 
    'BlockchainManager',
    'NotificationManager',
    'DisplayManager',
    'load_config',
    'save_config',
    'setup_first_run',
    'validate_config',
    'VERSION',
    'DEVELOPER'
]

def run():
    """Convenience function to run the monitor"""
    return main()

# Module dependency overview:
"""
Dependency Flow:
main.py
├── config.py
├── position_monitor.py
    ├── display.py
    │   ├── constants.py
    │   └── utils.py
    ├── blockchain.py
    │   ├── constants.py
    │   └── utils.py
    ├── notifications.py
    │   ├── constants.py
    │   └── utils.py
    └── constants.py
"""