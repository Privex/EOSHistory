import logging
import os
from os import getenv as env

from privex.helpers import env_csv
from privex.loghelper import LogHelper

from eoshistory.settings.core import BASE_DIR, DEBUG

#######
# Logging Configuration
#######

CONSOLE_LOG_LEVEL = env('LOG_LEVEL', 'DEBUG') if DEBUG else env('LOG_LEVEL', 'INFO')
CONSOLE_LOG_LEVEL = logging.getLevelName(CONSOLE_LOG_LEVEL.upper())
LOG_FORMATTER = logging.Formatter('[%(asctime)s]: %(name)-55s -> %(funcName)-20s : %(levelname)-8s:: %(message)s')

# Log messages equal/above the specified level to debug.log (default: DEBUG if debug enabled, otherwise INFO)
DBGFILE_LEVEL = env('DBGFILE_LEVEL', 'DEBUG') if DEBUG else env('LOG_LEVEL', 'INFO')
DBGFILE_LEVEL = logging.getLevelName(DBGFILE_LEVEL.upper())

# Log messages equal/above the specified level to error.log (default: WARNING)
ERRFILE_LEVEL = logging.getLevelName(env('ERRFILE_LEVEL', 'WARNING').upper())

# Use the same logging configuration for all privex modules
LOGGER_NAMES = env_csv('LOGGER_NAMES', ['historyapp', 'privex'])

# Main logger name
BASE_LOGGER = env('BASE_LOGGER_NAME', 'eoshistory')

# Output logs to respective files with automatic daily log rotation (up to 14 days of logs)
BASE_LOG_FOLDER = os.path.join(BASE_DIR, env('LOG_FOLDER', 'logs'))

# To make it easier to identify whether a log entry came from the web application, or from a cron (e.g. load_txs)
# we log to the sub-folder ``BASE_WEB_LOGS`` by default, and management commands such as load_txs will
# re-configure the logs to go to ``BASE_CRON_LOGS``
BASE_WEB_LOGS = os.path.join(BASE_LOG_FOLDER, env('BASE_WEB_LOGS', 'web'))
BASE_CRON_LOGS = os.path.join(BASE_LOG_FOLDER, env('BASE_CRON_LOGS', 'crons'))

#######
# End Logging Configuration
#######


def config_logger(*logger_names, log_dir=BASE_LOG_FOLDER, handler_level=CONSOLE_LOG_LEVEL, level=logging.DEBUG):
    """
    Used to allow isolated parts of this project to easily change the log output folder, e.g. allow Django
    management commands to change the logs folder to ``crons/``

    Currently only used by :class:`payments.management.CronLoggerMixin`

    Usage:

    >>> config_logger('someapp', 'otherlogger', 'mylogger', log_dir='/full/path/to/log/folder')

    :param str logger_names: List of logger names to replace logging config for (see LOGGER_NAMES)
    :param str log_dir:      Fully qualified path. Set each logger's timed_file log directory to this
    :return: :class:`logging.Logger` instance of BASE_LOGGER
    """
    _lh = LogHelper(BASE_LOGGER, formatter=LOG_FORMATTER, handler_level=logging.DEBUG, level=level)
    _lh.log.handlers.clear()  # Force reset the handlers on the base logger to avoid double/triple logging.
    _lh.add_console_handler(level=handler_level)  # Log to console with CONSOLE_LOG_LEVEL
    
    _dbg_log = os.path.join(log_dir, 'debug.log')
    _err_log = os.path.join(log_dir, 'error.log')
    
    _lh.add_timed_file_handler(_dbg_log, when='D', interval=1, backups=14, level=DBGFILE_LEVEL)
    _lh.add_timed_file_handler(_err_log, when='D', interval=1, backups=14, level=ERRFILE_LEVEL)
    
    l = _lh.get_logger()
    
    # Use the same logging configuration for all privex modules
    _lh.copy_logger(*logger_names)
    
    return l


LOGGER_IS_SETUP = False

if not LOGGER_IS_SETUP:
    log = config_logger(*LOGGER_NAMES, log_dir=BASE_WEB_LOGS)
    LOGGER_IS_SETUP = True
else:
    log = logging.getLogger(BASE_LOGGER)
