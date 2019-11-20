import asyncio
import getpass
import json
import sys
from threading import Thread
from typing import Tuple, List

import pika
from billiard.exceptions import SoftTimeLimitExceeded
from celery.result import AsyncResult
from django.conf import settings
from django.core.management import BaseCommand, CommandParser
from django.db.models.aggregates import Max
from lockmgr.lockmgr import LockMgr
from pika.adapters.blocking_connection import BlockingChannel
from privex.helpers import byteify

from eoshistory.connections import get_rmq_queue, get_celery_message_count, get_rmq
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


def add_task(task_id, block_num, chan: BlockingChannel, routing_key='new_task'):
    # chan, _ = get_rmq_queue(queue=queue)
    # r = get_redis()
    data = json.dumps([task_id, block_num])
    chan.basic_publish(
        exchange='', routing_key=routing_key, body=byteify(data),
        properties=pika.BasicProperties(content_type='text/plain', delivery_mode=1),
        # mandatory=True
    )
    # r.lpush(settings.REDIS_QUEUE_NAME, data)
    # log.debug('Inserted task ID %s and block number %s into exchange "eoshist" routing key "%s"',
    #           task_id, block_num, routing_key)


def import_add_task(block_num, chan):
    t = task_import_block(block_num)
    chan.queue_declare(queue=settings.RMQ_QUEUE, durable=True, exclusive=False, auto_delete=False)
    add_task(task_id=t.task_id, block_num=block_num, chan=chan)


class ImportChecker(Thread):
    def __init__(self, timeout=30):
        super().__init__()
        self.timeout = timeout
        chan, chan_conn = get_rmq()
        queue_chan, queue_chan_conn = get_rmq_queue()
        self.channel = chan
        self.queue_channel = queue_chan
        self.conn_queue = queue_chan_conn
        self.conn = chan_conn

    def wait_block_task(self, task_id: str, blocknum: int, timeout=30):
        # t = cls.tasks[task_id]  # type: AsyncResult
        try:
            t = AsyncResult(task_id)
            res = t.get(timeout=timeout)
            # blocknum = t.kwargs['block'] if hasattr(t, 'kwargs') else None
            if type(res) is dict and 'block_num' in res:
                log.info('Imported block %s successfully. Removing task %s', blocknum, task_id)
            else:
                log.info("Importing block %s didn't raise exception, but didn't return valid dict... "
                         "Removing task %s", blocknum, task_id)
            # del cls.tasks[task_id]
            
            return True
    
        except KeyboardInterrupt:
            print('Detected CTRL-C. Exiting.')
            return sys.exit()
        except SoftTimeLimitExceeded:
            log.debug('Import block task "%s" timed out. Will try again later.')
            return None
        except (Exception, BaseException):
            log.exception("ERROR: import_block raised an exception. Attempting to retry")
            try:
                new_t = task_import_block(blocknum)
                log.info('Re-queued import_block task for block number: %d - task ID: %s', blocknum, new_t.task_id)
                add_task(new_t.task_id, blocknum, self.queue_channel)
                return True
                # cls.tasks[new_t.task_id] = new_t
            except (BaseException, Exception, TypeError, AttributeError) as e:
                log.exception("Cannot retry import as there was an error while trying to re-queue task: %s", t.task_id)
        return False
    
    def run(self) -> None:
        chan = self.channel
        log.info('[ImportChecker] Consuming from queue %s', settings.RMQ_QUEUE)
        while True:
            try:
                for method_frame, properties, body in chan.consume(settings.RMQ_QUEUE):
                    task_id, block_num = json.loads(body)
                    ret = self.wait_block_task(task_id, block_num, self.timeout)
                    if not ret:
                        log.info('Got negative result from wait_block_task. Re-queueing check for task %s / block %s',
                                 task_id, block_num)
                        chan.basic_nack(method_frame.delivery_tag)
                        continue
                    log.info('Got success from wait_block_task. Sending ack.')
                    chan.basic_ack(method_frame.delivery_tag)
            except KeyboardInterrupt:
                break
        self.conn.close()
        self.conn_queue.close()
        log.info('[ImportChecker] Finished.')


class BlockQueue(Thread):
    def __init__(self, start_block: int, end_block: int, thread_num=1):
        super().__init__()
        self.start_block = start_block
        self.end_block = end_block
        self.thread_num = thread_num
        chan, conn = get_rmq_queue()
        self.channel = chan
        self.connection = conn
    
    def run(self) -> None:
        i = 1
        current_block = int(self.start_block)
        total_blocks = self.end_block - self.start_block
        
        while current_block < self.end_block:
            if i % 100 == 0 or current_block == self.end_block - 1:
                log.info('[Thread %d] Queued %d blocks out of %d blocks to import',
                         self.thread_num, i, total_blocks)
            import_add_task(current_block, chan=self.channel)
            i += 1
            current_block += 1
        self.connection.close()


class Command(BaseCommand):
    help = "Sync EOS blocks to the database"
    # tasks: Dict[str, AsyncResult] = {}
    # task_creators: List[Tuple[Coroutine, int]] = []
    # waiters: List[Tuple[Coroutine, int]] = []
    
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
        last_block, start_type = options['start_block'], options['start_type']
        # if options['start_block'] is None:
        #

        asyncio.run(self.sync_blocks(start_block=last_block, start_type=start_type))

    # @classmethod
    # async def wait_block_task(cls, task_id: str, blocknum: int, timeout=30):
    #     t = cls.tasks[task_id]   # type: AsyncResult
    #     try:
    #         res = t.get(timeout=timeout)
    #         # blocknum = t.kwargs['block'] if hasattr(t, 'kwargs') else None
    #         if type(res) is dict and 'block_num' in res:
    #             log.info('Imported block %s successfully. Removing task %s', blocknum, task_id)
    #         else:
    #             log.info("Importing block %s didn't raise exception, but didn't return valid dict... "
    #                      "Removing task %s", blocknum, task_id)
    #         del cls.tasks[task_id]
    #         return True
    #
    #     except KeyboardInterrupt:
    #         print('Detected CTRL-C. Exiting.')
    #         return sys.exit()
    #     except SoftTimeLimitExceeded:
    #         log.debug('Import block task "%s" timed out. Will try again later.')
    #         return None
    #     except (Exception, BaseException):
    #         log.exception("ERROR: import_block raised an exception. Attempting to retry")
    #         try:
    #             new_t = task_import_block(blocknum)
    #             log.info('Re-queued import_block task for block number: %d - task ID: %s', blocknum, new_t.task_id)
    #             cls.tasks[new_t.task_id] = new_t
    #         except (BaseException, Exception, TypeError, AttributeError) as e:
    #             log.exception("Cannot retry import as there was an error while trying to re-queue task: %s", t.task_id)
    #     return False

    # @classmethod
    # async def import_block(cls, block_num):
    #
    #     return t.task_id

    @classmethod
    async def sync_between(cls, start_block, end_block):
        blocks_left = end_block - start_block
        
        current_block = int(start_block)
        
        if blocks_left > MAX_BLOCKS:
            log.info(" >>> Launching %d import queue threads...", MAX_QUEUE_THREADS)
            while len(cls.queue_threads) < MAX_QUEUE_THREADS:
                t = BlockQueue(current_block, current_block + (MAX_BLOCKS - 1), len(cls.queue_threads) + 1)
                t.start()
                cls.queue_threads += [t]
                current_block += MAX_BLOCKS
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
    async def sync_blocks(cls, start_block=None, start_type=None):
        lck = f'eoshist_sync:{getpass.getuser()}'
        with LockMgr(lck):
            log.info("Main sync_blocks loop started. Obtained lock name '%s'.", lck)
            if start_block is None:
                gaps = find_gaps()
                if len(gaps) > 0:
                    log.info('Warning: Found %d separate block gaps. Filling missing block gaps...', len(gaps))
                    while len(gaps) > 0:
                        gap_start, gap_end = gaps.pop(0)
                        log.info('Filling gap between block %d and block %d ...', gap_start, gap_end)
                        await cls.sync_between(gap_start, gap_end)
                        await cls.clean_import_threads()
                        await cls.check_celery()

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
            
            i = 0
            log.info(' >>> Starting %d waiter threads', MAX_WAIT_THREADS)

            while len(cls.wait_threads) < MAX_QUEUE_THREADS:
                t = ImportChecker()
                t.start()
                cls.wait_threads += [t]
            
            while current_block < head_block:
                # if len(cls.tasks) >= settings.EOS_SYNC_MAX_QUEUE:
                #     log.info('Sync queue full. %d tasks in queue. Waiting for current tasks to finish.', len(cls.tasks))
                #     # await cls.call_creators()
                #     await cls.call_waiters()
                #     continue
                if i % 5000 == 0 or current_block == head_block:
                    log.info(
                         ' >>> Queued %d blocks out of %d blocks to import.',
                         i, total_blocks
                    )
                
                try:
                    await cls.check_celery()
                except KeyboardInterrupt:
                    return
                except Exception:
                    log.exception('ERROR - Something went wrong checking Celery queue length.')
                
                blocks_left = head_block - current_block
                if blocks_left > MAX_BLOCKS:
                    log.info(" >>> Launching %d import queue threads...", MAX_QUEUE_THREADS)
                    while len(cls.queue_threads) < MAX_QUEUE_THREADS:
                        t = BlockQueue(current_block, current_block + (MAX_BLOCKS - 1), len(cls.queue_threads)+1)
                        t.start()
                        cls.queue_threads += [t]
                        current_block += MAX_BLOCKS
                        i += MAX_BLOCKS
                    
                    await cls.clean_import_threads()
                        
                    
                

                
                # import_add_task(current_block)
                # t = task_import_block(current_block)
                # cls.tasks[t.task_id] = t
                # cls.waiters.append(
                #     (cls.wait_block_task(task_id=t.task_id, blocknum=current_block), current_block,)
                # )
                # current_block += 1
                # i += 1
                await asyncio.sleep(1)

            log.info(' >>> Waiting on waiter threads to finish...')
            while len(cls.wait_threads) > 0:
                t = cls.wait_threads.pop()
                t.join()
            
            # log.info('Finished queueing %d import_block tasks for Celery. '
            #          'Calling waiters to check task results... please wait.', total_blocks)
            
            # await cls.call_creators()
            # await cls.call_waiters()

            # rem_tasks = list(cls.tasks.keys())
            # while len(cls.waiters) > 0:
            #     w, b_num = cls.waiters[]
            #     log.info('Retrieving remaining block tasks.')
            #     for tid in rem_tasks:
            #         await cls.wait_block_task(tid)
    
            print(
                "\n============================================================================================\n"
                "\nFinished importing " + str(total_blocks) + " blocks!\n"
                "\n============================================================================================\n"
            )

    @classmethod
    async def check_celery(cls):
        while get_celery_message_count() >= settings.MAX_CELERY_QUEUE:
            msg_count = get_celery_message_count()
            log.info(' !!! > Celery currently has %d tasks in queue. Pausing until tasks fall below %d',
                     msg_count, settings.MAX_CELERY_QUEUE)
            await asyncio.sleep(20)

    @classmethod
    async def call_creators(cls):
        # Call all task creators
        log.info('Calling all celery task queue async routines... (currently %d routines...)', len(cls.task_creators))
        creator_crs = [w for w, _ in cls.task_creators]
        await asyncio.gather(*creator_crs)
        cls.task_creators = []

    @classmethod
    async def call_waiters(cls):
        # Call all remaining waiters
        log.info('Calling all waiters (currently %d waiters...)', len(cls.waiters))
        waiter_crs = [w for w, _ in cls.waiters]
        await asyncio.gather(*waiter_crs)
        cls.waiters = []
