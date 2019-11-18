"""
Django views, including JSON API views for Django Rest Framework.

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
from django.shortcuts import render

# Create your views here.
from django_filters import FilterSet, CharFilter
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.reverse import reverse

from historyapp.models import EOSBlock, EOSTransaction, EOSAction
from historyapp.serializers import EOSBlockSerializer, EOSTransactionSerializer, EOSActionSerializer


@api_view(['GET'])
def api_root(request, format=None):
    return Response({
        'blocks':           reverse('eosblock-list', request=request, format=format),
        'transactions':     reverse('eostransaction-list', request=request, format=format),
        'actions':          reverse('eosaction-list', request=request, format=format),
    })


class CustomPaginator(LimitOffsetPagination):
    default_limit = 100
    max_limit = 1000


class BlockAPI(viewsets.ReadOnlyModelViewSet):
    """
    This is the highest level of data provided by [Privex EOS History API](https://github.com/Privex/EOSHistory)
    
    Each block contains zero or more **transactions**, which are returned as hyperlinks allowing you to easily
    query them from your application without manually building URLs.
    
    You can go directly to individual blocks via their block number, e.g. [/api/blocks/12345](/api/blocks/12345)
    
    You can also filter blocks by various fields, see the "Filters" button in the top right.
    
    Most fields can be queried just by entering their name as a GET query, e.g. ``/api/blocks/?producer=bitfinexeos1``
    """
    queryset = EOSBlock.objects.all().order_by('-number')
    order_by = 'number'
    serializer_class = EOSBlockSerializer
    filterset_fields = (
        'number', 'producer', 'id', 'new_producers', 'producer_signature', 'ref_block_prefix', 'confirmed',
        'timestamp', 'created_at', 'updated_at'
    )
    pagination_class = CustomPaginator


class SignatureFilter(FilterSet):
    signatures = CharFilter(lookup_expr='contains')
    metadata = CharFilter(lookup_expr='contains')
    
    class Meta:
        model = EOSTransaction
        fields = (
            'txid', 'status', 'block__number', 'packed_trx', 'block__timestamp', 'signatures',
            'compression', 'metadata'
        )


class TransactionAPI(viewsets.ReadOnlyModelViewSet):
    """
    A transaction is a part of a [block](/api/blocks) which contains zero or more **actions** - the actions
    are what actually contain more useful information such as who sent it, and what it's actually doing.
    
    Included with each transaction result is a list of hyperlinked ``actions``, which allows you to
    easily query for the related actions to each transaction.
    
    You can go directly to individual transactions via their TXID, e.g.
    [/api/transactions/b3c40bdb774ec03ee4f2b27728dc1d579c646b15e7d144a7ec1c33b90229e08d/](
    /api/transactions/b3c40bdb774ec03ee4f2b27728dc1d579c646b15e7d144a7ec1c33b90229e08d/)
    
    You can also filter transactions by various fields, see the "Filters" button in the top right.
    
    Most fields can be queried just by entering their name as a GET query, including searching for an individual
    signature in``signatures``
    
    Example: [/api/transactions/?signatures=SIG_K1_KgEyNMeXjHkudArcknByEWxWQRJgnBgHc3KxxRfh6uNVLqVNxEkGHJHN5P7Eodrs
    4sF7aFQsaSjy3qx2R7FGZj8FpPEKi2](/api/transactions/?signatures=SIG_K1_KgEyNMeXjHkudArcknByEWxWQRJgnBgHc3KxxRfh6uNVL
    qVNxEkGHJHN5P7Eodrs4sF7aFQsaSjy3qx2R7FGZj8FpPEKi2)
    
    """
    queryset = EOSTransaction.objects.all().order_by('-created_at')
    order_by = 'created'
    serializer_class = EOSTransactionSerializer
    filterset_class = SignatureFilter
    # filterset_fields = (
    #     'txid', 'status', 'block__number', 'packed_trx', 'block__timestamp', 'signatures',
    #     'compression'
    # )
    pagination_class = CustomPaginator


class ActionAPI(viewsets.ReadOnlyModelViewSet):
    """
    An action is a part of a transaction, and contains useful information such as who sent it, and what it's
    actually doing.
    
    Included with each ``action`` result, is a backlink to the ``transaction`` it's part of, as well as
    a ``block_url`` which is a hyperlink back to the block it's part of.

    Unlike transactions and blocks, actions don't have a consistent ID on the network. Generally the *correct*
    way to reference an action is via it's transaction ID and index (position in the transaction's list of actions).
    
    For example, to reference the 2nd action in the transaction
    ``c4f4215e419fd3886ff5fb3486a963e667fd8fb8194a9343c09f42e679f609be`` you'd query it as below:
    
    ``
    /api/actions/?transaction__txid=c4f4215e419fd3886ff5fb3486a963e667fd8fb8194a9343c09f42e679f609be&action_index=1
    ``
    
    To ease querying ``transfer`` actions, we've included some additional fields which are a reference to the
    ``data`` JSON object: ``tx_from``, ``tx_to``, ``tx_memo``, ``tx_amount``, ``tx_precision``, ``tx_symbol``
    
    You can also filter transactions by various fields, see the "Filters" button in the top right.

    Most fields can be queried just by entering their name as a GET query, for example:
    [/api/transactions/?tx_from=privexinceos](/api/transactions/?tx_from=privexinceos)

    """
    queryset = EOSAction.objects.all().order_by('-created_at')
    order_by = 'created'
    serializer_class = EOSActionSerializer
    filterset_fields = (
        'transaction__txid', 'transaction__block__timestamp', 'action_index', 'account', 'name',
        'tx_from', 'tx_to', 'tx_memo', 'tx_amount', 'tx_precision', 'tx_symbol',
    )
    pagination_class = CustomPaginator
