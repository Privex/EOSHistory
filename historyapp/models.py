"""
Django database models

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
from datetime import datetime
from django.contrib.postgres.fields import JSONField
from django.db import models

# Create your models here.

MAX_STORED_DP = 20
"""Coin/token amounts are stored in the database with a maximum decimal place precision of the below integer block."""

MAX_STORED_DIGITS = 40
"""Maximum digits possible for coin/token amounts, e.g. 123.456 counts as 6 total digits (3 before dot, 3 after)"""


class EOSBlock(models.Model):
    """
    Represents an individual block on the EOS (or a fork) network.
    
    Transactions can be accessed via the relation attribute :py:attr:`.transactions`, while actions can be found
    on each individual transaction via :py:attr:`EOSTransaction.actions`
    """
    number = models.BigIntegerField(primary_key=True, null=False, blank=False)
    """The block number as stored on EOS, serving as the unique primary key"""
    
    timestamp = models.DateTimeField()
    """This holds the actual timestamp of when the block was produced"""
    
    producer = models.CharField(max_length=50, null=True, blank=True)
    """The block producer (BP) whom produced this block"""
    
    id = models.CharField(max_length=255, null=True, blank=True)
    """This is not the database ID, but represents the hex 'id' field on the block data"""
    
    new_producers = models.TextField(max_length=10000, null=True, blank=True)
    transaction_mroot = models.CharField(max_length=255, null=True, blank=True)
    action_mroot = models.CharField(max_length=255, null=True, blank=True)
    producer_signature = models.TextField(max_length=1000, null=True, blank=True)
    header_extensions = JSONField(default=list)
    
    ref_block_prefix = models.BigIntegerField(default=0)
    confirmed = models.BigIntegerField(default=0)
    schedule_version = models.BigIntegerField(default=0)
    
    # The date/time that this database entry was added/updated
    created_at = models.DateTimeField('Creation Time', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('Last Update', auto_now=True)
    
    @property
    def total_transactions(self):
        return self.transactions.count()


class EOSTransaction(models.Model):
    """
    Represents a single transaction contained within the 'transactions' field of a block.
    
    This model also contains all fields from ``x['transactions'][?]['trx']`` merged in for convenience and simplicity.
    
    You can access related actions ( :class:`.EOSAction` ) using the attribute :py:attr:`.actions`
    """
    txid = models.CharField(max_length=100, primary_key=True, null=False, blank=False)
    status = models.CharField(max_length=255, default='executed')
    compression = models.CharField(max_length=255, default='none')
    cpu_usage_us = models.BigIntegerField(default=0)
    net_usage_words = models.BigIntegerField(default=0)
    signatures = JSONField(default=list, null=True, blank=True)
    context_free_data = JSONField(default=list, null=True, blank=True)
    packed_trx = models.TextField(max_length=1000, blank=True, null=True)

    metadata = JSONField(default=dict, blank=True, null=True)
    """Metadata contains the data from ``x['transactions'][?]['trx']['transaction']`` minus the ``actions`` key."""
    
    block = models.ForeignKey(EOSBlock, on_delete=models.CASCADE, related_name='transactions')

    # The date/time that this database entry was added/updated
    created_at = models.DateTimeField('Creation Time', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('Last Update', auto_now=True)

    @property
    def timestamp(self) -> datetime:
        return self.block.timestamp

    @property
    def block_number(self) -> int:
        return self.block.number

    @property
    def total_actions(self):
        return self.actions.count()


class EOSAction(models.Model):
    """
    This model represents an individual action from within a transaction (see :class:`.EOSTransaction`).
    
    An action can represent any form of activity on the EOS network, such as transferring tokens, buying EOS RAM,
    staking/delegating EOS for bandwidth, creating accounts, and any smart contract calls.
    
    The field :py:attr:`.data` holds the contents of the original ``data`` key from the action as a :class:`.JSONField`
    allowing the metadata to easily be queried.
    
    The fields :py:attr:`tx_from`, :py:attr:`tx_to`, :py:attr:`tx_memo`, :py:attr:`tx_amount`, :py:attr:`tx_symbol`
    are not a standard part of EOS actions, however to/from/memo/amount/symbol are all included in a ``transfer``
    action's ``data`` section, so we make them available as optional model fields to allow for easier querying
    of transfer actions in the DB.
    """

    class Meta:
        """
        A transaction ID should only exist once within a particular coin. It may exist multiple times if each output
        has a unique `vout` number.
        """
        unique_together = (('transaction', 'action_index'),)
    
    id = models.BigIntegerField(primary_key=True, null=False, blank=False)

    transaction = models.ForeignKey(EOSTransaction, on_delete=models.CASCADE, related_name='actions')
    action_index = models.IntegerField(default=0)
    
    account = models.CharField(max_length=150, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    authorization = JSONField(default=list)
    data = JSONField(default=None)
    
    tx_from = models.CharField('TX Sender (from data)', max_length=150, null=True, blank=True, db_index=True)
    tx_to = models.CharField('TX Recipient (from data)', max_length=150, null=True, blank=True, db_index=True)
    tx_memo = models.TextField('TX Memo (from data)', max_length=1000, null=True, blank=True)
    tx_amount = models.DecimalField('Amount of tokens transacted (from data)', null=True, blank=True,
                                    max_digits=MAX_STORED_DIGITS, decimal_places=MAX_STORED_DP)
    tx_precision = models.IntegerField('TX Token Decimal Places', default=4)
    tx_symbol = models.CharField('TX Token Symbol (from data)', max_length=100, null=True, blank=True, db_index=True)
    hex_data = models.TextField(max_length=1000, null=True, blank=True)

    # The date/time that this database entry was added/updated
    created_at = models.DateTimeField('Creation Time', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('Last Update', auto_now=True)

    @property
    def block(self) -> EOSBlock:
        return self.transaction.block

    @property
    def txid(self) -> str:
        return self.transaction.txid

    @property
    def timestamp(self) -> datetime:
        return self.block.timestamp
    
    @property
    def block_number(self) -> int:
        return self.block.number

    block_url = block_number
    """This exists just as an alias for Django Rest Framework :class:`.EOSActionSerializer`"""
