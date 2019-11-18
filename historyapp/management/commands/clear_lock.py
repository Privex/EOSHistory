from django.core.management import BaseCommand, CommandParser
from lockmgr import lockmgr
from lockmgr.lockmgr import LockMgr


class Command(BaseCommand):
    help = "Releases a lock set using Privex's django-lockmgr package"
    
    def __init__(self):
        super(Command, self).__init__()
    
    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            'locks', type=str, nargs='+',
            help='One or more lockmgr lock names (as positional args) to release the locks for'
        )
    
    def handle(self, *args, **options):
        lockmgr.clean_locks()  # Clean up any locks due for expiration.
        locks: list = options['locks']
        
        if len(locks) == 0:
            print('No lock names specified.')
            return
        
        for l in locks:
            print()
            print(f"Releasing lock {l} from LockMgr...")
            LockMgr.unlock(l)
            print(f"Lock {l} has been removed (if it exists).")
        print("\n=========================================================\n")
        print("Finished clearing locks.")
        print("\n=========================================================\n")


