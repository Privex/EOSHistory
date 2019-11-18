"""
Django Admin views

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
from django.contrib import admin

# Register your models here.
from historyapp.models import EOSBlock, EOSTransaction, EOSAction


@admin.register(EOSBlock)
class EOSBlockAdmin(admin.ModelAdmin):
    list_display = ('number', 'producer', 'timestamp', 'total_transactions', 'created_at')
    ordering = ('-number',)


@admin.register(EOSTransaction)
class EOSTransactionAdmin(admin.ModelAdmin):
    list_display = ('txid', 'status', 'block_number', 'total_actions', 'timestamp', 'created_at')
    ordering = ('-created_at',)
    search_fields = ('txid', 'status',)


@admin.register(EOSAction)
class EOSActionAdmin(admin.ModelAdmin):
    list_display = ('txid', 'action_index', 'block_number', 'account', 'name', 'timestamp', 'created_at')
    ordering = ('-created_at',)

