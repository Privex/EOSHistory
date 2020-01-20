import sys

from django import db
from django.core.management.base import BaseCommand
from django.db import transaction

from historyapp.models import EOSBlock

import logging

log = logging.getLogger(__name__)


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
            
            log.info(" >>> Deleting blocks: %s", options['blocks'])
            with transaction.atomic():
                blocks = EOSBlock.objects.filter(number__in=options['blocks'])
                res = blocks.delete()
            log.info(f" [+++] Finished deleting {res[0]} blocks within: {options['blocks']}")
            log.info(" [+++] Objects deleted: %s", res[1])
            return
        elif options['end'] is not None and options['start'] is not None:
            start_block, end_block = int(options['start']), int(options['end'])
            if start_block >= end_block or start_block < 0 or end_block < 1:
                print(" !!! ERROR: Invalid start/end block")
                print(" !!! The end block must be AFTER the start block")
                print(" !!! The start block cannot be negative, and end block must be at least 1")
                return sys.exit(1)
            blocks_deleting = (end_block - start_block) + 1
            total_deleted = 0
            
            log.info(f" >>> Deleting UP TO {blocks_deleting} blocks between (and including) {start_block} and {end_block}")
            del_chunk = 2000
            if blocks_deleting > del_chunk:
                log.info(f" >>> More than {del_chunk} blocks to be deleted. Running deletion in chunked transactions of {del_chunk}.")
                curr_start = start_block
                curr_end = start_block + del_chunk
                
                while curr_end <= end_block + 1:
                    log.info(f" -> Deleting 2000 blocks - {curr_start} to {curr_end} ({end_block - curr_start} blocks left)")
                    with transaction.atomic():
                        blocks = EOSBlock.objects.filter(number__gte=curr_start, number__lte=curr_end)
                        res = blocks.delete()
                        total_deleted += res[0]
                    log.info(f" [+++] {res[0]} Objects deleted: {res[1]}")
                    
                    db.reset_queries()
                    
                    if curr_end >= end_block:
                        log.info(f" !!> Current end block ({curr_end}) is >= final block ({end_block}). Exiting.")
                        break
                    
                    curr_start = curr_end
                    if (curr_end + del_chunk) > end_block:
                        curr_end = end_block
                    else:
                        curr_end += del_chunk
            else:
                log.info(f" >>> Less than {del_chunk} blocks to be deleted. Deleting blocks in single transaction.")
    
                with transaction.atomic():
                    blocks = EOSBlock.objects.filter(number__gte=start_block, number__lte=end_block)
                    res = blocks.delete()
                    total_deleted = res[0]
                    log.info(" [+++] Objects deleted: %s", res[1])
            log.info(f" [+++] Successfully deleted {total_deleted} blocks between (and including) {start_block} and {end_block}")

            return
        print(" !!! ERROR: No valid arguments. You must specify either individual blocks OR --start / --end")
        print(" !!! You can only specify --start / --end OR individual blocks.")
        return sys.exit(1)

            
        



