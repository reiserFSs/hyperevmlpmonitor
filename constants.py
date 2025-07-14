#!/usr/bin/env python3
"""
Constants Module for HyperEVM LP Monitor
Contains all ABIs, default configuration, and constant values

UPDATED VERSION: Smart notification defaults with per-position cooldowns + Fee Tracking

Version: 1.4.1 (Smart Notifications + Fee Tracking)
Developer: 8roku8.hl
"""

# Version and metadata
VERSION = "1.4.1"
DEVELOPER = "8roku8.hl" 
CONFIG_FILE = "lp_monitor_config.json"

# Token symbol mappings for better display
TOKEN_SYMBOL_MAPPINGS = {
    "WHYPE": "HYPE",  # Wrapped HYPE should display as HYPE
    "WETH": "ETH",    # Wrapped ETH should display as ETH
    "WBTC": "BTC",    # Wrapped BTC should display as BTC
    # Add more mappings as needed
}

# Known contract addresses for better symbol detection
KNOWN_TOKENS = {
    # Add known token addresses and their preferred symbols here
    # "0x...": "HYPE",
    # "0x...": "USDT", 
}

# Default configuration with smart notification system + fee tracking
DEFAULT_CONFIG = {
    "version": VERSION,
    "wallet_address": "",
    "rpc_url": "https://rpc.hyperliquid.xyz/evm",
    "dexes": [],
    "check_interval": 30,
    "dynamic_thresholds": {
        "danger_threshold_pct": 5.0,     # % of range remaining = danger
        "warning_threshold_pct": 15.0,   # % of range remaining = warning
        "enable_dynamic": True
    },
    "display_settings": {
        "clear_screen": True,
        "color_scheme": "minimal",        # "full", "minimal", or "none"
        "debug_mode": False,
        "show_theoretical_amounts": True,  # Show what amounts would be if in range
        "show_raw_data": False,  # Show raw blockchain data for debugging
        "show_unclaimed_fees": True,  # Show unclaimed fees
        "fee_value_threshold": 0.01  # Only show fees above this USD value
    },
    "notifications": {
        "enabled": False,
        "type": "telegram",  # telegram, discord, pushover, email
        "notification_cooldown": 900,  # 15 minutes global cooldown (reduced from 1 hour)
        "notify_on_issues_only": False,   # Smart notifications work well for all updates
        "include_fees_in_notifications": True,  # Include fee information in notifications
        "smart_cooldowns": {
            "status_change": 0,          # Immediate notification for any status change
            "same_out_of_range": 30 * 60,  # 30 min for repeated out-of-range
            "same_danger": 60 * 60,      # 1 hour for repeated danger
            "same_warning": 2 * 60 * 60, # 2 hours for repeated warning  
            "same_safe": 6 * 60 * 60,    # 6 hours for repeated safe
        },
        "telegram": {
            "bot_token": "",
            "chat_id": ""
        },
        "discord": {
            "webhook_url": ""
        },
        "pushover": {
            "user_key": "",
            "api_token": ""
        },
        "email": {
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
            "email_address": "",
            "email_password": "",
            "recipient_email": ""
        }
    }
}

# Uniswap V3 Pool ABI (works with most V3 forks)
POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Algebra Integral Pool ABI (Version 1 - Standard)
ALGEBRA_POOL_ABI_V1 = [
    {
        "inputs": [],
        "name": "globalState",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "fee", "type": "uint16"},
            {"name": "timepointIndex", "type": "uint16"},
            {"name": "communityFeeToken0", "type": "uint8"},
            {"name": "communityFeeToken1", "type": "uint8"},
            {"name": "unlocked", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Alternative Algebra ABI for different implementations
ALGEBRA_POOL_ABI_V3 = [
    {
        "inputs": [],
        "name": "globalState",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "lastFee", "type": "uint16"},
            {"name": "pluginConfig", "type": "uint8"},
            {"name": "communityFee", "type": "uint16"},
            {"name": "unlocked", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Minimal ABI for raw calls
MINIMAL_POOL_ABI = [
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# ERC20 Token ABI for decimals and symbols
TOKEN_ABI = [
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# NonFungiblePositionManager ABI (standard across V3 forks) + Fee Collection
POSITION_MANAGER_ABI = [
    {
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "owner", "type": "address"}, 
            {"name": "index", "type": "uint256"}
        ],
        "name": "tokenOfOwnerByIndex",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "positions",
        "outputs": [
            {"name": "nonce", "type": "uint96"},
            {"name": "operator", "type": "address"},
            {"name": "token0", "type": "address"},
            {"name": "token1", "type": "address"},
            {"name": "fee", "type": "uint24"},
            {"name": "tickLower", "type": "int24"},
            {"name": "tickUpper", "type": "int24"},
            {"name": "liquidity", "type": "uint128"},
            {"name": "feeGrowthInside0LastX128", "type": "uint256"},
            {"name": "feeGrowthInside1LastX128", "type": "uint256"},
            {"name": "tokensOwed0", "type": "uint128"},
            {"name": "tokensOwed1", "type": "uint128"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "factory",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "components": [
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "recipient", "type": "address"},
                    {"name": "amount0Max", "type": "uint128"},
                    {"name": "amount1Max", "type": "uint128"}
                ],
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "collect",
        "outputs": [
            {"name": "amount0", "type": "uint256"},
            {"name": "amount1", "type": "uint256"}
        ],
        "stateMutability": "payable",
        "type": "function"
    }
]

# Factory ABI to get pool addresses
FACTORY_ABI = [
    {
        "inputs": [
            {"name": "token0", "type": "address"},
            {"name": "token1", "type": "address"},
            {"name": "fee", "type": "uint24"}
        ],
        "name": "getPool",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Algebra Factory ABI (different pool creation method)
ALGEBRA_FACTORY_ABI = [
    {
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"}
        ],
        "name": "poolByPair",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]