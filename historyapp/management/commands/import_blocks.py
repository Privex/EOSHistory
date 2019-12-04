from django.core.management import BaseCommand, CommandParser

from historyapp.models import EOSBlock
from historyapp.tasks import import_block
import logging

log = logging.getLogger(__name__)


def load_block(block_num, force=False):
    try:
        EOSBlock.objects.get(number=block_num)
        print(f" >>> Block number {block_num} already exists.")
        if force:
            print(f" >>> Option --force specified. Deleting block {block_num}")
            EOSBlock.objects.filter(number=block_num).delete()
            print(f" >>> Re-importing block {block_num}...")
            return import_block(block_num)
        return None
    except EOSBlock.DoesNotExist:
        print(f" >>> Block number {block_num} did not exist. Importing now.")
        return import_block(block_num)


class Command(BaseCommand):
    help = "(Re-)import one or more individual EOS blocks synchronously"
    
    def __init__(self):
        super(Command, self).__init__()
    
    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            'blocks', type=int, nargs='+', help='One or more blocks to (re-)import'
        )
        parser.add_argument(
            '-f', '--force', help='If the block(s) already exist, delete and re-import them.',
            action='store_true', dest='force', default=False
        )
    
    def handle(self, *args, **options):
        print()
        print(
            "==========================================================#\n"
            "#                                                         #\n"
            "# EOS Block History Scanner                               #\n"
            "# (C) 2019 Privex Inc.        Released under GNU AGPLv3   #\n"
            "#                                                         #\n"
            "# github.com/Privex/EOSHistory                            #\n"
            "#                                                         #\n"
            "#=========================================================#\n"
        )
        print()
        blocks: list = options['blocks']
        
        for b in blocks:
            print(f" >>> Checking block {b}")
            try:
                res = load_block(b, options['force'])
                if res is None:
                    print(f' [!!!] Block {b} was skipped.')
                else:
                    print(f' +++ Block {b} and {res.get("txs_imported")} transactions were imported successfully :)')
            except (BaseException, Exception) as e:
                log.exception("Exception while importing block %d", b)
