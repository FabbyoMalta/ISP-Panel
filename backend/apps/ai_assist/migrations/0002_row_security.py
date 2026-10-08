"""Enables RLS on this app's tables — ai_assist didn't exist when
apps.tenancy.migrations.0002_row_security installed RLS for every other
tenant-scoped app, so it never saw these two tables. Same install/
uninstall logic, scoped to just this app's models (migrations are
frozen in time, so this intentionally duplicates rather than imports
that module). See docs/security.md and AGENTS.md rule #3 — RLS is a
hard security boundary, this only ever adds coverage, never weakens it.
"""

from django.db import migrations

APPS = ["ai_assist"]


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.quote_name
    for app in APPS:
        for model in apps.get_app_config(app).get_models():
            fields = {f.name: f for f in model._meta.fields}
            if "tenant" not in fields:
                continue
            table = quote(model._meta.db_table)
            schema_editor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            schema_editor.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            expression = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
            schema_editor.execute(
                f"CREATE POLICY tenant_isolation ON {table} USING ({expression}) WITH CHECK ({expression})"
            )
            for field in model._meta.fields:
                if (
                    field.is_relation
                    and field.related_model
                    and any(f.name == "tenant" for f in field.related_model._meta.fields)
                ):
                    target = quote(field.related_model._meta.db_table)
                    constraint = quote(f"{model._meta.db_table}_{field.name}_same_tenant")
                    schema_editor.execute(
                        f"ALTER TABLE {table} ADD CONSTRAINT {constraint} FOREIGN KEY (tenant_id, {quote(field.column)}) "
                        f"REFERENCES {target} (tenant_id, id) DEFERRABLE INITIALLY IMMEDIATE"
                    )


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.quote_name
    for app in APPS:
        for model in apps.get_app_config(app).get_models():
            if not any(f.name == "tenant" for f in model._meta.fields):
                continue
            table = quote(model._meta.db_table)
            for field in model._meta.fields:
                if (
                    field.is_relation
                    and field.related_model
                    and any(f.name == "tenant" for f in field.related_model._meta.fields)
                ):
                    constraint = quote(f"{model._meta.db_table}_{field.name}_same_tenant")
                    schema_editor.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
            schema_editor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            schema_editor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [("ai_assist", "0001_initial")]
    operations = [migrations.RunPython(install, uninstall)]
