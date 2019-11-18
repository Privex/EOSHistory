from django.core.management import BaseCommand, CommandParser
from lockmgr import lockmgr
from lockmgr.models import Lock


class Command(BaseCommand):
    help = "List all locks that were set using Privex's django-lockmgr package"
    
    def __init__(self):
        super(Command, self).__init__()
    
    def handle(self, *args, **options):
        lockmgr.clean_locks()   # Clean up any locks due for expiration.
        lock_count = Lock.objects.count()
        print()
        print(f"There are currently {lock_count} active locks using Privex Django-LockMgr")
        
        print("\n=========================================================\n")
        for l in Lock.objects.all():
            print(
                f"<Lock name='{l.name}' locked_by='{l.locked_by}' lock_process='{l.lock_process}' "
                f"locked_until='{l.locked_until}'>"
            )
        print("\n=========================================================\n")


