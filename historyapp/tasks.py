"""
Celery tasks for running in the background

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
from celery.app.task import Context, Task
from celery.utils.log import get_task_logger
from django.db import transaction
from django.db.utils import IntegrityError
from lockmgr.lockmgr import LockMgr
from privex.helpers import run_sync
from privex.loghelper import LogHelper
from psycopg2 import errors
from lockmgr.lockmgr import LockMgr
from eoshistory.celery import app
from eoshistory.settings import config_logger
from historyapp.lib import eos, loader
from historyapp.lib.loader import _import_block, InvalidTransaction
from historyapp.models import EOSBlock, EOSTransaction
import logging

# log = logging.getLogger(__name__)
# log.propagate = False
# log.handlers.clear()

log = get_task_logger(__name__)


class TaskBase(Task):
    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)

    def __init__(self):
        global log
        log.handlers.clear()
        _l = logging.getLogger('historyapp.lib.loader')
        _l.propagate = False
        _l.handlers.clear()


@app.task(base=TaskBase, autoretry_for=(Exception,), retry_kwargs={'max_retries': 5, 'countdown': 2})
def import_block(block: int) -> dict:
    with LockMgr(f'eoshist_impblock:{block}'):
        log.debug('Importing block %d via _import_block...', block)
        with transaction.atomic():
            _b = run_sync(_import_block, block)
            if type(_b) not in [tuple, list] or len(_b) == 1:
                return dict(block_num=_b.number, timestamp=str(_b.timestamp), txs_imported=0)
            db_block, raw_block = _b
        
            raw_block: eos.EOSBlock
            db_block: EOSBlock
            
            total_txs = 0
            for tx in raw_block.transactions:   # type: eos.EOSTransaction
                if total_txs % 10 == 0 or total_txs == 0 or total_txs == len(raw_block.transactions)-1:
                    log.debug('Importing transaction %d out of %d', total_txs+1, len(raw_block.transactions))
                try:
                    with transaction.atomic():
                        # Import the current TX into the DB
                        run_sync(loader.import_transaction, block=db_block, tx=tx)
                
                        if total_txs % 10 == 0 or total_txs == 0 or total_txs == len(raw_block.transactions)-1:
                            log.debug('Importing actions contained in transaction %d', total_txs+1)
                        # Import the all actions contained in this TX
                        run_sync(loader.import_actions, tx)
                except InvalidTransaction as e:
                    log.debug("Skipping transaction %d out of %d on block %d due to InvalidTransaction: %s",
                                total_txs+1, len(raw_block.transactions), block, str(e))
                except (IntegrityError, errors.UniqueViolation) as e:
                    if 'duplicate key value' in str(e):
                        log.warning('WARNING: (Block Import: %d) Transaction ID "%s" already exists... '
                                    'Exception: %s %s', block, tx.id, type(e), str(e))
                    else:
                        log.error('An unknown IntegrityError/UniqueViolation occurred while importing TX %s - '
                                  'Exception: %s %s', tx.id, type(e), str(e))
                except (Exception, BaseException) as e:
                    log.error('An unknown exception occurred while importing TX %s - Skipping TX. - '
                              'Exception: %s %s', tx.id, type(e), str(e))
                total_txs += 1
            
        return dict(block_num=db_block.number, timestamp=str(db_block.timestamp), txs_imported=total_txs)


@app.task(base=TaskBase)
def handle_errors(request: Context, exc, traceback, block):
    log.info('Block Number: %s', block)
    log.info('Request: %s', request)
    log.info('Exc - Type: %s ||| Message: %s', type(exc), str(exc))
    log.info('Traceback: %s', traceback)
    tname = request.task

    ex_type = type(exc)
    e = exc

    if ex_type in [IntegrityError, errors.UniqueViolation]:
        if 'duplicate key value' in str(e):
            return log.warning('WARNING: Database item already exists... Block: %s Exception: %s %s',
                               block, type(e), str(e))
        else:
            return log.error('An unknown IntegrityError/UniqueViolation occurred while importing block %s - '
                             'Exception: %s %s', block, type(e), str(e))
    log.exception('UNHANDLED EXCEPTION. Task %s raised exception: %s (Message: %s) ... Block: %s\nTraceback: %s',
                  tname, type(e), str(e), block, traceback)
    return


@app.task(base=TaskBase)
def success_import_block(block_res: dict):
    log.warning('Task import_block reported that block %d and %d transactions were imported successfully :)',
                block_res.get('block_num'), block_res.get('txs_imported'))
    # log.info('success_import_block was triggered!')
    # a = list(args)
    # kw = dict(kwargs)
    # for i, v in enumerate(a):
    #     log.info('Positional arg %d = %s', i, v)
    # for k, v in kw.items():
    #     log.info('Keyword arg %s = %s', k, v)
    # log.info('success_import_block finished.')


def task_import_block(block: int, queue='celery'):
    return import_block.apply_async(
        kwargs=dict(block=int(block)),
        link=success_import_block.s(),
        link_error=handle_errors.s(block),
        queue=queue,
    )


# @app.task


def _sync_from_to(start_block: int, end_block: int):
    current_block = int(start_block)
    
    while current_block < end_block:
        try:
            import_block(block=current_block)
        except (Exception, BaseException):
            log.exception("ERROR: Something went wrong while importing block %d", current_block)
