"""
Async EOS API client allowing for high speed block importing

**Copyright**::

    +===================================================+
    |                 © 2019 Privex Inc.                |
    |               https://www.privex.io               |
    +===================================================+
    |                                                   |
    |        Privex EOS History API                     |
    |                                                   |
    |        Core Developer(s):                         |
    |                                                   |
    |          (+)  Chris (@someguy123) [Privex]        |
    |                                                   |
    +===================================================+

"""
from typing import Union, List
import attr
import httpx
from privex.helpers.asyncx import run_sync
import privex.jsonrpc
from privex.coin_handlers.base.objects import AttribDictable


def attr_dict(cls: type, data: dict):
    """
    Removes keys from the passed dict ``data`` which don't exist on ``cls`` (thus would get rejected as kwargs),
    then create and return an instance of ``cls``, passing the filtered data as keyword args.
    
    Ensures that any keys in your dictionary which don't exist on ``cls`` are automatically filtered out, instead
    of causing an error due to unexpected keyword arguments.
    
    Example::
    
        >>> data = dict(timestamp="2019-01-01Z00:00", producer='eosio', block_num=1234, example='hello')
        >>> my_block = attr_dict(EOSBlock, data)
        
    
    :param cls:
    :param data:
    :return:
    """
    if hasattr(cls, '__attrs_attrs__'):
        cls_keys = [atr.name for atr in cls.__attrs_attrs__]
    else:
        cls_keys = [k for k in cls.__dict__.keys() if k[0] != '_']
    
    clean_data = {x: y for x, y in data.items() if x in cls_keys}
    return cls(**clean_data)


@attr.s
class EOSTransaction(AttribDictable):
    status = attr.ib(type=str)
    cpu_usage_us = attr.ib(type=int, default=0)
    net_usage_words = attr.ib(type=int, default=0)
    trx = attr.ib(type=Union[dict, str], default=None)
    """
    Contents of ``trx``::
        
        dict_keys([
            id:str, signatures:list, compression:str, packed_context_free_data:str, context_free_data:list,
            packed_trx:str, transaction:dict
        ])
    
    """
    
    id = attr.ib(type=str)
    signatures = attr.ib(type=list)
    compression = attr.ib(type=str)
    context_free_data = attr.ib(type=list)
    packed_trx = attr.ib(type=str)
    transaction = attr.ib(type=Union[dict, str])
    """
    Contents of ``trx['transaction']``::
        
        dict_keys([
            expiration:str, ref_block_num:int, ref_block_prefix:int, max_net_usage_words:int, max_cpu_usage_ms:int,
            delay_sec:int, context_free_actions:list, actions:List[dict], transaction_extensions:list
        ])
        
    Contents of a ``trx['transaction']['actions']`` dict::
    
        dict_keys([account:str, name:str, authorization:List[dict], data:dict, hex_data])
    
    """

    @id.default
    def _id_default(self):
        if type(self.trx) is str:
            return self.trx
        if type(self.trx) is dict:
            return self.trx['id']
        return None
    
    @signatures.default
    def _signatures_default(self): return self.trx['signatures'] if type(self.trx) is dict else []
    
    @compression.default
    def _compression_default(self): return self.trx['compression'] if type(self.trx) is dict else 'none'

    @context_free_data.default
    def _context_free_data_default(self): return self.trx['context_free_data'] if type(self.trx) is dict else []

    @packed_trx.default
    def _packed_trx_default(self): return self.trx['packed_trx'] if type(self.trx) is dict else None

    @transaction.default
    def _transaction_default(self): return self.trx['transaction'] if type(self.trx) is dict else None

    @staticmethod
    def from_dict(data: dict):
        if isinstance(data, EOSTransaction):
            return data
        return attr_dict(EOSTransaction, data)
    
    @staticmethod
    def from_list(data: List[dict]) -> list:
        if len(data) == 0:
            return []
        if isinstance(data[0], EOSTransaction):
            return data
        
        return [attr_dict(EOSTransaction, d) for d in data]


@attr.s
class EOSBlock(AttribDictable):
    timestamp = attr.ib(type=str)
    producer = attr.ib(type=str)
    block_num = attr.ib(type=int)
    ref_block_prefix = attr.ib(type=int)
    
    confirmed = attr.ib(type=int, default=0)
    previous = attr.ib(type=str, default=None)
    transaction_mroot = attr.ib(type=str, default=None)
    action_mroot = attr.ib(type=str, default=None)
    id = attr.ib(type=str, default=None)
    new_producers = attr.ib(default=None)
    header_extensions = attr.ib(type=list, factory=list)
    producer_signature = attr.ib(type=str, default=None)
    transactions = attr.ib(type=List[EOSTransaction], factory=list, converter=EOSTransaction.from_list)
    block_extensions = attr.ib(type=list, factory=list)
    schedule_version = attr.ib(type=int, default=None)

    @staticmethod
    def from_dict(data: dict):
        return attr_dict(EOSBlock, data)

    @staticmethod
    def from_list(data: List[dict]) -> list:
        return [attr_dict(EOSBlock, d) for d in data]


class Api:
    url: str
    endpoints = {
        'get_block': '/v1/chain/get_block',
        'get_info': '/v1/chain/get_info',
        'get_currency_balance': '/v1/chain/get_currency_balance',
        'get_currency_stats': '/v1/chain/get_currency_stats',
        'get_producers': '/v1/chain/get_producers',
        'get_table_by_scope': '/v1/chain/get_table_by_scope',
        'get_table_rows': '/v1/chain/get_table_rows',
    }
    
    def __init__(self, url="https://eos.greymass.com"):
        self.url = url.strip().strip('/')
    
    async def get_block(self, number: int) -> EOSBlock:
        """
        Get the contents of the EOS block number ``number`` - returned as a dictionary (see detailed return info
        at bottom of this method's docs).
        
        Example::
            
            >>> a = Api()
            >>> b = await a.get_block(1234)
            >>> b['producer']
            'eosio'
            >>> b['id']
            '000004d25627320e2f442b62ac39735caf0dbc5c0c5c8c0ac0ba735c17a022e7'
        
        
        :param number:
        :return:
        
        Returned dictionary::
            
             dict_keys([
                timestamp:str, producer:str, confirmed:int, previous:str, transaction_mroot:str, action_mroot:str,
                id:str, new_producers, header_extensions:list, producer_signature:str, transactions:List[dict],
                block_extensions:list, block_num:int, ref_block_prefix:int, schedule_version:int
             ])
        
        **Content of transactions list**::
        
        First layer dict::
        
            dict_keys(['status', 'cpu_usage_us', 'net_usage_words', 'trx'])
        
        Contents of ``trx``::
        
            dict_keys([
                id:str, signatures:list, compression:str, packed_context_free_data:str, context_free_data:list,
                packed_trx:str, transaction:dict
            ])
        
        Contents of ``trx['transaction']``::
        
            dict_keys([
                expiration:str, ref_block_num:int, ref_block_prefix:int, max_net_usage_words:int, max_cpu_usage_ms:int,
                delay_sec:int, context_free_actions:list, actions:List[dict], transaction_extensions:list
            ])
        
        Contents of a ``trx['transaction']['actions']`` dict::
        
            dict_keys([account:str, name:str, authorization:List[dict], data:dict, hex_data])

         * ``account`` - The account / contract which created the action
         
         * ``name`` - The type of action occurring, e.g. ``newaccount``, ``buyrambytes`` or ``transfer``
         
         * ``data`` - Usually a dictionary containing metadata about the action, such as how many tokens were
           transferred, how much of a token was staked, who the TX is *actually* from/to etc.

        """
        b = await self._call(self.endpoints['get_block'], block_num_or_id=number)
        
        return EOSBlock.from_dict(b)

    async def get_info(self) -> dict:
        return await self._call(self.endpoints['get_info'])
    
    async def _call(self, _endpoint: str, *args, **kwargs) -> Union[dict, list]:
        """
        Internal function used for making an async EOS RPC call.
        
        If positional arguments are specified, the JSON POST payload will be a list composed of positional arguments
        (specified after _endpoint).
        If no positional args are specified, then keyword arguments will be used - the JSON POST payload will be a
        dictionary composed of the kwargs.
        
        Example usage - keyword args are sent as a JSON dict::
        
            >>> self._call('/v1/chain/get_block', block_num_or_id=12345)
        
        Example usage - positional args are sent as a JSON list/array::
        
            >>> self._call('/v1/chain/push_transactions', {"expiration": 1234}, {"expiration": 3456})
        
        
        :param str _endpoint: The URL endpoint to call, e.g. ``/v1/chain/get_block``
        :param args: Positional arguments will be converted into a list and sent as the JSON POST body.
        :param kwargs: Keyword arguments will be converted into a dict and sent as the JSON POST body.
        :return dict|list result: The response returned from the RPC call.
        """
        _endpoint = '/' + _endpoint.strip('/')
        body = list(args) if len(args) > 0 else dict(kwargs)
        async with httpx.AsyncClient() as client:
            client.headers['Content-Type'] = 'application/json'
            r = await client.post(self.url + _endpoint, json=body)
            res = r.json()
        return res

    def sync_call(self, _endpoint: str, *args, **kwargs) -> Union[dict, list]:
        """
        This method is primarily intended for debugging, and is not recommended for actual use in code.
        
        It uses privex-helpers' :func:`.run_sync` to run :meth:`._call` synchronously, allowing for debugging
        this class via the standard Python REPL which doesn't allow for ``await`` or ``async with`` etc.
        
        :param str _endpoint: The URL endpoint to call, e.g. ``/v1/chain/get_block``
        :param args: Positional arguments will be converted into a list and sent as the JSON POST body.
        :param kwargs: Keyword arguments will be converted into a dict and sent as the JSON POST body.
        :return dict|list result: The response returned from the RPC call.
        """
        return run_sync(self._call, _endpoint, *args, **kwargs)

    def __getattr__(self, name):
        """
        Methods that haven't yet been defined are simply passed off to :meth:`._call` with the positional and kwargs.

        This means ``rpc.get_abi(account_name='john')`` is equivalent to ``rpc._call('get_abi', account_name='john')``

        :param name: Name of the attribute requested
        :return: Dict or List from call result
        """
    
        def c(*args, **kwargs):
            return self._call(self.endpoints[name], *args, **kwargs)
    
        return c
