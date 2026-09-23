from django.db import migrations


def install(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute('''
        CREATE FUNCTION prevent_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Published history is immutable'; END;
        $$;
        CREATE TRIGGER security_append_only BEFORE UPDATE OR DELETE ON accounts_securityevent
          FOR EACH ROW EXECUTE FUNCTION prevent_history_change();
        CREATE TRIGGER metric_append_only BEFORE UPDATE OR DELETE ON metrics_metricobservation
          FOR EACH ROW EXECUTE FUNCTION prevent_history_change();
        CREATE TRIGGER template_immutable BEFORE UPDATE OR DELETE ON assessments_assessmenttemplateversion
          FOR EACH ROW EXECUTE FUNCTION prevent_history_change();
        CREATE TRIGGER published_assessment_immutable BEFORE UPDATE OR DELETE ON assessments_assessment
          FOR EACH ROW WHEN (OLD.published_at IS NOT NULL) EXECUTE FUNCTION prevent_history_change();
        CREATE FUNCTION protect_published_answer() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP IN ('UPDATE','DELETE') AND EXISTS (SELECT 1 FROM assessments_assessment WHERE id=OLD.assessment_id AND published_at IS NOT NULL) THEN
            RAISE EXCEPTION 'Published answers are immutable';
          END IF;
          IF TG_OP IN ('INSERT','UPDATE') AND EXISTS (SELECT 1 FROM assessments_assessment WHERE id=NEW.assessment_id AND published_at IS NOT NULL) THEN
            RAISE EXCEPTION 'Published answers are immutable';
          END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$;
        CREATE TRIGGER published_answer_immutable BEFORE INSERT OR UPDATE OR DELETE ON assessments_assessmentanswer
          FOR EACH ROW EXECUTE FUNCTION protect_published_answer();
    ''')


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute('''
        DROP TRIGGER IF EXISTS security_append_only ON accounts_securityevent;
        DROP TRIGGER IF EXISTS metric_append_only ON metrics_metricobservation;
        DROP TRIGGER IF EXISTS template_immutable ON assessments_assessmenttemplateversion;
        DROP TRIGGER IF EXISTS published_assessment_immutable ON assessments_assessment;
        DROP TRIGGER IF EXISTS published_answer_immutable ON assessments_assessmentanswer;
        DROP FUNCTION IF EXISTS protect_published_answer();
        DROP FUNCTION IF EXISTS prevent_history_change();
    ''')


class Migration(migrations.Migration):
    dependencies = [('tenancy','0002_row_security'), ('accounts','0002_securityevent')]
    operations = [migrations.RunPython(install,uninstall)]
