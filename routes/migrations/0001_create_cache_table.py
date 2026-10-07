"""Create the database cache table as part of `migrate`.

The cache is the database-backed one (see `CACHES` in settings), which normally
needs a separate `createcachetable` call. Putting it in a migration means
`python manage.py migrate` leaves the project fully set up, and the test database
gets the table too.
"""

from django.core.management import call_command
from django.db import migrations

CACHE_TABLE = "api_cache"


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


def drop_cache_table(apps, schema_editor):
    schema_editor.execute(f"DROP TABLE IF EXISTS {schema_editor.quote_name(CACHE_TABLE)}")


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.RunPython(create_cache_table, drop_cache_table)]
