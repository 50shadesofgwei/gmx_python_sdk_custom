import json
import os

from .get import GetData
from .get_open_interest import OpenInterest
from ..gmx_utils import (
    get_funding_factor_per_period, base_dir, execute_threading,
)


class GetFundingFee(GetData):
    def __init__(self, config, use_local_datastore: bool = False):
        super().__init__(config)
        self.config = config
        self.use_local_datastore = use_local_datastore

    def _get_data_processing(self, open_interest: dict, oracle_prices: dict, target_market: str = None):
        """
        Generate the dictionary of funding APR data

        Returns
        -------
        funding_apr : dict
            dictionary of funding data.

        """

        # define empty lists to pass to zip iterater later on
        mapper = []
        output_list = []
        long_interest_usd_list = []
        short_interest_usd_list = []

        # loop markets
        for market_key in self.markets.info:
            if target_market:
                if market_key != target_market:
                    continue
            symbol = self.markets.get_market_symbol(market_key)
            index_token_address = self.markets.get_index_token_address(
                market_key
            )
            if index_token_address == '0x0000000000000000000000000000000000000000':
                continue
            
            self._get_token_addresses(market_key)

            output = self._get_oracle_prices(
                market_key,
                index_token_address,
                oracle_prices
            )

            mapper.append(symbol)
            output_list.append(output)
            long_interest_usd_list = (
                long_interest_usd_list +
                [
                    open_interest['long'][symbol] * 10 ** 30
                ]
            )
            short_interest_usd_list = (
                short_interest_usd_list +
                [
                    open_interest['short'][symbol] * 10 ** 30
                ]
            )

        # Multithreaded call on contract
        threaded_output = execute_threading(output_list)
        for (
            output,
            long_interest_usd,
            short_interest_usd,
            symbol
        ) in zip(
            threaded_output,
            long_interest_usd_list,
            short_interest_usd_list,
            mapper
        ):

            market_info_dict = {
                "market_token": output[0][0],
                "index_token": output[0][1],
                "long_token": output[0][2],
                "short_token": output[0][3],
                "long_borrow_fee": output[1],
                "short_borrow_fee": output[2],
                "is_long_pays_short": output[4][0],
                "funding_factor_per_second": output[4][1]
            }

            long_funding_fee = get_funding_factor_per_period(
                market_info_dict,
                True,
                3600,
                long_interest_usd,
                short_interest_usd
            )

            short_funding_fee = get_funding_factor_per_period(
                market_info_dict,
                False,
                3600,
                long_interest_usd,
                short_interest_usd
            )

            self.output['long'][symbol] = long_funding_fee
            self.output['short'][symbol] = short_funding_fee

        return self.output
