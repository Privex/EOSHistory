import asyncio
import getpass
import json
import math
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
from lockmgr.lockmgr import LockMgr
from privex.helpers import dec_round

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
       gap_start;
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
    def __init__(self, start_block: int, end_block: int, thread_num=1):
        super().__init__()
        self.start_block = start_block
        self.end_block = end_block
        self.thread_num = thread_num
    
    def run(self) -> None:
        i = 1
        current_block = int(self.start_block)
        total_blocks = self.end_block - self.start_block
        
        while current_block < self.end_block:
            if i % 100 == 0 or current_block == self.end_block - 1:
                log.info('[Thread %d] Queued %d blocks out of %d blocks to import',
                         self.thread_num, i, total_blocks)
            task_import_block(current_block)
            i += 1
            current_block += 1


class Command(BaseCommand):
    help = "Sync EOS blocks to the database"
    
    queue_threads = []
    wait_threads = []
    
    def __init__(self):
        super(Command, self).__init__()
    
    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            '--start-block', type=int, help='Start from this block (note --start-type affects meaning of this)',
            dest='start_block', default=None
        )
        parser.add_argument(
            '--end-block', type=int, help='End on this block. ',
            dest='end_block', default=None
        )
        parser.add_argument(
            '--relative-end', type=bool, help='End on this block. ',
            dest='end_block', default=None
        )

        parser.add_argument('-g', '--skip-gaps', action='store_true', dest='skip_gaps', default=False,
                            help='Do not attempt to fill block gaps.')
        parser.add_argument(
            '--start-type', type=str, help="Either 'rel' (start block means relative blocks behind head),\n"
                                           "or 'exact' (start block means start from this exact block number)",
            dest='start_type', default=None
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
        log.info(' >>> Started SYNC_BLOCKS Django command. Booting up AsyncIO event loop. ')
        # last_block, start_type = options['start_block'], options['start_type']
        # if options['start_block'] is None:
        #

        asyncio.run(self.sync_blocks(**options))

    @classmethod
    async def sync_between(cls, start_block, end_block):
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
                t = BlockQueue(current_block, _end, len(cls.queue_threads) + 1)
                t.start()
                cls.queue_threads += [t]
                current_threads += 1
                current_block += MAX_BLOCKS
                try:
                    await asyncio.sleep(1)
                    await cls.check_celery()
                except (KeyboardInterrupt, CancelledError):
                    await cls.clean_import_threads()
                    return
                except Exception:
                    log.exception('ERROR - Something went wrong checking Celery queue length.')
        else:
            t = BlockQueue(start_block, end_block, len(cls.queue_threads) + 1)
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
        lck = f'eoshist_sync:{getpass.getuser()}'
        with LockMgr(lck):
            log.info("Main sync_blocks loop started. Obtained lock name '%s'.", lck)
            try:
                await cls.check_celery()
            except (KeyboardInterrupt, CancelledError):
                await cls.clean_import_threads()
                return
            except Exception:
                log.exception('ERROR - Something went wrong checking Celery queue length.')
            
            if start_block is None:
                if not options['skip_gaps']:
                    await cls.fill_gaps()

                start_block = settings.EOS_START_BLOCK
                if EOSBlock.objects.count() > 0:
                    start_block = EOSBlock.objects.aggregate(Max('number'))['number__max']
                    start_type = 'exact'
                    log.info('Found existing blocks. Starting from block %d (changed start_type to exact)', start_block)
            
            _start_block = settings.EOS_START_BLOCK if start_block is None else start_block
            _start_block = int(_start_block)
            start_type = settings.EOS_START_TYPE if start_type is None else start_type
            
            
            log.info("Getting blockchain info from RPC node: %s", settings.EOS_NODE)
            a = eos.Api(url=settings.EOS_NODE)
            info = await a.get_info()
            head_block = int(info['head_block_num'])
            start_block = int(_start_block)
            if start_type.lower() == 'relative':
                start_block = head_block - int(_start_block)

            current_block = int(start_block)
            total_blocks = head_block - start_block

            log.info(
                "Importing blocks starting from %d - to head block %d. Total blocks to load: %d",
                start_block, head_block, total_blocks
            )

            time_start = timezone.now()

            i = 0
            
            while current_block < head_block:
                blocks_left = head_block - current_block
                
                if i > 0 and (i % 100 == 0 or current_block == head_block):
                    log.info('Head block: %d', head_block)
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

                # if blocks_left > MAX_BLOCKS:
                # log.info(" >>> Launching %d import queue threads...", MAX_QUEUE_THREADS)
                # while len(cls.queue_threads) < MAX_QUEUE_THREADS:
                #     t = BlockQueue(current_block, current_block + (MAX_BLOCKS - 1), len(cls.queue_threads)+1)
                #     t.start()
                #     cls.queue_threads += [t]
                #     current_block += MAX_BLOCKS
                #     i += MAX_BLOCKS
                #
                _end = current_block + settings.EOS_SYNC_MAX_QUEUE
                _end = head_block if _end > head_block else _end
                blocks_queued = _end - current_block
                try:
                    await cls.sync_between(current_block, _end)
                    await cls.clean_import_threads()
                    await asyncio.sleep(3)
                except (KeyboardInterrupt, CancelledError):
                    log.error('CTRL-C detected. Please wait while threads terminate...')
                    await cls.clean_import_threads()
                    return
                current_block += blocks_queued
                i += blocks_queued
    
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
        # chan, conn = get_rmq_queue()
        log.info('Warning: Found %d separate block gaps. Filling missing block gaps...', len(gaps))
        while len(gaps) > 0:
            gap_start, gap_end = gaps.pop(0)
            if gap_start == gap_end:
                log.info('Filling individual missing block %d', gap_start)
                task_import_block(gap_start)
                continue
            gap_end = gap_end + 1
            log.info('Filling gap between block %d and block %d ...', gap_start, gap_end)
            await cls.sync_between(gap_start, gap_end)
            await cls.clean_import_threads()
            await asyncio.sleep(1)
            await cls.check_celery()
            
        # conn.close()

    @classmethod
    async def check_celery(cls):
        while get_celery_message_count() >= settings.MAX_CELERY_QUEUE:
            msg_count = get_celery_message_count()
            log.info(' !!! > Celery currently has %d tasks in queue. Pausing until tasks fall below %d',
                     msg_count, settings.MAX_CELERY_QUEUE)
            await asyncio.sleep(20)

