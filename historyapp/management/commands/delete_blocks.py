import sys

from django.core.management.base import BaseCommand
from django.db import transaction

from historyapp.models import EOSBlock


class Command(BaseCommand):
    help = 'Delete individual / a range of blocks from the database, including related objects'

    def __init__(self):
        super(Command, self).__init__()
    
    def add_arguments(self, parser):
        # Named (optional) arguments
        parser.add_argument(
            '--start', type=int, default=None,
            help="Delete blocks starting from this number (requires --end)",
        )
        parser.add_argument(
            '--end', type=int, default=None,
            help="Delete blocks until this number (requires --start)",
        )
        parser.add_argument(
            'blocks', type=int, help='One or more individual blocks to delete - as positional args. Cannot'
                                     'be used with --start / --end',
            nargs='*'
        )
        
    def handle(self, *args, **options):
        if len(options['blocks']) > 0:
            if options['end'] is not None or options['start'] is not None:
                print(" !!! ERROR: You've specified both individual blocks AND --start / --end")
                print(" !!! You can only specify --start / --end OR individual blocks.")
                return sys.exit(1)
            
            print(" >>> Deleting blocks:", options['blocks'])
            with transaction.atomic():
                blocks = EOSBlock.objects.filter(number__in=options['blocks'])
                res = blocks.delete()
            print(f" [+++] Finished deleting {res[0]} blocks within: {options['blocks']}")
            print(" [+++] Objects deleted:", res[1])
            return
        elif options['end'] is not None and options['start'] is not None:
            start_block, end_block = int(options['start']), int(options['end'])
            if start_block >= end_block or start_block < 0 or end_block < 1:
                print(" !!! ERROR: Invalid start/end block")
                print(" !!! The end block must be AFTER the start block")
                print(" !!! The start block cannot be negative, and end block must be at least 1")
                return sys.exit(1)
            blocks_deleting = (end_block - start_block) + 1
            print(f" >>> Deleting UP TO {blocks_deleting} blocks between (and including) {start_block} and {end_block}")
            with transaction.atomic():
                blocks = EOSBlock.objects.filter(number__gte=start_block, number__lte=end_block)
                res = blocks.delete()
            print(f" [+++] Successfully deleted {res[0]} blocks between (and including) {start_block} and {end_block}")
            print(" [+++] Objects deleted:", res[1])

            return
        print(" !!! ERROR: No valid arguments. You must specify either individual blocks OR --start / --end")
        print(" !!! You can only specify --start / --end OR individual blocks.")
        return sys.exit(1)

            
        



