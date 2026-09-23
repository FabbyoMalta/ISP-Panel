from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Recusa execução PostgreSQL com papel privilegiado ou RLS ausente."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("Runtime de produção exige PostgreSQL.")
        with connection.cursor() as cursor:
            cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
            if any(cursor.fetchone()):
                raise CommandError("Runtime não pode usar superusuário ou BYPASSRLS.")
            cursor.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner=current_user"
            )
            if cursor.fetchone()[0]:
                raise CommandError("Runtime não pode ser proprietário de tabelas.")
            cursor.execute("""
                SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname='tenant_id'
                WHERE n.nspname='public' AND c.relkind='r' AND c.relname!='tenancy_tenantmembership'
                AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity
                     OR NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid))
            """)
            missing = cursor.fetchall()
            if missing:
                raise CommandError(f"Tabelas sem proteção RLS: {missing}")
        self.stdout.write(self.style.SUCCESS("Papel runtime e políticas RLS verificados."))
