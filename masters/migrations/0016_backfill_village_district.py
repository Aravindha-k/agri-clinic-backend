from django.db import migrations


def _get_columns(connection, table_name):
    with connection.cursor() as cursor:
        return {
            c.name
            for c in connection.introspection.get_table_description(cursor, table_name)
        }


def backfill_village_district(apps, schema_editor):
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))

    if "masters_village" not in tables:
        return

    village_columns = _get_columns(connection, "masters_village")
    if "district_id" not in village_columns:
        return

    with connection.cursor() as cursor:
        # Legacy-path support: if old taluk table/column still exists in this DB state,
        # copy district_id from taluk into village.
        if "masters_taluk" in tables and "taluk_id" in village_columns:
            cursor.execute(
                """
                UPDATE masters_village AS v
                SET district_id = t.district_id
                FROM masters_taluk AS t
                WHERE v.district_id IS NULL
                  AND v.taluk_id = t.id
                  AND t.district_id IS NOT NULL
                """
            )

        # Fallback: infer village district from related farmer records.
        if "masters_farmer" in tables:
            farmer_columns = _get_columns(connection, "masters_farmer")
            if "village_id" in farmer_columns and "district_id" in farmer_columns:
                cursor.execute(
                    """
                    UPDATE masters_village AS v
                    SET district_id = src.district_id
                    FROM (
                        SELECT village_id, MAX(district_id) AS district_id
                        FROM masters_farmer
                        WHERE village_id IS NOT NULL AND district_id IS NOT NULL
                        GROUP BY village_id
                    ) AS src
                    WHERE v.id = src.village_id
                      AND v.district_id IS NULL
                    """
                )


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0015_problemcategory"),
    ]

    operations = [
        migrations.RunPython(backfill_village_district, noop_reverse),
    ]
