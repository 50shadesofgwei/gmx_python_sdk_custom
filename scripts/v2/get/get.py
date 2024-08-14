import logging

from .get_markets import Markets
from .get_oracle_prices import OraclePrices
from ..gmx_utils import (
    get_reader_contract, contract_map, save_json_file_to_datastore,
    save_csv_to_datastore, make_timestamped_dataframe
)


class GetData:
    def __init__(
        self, config: str, use_local_datastore: bool = False,
        filter_swap_markets: bool = True
    ):
        self.config = config
        self.use_local_datastore = use_local_datastore
        self.filter_swap_markets = filter_swap_markets

        self.log = logging.getLogger(self.__class__.__name__)
        self.markets = Markets(config)
        self.reader_contract = get_reader_contract(config)
        self.data_store_contract_address = (
            contract_map[self.config.chain]['datastore']['contract_address']
        )
        self.output = {
            "long": {},
            "short": {}
        }

        self._long_token_address = None
        self._short_token_address = None

    def get_data(self, to_json: bool = False, to_csv: bool = False):
        if self.filter_swap_markets:
            self._filter_swap_markets()

        data = self._get_data_processing()

        if to_json:
            save_json_file_to_datastore(
                "{}_data.json".format(self.config.chain),
                data
            )

        if to_csv:
            data = make_timestamped_dataframe(data)
            save_csv_to_datastore(
                "{}_data.csv".format(self.config.chain),
                data
            )

        return data

    def _get_data_processing(self):
        pass

    def _get_token_addresses(self, market_key: str):
        self._long_token_address = self.markets.get_long_token_address(
            market_key
        )
        self._short_token_address = self.markets.get_short_token_address(
            market_key
        )


    def _filter_swap_markets(self):
        # TODO: Move to markets MAYBE
        keys_to_remove = []
        for market_key in self.markets.info:
            market_symbol = self.markets.get_market_symbol(market_key)
            if 'SWAP' in market_symbol:
                # Remove swap markets from dict
                keys_to_remove.append(market_key)

        [self.markets.info.pop(k) for k in keys_to_remove]

    def _get_pnl(
        self, market: list, prices_list: list, is_long: bool,
        maximize: bool = False
    ):
        open_interest_pnl = (
            self.reader_contract.functions.getOpenInterestWithPnl(
                self.data_store_contract_address,
                market,
                prices_list,
                is_long,
                maximize
            )
        )

        pnl = self.reader_contract.functions.getPnl(
            self.data_store_contract_address,
            market,
            prices_list,
            is_long,
            maximize
        )

        return open_interest_pnl, pnl

    def _get_oracle_prices(
        self,
        market_key: str,
        index_token_address: str,
        oracle_prices: dict,
        return_tuple: bool = False,
    ):
        """
        For a given market get the marketInfo from the reader contract

        Parameters
        ----------
        market_key : str
            address of GMX market.
        index_token_address : str
            address of index token.
        long_token_address : str
            address of long collateral token.
        short_token_address : str
            address of short collateral token.

        Returns
        -------
        reader_contract object
            unexecuted reader contract object.

        """
        oracle_prices_dict = oracle_prices

        try:
            prices = (
                (
                    int(
                        (
                            oracle_prices_dict[index_token_address]
                            ['minPriceFull']
                        )
                    ),
                    int(
                        (
                            oracle_prices_dict[index_token_address]
                            ['maxPriceFull']
                        )
                    )
                ),
                (
                    int(
                        (
                            oracle_prices_dict[self._long_token_address]
                            ['minPriceFull']
                        )
                    ),
                    int(
                        (
                            oracle_prices_dict[self._long_token_address]
                            ['maxPriceFull']
                        )
                    )
                ),
                (
                    int(
                        (
                            oracle_prices_dict[self._short_token_address]
                            ['minPriceFull']
                        )
                    ),
                    int(
                        (
                            oracle_prices_dict[self._short_token_address]
                            ['maxPriceFull']
                        )
                    )
                ))

        # TODO - this needs to be here until GMX add stables to signed price
        # API
        except KeyError:
            prices = (
                (
                    int(
                        oracle_prices_dict[index_token_address]['minPriceFull']
                    ),
                    int(
                        oracle_prices_dict[index_token_address]['maxPriceFull']
                    )
                ),
                (
                    int(
                        (
                            oracle_prices_dict[self._long_token_address]
                            ['minPriceFull']
                        )
                    ),
                    int(
                        (
                            oracle_prices_dict[self._long_token_address]
                            ['maxPriceFull']
                        )
                    )
                ),
                (
                    int(1000000000000000000000000),
                    int(1000000000000000000000000)
                ))

        if return_tuple:
            return prices

        return self.reader_contract.functions.getMarketInfo(
            self.data_store_contract_address,
            prices,
            market_key
        )
