from django.db import migrations, models


def hours_to_seconds(apps, schema_editor):
    UserLibrary = apps.get_model('mfs', 'UserLibrary')
    for entry in UserLibrary.objects.filter(playtime_hours__gt=0):
        entry.playtime_seconds = entry.playtime_hours * 3600
        entry.save(update_fields=['playtime_seconds'])


def seconds_to_hours(apps, schema_editor):
    UserLibrary = apps.get_model('mfs', 'UserLibrary')
    for entry in UserLibrary.objects.filter(playtime_seconds__gt=0):
        entry.playtime_hours = entry.playtime_seconds // 3600
        entry.save(update_fields=['playtime_hours'])


class Migration(migrations.Migration):

    dependencies = [
        ('mfs', '0028_library_game_details'),
    ]

    operations = [
        migrations.AddField(
            model_name='userlibrary',
            name='playtime_seconds',
            field=models.PositiveIntegerField(default=0, verbose_name='Время в игре (секунд)'),
        ),
        migrations.AddField(
            model_name='userlibrary',
            name='session_started_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Запущена в'),
        ),
        migrations.RunPython(hours_to_seconds, seconds_to_hours),
        migrations.RemoveField(
            model_name='userlibrary',
            name='playtime_hours',
        ),
    ]
