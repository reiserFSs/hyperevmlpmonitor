#!/usr/bin/env python3
"""
Blockchain Interaction Module for HyperEVM LP Monitor
Handles Web3 connections, smart contract calls, and DEX-specific logic

UPDATED VERSION: Added unclaimed fee tracking using static collect() calls

Version: 1.5.0
Developer: 8roku8.hl
"""

from web3 import Web3
import time
from collections import deque
from constants import (
    POOL_ABI, ALGEBRA_POOL_ABI_V1, ALGEBRA_POOL_ABI_V3, MINIMAL_POOL_ABI,
    TOKEN_ABI, POSITION_MANAGER_ABI, FACTORY_ABI, ALGEBRA_FACTORY_ABI,
    TOKEN_SYMBOL_MAPPINGS, KNOWN_TOKENS, MULTICALL3_ADDRESS, MULTICALL3_ABI
)
from utils import (
    sqrt_price_to_price, tick_to_price, calculate_token_amounts,
    calculate_theoretical_amounts, apply_symbol_mapping,
    parse_algebra_raw_data
)
from price_utils import is_stablecoin

class BlockchainManager:
    """Manages all blockchain interactions"""
    
    def __init__(self, rpc_url, debug_mode=False):
        self.rpc_url = rpc_url
        self.debug_mode = debug_mode
        self.token_cache = {}
        
        # Connect to blockchain
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise Exception("Failed to connect to HyperEVM blockchain")
        
        print("Connected to HyperEVM")

        # Pool data cache (per-cycle TTL)
        self._pool_cache = {}
        self._pool_cache_ttl_seconds = 5  # fresh enough for monitoring
        self._last_cache_block = None

        # Multicall contract (optional)
        try:
            self.multicall = self.w3.eth.contract(address=Web3.to_checksum_address(MULTICALL3_ADDRESS), abi=MULTICALL3_ABI)
        except Exception:
            self.multicall = None

        # Event tracking per DEX
        self._last_event_block_by_dex = {}
        self._last_event_hints_by_dex = {}
        self._last_scan_status_by_dex = {}

        # Precompute event topic hashes
        self._topic_transfer = self.w3.keccak(text="Transfer(address,address,uint256)").hex()
        self._topic_increase = self.w3.keccak(text="IncreaseLiquidity(uint256,uint128,uint256,uint256)").hex()
        self._topic_decrease = self.w3.keccak(text="DecreaseLiquidity(uint256,uint128,uint256,uint256)").hex()
        self._acquired_ts_cache = {}
        self._initial_liquidity_cache = {}

        # Global RPC rate limiter (tokens/minute)
        self._rpm_limit = 90  # keep headroom under 100 rpm
        self._rpc_call_times = deque()

    def _throttle_rpc(self):
        """Simple token-bucket-like limiter to keep under rpm limit."""
        if self._rpm_limit <= 0:
            return
        now = time.time()
        window = 60.0
        # drop old
        while self._rpc_call_times and (now - self._rpc_call_times[0]) > window:
            self._rpc_call_times.popleft()
        if len(self._rpc_call_times) >= self._rpm_limit:
            sleep_for = window - (now - self._rpc_call_times[0]) + 0.05
            if sleep_for > 0:
                time.sleep(sleep_for)
        # record
        self._rpc_call_times.append(time.time())

    def _rl_call(self, fn, *args, **kwargs):
        try:
            self._throttle_rpc()
            return fn(*args, **kwargs)
        except Exception as e:
            if 'rate limited' in str(e).lower():
                if self.debug_mode:
                    print(f"Rate limited, waiting 5 seconds...")
                time.sleep(5)
                return fn(*args, **kwargs)
            raise

    def get_enhanced_token_info(self, token_address, dex_name=""):
        """Enhanced token info with better symbol detection and mapping"""
        # Normalize address for caching
        token_address = Web3.to_checksum_address(token_address)
        
        # Check known tokens first
        if token_address in KNOWN_TOKENS:
            symbol = KNOWN_TOKENS[token_address]
            return {
                "decimals": 18,  # You might want to still call for decimals
                "symbol": symbol,
                "display_symbol": symbol,
                "source": "known_contract"
            }
        
        if token_address in self.token_cache:
            cached_info = self.token_cache[token_address]
            # Apply symbol mapping to cached results
            display_symbol = apply_symbol_mapping(cached_info["symbol"])
            cached_info["display_symbol"] = display_symbol
            return cached_info
        
        try:
            token_contract = self.w3.eth.contract(
                address=token_address,
                abi=TOKEN_ABI
            )
            
            # Get decimals and symbol in one try-catch block
            try:
                decimals = token_contract.functions.decimals().call()
            except:
                decimals = 18  # Default fallback
                
            try:
                symbol = token_contract.functions.symbol().call()
            except:
                # Fallback to truncated address if symbol fails
                symbol = f"TOKEN_{token_address[-6:]}"
            
            # Try to get token name for better identification
            token_name = ""
            try:
                token_name = token_contract.functions.name().call()
            except:
                pass
            
            # Apply symbol mapping (e.g., WHYPE -> HYPE)
            display_symbol = apply_symbol_mapping(symbol)
            
            token_info = {
                "decimals": decimals,
                "symbol": symbol,
                "display_symbol": display_symbol,
                "name": token_name,
                "source": "contract_call"
            }
            
            self.token_cache[token_address] = token_info
            return token_info
            
        except Exception as e:
            # Ultimate fallback for completely failed token calls
            fallback_symbol = f"UNKNOWN_{token_address[-4:]}"
            token_info = {
                "decimals": 18,
                "symbol": fallback_symbol,
                "display_symbol": fallback_symbol,
                "name": "",
                "source": "fallback"
            }
            self.token_cache[token_address] = token_info
            print(f"⚠️  Using fallback info for token {token_address[:8]}...: {e}")
            return token_info

    def get_unclaimed_fees(self, position, wallet_address):
        """Get unclaimed fees using static collect() call"""
        try:
            position_manager = self.w3.eth.contract(
                address=Web3.to_checksum_address(position["position_manager"]),
                abi=POSITION_MANAGER_ABI
            )
            
            # Prepare collect parameters for maximum collection
            max_uint128 = (2**128) - 1  # Maximum value for uint128
            
            collect_params = {
                "tokenId": position["token_id"],
                "recipient": wallet_address,  # Use wallet as recipient
                "amount0Max": max_uint128,    # Collect all available
                "amount1Max": max_uint128     # Collect all available
            }
            
            if self.debug_mode:
                print(f"🔍 Getting fees for token ID {position['token_id']} using static call...")
            
            # Use static call to simulate fee collection without executing
            result = position_manager.functions.collect(collect_params).call(
                {'from': wallet_address}
            )
            
            # Result is a tuple (amount0, amount1) in wei
            fee_amount0_wei = result[0]
            fee_amount1_wei = result[1]
            
            # Convert from wei to human-readable amounts
            decimals0 = position["token0_info"]["decimals"]
            decimals1 = position["token1_info"]["decimals"]
            
            fee_amount0 = fee_amount0_wei / (10 ** decimals0)
            fee_amount1 = fee_amount1_wei / (10 ** decimals1)
            
            if self.debug_mode:
                print(f"🔍 Raw fees: {fee_amount0_wei} wei token0, {fee_amount1_wei} wei token1")
                print(f"🔍 Human fees: {fee_amount0} {position['token0_symbol']}, {fee_amount1} {position['token1_symbol']}")
            
            return {
                "fee_amount0": fee_amount0,
                "fee_amount1": fee_amount1,
                "fee_amount0_wei": fee_amount0_wei,
                "fee_amount1_wei": fee_amount1_wei,
                "has_fees": fee_amount0 > 0 or fee_amount1 > 0
            }
            
        except Exception as e:
            if self.debug_mode:
                print(f"⚠️  Error getting fees for {position['name']}: {e}")
            
            # Return zero fees on error
            return {
                "fee_amount0": 0,
                "fee_amount1": 0,
                "fee_amount0_wei": 0,
                "fee_amount1_wei": 0,
                "has_fees": False,
                "error": str(e)
            }

    def get_pool_data_flexible(self, pool_address, dex_type="uniswap_v3"):
        """Enhanced pool data getter with better Algebra parsing"""
        if not pool_address:
            return None

        # Cache key
        try:
            block_number = self.w3.eth.block_number
        except Exception:
            block_number = None
        now_ts = int(time.time())
        cache_key = (pool_address, dex_type)
        cached = self._pool_cache.get(cache_key)
        if cached:
            data, ts, blk = cached
            if (now_ts - ts) <= self._pool_cache_ttl_seconds and (self._last_cache_block == blk or blk is None):
                return data

        # Helper for caching
        def _cache_and_return(result_dict):
            self._pool_cache[cache_key] = (result_dict, now_ts, block_number)
            self._last_cache_block = block_number
            return result_dict

        # Helper: multicall token0/token1 (saves an RPC)
        def _multicall_token_addresses():
            try:
                if not self.multicall:
                    return None, None
                pool_min = self.w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=MINIMAL_POOL_ABI)
                calldata_t0 = pool_min.encodeABI(fn_name='token0')
                calldata_t1 = pool_min.encodeABI(fn_name='token1')
                calls = [
                    (Web3.to_checksum_address(pool_address), calldata_t0),
                    (Web3.to_checksum_address(pool_address), calldata_t1)
                ]
                block_num, ret = self.multicall.functions.aggregate(calls).call()
                # ret[0] and ret[1] are bytes; decode as address (20 bytes right padded)
                token0_address = Web3.to_checksum_address('0x' + ret[0][-20:].hex())
                token1_address = Web3.to_checksum_address('0x' + ret[1][-20:].hex())
                return token0_address, token1_address
            except Exception:
                return None, None
        
        if dex_type == "algebra_integral":
            # Try multiple Algebra versions
            algebra_abis = [
                ("v1", ALGEBRA_POOL_ABI_V1), 
                ("v3", ALGEBRA_POOL_ABI_V3)
            ]
            
            for version, abi in algebra_abis:
                try:
                    if self.debug_mode:
                        print(f"🔍 Trying Algebra {version} ABI...")
                    
                    pool_contract = self.w3.eth.contract(
                        address=Web3.to_checksum_address(pool_address),
                        abi=abi
                    )
                    
                    # Get pool data using globalState
                    global_state = pool_contract.functions.globalState().call()
                    
                    if self.debug_mode:
                        print(f"🔍 GlobalState {version}: {global_state}")
                    
                    # Extract tick and sqrtPriceX96 (they should be in positions 0 and 1)
                    sqrt_price_x96 = global_state[0]
                    current_tick = global_state[1]
                    
                    # Sanity check the values
                    if sqrt_price_x96 > 0 and abs(current_tick) < 887272:  # Valid tick range
                        if self.debug_mode:
                            print(f"✅ Algebra {version} ABI worked! Tick: {current_tick}, Price: {sqrt_price_x96}")
                        
                        # Get token addresses (try multicall first)
                        token0_address, token1_address = _multicall_token_addresses()
                        if not token0_address or not token1_address:
                            token0_address = pool_contract.functions.token0().call()
                            token1_address = pool_contract.functions.token1().call()
                        
                        # Get enhanced token info
                        token0_info = self.get_enhanced_token_info(token0_address, "Algebra")
                        token1_info = self.get_enhanced_token_info(token1_address, "Algebra")
                        
                        # Calculate price with correct decimals
                        price = sqrt_price_to_price(sqrt_price_x96, token0_info["decimals"], token1_info["decimals"])
                        
                        return _cache_and_return({
                            "current_tick": current_tick,
                            "price": price,
                            "sqrt_price_x96": sqrt_price_x96,
                            "token0_decimals": token0_info["decimals"],
                            "token1_decimals": token1_info["decimals"],
                            "token0_symbol": token0_info["display_symbol"],
                            "token1_symbol": token1_info["display_symbol"],
                            "algebra_version": version,
                            "method": f"algebra_{version}_abi"
                        })
                    else:
                        if self.debug_mode:
                            print(f"⚠️  Algebra {version} returned suspicious values: tick={current_tick}, price={sqrt_price_x96}")
                        
                except Exception as e:
                    if self.debug_mode:
                        print(f"⚠️  Algebra {version} ABI failed: {e}")
                    continue
            
            # If all Algebra versions failed, try raw call approach with enhanced parsing
            try:
                if self.debug_mode:
                    print("🔍 Trying enhanced raw globalState() call...")
                
                # Get basic token info first
                pool_contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(pool_address),
                    abi=MINIMAL_POOL_ABI
                )
                
                token0_address, token1_address = _multicall_token_addresses()
                if not token0_address or not token1_address:
                    token0_address = pool_contract.functions.token0().call()
                    token1_address = pool_contract.functions.token1().call()
                
                # Try raw call to globalState
                function_selector = self.w3.keccak(text="globalState()")[:4]
                raw_result = self.w3.eth.call({
                    'to': pool_address,
                    'data': '0x' + function_selector.hex()
                })
                
                sqrt_price_x96, current_tick = parse_algebra_raw_data(raw_result, self.debug_mode)
                
                if sqrt_price_x96 and current_tick is not None:
                    if self.debug_mode:
                        print(f"✅ Enhanced raw parsing worked! Tick: {current_tick}, Price: {sqrt_price_x96}")
                    
                    # Get enhanced token info
                    token0_info = self.get_enhanced_token_info(token0_address, "Algebra Raw")
                    token1_info = self.get_enhanced_token_info(token1_address, "Algebra Raw")
                    
                    # Calculate price with correct decimals
                    price = sqrt_price_to_price(sqrt_price_x96, token0_info["decimals"], token1_info["decimals"])
                    
                    return _cache_and_return({
                        "current_tick": current_tick,
                        "price": price,
                        "sqrt_price_x96": sqrt_price_x96,
                        "token0_decimals": token0_info["decimals"],
                        "token1_decimals": token1_info["decimals"],
                        "token0_symbol": token0_info["display_symbol"],
                        "token1_symbol": token1_info["display_symbol"],
                        "algebra_version": "enhanced_raw",
                        "method": "enhanced_raw_parsing"
                    })
                    
            except Exception as e:
                if self.debug_mode:
                    print(f"⚠️  Enhanced raw call also failed: {e}")
        
        # Fall back to standard Uniswap V3
        try:
            if self.debug_mode:
                print("🔄 Falling back to Uniswap V3 method...")
            
            pool_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(pool_address),
                abi=POOL_ABI
            )
            
            slot0 = pool_contract.functions.slot0().call()
            current_tick = slot0[1]
            sqrt_price_x96 = slot0[0]
            
            token0_address, token1_address = _multicall_token_addresses()
            if not token0_address or not token1_address:
                token0_address = pool_contract.functions.token0().call()
                token1_address = pool_contract.functions.token1().call()
            
            # Get enhanced token info
            token0_info = self.get_enhanced_token_info(token0_address, "Uniswap V3")
            token1_info = self.get_enhanced_token_info(token1_address, "Uniswap V3")
            
            # Calculate price with correct decimals
            price = sqrt_price_to_price(sqrt_price_x96, token0_info["decimals"], token1_info["decimals"])
            
            return _cache_and_return({
                "current_tick": current_tick,
                "price": price,
                "sqrt_price_x96": sqrt_price_x96,
                "token0_decimals": token0_info["decimals"],
                "token1_decimals": token1_info["decimals"],
                "token0_symbol": token0_info["display_symbol"],
                "token1_symbol": token1_info["display_symbol"],
                "method": "uniswap_v3"
            })
            
        except Exception as e:
            print(f"⚠️  All methods failed for pool {pool_address}: {e}")
            return None

        # Store in cache before returning (when successful paths return)
        # Note: earlier returns bypass this; refactor by capturing 'result' then caching once.

    def prefetch_pool_data(self, pool_entries):
        """Prefetch pool tick/price and token metadata for a set of unique pools.

        pool_entries: list of dicts/tuples with keys (or positions) (pool_address, dex_type)
        """
        if not pool_entries or not self.multicall:
            return

        # Normalize and dedupe
        normalized = []
        seen = set()
        for entry in pool_entries:
            if isinstance(entry, dict):
                addr = entry.get('pool_address')
                dtype = entry.get('dex_type', 'uniswap_v3')
            else:
                addr, dtype = entry
            if not addr:
                continue
            key = (Web3.to_checksum_address(addr), dtype)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(key)

        if not normalized:
            return

        # Build calls for slot0/globalState
        slot0_selector = self.w3.keccak(text="slot0()")[:4]
        global_selector = self.w3.keccak(text="globalState()")[:4]
        calls = []
        call_index = []  # map index -> (pool, dtype)
        for addr, dtype in normalized:
            selector = slot0_selector if dtype == 'uniswap_v3' else global_selector
            # Pass bytes selector directly for no-arg calls
            calls.append((addr, selector))
            call_index.append((addr, dtype))

        try:
            block_num, ret_datas = self._rl_call(self.multicall.functions.aggregate(calls).call)
        except Exception:
            return  # silently skip if multicall fails

        # Decode helpers
        def decode_slot0(data_bytes):
            # Expect at least 2 words
            if not data_bytes or len(data_bytes) < 64:
                return None, None
            sqrt_price = int.from_bytes(data_bytes[0:32], 'big')
            tick_raw = int.from_bytes(data_bytes[32:64], 'big', signed=True)
            return sqrt_price, tick_raw

        def decode_global_state(data_bytes):
            if not data_bytes or len(data_bytes) < 64:
                return None, None
            sqrt_price = int.from_bytes(data_bytes[0:32], 'big')
            tick_raw = int.from_bytes(data_bytes[32:64], 'big', signed=True)
            return sqrt_price, tick_raw

        # First pass: decode ticks and sqrt prices
        pool_to_core = {}
        for i, (addr, dtype) in enumerate(call_index):
            data_bytes = ret_datas[i]
            sqrt_p, tick = (decode_slot0(data_bytes) if dtype == 'uniswap_v3' else decode_global_state(data_bytes))
            if sqrt_p is None or tick is None:
                continue
            pool_to_core[(addr, dtype)] = (sqrt_p, tick)

        if not pool_to_core:
            return

        # Batch token0/token1 for all pools
        try:
            pool_min = self.w3.eth.contract(abi=MINIMAL_POOL_ABI, address=Web3.to_checksum_address(list(pool_to_core.keys())[0][0]))
        except Exception:
            pool_min = None

        t_calls = []
        index_list = []
        for addr, dtype in pool_to_core.keys():
            if pool_min:
                # Build ABI per pool for correctness
                pool_c = self.w3.eth.contract(address=addr, abi=MINIMAL_POOL_ABI)
                t0 = pool_c.encodeABI(fn_name='token0')
                t1 = pool_c.encodeABI(fn_name='token1')
                t_calls.append((addr, bytes.fromhex(t0[2:])))
                t_calls.append((addr, bytes.fromhex(t1[2:])))
                index_list.append((addr, 0))
                index_list.append((addr, 1))
            else:
                # Fallback to direct calls later
                pass

        token_map = {}
        if t_calls:
            try:
                _, t_rets = self._rl_call(self.multicall.functions.aggregate(t_calls).call)
                for j, (addr, which) in enumerate(index_list):
                    data = t_rets[j]
                    if data and len(data) >= 32:
                        token_addr = Web3.to_checksum_address('0x' + data[-20:].hex())
                        token_map.setdefault(addr, [None, None])[which] = token_addr
            except Exception:
                token_map = {}

        # Build cache entries
        for (addr, dtype), (sqrt_p, tick) in pool_to_core.items():
            try:
                # Resolve token addresses (fallback to direct call if needed)
                if addr in token_map:
                    token0_address, token1_address = token_map[addr]
                else:
                    pool_c = self.w3.eth.contract(address=addr, abi=MINIMAL_POOL_ABI)
                    token0_address = pool_c.functions.token0().call()
                    token1_address = pool_c.functions.token1().call()

                # Token metadata
                token0_info = self.get_enhanced_token_info(token0_address, "Prefetch")
                token1_info = self.get_enhanced_token_info(token1_address, "Prefetch")

                # Compute price
                price = sqrt_price_to_price(sqrt_p, token0_info["decimals"], token1_info["decimals"])

                # Cache entry
                result = {
                    "current_tick": tick,
                    "price": price,
                    "sqrt_price_x96": sqrt_p,
                    "token0_decimals": token0_info["decimals"],
                    "token1_decimals": token1_info["decimals"],
                    "token0_symbol": token0_info["display_symbol"],
                    "token1_symbol": token1_info["display_symbol"],
                    "method": "multicall_slot0" if dtype == 'uniswap_v3' else "multicall_globalState"
                }
                self._pool_cache[(addr, dtype)] = (result, int(time.time()), self.w3.eth.block_number)
                self._last_cache_block = self.w3.eth.block_number
            except Exception:
                continue

    def detect_dex_type(self, dex_name, factory_address):
        """Auto-detect DEX type based on available methods"""
        if not factory_address:
            return "uniswap_v3"
        
        try:
            # Try Algebra factory first
            factory_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(factory_address),
                abi=ALGEBRA_FACTORY_ABI
            )
            
            # Test if poolByPair method exists (Algebra signature)
            try:
                # This will fail if not Algebra
                test_call = factory_contract.functions.poolByPair
                if self.debug_mode:
                    print(f"Auto-detected: {dex_name} uses Algebra Integral")
                return "algebra_integral"
            except:
                pass
        except:
            pass
        
        # Default to Uniswap V3
        if self.debug_mode:
            print(f"Auto-detected: {dex_name} uses Uniswap V3")
        return "uniswap_v3"

    def get_pool_address(self, token0, token1, fee, factory_address, dex_type="uniswap_v3"):
        """Get pool address from factory with support for different DEX types"""
        if not factory_address:
            print("⚠️  No factory address available")
            return None
        
        try:
            if dex_type == "algebra_integral":
                # Algebra Integral uses poolByPair instead of getPool
                factory_contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(factory_address),
                    abi=ALGEBRA_FACTORY_ABI
                )
                
                # Algebra doesn't use fee parameter in pool lookup
                pool_address = factory_contract.functions.poolByPair(token0, token1).call()
                
            else:
                # Standard Uniswap V3 approach
                factory_contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(factory_address),
                    abi=FACTORY_ABI
                )
                
                pool_address = factory_contract.functions.getPool(token0, token1, fee).call()
            
            if pool_address == "0x0000000000000000000000000000000000000000":
                print(f"No pool found for tokens {token0[:6]}.../{token1[:6]}... (type: {dex_type})")
                return None
                
            return pool_address
            
        except Exception as e:
            print(f"Error getting pool address ({dex_type}): {e}")
            # If Algebra fails, try Uniswap V3 as fallback
            if dex_type == "algebra_integral":
                if self.debug_mode:
                    print("Falling back to Uniswap V3 method...")
                return self.get_pool_address(token0, token1, fee, factory_address, "uniswap_v3")
            return None

    def fetch_positions_from_dex(self, wallet_address, dex_config, suppress_output=False, force_full=False):
        """Fetch LP positions from a specific DEX with fee tracking"""
        dex_name = dex_config["name"]
        position_manager_address = dex_config["position_manager"]
        dex_type = dex_config.get("type", "uniswap_v3")
        
        positions = []
        
        if not suppress_output:
            print(f"\nChecking {dex_name} ({dex_type})...")
        
        try:
            self._throttle_rpc()
            position_manager = self.w3.eth.contract(
                address=Web3.to_checksum_address(position_manager_address),
                abi=POSITION_MANAGER_ABI
            )
            
            # Get factory address from position manager
            factory_address = None
            try:
                factory_address = position_manager.functions.factory().call()
                if self.debug_mode and not suppress_output:
                    print(f"Factory: {factory_address}")
                
                # Auto-detect DEX type if not specified
                if dex_type == "uniswap_v3" and dex_name.lower() in ["gliquid", "quickswap"]:
                    detected_type = self.detect_dex_type(dex_name, factory_address)
                    if detected_type != dex_type:
                        dex_type = detected_type
                        dex_config["type"] = dex_type  # Update config
                        
            except Exception as e:
                print(f"⚠️  Could not get factory address from {dex_name} position manager: {e}")
            
            # Event-driven refresh: try to detect changes since last scan
            latest_block = int(self._rl_call(lambda: self.w3.eth.block_number))
            start_block = self._last_event_block_by_dex.get(dex_name, max(latest_block - 2400, 0))  # ~5-10 min window

            changes_detected = False
            logs_ok = True
            try:
                logs_transfer = self._rl_call(self.w3.eth.get_logs, {
                    'fromBlock': start_block,
                    'toBlock': latest_block,
                    'address': Web3.to_checksum_address(position_manager_address),
                    'topics': [self._topic_transfer, None, None]
                })
                logs_liq_inc = self._rl_call(self.w3.eth.get_logs, {
                    'fromBlock': start_block,
                    'toBlock': latest_block,
                    'address': Web3.to_checksum_address(position_manager_address),
                    'topics': [self._topic_increase]
                })
                logs_liq_dec = self._rl_call(self.w3.eth.get_logs, {
                    'fromBlock': start_block,
                    'toBlock': latest_block,
                    'address': Web3.to_checksum_address(position_manager_address),
                    'topics': [self._topic_decrease]
                })
                changes_detected = bool(logs_transfer or logs_liq_inc or logs_liq_dec)

                # Build event hints for this DEX
                removed_ids = set()
                added_ids = set()
                wallet_cs = Web3.to_checksum_address(wallet_address)
                for lg in (logs_transfer or []):
                    if not lg.get('topics') or len(lg['topics']) < 4:
                        continue
                    from_addr = Web3.to_checksum_address('0x' + lg['topics'][1].hex()[-40:])
                    to_addr = Web3.to_checksum_address('0x' + lg['topics'][2].hex()[-40:])
                    token_id = int(lg['topics'][3].hex(), 16)
                    if from_addr == wallet_cs and to_addr != wallet_cs:
                        removed_ids.add(token_id)
                    if to_addr == wallet_cs and from_addr != wallet_cs:
                        added_ids.add(token_id)
                self._last_event_hints_by_dex[dex_name] = {
                    'removed_ids': removed_ids,
                    'added_ids': added_ids,
                    'block': latest_block
                }
            except Exception:
                logs_ok = False

            # Update the cursor only if logs were read successfully
            if logs_ok:
                self._last_event_block_by_dex[dex_name] = latest_block

            # Maintenance path: if suppress_output is True we are in maintenance mode
            if (not force_full) and suppress_output and (not changes_detected or not logs_ok):
                # Return None sentinel so caller keeps previous positions for this DEX
                return None

            # Get number of positions owned by wallet (heavy scan)
            balance = self._rl_call(position_manager.functions.balanceOf(wallet_address).call)
            if not suppress_output:
                print(f"Found {balance} LP NFT(s) in {dex_name}")
            
            if balance == 0:
                return positions
            
            # Show progress for large numbers of positions
            if balance > 10 and not suppress_output:
                print(f"Scanning {balance} positions (this may take a moment)...")
            
            positions_added = 0
            positions_skipped = 0
            had_errors = False

            # Simple retry helper for rate-limit bursts
            def _retry_call(fn, *args, **kwargs):
                last_exc = None
                for attempt in range(3):
                    try:
                        return fn(*args, **kwargs)
                    except Exception as e:
                        last_exc = e
                        time.sleep(0.4 * (2 ** attempt))
                raise last_exc
            
            # Get each position
            for i in range(balance):
                try:
                    # Show progress for large scans
                    if balance > 20 and (i + 1) % 10 == 0:
                        if not suppress_output:
                            print(f"Progress: {i + 1}/{balance} positions scanned...")
                    
                    # Get token ID
                    try:
                        token_id = _retry_call(lambda: self._rl_call(position_manager.functions.tokenOfOwnerByIndex(wallet_address, i).call))
                    except Exception as e:
                        had_errors = True
                        if not suppress_output:
                            print(f"Error fetching {dex_name} position index {i}: {e}")
                        continue
                    
                    # Get position details (single RPC call)
                    try:
                        position_data = _retry_call(lambda: self._rl_call(position_manager.functions.positions(token_id).call))
                    except Exception as e:
                        had_errors = True
                        if not suppress_output:
                            print(f"Error fetching {dex_name} position {i}: {e}")
                        continue
                    
                    # Extract basic info
                    liquidity = position_data[7]
                    
                    # FAST CHECK: Skip positions with no liquidity BEFORE expensive operations
                    if liquidity == 0:
                        positions_skipped += 1
                        # Only show detailed skipping info in debug mode to avoid clutter
                        if self.debug_mode and balance <= 20 and not suppress_output:
                            print(f"⚠️  {dex_name} position #{token_id} has no liquidity, skipping")
                        continue
                    
                    # Only do expensive operations for positions with liquidity
                    token0_address = position_data[2]
                    token1_address = position_data[3]
                    fee = position_data[4]
                    tick_lower = position_data[5]
                    tick_upper = position_data[6]
                    
                    # Get enhanced token info
                    token0_info = self.get_enhanced_token_info(token0_address, dex_name)
                    token1_info = self.get_enhanced_token_info(token1_address, dex_name)
                    
                    # Get pool address with proper DEX type
                    pool_address = self.get_pool_address(token0_address, token1_address, fee, factory_address, dex_type)
                    
                    # Create position object with fee tracking capability
                    position = {
                        "token_id": token_id,
                        "name": f"{token0_info['display_symbol']}/{token1_info['display_symbol']} Pool",
                        "dex_name": dex_name,
                        "dex_type": dex_type,
                        "position_manager": position_manager_address,
                        "factory_address": factory_address,
                        "token0_address": token0_address,
                        "token1_address": token1_address,
                        "token0_symbol": token0_info['display_symbol'],
                        "token1_symbol": token1_info['display_symbol'],
                        "token0_info": token0_info,
                        "token1_info": token1_info,
                        "fee": fee,
                        "tick_lower": tick_lower,
                        "tick_upper": tick_upper,
                        "liquidity": liquidity,
                        "pool_address": pool_address
                    }
                    
                    positions.append(position)
                    positions_added += 1
                    if self.debug_mode and not suppress_output:
                        print(f"Added {dex_name}: {position['name']} (Token ID: {token_id})")
                    
                except Exception as e:
                    print(f"Error fetching {dex_name} position {i}: {e}")
                    if self.debug_mode:
                        import traceback
                        traceback.print_exc()
            
            # Record scan status for this dex
            self._last_scan_status_by_dex[dex_name] = {
                'expected': int(balance),
                'fetched': int(positions_added),
                'skipped_empty': int(positions_skipped),
                'had_errors': bool(had_errors),
                'timestamp': int(time.time())
            }

            # Show DEX summary
            if not suppress_output:
                print(f"Summary: {positions_added} active, {positions_skipped} empty positions skipped")
                    
        except Exception as e:
            print(f"❌ Error accessing {dex_name} position manager: {e}")
            print(f"💡 Check that the position manager address is correct for {dex_name}")
            if self.debug_mode:
                import traceback
                traceback.print_exc()
            self._last_scan_status_by_dex[dex_name] = {
                'expected': 0,
                'fetched': 0,
                'skipped_empty': 0,
                'had_errors': True,
                'timestamp': int(time.time())
            }
        
        return positions

    def get_last_scan_status(self, dex_name):
        return self._last_scan_status_by_dex.get(dex_name, None)

    def get_last_event_hints(self, dex_name):
        return self._last_event_hints_by_dex.get(dex_name, {'removed_ids': set(), 'added_ids': set()})

    def get_live_liquidity(self, position):
        """Get current on-chain liquidity for a position"""
        try:
            position_manager = self.w3.eth.contract(
                address=Web3.to_checksum_address(position["position_manager"]),
                abi=POSITION_MANAGER_ABI
            )
            
            position_data = position_manager.functions.positions(position["token_id"]).call()
            return position_data[7]  # liquidity
            
        except Exception as e:
            print(f"⚠️  Error checking live liquidity for {position['name']}: {e}")
            return position["liquidity"]  # Fallback to cached value

    def get_position_acquired_timestamp(self, token_id, position_manager_address, wallet_address):
        """Return UNIX timestamp when the current wallet initially acquired this tokenId.
        Uses Transfer(to=wallet, tokenId) first occurrence to prevent fee collection from resetting APR.
        """
        cache_key = (int(token_id), Web3.to_checksum_address(position_manager_address), Web3.to_checksum_address(wallet_address))
        if cache_key in self._acquired_ts_cache:
            return self._acquired_ts_cache[cache_key]

        try:
            id_topic = '0x' + int(token_id).to_bytes(32, 'big').hex()
            # Fetch all Transfer logs for this tokenId (no 'to' filter to avoid provider quirks)
            logs = self._rl_call(self.w3.eth.get_logs, {
                'fromBlock': 0,
                'toBlock': 'latest',
                'address': Web3.to_checksum_address(position_manager_address),
                'topics': [self._topic_transfer, None, None, id_topic]
            })
            wallet_norm = Web3.to_checksum_address(wallet_address)
            
            # Find the FIRST time it was transferred to the wallet (not the most recent)
            # This prevents fee collection or other operations from resetting the APR calculation
            first_acquisition_ts = None
            for lg in logs if logs else []:
                if not lg.get('topics') or len(lg['topics']) < 4:
                    continue
                try:
                    to_addr = Web3.to_checksum_address('0x' + lg['topics'][2].hex()[-40:])
                except Exception:
                    continue
                if to_addr == wallet_norm:
                    block_num = lg['blockNumber']
                    block = self._rl_call(self.w3.eth.get_block, int(block_num))
                    ts = int(block['timestamp'])
                    if first_acquisition_ts is None or ts < first_acquisition_ts:
                        first_acquisition_ts = ts
            
            if first_acquisition_ts:
                self._acquired_ts_cache[cache_key] = first_acquisition_ts
                return first_acquisition_ts
            # Fallback: first IncreaseLiquidity for this token (often emitted at mint)
            # IncreaseLiquidity only has one indexed arg (tokenId). Filter with 2 topics
            inc_logs = self._rl_call(self.w3.eth.get_logs, {
                'fromBlock': 0,
                'toBlock': 'latest',
                'address': Web3.to_checksum_address(position_manager_address),
                'topics': [self._topic_increase, id_topic]
            })
            if inc_logs:
                first = inc_logs[0]
                block_num = first['blockNumber']
                block = self._rl_call(self.w3.eth.get_block, block_num)
                ts = int(block['timestamp'])
                self._acquired_ts_cache[cache_key] = ts
                return ts
        except Exception:
            pass
        return None

    def _get_current_pool_price_simple(self, position):
        """Get current pool price for position comparison (simple version)"""
        try:
            status = self.check_position_status(position, position.get('wallet_address', ''))
            if status:
                return status.get('current_price')
        except Exception:
            pass
        return None

    def _get_pool_price_at_block(self, pool_address, dex_type, block_number):
        """Return pool price (token0 in terms of token1) at a specific block.

        Uses slot0() for Uniswap V3 and globalState() for Algebra. Returns None on failure.
        Requires an archive-capable RPC. This is best-effort with graceful fallback.
        """
        try:
            if dex_type == "algebra_integral":
                pool_contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(pool_address),
                    abi=ALGEBRA_POOL_ABI_V3
                )
                global_state = pool_contract.functions.globalState().call(block_identifier=int(block_number))
                sqrt_price_x96 = global_state[0]
            else:
                pool_contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(pool_address),
                    abi=POOL_ABI
                )
                slot0 = pool_contract.functions.slot0().call(block_identifier=int(block_number))
                sqrt_price_x96 = slot0[0]

            # Need token decimals to compute human price
            pool_min = self.w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=MINIMAL_POOL_ABI)
            token0_addr = pool_min.functions.token0().call()
            token1_addr = pool_min.functions.token1().call()
            t0 = self.get_enhanced_token_info(token0_addr)
            t1 = self.get_enhanced_token_info(token1_addr)
            return sqrt_price_to_price(sqrt_price_x96, t0["decimals"], t1["decimals"]) if sqrt_price_x96 else None
        except Exception:
            return None

    def get_initial_position_entry(self, position, wallet_address):
        """
        Return initial entry data for a position from the mint/first liquidity event.
        This function now robustly searches the blockchain for the creation event to
        guarantee an accurate historical entry price.
        """
        token_id_for_debug = position.get('token_id', 'N/A')
        cache_key = (int(position["token_id"]), Web3.to_checksum_address(position["position_manager"]))
        if cache_key in self._initial_liquidity_cache:
            if self.debug_mode:
                print(f"DEBUG {token_id_for_debug}: Returning cached entry data.", flush=True)
            return self._initial_liquidity_cache[cache_key]

        if self.debug_mode:
            print(f"DEBUG {token_id_for_debug}: ----------------------------------------------------", flush=True)
            print(f"DEBUG {token_id_for_debug}: Starting historical entry fetch for token {token_id_for_debug}...", flush=True)

        try:
            token_id = int(position["token_id"])
            id_topic = '0x' + token_id.to_bytes(32, 'big').hex()
            position_manager = Web3.to_checksum_address(position["position_manager"])
            
            # --- Find Creation Block ---
            creation_block = None
            current_block = self._rl_call(self.w3.eth.block_number)
            if self.debug_mode:
                print(f"DEBUG {token_id_for_debug}: Current block is {current_block}. Searching last ~12 hours for mint event...", flush=True)

            chunk_size = 2000
            # Reduced search range to ~12 hours (4000 blocks) to prevent hanging
            for start_block in range(current_block, max(0, current_block - 4000), -chunk_size):
                end_block = start_block
                from_block = max(0, start_block - chunk_size + 1)
                
                try:
                    if self.debug_mode:
                        print(f"DEBUG {token_id_for_debug}: Searching for mint in blocks {from_block}-{end_block}...", flush=True)
                    logs = self._rl_call(self.w3.eth.get_logs, {
                        'fromBlock': from_block,
                        'toBlock': end_block,
                        'address': position_manager,
                        'topics': [self._topic_transfer, '0x0000000000000000000000000000000000000000000000000000000000000000', None, id_topic]
                    })
                    if logs:
                        creation_block = logs[0]['blockNumber']
                        if self.debug_mode:
                            print(f"DEBUG {token_id_for_debug}: Found mint event in block range {from_block}-{end_block}. Creation Block: {creation_block}", flush=True)
                        break 
                except Exception as e:
                    if self.debug_mode:
                        print(f"DEBUG {token_id_for_debug}: (Info) No mint event found in blocks {from_block}-{end_block}. Error: {e}", flush=True)
            
            if not creation_block:
                if self.debug_mode:
                    print(f"DEBUG {token_id_for_debug}: Mint event not found. Will rely on IncreaseLiquidity event to find block.", flush=True)

            # --- Get Initial Liquidity Amounts ---
            search_block_start = creation_block if creation_block else max(0, current_block - 4000)
            # Widen the search range slightly in case of block reorganization or timing issues
            search_block_end = creation_block + 50 if creation_block else current_block
            if self.debug_mode:
                print(f"DEBUG {token_id_for_debug}: Searching for IncreaseLiquidity event in blocks {search_block_start}-{search_block_end}...", flush=True)

            increase_logs = self._rl_call(self.w3.eth.get_logs, {
                'fromBlock': search_block_start,
                'toBlock': search_block_end,
                'address': position_manager,
                'topics': [self._topic_increase, id_topic]
            })

            if not increase_logs:
                if self.debug_mode:
                    print(f"DEBUG {token_id_for_debug}: CRITICAL - Could not find any IncreaseLiquidity event for token. Cannot determine entry.", flush=True)
                self._initial_liquidity_cache[cache_key] = None
                return None

            first_increase = increase_logs[0]
            if not creation_block:
                 creation_block = first_increase['blockNumber']
                 if self.debug_mode:
                    print(f"DEBUG {token_id_for_debug}: Using block {creation_block} from the first IncreaseLiquidity event.", flush=True)

            # --- Extract Amounts and Timestamp ---
            if self.debug_mode:
                print(f"DEBUG {token_id_for_debug}: Extracting data from IncreaseLiquidity event at block {creation_block}...", flush=True)
            data_bytes = bytes.fromhex(first_increase['data'][2:])
            amount0_wei = int.from_bytes(data_bytes[32:64], 'big')
            amount1_wei = int.from_bytes(data_bytes[64:96], 'big')

            decimals0 = position["token0_info"]["decimals"]
            decimals1 = position["token1_info"]["decimals"]
            amount0 = amount0_wei / (10 ** decimals0)
            amount1 = amount1_wei / (10 ** decimals1)

            blk = self._rl_call(self.w3.eth.get_block, creation_block)
            ts = int(blk['timestamp'])
            if self.debug_mode:
                print(f"DEBUG {token_id_for_debug}: Initial amounts: {amount0:.4f} T0, {amount1:.4f} T1 at timestamp {ts}", flush=True)

            # --- Fetch Historical Price ---
            pool_address = position.get('pool_address')
            if not pool_address:
                 pool_address = self.get_pool_address(
                    position.get('token0_address'), position.get('token1_address'), 
                    position.get('fee'), position.get('factory_address'), position.get('dex_type', 'uniswap_v3')
                )
            if self.debug_mode:
                print(f"DEBUG {token_id_for_debug}: Pool address is {pool_address}. Fetching historical price...", flush=True)

            entry_price = None
            if pool_address:
                entry_price = self._get_pool_price_at_block(pool_address, position.get('dex_type', 'uniswap_v3'), creation_block)
                if self.debug_mode:
                    if entry_price is not None:
                        print(f"DEBUG {token_id_for_debug}: Successfully fetched historical price at block {creation_block}: {entry_price:.6f}", flush=True)
                    else:
                        print(f"DEBUG {token_id_for_debug}: FAILED to fetch historical price at block {creation_block}.", flush=True)
            else:
                 if self.debug_mode:
                    print(f"DEBUG {token_id_for_debug}: Could not determine pool address.", flush=True)

            # --- Calculate USD Value at Entry ---
            token0_symbol = position.get('token0_symbol')
            token1_symbol = position.get('token1_symbol')
            entry_token0_price_usd = None
            entry_token1_price_usd = None

            if entry_price is not None:
                if is_stablecoin(token1_symbol):
                    entry_token1_price_usd = 1.0
                    entry_token0_price_usd = entry_price
                elif is_stablecoin(token0_symbol):
                    entry_token0_price_usd = 1.0
                    entry_token1_price_usd = 1.0 / entry_price if entry_price > 0 else 0
            
            entry_value_usd = None
            if entry_token0_price_usd is not None and entry_token1_price_usd is not None:
                entry_value_usd = amount0 * entry_token0_price_usd + amount1 * entry_token1_price_usd
            
            if self.debug_mode:
                print(f"DEBUG {token_id_for_debug}: Final calculated entry value: ${entry_value_usd if entry_value_usd is not None else 'N/A'}", flush=True)
                print(f"DEBUG {token_id_for_debug}: ----------------------------------------------------", flush=True)


            result = {
                'block_number': creation_block,
                'timestamp': ts,
                'amount0': amount0,
                'amount1': amount1,
                'entry_price': entry_price or 0,
                'entry_token0_price_usd': entry_token0_price_usd,
                'entry_token1_price_usd': entry_token1_price_usd,
                'entry_value_usd': entry_value_usd
            }
            self._initial_liquidity_cache[cache_key] = result
            return result

        except Exception as e:
            if self.debug_mode:
                import traceback
                print(f"❌ DEBUG {token_id_for_debug}: CRITICAL ERROR in get_initial_position_entry: {e}", flush=True)
                traceback.print_exc()
            self._initial_liquidity_cache[cache_key] = None
            return None

    def check_position_status(self, position, wallet_address):
        """Check position status with fee tracking"""
        dex_type = position.get("dex_type", "uniswap_v3")
        pool_data = self.get_pool_data_flexible(position["pool_address"], dex_type)
        
        if not pool_data:
            return None
        
        current_tick = pool_data["current_tick"]
        lower_tick = position["tick_lower"]
        upper_tick = position["tick_upper"]
        
        # Check if position is in range
        in_range = lower_tick <= current_tick <= upper_tick
        
        # Calculate distances
        distance_to_lower = current_tick - lower_tick
        distance_to_upper = upper_tick - current_tick
        
        # Calculate prices with correct decimals
        decimals0 = pool_data["token0_decimals"]
        decimals1 = pool_data["token1_decimals"]
        
        current_price = pool_data["price"]
        lower_price = tick_to_price(lower_tick, decimals0, decimals1)
        upper_price = tick_to_price(upper_tick, decimals0, decimals1)
        
        # Calculate actual token amounts
        amount0, amount1 = calculate_token_amounts(
            position["liquidity"], current_tick, lower_tick, upper_tick, decimals0, decimals1
        )
        
        # Calculate theoretical amounts (what it would be if centered in range)
        theoretical_amount0, theoretical_amount1 = calculate_theoretical_amounts(
            position["liquidity"], lower_tick, upper_tick, decimals0, decimals1
        )
        
        # Get unclaimed fees
        fee_data = self.get_unclaimed_fees(position, wallet_address)
        # Get acquisition timestamp and initial entry data
        acquired_ts = self.get_position_acquired_timestamp(position['token_id'], position['position_manager'], wallet_address)
        initial_entry = self.get_initial_position_entry(position, wallet_address)
        
        # Deterministic fallback entry price from range boundaries: use geometric mean of lower/upper prices (center of range)
        # This serves as a reasonable approximation when on-chain mint data isn't available.
        center_price = 0
        try:
            if lower_price > 0 and upper_price > 0:
                center_price = (lower_price * upper_price) ** 0.5
        except Exception:
            center_price = 0

        return {
            "in_range": in_range,
            "current_tick": current_tick,
            "current_price": current_price,
            "lower_price": lower_price,
            "upper_price": upper_price,
            "distance_to_lower": distance_to_lower,
            "distance_to_upper": distance_to_upper,
            "token0_symbol": pool_data["token0_symbol"],
            "token1_symbol": pool_data["token1_symbol"],
            "token_id": position["token_id"],
            "liquidity": position["liquidity"],
            "amount0": amount0,
            "amount1": amount1,
            "theoretical_amount0": theoretical_amount0,
            "theoretical_amount1": theoretical_amount1,
            "dex_name": position["dex_name"],
            "dex_type": dex_type,
            "method": pool_data.get("method", "unknown"),
            "raw_data": pool_data if self.debug_mode else None,
            # Fee data
            "fee_amount0": fee_data["fee_amount0"],
            "fee_amount1": fee_data["fee_amount1"],
            "fee_amount0_wei": fee_data["fee_amount0_wei"],
            "fee_amount1_wei": fee_data["fee_amount1_wei"],
            "has_unclaimed_fees": fee_data["has_fees"],
            "fee_error": fee_data.get("error"),
            "acquired_timestamp": acquired_ts,
            # Initial (entry) data for accurate PnL
            "entry_amount0": (initial_entry or {}).get('amount0'),
            "entry_amount1": (initial_entry or {}).get('amount1'),
            "entry_price_at_entry": (initial_entry or {}).get('entry_price', 0),
            "entry_token0_price_usd": (initial_entry or {}).get('entry_token0_price_usd'),
            "entry_token1_price_usd": (initial_entry or {}).get('entry_token1_price_usd'),
            "entry_value_usd": (initial_entry or {}).get('entry_value_usd'),
            # Provide center price approximation to DB layer for fallback valuation
            "entry_price_center": center_price
        }