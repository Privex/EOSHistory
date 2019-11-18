import sys

from django.core.management import BaseCommand, CommandParser
from lockmgr import lockmgr
from lockmgr.lockmgr import LockMgr

from historyapp.models import EOSTransaction, EOSBlock, EOSAction


class Command(BaseCommand):
    help = "Deletes all rows from a given table. Be aware that due to foreign keys, deleting 'blocks' will also delete " \
           "transactions and actions - and deleting transactions will delete all actions too." \
           " /// Options: blocks, transactions, actions"
    
    def __init__(self):
        super(Command, self).__init__()
    
    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            'table', type=str,
            help='A table to clear all data from. Options: blocks, transactions, actions'
        )
    
    def handle(self, *args, **options):
        
        t = options['table']
        if t == 'transactions':
            print('Please wait... deleting all EOS transactions + related actions...')
            EOSTransaction.objects.all().delete()
            return print('Deleted all EOS transactions + related actions.')
        if t == 'blocks':
            print('Please wait... deleting all EOS blocks + related transactions + related actions...')
            EOSBlock.objects.all().delete()
            return print('Deleted all EOS blocks + related transactions + related actions.')
        if t == 'actions':
            print('Please wait... deleting all EOS actions...')
            EOSAction.objects.all().delete()
            return print('Deleted all EOS actions.')
        
        print(f'Unknown table "{t}". Options: blocks, transactions, actions')
        sys.exit(1)
        


