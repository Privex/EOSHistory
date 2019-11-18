import asyncio
import getpass
import random
from time import sleep
from typing import Tuple, Coroutine, List, Dict

from billiard.exceptions import SoftTimeLimitExceeded
from celery.result import AsyncResult
from django.conf import settings
from django.core.management import BaseCommand, CommandParser
from django.db.models.aggregates import Max
from lockmgr import lockmgr
from lockmgr.lockmgr import LockMgr
from privex.helpers import run_sync

from historyapp.lib import eos
from historyapp.models import EOSBlock
from historyapp.tasks import task_import_block

import logging

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync EOS blocks to the database"
    tasks: Dict[str, AsyncResult] = {}
    task_creators: List[Tuple[Coroutine, int]] = []
    waiters: List[Tuple[Coroutine, int]] = []
    
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
        if options['start_block'] is None:
            last_block = settings.EOS_START_BLOCK
            if EOSBlock.objects.count() > 0:
                last_block = EOSBlock.objects.aggregate(Max('number'))['number__max']
                start_type = 'exact'
                log.info('Found existing blocks. Starting from block %d (changed start_type to exact)', last_block)

        asyncio.run(self.sync_blocks(start_block=last_block, start_type=start_type))

    @classmethod
    async def wait_block_task(cls, task_id: str, blocknum: int, timeout=30):
        t = cls.tasks[task_id]   # type: AsyncResult
        try:
            res = t.get(timeout=timeout)
            # blocknum = t.kwargs['block'] if hasattr(t, 'kwargs') else None
            if type(res) is dict and 'block_num' in res:
                log.info('Imported block %s successfully. Removing task %s', blocknum, task_id)
            else:
                log.info("Importing block %s didn't raise exception, but didn't return valid dict... "
                         "Removing task %s", blocknum, task_id)
            del cls.tasks[task_id]
            return True
            
        except SoftTimeLimitExceeded:
            log.debug('Import block task "%s" timed out. Will try again later.')
            return None
        except (Exception, BaseException):
            log.exception("ERROR: import_block raised an exception. Attempting to retry")
            try:
                new_t = task_import_block(blocknum)
                log.info('Re-queued import_block task for block number: %d - task ID: %s', blocknum, new_t.task_id)
                cls.tasks[new_t.task_id] = new_t
            except (BaseException, Exception, TypeError, AttributeError) as e:
                log.exception("Cannot retry import as there was an error while trying to re-queue task: %s", t.task_id)
        return False

    # @classmethod
    # async def import_block(cls, block_num):
    #
    #     return t.task_id

    @classmethod
    async def sync_blocks(cls, start_block=None, start_type=None):
        lck = f'eoshist_sync:{getpass.getuser()}'
        with LockMgr(lck):
            log.info("Main sync_blocks loop started. Obtained lock name '%s'.", lck)
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
            while current_block < head_block:
                if len(cls.tasks) >= settings.EOS_SYNC_MAX_QUEUE:
                    log.info('Sync queue full. %d tasks in queue. Waiting for current tasks to finish.', len(cls.tasks))
                    # await cls.call_creators()
                    await cls.call_waiters()
                    continue
                if i % 20 == 0 or current_block == head_block:
                    log.info('Queued %d blocks out of %d blocks to import. (%d tasks in queue / %d creators in queue)',
                             i, total_blocks, len(cls.tasks), len(cls.task_creators))
                
                t = task_import_block(current_block)
                cls.tasks[t.task_id] = t
                cls.waiters.append(
                    (cls.wait_block_task(task_id=t.task_id, blocknum=current_block), current_block,)
                )
                current_block += 1
                i += 1
                await asyncio.sleep(0.01)

            log.info('Finished queueing %d import_block tasks for Celery. '
                     'Calling waiters to check task results... please wait.', total_blocks)
            
            # await cls.call_creators()
            await cls.call_waiters()

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
