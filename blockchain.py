#!/usr/bin/env python3
"""
Blockchain Interaction Module for HyperEVM LP Monitor
Handles Web3 connections, smart contract calls, and DEX-specific logic

UPDATED VERSION: Added unclaimed fee tracking using static collect() calls

Version: 1.4.1 (With Fee Tracking)
Developer: 8roku8.hl
"""

from web3 import Web3
import time
from constants import (
    POOL_ABI, ALGEBRA_POOL_ABI_V1, ALGEBRA_POOL_ABI_V3, MINIMAL_POOL_ABI,
    TOKEN_ABI, POSITION_MANAGER_ABI, FACTORY_ABI, ALGEBRA_FACTORY_ABI,
    TOKEN_SYMBOL_MAPPINGS, KNOWN_TOKENS
)
from utils import (
    sqrt_price_to_price, tick_to_price, calculate_token_amounts,
    calculate_theoretical_amounts, apply_symbol_mapping,
    parse_algebra_raw_data
)

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
                        
                        # Get token addresses
                        token0_address = pool_contract.functions.token0().call()
                        token1_address = pool_contract.functions.token1().call()
                        
                        # Get enhanced token info
                        token0_info = self.get_enhanced_token_info(token0_address, "Algebra")
                        token1_info = self.get_enhanced_token_info(token1_address, "Algebra")
                        
                        # Calculate price with correct decimals
                        price = sqrt_price_to_price(sqrt_price_x96, token0_info["decimals"], token1_info["decimals"])
                        
                        return {
                            "current_tick": current_tick,
                            "price": price,
                            "sqrt_price_x96": sqrt_price_x96,
                            "token0_decimals": token0_info["decimals"],
                            "token1_decimals": token1_info["decimals"],
                            "token0_symbol": token0_info["display_symbol"],
                            "token1_symbol": token1_info["display_symbol"],
                            "algebra_version": version,
                            "method": f"algebra_{version}_abi"
                        }
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
                
                token0_address = pool_contract.functions.token0().call()
                token1_address = pool_contract.functions.token1().call()
                
                # Try raw call to globalState
                function_selector = self.w3.keccak(text="globalState()")[:4]
                raw_result = self.w3.eth.call({
                    'to': pool_address,
                    'data': function_selector.hex()
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
                    
                    return {
                        "current_tick": current_tick,
                        "price": price,
                        "sqrt_price_x96": sqrt_price_x96,
                        "token0_decimals": token0_info["decimals"],
                        "token1_decimals": token1_info["decimals"],
                        "token0_symbol": token0_info["display_symbol"],
                        "token1_symbol": token1_info["display_symbol"],
                        "algebra_version": "enhanced_raw",
                        "method": "enhanced_raw_parsing"
                    }
                    
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
            
            # Get token addresses
            token0_address = pool_contract.functions.token0().call()
            token1_address = pool_contract.functions.token1().call()
            
            # Get enhanced token info
            token0_info = self.get_enhanced_token_info(token0_address, "Uniswap V3")
            token1_info = self.get_enhanced_token_info(token1_address, "Uniswap V3")
            
            # Calculate price with correct decimals
            price = sqrt_price_to_price(sqrt_price_x96, token0_info["decimals"], token1_info["decimals"])
            
            return {
                "current_tick": current_tick,
                "price": price,
                "sqrt_price_x96": sqrt_price_x96,
                "token0_decimals": token0_info["decimals"],
                "token1_decimals": token1_info["decimals"],
                "token0_symbol": token0_info["display_symbol"],
                "token1_symbol": token1_info["display_symbol"],
                "method": "uniswap_v3"
            }
            
        except Exception as e:
            print(f"⚠️  All methods failed for pool {pool_address}: {e}")
            return None

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

    def fetch_positions_from_dex(self, wallet_address, dex_config, silent=False):
        """Fetch LP positions from a specific DEX with fee tracking"""
        dex_name = dex_config["name"]
        position_manager_address = dex_config["position_manager"]
        dex_type = dex_config.get("type", "uniswap_v3")
        
        positions = []
        
        if not silent:
            print(f"\nChecking {dex_name} ({dex_type})...")
        
        try:
            position_manager = self.w3.eth.contract(
                address=Web3.to_checksum_address(position_manager_address),
                abi=POSITION_MANAGER_ABI
            )
            
            # Get factory address from position manager
            factory_address = None
            try:
                factory_address = position_manager.functions.factory().call()
                if self.debug_mode and not silent:
                    print(f"Factory: {factory_address}")
                
                # Auto-detect DEX type if not specified
                if dex_type == "uniswap_v3" and dex_name.lower() in ["gliquid", "quickswap"]:
                    detected_type = self.detect_dex_type(dex_name, factory_address)
                    if detected_type != dex_type:
                        dex_type = detected_type
                        dex_config["type"] = dex_type  # Update config
                        
            except Exception as e:
                print(f"⚠️  Could not get factory address from {dex_name} position manager: {e}")
            
            # Get number of positions owned by wallet
            balance = position_manager.functions.balanceOf(wallet_address).call()
            if not silent:
                print(f"Found {balance} LP NFT(s) in {dex_name}")
            
            if balance == 0:
                return positions
            
            # Show progress for large numbers of positions
            if balance > 10 and not silent:
                print(f"Scanning {balance} positions (this may take a moment)...")
            
            positions_added = 0
            positions_skipped = 0
            
            # Get each position
            for i in range(balance):
                try:
                    # Show progress for large scans
                    if balance > 20 and (i + 1) % 10 == 0:
                        if not silent:
                            print(f"Progress: {i + 1}/{balance} positions scanned...")
                    
                    # Get token ID
                    token_id = position_manager.functions.tokenOfOwnerByIndex(wallet_address, i).call()
                    
                    # Get position details (single RPC call)
                    position_data = position_manager.functions.positions(token_id).call()
                    
                    # Extract basic info
                    liquidity = position_data[7]
                    
                    # FAST CHECK: Skip positions with no liquidity BEFORE expensive operations
                    if liquidity == 0:
                        positions_skipped += 1
                        # Only show detailed skipping info in debug mode to avoid clutter
                        if self.debug_mode and balance <= 20 and not silent:
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
                    if self.debug_mode and not silent:
                        print(f"Added {dex_name}: {position['name']} (Token ID: {token_id})")
                    
                except Exception as e:
                    print(f"Error fetching {dex_name} position {i}: {e}")
                    if self.debug_mode:
                        import traceback
                        traceback.print_exc()
            
            # Show DEX summary (always show a compact summary to replace per-position logs)
            if not silent:
                print(f"Summary: {positions_added} active, {positions_skipped} empty positions skipped")
                    
        except Exception as e:
            print(f"❌ Error accessing {dex_name} position manager: {e}")
            print(f"💡 Check that the position manager address is correct for {dex_name}")
            if self.debug_mode:
                import traceback
                traceback.print_exc()
        
        return positions

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
            "fee_error": fee_data.get("error")
        }