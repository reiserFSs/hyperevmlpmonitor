# About
A concentrated liquidity pool monitor that tracks positions across multiple DEXes on HyperEVM. Completely vibe coded with Claude Sonnet 4, so expect bugs and report them on Discord / open issues on Git.

The main features of this monitor is essentially the notification feature. Let the script run on your VPS / Raspberry Pi and get notifications on the go about your positions.

# Features
- Dynamic position tracking (auto-detects new/removed positions)
- Multi-notification support (Telegram, Discord)
- Real-time price monitoring with dynamic thresholds going by tick size
- Multi-DEX support (Uniswap V3, Algebra Integral)
- Unclaimed fee tracking
- PnL / IL tracking
- Modular architecture for maintainability

# Installation
Git clone this repository or download the release from Git and extract it into a new folder. Installation for Windows should be similar if you have Python3 installed. Would recommend using the Git Bash terminal for Windows.

Clone into the repository (If using the Release instead, this step is not needed.)
```
git clone https://github.com/reiserFSs/hyperevmlpmonitor
```
Change directory
```
cd hyperevmlpmonitor
```
Install Python dependencies
```
pip3 install -r requirements.txt
```
Run the script
```
python3 main.py
```

You should then see the following screen upon loading the script for the first time:

```
╔══════════════════════════════════════════════════════════════╗
║                 💧 HYPEREVM LP MONITOR                       ║
║                  Multi-DEX Position Tracker                  ║
║                    v1.4.1 by 8roku8.hl                       ║
║              (Modular + Fee Tracking)                        ║
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
Proceed with the first time setup as outlined by the terminal output. It'll ask you for the contract address of the NonfungiblePositionManager of each dex you're configuring. These are usually found in the docs, or just pull them from HyperEVMScan, but here are some of the common ones: 

For Hybra Finance:
```
0x934C4f47B2D3FfcA0156A45DEb3A436202aF1efa
```
For Kittenswap:
```
0xB9201e89f94a01FF13AD4CAeCF43a2e232513754
```
For Gliquid:
```
0x69D57B9D705eaD73a5d2f2476C30c55bD755cc2F
```
For Hyperswap
```
0x6eDA206207c09e5428F281761DdC0D300851fBC8
```

For Laminar
```
0xfdf8b1f915198ed043ee52ec367c3df8ed5c9d79
```
The script will pull the correct factory address from the NFTPositionManager.

# Example Output
<img width="1345" height="604" alt="image" src="https://github.com/user-attachments/assets/f819ebbc-5c1c-46d9-a8da-fa231095bca7" />


# Notification Example
<img width="372" height="373" alt="image" src="https://github.com/user-attachments/assets/764c519c-1781-4fa8-97a7-b5bafb70c443" />

# IL Interpretation
Positive (+) → LP position plus fees is outperforming HODL by that percentage.
Negative (−) → underperforming HODL by that percentage.

# APR Interpretation
APR is being calculated over a 24h rolling window locally. So APRs start high initially and then stabilize after 24h. A timer on how long the position is in the local database is included beneath the APR of each position.

# Troubleshooting

For troubleshooting, please enable debug mode in ```lp_monitor_config.json``` 

```
"debug_mode": false,
```
Set it to ```true``` and load the script again. 
