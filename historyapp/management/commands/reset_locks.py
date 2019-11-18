from django.core.management import BaseCommand, CommandParser
from lockmgr import lockmgr
from lockmgr.models import Lock


class Command(BaseCommand):
    help = "Clears all locks that were set using Privex's django-lockmgr package"
    
    def __init__(self):
        super(Command, self).__init__()
    
    def handle(self, *args, **options):
        lockmgr.clean_locks()  # Clean up any locks due for expiration.
    
        lock_count = Lock.objects.count()
        print("WARNING: You are about to clear ALL locks set using Privex LockMgr.\n"
              "You should only do this if you know what you're doing, and have made sure to stop any running\n"
              "instances of your application, to ensure no conflicts are caused by removing ALL LOCKS.\n\n")
        print(f"The following {lock_count} locks would be removed:")

        print("\n=========================================================\n")
        for l in Lock.objects.all():
            print(l)
        print("\n=========================================================\n")

        print('Are you SURE you want to clear all locks?')
        answer = input('Type YES in all capitals if you are sure > ').strip()
        print()
        print("\n=========================================================\n")
        if answer != 'YES':
            print("You didn't type YES so we're now returning you back to the terminal.")
            print("\n=========================================================\n")
            return
        print("Please wait... Removing all locks regardless of their status or expiration.\n")

        total_del, _ = Lock.objects.all().delete()

        print(f"A total of {total_del} lock rows were deleted. All locks should now be removed.\n")

        print("")
        print("\n=========================================================\n")
        print("Finished clearing locks.")
        print("\n=========================================================\n")


