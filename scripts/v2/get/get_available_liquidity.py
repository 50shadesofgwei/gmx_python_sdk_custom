import time

import numpy as np
from numerize import numerize
from typing import Tuple, Any
from GlobalUtils.logger import logger

from .get import GetData
from ..gmx_utils import execute_threading
from ..keys import (
    get_datastore_contract, pool_amount_key, reserve_factor_key,
    open_interest_reserve_factor_key
)


class GetAvailableLiquidity(GetData):
    def __init__(self, config, use_local_datastore: bool = False):
        super().__init__(config)

    def _get_data_processing(self, open_interest: dict, oracle_prices: dict) -> dict:
        """
        Generate the dictionary of available liquidity

        Returns
        -------
        funding_apr: dict
            dictionary of available liquidity

        """
        try:

            reserved_long_list = []
            reserved_short_list = []
            token_price_list = []
            mapper = []
            long_pool_amount_list = []
            long_reserve_factor_list = []
            long_open_interest_reserve_factor_list = []
            short_pool_amount_list = []
            short_reserve_factor_list = []
            short_open_interest_reserve_factor_list = []
            long_precision_list = []
            short_precision_list = []
            self._filter_swap_markets()

            for market_key in self.markets.info:
                self._get_token_addresses(market_key)
                market_symbol = self.markets.get_market_symbol(market_key)
                index_token_address = self.markets.get_index_token_address(market_key)

                if index_token_address == '0x0000000000000000000000000000000000000000':
                    continue

                long_decimal_factor = self.markets.get_decimal_factor(
                    market_key=market_key,
                    long=True,
                    short=False
                )
                short_decimal_factor = self.markets.get_decimal_factor(
                    market_key=market_key,
                    long=False,
                    short=True
                )
                long_precision = 10**(30 + long_decimal_factor)
                short_precision = 10**(30 + short_decimal_factor)
                oracle_precision = 10**(30 - long_decimal_factor)

                # collate market symbol to map dictionary later
                mapper.append(market_symbol)

                # LONG POOL
                (
                    long_pool_amount,
                    long_reserve_factor,
                    long_open_interest_reserve_factor
                ) = self.get_max_reserved_usd(
                    market_key,
                    self._long_token_address,
                    True
                )
                reserved_long_list.append(open_interest['long'][market_symbol])
                long_pool_amount_list.append(long_pool_amount)
                long_reserve_factor_list.append(long_reserve_factor)
                long_open_interest_reserve_factor_list.append(
                    long_open_interest_reserve_factor
                )
                long_precision_list.append(long_precision)

                # SHORT POOL
                (
                    short_pool_amount,
                    short_reserve_factor,
                    short_open_interest_reserve_factor
                ) = self.get_max_reserved_usd(
                    market_key,
                    self._short_token_address,
                    False
                )
                reserved_short_list.append(open_interest['short'][market_symbol])
                short_pool_amount_list.append(short_pool_amount)
                short_reserve_factor_list.append(short_reserve_factor)
                short_open_interest_reserve_factor_list.append(
                    short_open_interest_reserve_factor
                )
                short_precision_list.append(short_precision)

                # Calculate token price
                token_price = np.median(
                    [
                        float(
                            oracle_prices[self._long_token_address]['maxPriceFull']
                        ) / oracle_precision,
                        float(
                            oracle_prices[self._long_token_address]['minPriceFull']
                        ) / oracle_precision
                    ]
                )
                token_price_list.append(token_price)

            long_pool_amount_output = execute_threading(long_pool_amount_list)
            short_pool_amount_output = execute_threading(short_pool_amount_list)

            long_reserve_factor_list_output = execute_threading(
                long_reserve_factor_list
            )

            short_reserve_factor_list_output = execute_threading(
                short_reserve_factor_list
            )

            long_open_interest_reserve_factor_list_output = execute_threading(
                long_open_interest_reserve_factor_list
            )

            short_open_interest_reserve_factor_list_output = execute_threading(
                short_open_interest_reserve_factor_list
            )

            for (
                long_pool_amount,
                short_pool_amount,
                long_reserve_factor,
                short_reserve_factor,
                long_open_interest_reserve_factor,
                short_open_interest_reserve_factor,
                reserved_long,
                reserved_short,
                token_price,
                token_symbol,
                long_precision,
                short_precision
            ) in zip(
                long_pool_amount_output,
                short_pool_amount_output,
                long_reserve_factor_list_output,
                short_reserve_factor_list_output,
                long_open_interest_reserve_factor_list_output,
                short_open_interest_reserve_factor_list_output,
                reserved_long_list,
                reserved_short_list,
                token_price_list,
                mapper,
                long_precision_list,
                short_precision_list
            ):

                # select the lesser of maximum value of pool reserves or open
                # interest limit
                if long_open_interest_reserve_factor < long_reserve_factor:
                    long_reserve_factor = long_open_interest_reserve_factor

                if "2" in token_symbol:
                    long_pool_amount = long_pool_amount / 2

                long_max_reserved_tokens = (
                    long_pool_amount * long_reserve_factor
                )

                long_max_reserved_usd = (
                    long_max_reserved_tokens / long_precision * token_price
                )

                long_liquidity = long_max_reserved_usd - float(reserved_long)

                # select the lesser of maximum value of pool reserves or open
                # interest limit
                if short_open_interest_reserve_factor < short_reserve_factor:
                    short_reserve_factor = short_open_interest_reserve_factor

                short_max_reserved_usd = (short_pool_amount * short_reserve_factor)

                short_liquidity = (
                    short_max_reserved_usd / short_precision - float(
                        reserved_short
                    )
                )

                # If its a single side market need to calculate on token
                # amount rather than $ value
                if "2" in token_symbol:
                    short_pool_amount = short_pool_amount / 2

                    short_max_reserved_tokens = (
                        short_pool_amount * short_reserve_factor
                    )

                    short_max_reserved_usd = (
                        short_max_reserved_tokens / short_precision * token_price
                    )

                    short_liquidity = short_max_reserved_usd - float(reserved_short)

                self.output['long'][token_symbol] = float(long_liquidity)
                self.output['short'][token_symbol] = short_liquidity

            return self.output
        
        except Exception as e:
            logger.error(f'GMX-SDK: get_available_liquidity - Failed to get available liquidity from GMX smart contracts. Error: {e}', exc_info=True)
            return None

    def get_max_reserved_usd(self, market: str, token: str, is_long: bool) -> (
        Tuple[Any, Any, Any]
    ):
        """
        For a given market, long/short token and pool direction get the
        uncalled web3 functions to calculate pool size, pool reserve factor
        and open interest reserve factor

        Parameters
        ----------
        market: str
            contract address of GMX market.
        token: str
            contract address of long or short token.
        is_long: bool
            pass True for long pool or False for short.

        Returns
        -------
        pool_amount: web3.contract_obj
            uncalled web3 contract object for pool amount.
        reserve_factor: web3.contract_obj
            uncalled web3 contract object for pool reserve factor.
        open_interest_reserve_factor: web3.contract_obj
            uncalled web3 contract object for open interest reserve factor.

        """
        pool_amount: Any  # Type: web3._utils.datatypes.getUint
        reserve_factor: Any  # Type: web3._utils.datatypes.getUint
        open_interest_reserve_factor: Any  # Type: web3._utils.datatypes.getUint

        # get web3 datastore object
        datastore = get_datastore_contract(self.config)

        # get hashed keys for datastore
        pool_amount_hash_data = pool_amount_key(
            market,
            token
        )
        reserve_factor_hash_data = reserve_factor_key(
            market,
            is_long
        )
        open_interest_reserve_factor_hash_data = (
            open_interest_reserve_factor_key(
                market,
                is_long
            )
        )

        pool_amount = datastore.functions.getUint(
            pool_amount_hash_data
        )
        reserve_factor = datastore.functions.getUint(
            reserve_factor_hash_data
        )
        open_interest_reserve_factor = datastore.functions.getUint(
            open_interest_reserve_factor_hash_data
        )

        return pool_amount, reserve_factor, open_interest_reserve_factor


if __name__ == "__main__":
    data = GetAvailableLiquidity(
        chain="arbitrum",
        use_local_datastore=False
    ).get_data(
        to_csv=False
    )
