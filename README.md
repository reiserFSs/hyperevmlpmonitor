# About
A concentraded liquidity pool monitor that tracks positions across multiple DEXes on HyperEVM. Completely vibe coded with Claude Sonnet 4, so expect bugs and report them on Discord / open issues on Git.

# Features
- Dynamic position tracking (auto-detects new/removed positions)
- Multi-notification support (Telegram, Discord, Pushover, Email - NOT RECOMMENDED, NO HASHING OF PWS IMPLEMENTED YET, PLUS GOOGLE DOESN'T ALLOW PASSCODES ANYMORE)
- Real-time price monitoring with dynamic thresholds going by tick size
- Multi-DEX support (Uniswap V3, Algebra Integral)
- Unclaimed fee tracking
- Modular architecture for maintainability

# Installation
Git clone this repository or download the files as a zip from Git and extract them into a new folder.

```
git clone https://github.com/reiserFSs/hyperevmlpmonitor
```

```
cd hyperevmlpmonitor
```

```
pip3 install -r requirements.txt
```

```
python3 main.py
```

You should then see the following screen upon loading the script for the first time:

```
╔══════════════════════════════════════════════════════════════╗
║                 💧 HYPEREVM LP MONITOR                       ║
║                  Multi-DEX Position Tracker                 ║
║                    v1.4.1 by 8roku8.hl                      ║
║              (Modular + Fee Tracking)                       ║
╚══════════════════════════════════════════════════════════════╝

🔧 Loading configuration...
⚙️  Configuration file not found. Creating default config...
✅ Created lp_monitor_config.json
📝 Please edit the configuration file and restart the monitor.
🚀 Starting first-time setup...
╔══════════════════════════════════════════════════════════════╗
║              WELCOME TO HYPEREVM LP MONITOR                 ║
║                    First Time Setup                         ║
╚══════════════════════════════════════════════════════════════╝

Let's set up your LP monitor. You can modify these settings later in lp_monitor_config.json

📺 Display Options:
1. Minimal colors (recommended - red/green for status only)
2. No colors (plain text)
3. Full colors (original colorful interface)
Choose color scheme (1-3, default: 1):
```
Proceed with the first time setup as outlined by the terminal output. It'll ask you for the contract address of the NonfungiblePositionManager of each dex you're configuring. These are usually found in the docs, or just pull them from HyperEVMScan. 

# Troubleshooting

For troubleshooting, please enable debug mode in ```lp_monitor_config.json``` 

```
"debug_mode": false,
```
Set it to ```true``` and load the script again. 
