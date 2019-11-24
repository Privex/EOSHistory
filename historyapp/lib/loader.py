"""
Various async functions for importing / parsing blockchain data from EOS into more human friendly objects

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
import random
from decimal import Decimal
from typing import Union, List, Tuple
import pytz
from dateutil.parser import parse
from django.conf import settings
from django.db import transaction
from django.db.utils import IntegrityError
from django.utils import timezone
from privex.helpers import empty, PrivexException

from historyapp.lib import eos
from historyapp.models import EOSBlock, EOSTransaction, EOSAction
import logging

log = logging.getLogger(__name__)


class InvalidTransaction(PrivexException):
    """Raised when a passed transaction is corrupted / missing important data for import."""


async def _import_block(block: Union[eos.EOSBlock, int]) -> Tuple[EOSBlock, eos.EOSBlock]:
    """
    Import a given block number, or instance of :class:`.eos.EOSBlock` into the database.
    
    Note: This function does NOT import the transactions or actions. For a full import, see :func:`.import_block`
    
        >>> db_block, raw_block = _import_block(12345)
    
    :param block:
    :return Tuple[EOSBlock,eos.EOSBlock] blocks: A tuple containing both :class:`.EOSBlock`, and :class:`.eos.EOSBlock`
    """

    b = block
    
    if type(block) is int:
        try:
            _b = EOSBlock.objects.get(number=block)
            log.info('Found block "%s" in the database! Returning DB block instead.', block)
            return _b
        except EOSBlock.DoesNotExist:
            log.debug('Checked DB for existing block but not found. Continuing with import.')
        
        api = eos.Api(url=random.choice(settings.EOS_NODE))
        b = await api.get_block(block)
        block_num = b.block_num
    else:
        try:
            _b = EOSBlock.objects.get(number=block.block_num)
            log.info('Found block "%s" in the database! Returning DB block instead.', block.block_num)
            return _b
        except EOSBlock.DoesNotExist:
            log.debug('Checked DB for existing block but not found. Continuing with import.')
            block_num = block.block_num
    
    with transaction.atomic():
        try:
            EOSBlock.objects.get(number=block_num)
            raise IntegrityError(f'(loader.import_transaction) duplicate key value - Block {block_num} already exists.')
        except EOSBlock.DoesNotExist:
            pass
        dt = parse(b.timestamp)
        dt = timezone.make_aware(dt, pytz.UTC)
        _b = EOSBlock(
            number=int(block_num), timestamp=dt, producer=b.producer, id=b.id,
            new_producers=b.new_producers, transaction_mroot=b.transaction_mroot, action_mroot=b.action_mroot,
            producer_signature=b.producer_signature, header_extensions=b.header_extensions,
            ref_block_prefix=b.ref_block_prefix, confirmed=b.confirmed, schedule_version=b.schedule_version
        )
        _b.save()
        return _b, b

    # try:
    #     with transaction.atomic():
    #         dt = parse(b.timestamp)
    #         dt = timezone.make_aware(dt, pytz.UTC)
    #         _b = EOSBlock(
    #             number=int(block), timestamp=dt, producer=b.producer, id=b.id,
    #             new_producers=b.new_producers, transaction_mroot=b.transaction_mroot, action_mroot=b.action_mroot,
    #             producer_signature=b.producer_signature, header_extensions=b.header_extensions,
    #             ref_block_prefix=b.ref_block_prefix, confirmed=b.confirmed, schedule_version=b.schedule_version
    #         )
    #         _b.save()
    #
    # except IntegrityError as e:
    #     if 'duplicate key value' in str(e):
    #         log.warning('WARNING: Block "%d" already exists despite previous retrieval check... '
    #                     'Exception: %s %s', block, type(e), str(e))
    #         return EOSBlock.objects.get(number=block)
    #     else:
    #         raise e
    
    # return _b, b


async def import_transaction(block: Union[EOSBlock, int], tx: eos.EOSTransaction) -> EOSTransaction:
    if type(block) is int:
        try:
            block = EOSBlock.objects.get(number=block)
        except EOSBlock.DoesNotExist:
            block = _import_block(block=block)
    elif not isinstance(block, EOSBlock):
        raise AttributeError('import_transaction expects either a models.EOSBlock object or a block number. '
                             f'Instead, got type: {type(block)}')
    if empty(tx.id):
        raise InvalidTransaction('Passed transaction to import_transaction is missing a TXID. Cannot import. '
                                 f'Transaction object: {tx}')
    if tx.status != 'executed':
        raise InvalidTransaction(
            f"Transaction status isn't 'executed'. Should be ignored. Status: '{tx.status}' - TXID: {tx.id}"
        )
    # try:
    #     btx = EOSTransaction.objects.get(txid=tx.id)
    #     log.info('Found transaction ID "%s" in the database! Returning DB transaction instead.', tx.id)
    #     return btx
    # except EOSTransaction.DoesNotExist:
    #     log.debug('Checked DB for existing transaction but not found. Continuing with import.')
    
    meta = None
    if tx.transaction is not None:
        meta = dict(tx.transaction)
        if 'actions' in meta:
            del meta['actions']
    with transaction.atomic():
        try:
            ex_tx = EOSTransaction.objects.get(txid=tx.id)   # type: EOSTransaction
            # if ex_tx.block_number <= block.number:
            #     log.info('Found existing TX. TX block: %s - Current import block: %s - '
            #              'block not newer, raising IntegrityError. TXID %s')
            raise IntegrityError(f'(loader.import_transaction) duplicate key value - TXID {tx.id} already exists.')
        except EOSTransaction.DoesNotExist:
            pass
        
        btx = EOSTransaction(
            txid=tx.id, status=tx.status, compression=tx.compression, cpu_usage_us=tx.cpu_usage_us,
            net_usage_words=tx.net_usage_words, signatures=tx.signatures, context_free_data=tx.context_free_data,
            packed_trx=tx.packed_trx, metadata=meta, block=block
        )
        btx.save()
    
    return btx


async def import_actions(tx: eos.EOSTransaction) -> List[EOSAction]:
    """
    Creates a :class:`.EOSAction` in the database for each action in the passed transaction instance ``tx``.
    
        >>> db_b, b = await _import_block(12345)           # Import the block and get a models.EOSBlock + eos.EOSBlock
        >>> tx = b.transactions[0]                         # Get the first transaction in the block
        >>> db_tx = await import_transaction(db_b, tx)     # Import the eos.EOSTransaction and get models.EOSTransaction
        >>> acts = await import_actions(tx)                # Import the actions from the eos.EOSTransaction
    
    :param tx: An instance of :class:`eos.EOSTransaction` (NOT the model EOSTransaction, the lib.loader version)
    :return List[EOSAction] actions: A list of :class:`.EOSAction` model instances, each saved to the DB.
    """
    actions = []
    if type(tx.transaction) is not dict:
        raise InvalidTransaction(f'EOSTransaction.transaction is not a dict. Cannot import. Transaction object: {tx}')
    
    try:
        db_tx = EOSTransaction.objects.get(txid=tx.id)
    except EOSTransaction.DoesNotExist:
        raise InvalidTransaction(f'Passed transaction has not been imported to the DB! Cannot import actions. "{tx}"')
    
    _a = tx.transaction.get('actions', [])
    
    for i, a in enumerate(_a):    # type: dict
        actions.append(await _prep_action(db_tx=db_tx, action=a, index=i))
    
    EOSAction.objects.bulk_create(actions, ignore_conflicts=True)
    
    return actions


async def _prep_action(db_tx: EOSTransaction, action: dict, index: int) -> EOSAction:
    """
    Prepares a dict ``action`` from a :class:`.eos.EOSTransaction` for database insertion by extracting
    information such as the contract account, and parses any transaction metadata such as to/from account, memo
    quantity, symbol and precision.
    
    After the action has been parsed, this function will return a :class:`.EOSAction` model instance
    (NOT SAVED TO THE DB!).
    
        >>> db_b, b = await _import_block(12345)           # Import the block and get a models.EOSBlock + eos.EOSBlock
        >>> tx = b.transactions[0]                         # Get the first transaction in the block
        >>> act = tx.transaction['actions'][0]             # Get the first action in the transaction
        >>> db_tx = await import_transaction(db_b, tx)     # Import the eos.EOSTransaction and get models.EOSTransaction
        >>> await _prep_action(db_tx=db_tx, action=act)    # Pass model TX and dict action, get models.EOSAction
    
    :param EOSTransaction db_tx: An instance of an :class:`.EOSTransaction` model to attach the ``action`` to.
    :param dict action: The action to parse and return an :class:`.EOSAction` for.
    :param int index: The position this action was in, in the actions list of the transaction
    :return EOSAction act: An unsaved model instance of :class:`.EOSAction`
    """
    data = dict(
        account=action.get('account'), name=action.get('name'), authorization=action.get('authorization', []),
        data=action.get('data', {}), hex_data=action.get('hex_data'), action_index=index
    )

    if type(data['data']) is dict and len(data['data'].keys()) > 0:
        if 'from' in data['data']: data['tx_from'] = data['data']['from']
        if 'to' in data['data']: data['tx_to'] = data['data']['to']
        if 'memo' in data['data']: data['tx_memo'] = data['data']['memo']

        if 'quantity' in data['data']:
            amt, sym = data['data']['quantity'].split()
            data['tx_precision'] = 0 if '.' not in amt else len(str(amt.split('.')[1]))
            data['tx_amount'] = Decimal(amt)
            data['tx_symbol'] = sym.upper()
    
    act = EOSAction(transaction=db_tx, **data)
    
    return act

