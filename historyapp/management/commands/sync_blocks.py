import asyncio
import getpass
import json
import math
import random
import sys
from asyncio import CancelledError
from datetime import timedelta
from decimal import Decimal
from threading import Thread
from typing import Tuple, List

from django.conf import settings
from django.core.management import BaseCommand, CommandParser
from django.db.models.aggregates import Max
from django.utils import timezone
from lockmgr.lockmgr import LockMgr, renew_lock
from privex.helpers import dec_round, empty

from eoshistory.connections import get_celery_message_count
# from eoshistory.settings import
from historyapp.lib import eos
from historyapp.models import EOSBlock
from historyapp.tasks import task_import_block
from django.db import connection

import logging

log = logging.getLogger(__name__)

MAX_QUEUE_THREADS, MAX_WAIT_THREADS = settings.MAX_QUEUE_THREADS, settings.MAX_WAIT_THREADS
MAX_BLOCKS = settings.MAX_BLOCKS_THREAD


query_gaps = """
SELECT
       gap_start, gap_end FROM (
              SELECT number + 1 AS gap_start,
              next_nr - 1 AS gap_end
              FROM (
                     SELECT number, lead(number) OVER (ORDER BY number) AS next_nr
                     FROM historyapp_eosblock
              ) nr
              WHERE nr.number + 1 <> nr.next_nr
       ) AS g
UNION ALL (
       SELECT
              0 AS gap_start,
              number AS gap_end
       FROM
              historyapp_eosblock
       ORDER BY
              number
       ASC LIMIT 1
)
ORDER BY
       gap_start DESC;
"""


def find_gaps(ignore_zero=True) -> List[Tuple[int, int]]:
    """Finds gaps in the block database. If ignore_zero is True, will skip the gap between 0 and the lowest block"""
    with connection.cursor() as cursor:
        cursor.execute(query_gaps)
        rows = list(cursor.fetchall())
        if ignore_zero and len(rows) > 0 and int(rows[0][0]) == 0:
            rows.pop(0)
    return rows


class BlockQueue(Thread):
    def __init__(self, start_block: int, end_block: int, thread_num=1, queue=None):
        super().__init__()
        self.start_block = start_block
        self.end_block = end_block
        self.thread_num = thread_num
        self.queue = queue
    
    def run(self) -> None:
        i = 1
        current_block = int(self.start_block)
        total_blocks = self.end_block - self.start_block
        
        while current_block < self.end_block:
            if i % 100 == 0 or current_block == self.end_block - 1:
                log.info('[Thread %d] Queued %d blocks out of %d blocks to import',
                         self.thread_num, i, total_blocks)
            args = {"block": current_block}
            if self.queue is not None: args['queue'] = self.queue
            task_import_block(**args)
            i += 1
            current_block += 1


class Command(BaseCommand):
    help = "Sync EOS blocks to the database"
    
    queue_threads = []
    wait_threads = []
    lock_sync_blocks = None
    lock_fill_gaps = None
    queue: str = None
    
    def __init__(self):
        super(Command, self).__init__()
    
    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            '--start-block', type=int, help='Start from this block (note --start-type affects meaning of this)',
            dest='start_block', default=None
        )
        parser.add_argument(
            '--end-block', type=int, help='End on this block number. If --relative-blocks is passed, this option '
                                          'changes to "sync this many blocks from start_block".',
            dest='end_block', default=None
        )
        parser.add_argument(
            '--relative-end', type=bool, help='Change the meaning of --end-block from exact (sync until block x)'
                                              'to relative (sync x blocks from start_block)',
            dest='relative_end', default=False
        )

        parser.add_argument('-g', '--skip-gaps', action='store_true', dest='skip_gaps', default=False,
                            help='Do not attempt to fill block gaps.')
        parser.add_argument('-k', '--gaps-only', action='store_true', dest='gaps_only', default=False,
                            help='Only fill gaps (do not sync blocks)')
        parser.add_argument(
            '--start-type', type=str, help="Either 'rel' (start block means relative blocks behind head),\n"
                                           "or 'exact' (start block means start from this exact block number)",
            dest='start_type', default=None
        )

        parser.add_argument(
            '-q', '--queue', type=str, help="Use a different Celery queue (also changes lock prefix allowing for "
                                            "multiple instances of sync_blocks)",
            dest='queue', default=None
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
        
        # last_block, start_type = options['start_block'], options['start_type']
        # if options['start_block'] is None:
        #
        Command.queue = options.pop('queue', settings.DEFAULT_CELERY_QUEUE)
        Command.queue = settings.DEFAULT_CELERY_QUEUE if empty(Command.queue) else Command.queue
        Command.lock_sync_blocks = f'eoshist_sync:{Command.queue}:{getpass.getuser()}'
        Command.lock_fill_gaps = f'eoshist_gaps:{Command.queue}:{getpass.getuser()}'
        log.info(' >>> Using Celery queue "%s"', Command.queue)
        log.info(' >>> Started SYNC_BLOCKS Django command. Booting up AsyncIO event loop. ')

        asyncio.run(self.sync_blocks(**options))

    @classmethod
    async def sync_between(cls, start_block, end_block, renew=None):
        blocks_left = end_block - start_block
        
        current_block = int(start_block)
        current_threads = 0
        if blocks_left > MAX_BLOCKS:
            max_threads = math.ceil(blocks_left / MAX_BLOCKS)
            spin_threads = max_threads if max_threads < MAX_QUEUE_THREADS else MAX_QUEUE_THREADS
            spin_threads = 1 if spin_threads < 1 else spin_threads
            log.info(" >>> Launching %d import queue threads...", spin_threads)
            
            while current_threads < spin_threads and current_block <= end_block:
                _end = current_block + MAX_BLOCKS
                _end = end_block if _end > end_block else _end
                t = BlockQueue(current_block, _end, len(cls.queue_threads) + 1, queue=cls.queue)
                t.start()
                cls.queue_threads += [t]
                current_threads += 1
                current_block += MAX_BLOCKS
                try:
                    await asyncio.sleep(1)
                    await cls.check_celery(renew=renew)
                except (KeyboardInterrupt, CancelledError):
                    await cls.clean_import_threads()
                    return
                except Exception:
                    log.exception('ERROR - Something went wrong checking Celery queue length.')
        else:
            t = BlockQueue(start_block, end_block, len(cls.queue_threads) + 1, queue=cls.queue)
            t.start()
            cls.queue_threads += [t]

    @classmethod
    async def clean_import_threads(cls):
        log.info(' >>> Waiting on queue threads to finish...')
        while len(cls.queue_threads) > 0:
            t = cls.queue_threads.pop()
            t.join()
    
    @classmethod
    async def sync_blocks(cls, start_block=None, start_type=None, **options):
        lck = cls.lock_sync_blocks
        log.info("Main sync_blocks loop started.")
        try:
            await cls.check_celery()
        except (KeyboardInterrupt, CancelledError):
            await cls.clean_import_threads()
            return
        except Exception:
            log.exception('ERROR - Something went wrong checking Celery queue length.')

        if not options['skip_gaps']:
            await cls.fill_gaps()
        
        if options['gaps_only']:
            log.info('Requested gaps_only, not skipping blocks...')
            return
        
        end_block = options.pop('end_block')
        relative_end = options.pop('relative_end', False)
        
        if start_block is None:
            start_block = settings.EOS_START_BLOCK
            if EOSBlock.objects.count() > 0:
                start_block = EOSBlock.objects.aggregate(Max('number'))['number__max']
                start_type = 'exact'
                log.info('Found existing blocks. Starting from block %d (changed start_type to exact)', start_block)

        if end_block is not None and relative_end:
            _end = int(end_block)
            end_block = start_block + _end

        with LockMgr(lck) as lm:
            log.info('Obtained lock name %s', lck)
            _start_block = settings.EOS_START_BLOCK if start_block is None else start_block
            _start_block = int(_start_block)
            start_type = settings.EOS_START_TYPE if start_type is None else start_type
            _node = random.choice(settings.EOS_NODE)
            log.info("Getting blockchain info from RPC node: %s", _node)
            a = eos.Api(url=_node)
            info = await a.get_info()
            head_block = int(info['head_block_num'])
            start_block = int(_start_block)
            if start_type.lower() == 'relative':
                start_block = head_block - int(_start_block)

            if end_block is not None:
                if end_block > head_block:
                    log.error("ERROR: End block '%d' is higher than actual head block '%d'. Cannot sync.",
                              end_block, head_block)
                    return
            else:
                end_block = head_block
            
            current_block = int(start_block)
            total_blocks = end_block - start_block

            log.info(
                "Importing blocks starting from %d - to end block %d. Total blocks to load: %d",
                start_block, end_block, total_blocks
            )

            time_start = timezone.now()

            i = 0
            
            while current_block < end_block:
                lm.renew(expires=300, add_time=False)
                blocks_left = end_block - current_block
                
                if i > 0 and (i % 100 == 0 or current_block == end_block):
                    log.info('End block: %d // Head block: %d', end_block, head_block)
                    log.info('Current block: %d', current_block)
                    log.info(
                         ' >>> Queued %d blocks out of %d blocks to import.',
                         i, total_blocks
                    )
                    log.info(
                        ' >>> %d blocks remaining. Progress: %f%%',
                        blocks_left, dec_round(
                            Decimal((i / total_blocks) * 100)
                        )
                    )
                    time_taken = timezone.now() - time_start
                    time_taken_sec = time_taken.total_seconds()
                    log.info(' >>> Started at %s', time_start)
                    bps = Decimal(i / time_taken_sec)
                    eta_secs = blocks_left // bps
                    log.info(' >>> Estd. blocks per second %f', dec_round(bps))
                    log.info(' >>> Estd. finish in %f seconds //// %f hours', eta_secs, eta_secs / 60 / 60)
                    log.info(' >>> Estd. finish date/time: %s', timezone.now() + timedelta(seconds=int(eta_secs)))

                _end = current_block + settings.EOS_SYNC_MAX_QUEUE
                _end = end_block if _end > end_block else _end
                blocks_queued = _end - current_block
                try:
                    await cls.sync_between(current_block, _end, renew=lck)
                    await cls.clean_import_threads()
                    await asyncio.sleep(3)
                except (KeyboardInterrupt, CancelledError):
                    log.error('CTRL-C detected. Please wait while threads terminate...')
                    await cls.clean_import_threads()
                    return
                current_block += blocks_queued
                i += blocks_queued

            if not options['skip_gaps']:
                log.info('=============================================================================')
                log.info('Finished syncing blocks. Waiting for Celery queue to empty completely,')
                log.info('then filling any leftover gaps.')
                log.info('=============================================================================')
                await cls.check_celery(max_queue=2)
                await cls.fill_gaps()
                await cls.check_celery(max_queue=2)

            print(
                "\n============================================================================================\n"
                "\nFinished importing " + str(total_blocks) + " blocks!\n"
                "\n============================================================================================\n"
            )

    @classmethod
    async def fill_gaps(cls):
        gaps = find_gaps()
        if len(gaps) == 0:
            return
        lck = cls.lock_fill_gaps
        with LockMgr(lck) as lm:
            # chan, conn = get_rmq_queue()
            log.info('Warning: Found %d separate block gaps. Filling missing block gaps...', len(gaps))
            i = 0
            total_gaps = len(gaps)
            while len(gaps) > 0:
                gap_start, gap_end = gaps.pop(0)
                i += 1
                if gap_start == gap_end:
                    log.info('[Gap %d / %d] Filling individual missing block %d', i, total_gaps, gap_start)
                    task_import_block(gap_start, queue=cls.queue)
                    continue
                gap_end = gap_end + 1
                log.info('[Gap %d / %d] Filling gap between block %d and block %d ...',
                         i, total_gaps, gap_start, gap_end)
                await cls.sync_between(gap_start, gap_end)
                await cls.clean_import_threads()
                await asyncio.sleep(1)
                await cls.check_celery(renew=lck)
                lm.renew(expires=300, add_time=False)
    
    @classmethod
    async def check_celery(cls, renew=None, max_queue=settings.MAX_CELERY_QUEUE):
        while get_celery_message_count(queue=cls.queue) >= max_queue:
            msg_count = get_celery_message_count(queue=cls.queue)
            log.info(' !!! > Celery currently has %d tasks in queue. Pausing until tasks fall below %d',
                     msg_count, max_queue)
            if renew is not None:
                # Ensure the lock doesn't expire due to waiting for Celery
                renew_lock(renew, expires=25, add_time=True, create=True)
            await asyncio.sleep(15)

