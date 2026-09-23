from django.db import migrations


APPS = ["clients", "inventory", "assessments", "recommendations", "risks", "metrics", "timeline", "external_links", "audit"]


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return  # SQLite is for development only; production settings reject it.
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
            schema_editor.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({expression}) WITH CHECK ({expression})")
            for field in model._meta.fields:
                if field.is_relation and field.related_model and any(f.name == "tenant" for f in field.related_model._meta.fields):
                    target = quote(field.related_model._meta.db_table)
                    constraint = quote(f"{model._meta.db_table}_{field.name}_same_tenant")
                    schema_editor.execute(
                        f"ALTER TABLE {table} ADD CONSTRAINT {constraint} FOREIGN KEY (tenant_id, {quote(field.column)}) "
                        f"REFERENCES {target} (tenant_id, id) DEFERRABLE INITIALLY IMMEDIATE"
                    )
    schema_editor.execute("""
        CREATE FUNCTION prevent_audit_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Audit entries are append-only'; END;
        $$;
        CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_auditentry
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_change();
    """)


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS audit_append_only ON audit_auditentry")
    schema_editor.execute("DROP FUNCTION IF EXISTS prevent_audit_change()")
    quote = schema_editor.quote_name
    for app in APPS:
        for model in apps.get_app_config(app).get_models():
            if not any(f.name == "tenant" for f in model._meta.fields):
                continue
            table = quote(model._meta.db_table)
            for field in model._meta.fields:
                if field.is_relation and field.related_model and any(f.name == "tenant" for f in field.related_model._meta.fields):
                    constraint = quote(f"{model._meta.db_table}_{field.name}_same_tenant")
                    schema_editor.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
            schema_editor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            schema_editor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [(app, "0001_initial") for app in APPS] + [("tenancy", "0001_initial")]
    operations = [migrations.RunPython(install, uninstall)]
