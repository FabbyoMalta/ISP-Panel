from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import AuthAttempt


class Command(BaseCommand):
    help = "Remove contadores de autenticação com janelas encerradas há mais de um dia."

    def handle(self, *args, **options):
        count, _ = AuthAttempt.objects.filter(
            window_start__lt=timezone.now() - timedelta(days=1)
        ).delete()
        self.stdout.write(f"{count} contadores antigos removidos.")
