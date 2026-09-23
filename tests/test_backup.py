import os
import subprocess
import uuid
from pathlib import Path

import psycopg
import pytest
from django.db import connection
from psycopg import sql


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(
    connection.vendor != "postgresql" or not os.getenv("PG_BIN"),
    reason="Requires PostgreSQL and PG_BIN with matching pg_dump/pg_restore",
)
def test_backup_restores_data_policies_and_history(domain, tmp_path):
    config = connection.settings_dict
    params = {
        "user": config["USER"],
        "password": config["PASSWORD"],
        "host": config["HOST"],
        "port": config["PORT"],
    }
    recovery_name = "isp_restore_" + uuid.uuid4().hex[:12]
    env = dict(os.environ, PGPASSWORD=config["PASSWORD"])
    binary = Path(os.environ["PG_BIN"])
    dump = tmp_path / "restore-test.dump"
    common = ["-h", config["HOST"], "-p", str(config["PORT"]), "-U", config["USER"]]
    subprocess.run(
        [
            str(binary / "pg_dump"),
            *common,
            "-d",
            config["NAME"],
            "--format=custom",
            "--no-owner",
            "-f",
            str(dump),
        ],
        env=env,
        check=True,
        capture_output=True,
    )
    with psycopg.connect(dbname="postgres", autocommit=True, **params) as admin:
        admin.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(
                sql.Identifier(recovery_name)
            )
        )
        try:
            subprocess.run(
                [
                    str(binary / "pg_restore"),
                    *common,
                    "-d",
                    recovery_name,
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    str(dump),
                ],
                env=env,
                check=True,
                capture_output=True,
            )
            with psycopg.connect(dbname=recovery_name, **params) as restored:
                assert restored.execute("SELECT count(*) FROM tenancy_tenant").fetchone()[0] == 2
                assert (
                    restored.execute(
                        "SELECT title FROM recommendations_recommendation WHERE id=%s",
                        [domain.rec_a.pk],
                    ).fetchone()[0]
                    == domain.rec_a.title
                )
                assert restored.execute(
                    "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE relname='recommendations_recommendation'"
                ).fetchone()[0]
                assert (
                    restored.execute(
                        "SELECT count(*) FROM pg_trigger WHERE tgname='audit_append_only'"
                    ).fetchone()[0]
                    == 1
                )
                assert (
                    restored.execute(
                        "SELECT count(*) FROM pg_policy WHERE polname='tenant_isolation'"
                    ).fetchone()[0]
                    > 10
                )
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(recovery_name)))
