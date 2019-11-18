"""
Django Rest Framework serializer and filter classes

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
from rest_framework import serializers

from historyapp.models import EOSBlock, EOSTransaction, EOSAction


class EOSBlockSerializer(serializers.HyperlinkedModelSerializer):
    # class Meta:
    #     model = EOSBlock
    #     exclude = ()
    class Meta:
        model = EOSBlock
        fields = (
            'number',
            'url',
            'timestamp',
            'producer',
            'id',
            'new_producers',
            'transaction_mroot',
            'action_mroot',
            'producer_signature',
            'header_extensions',
            'ref_block_prefix',
            'confirmed',
            'schedule_version',
            'transactions',
            'created_at',
            'updated_at',
        )


# class EOSTransactionSerializer(serializers.HyperlinkedModelSerializer):
#     class Meta:
#         model = EOSBlock
#         fields = (
#             'number',
#             'timestamp',
#             'producer',
#             'id',
#             'new_producers',
#             'transaction_mroot',
#             'action_mroot',
#             'producer_signature',
#             'header_extensions',
#             'ref_block_prefix',
#             'confirmed',
#             'schedule_version',
#             'created_at',
#             'updated_at',
#         )


class EOSTransactionSerializer(serializers.HyperlinkedModelSerializer):
    total_actions = serializers.ReadOnlyField()
    block_number = serializers.ReadOnlyField()
    timestamp = serializers.ReadOnlyField()

    # class Meta:
    #     model = EOSTransaction
    #     exclude = ()
    
    class Meta:
        model = EOSTransaction
        fields = (
            'txid',
            'url',
            'status',
            'compression',
            'cpu_usage_us',
            'net_usage_words',
            'signatures',
            'context_free_data',
            'packed_trx',
            'metadata',
            'timestamp',
            'block_number',
            'total_actions',
            'actions',
            'created_at',
            'updated_at',
        )


class EOSActionSerializer(serializers.HyperlinkedModelSerializer):
    txid = serializers.ReadOnlyField()
    block_number = serializers.ReadOnlyField()
    timestamp = serializers.ReadOnlyField()
    
    block_url = serializers.HyperlinkedRelatedField(
        'eosblock-detail', read_only=True,
    )

    # class Meta:
    #     model = EOSAction
    #     exclude = ()
    
    class Meta:
        model = EOSAction
        fields = (
            'txid',
            'url',
            'transaction',
            'timestamp',
            'block_url',
            'block_number',
            'action_index',
            'account',
            'name',
            'authorization',
            'data',
            'tx_from',
            'tx_to',
            'tx_memo',
            'tx_amount',
            'tx_precision',
            'tx_symbol',
            'hex_data',
            'created_at',
            'updated_at',
        )
