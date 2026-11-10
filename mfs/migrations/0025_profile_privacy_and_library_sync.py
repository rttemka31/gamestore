from django.db import migrations, models


def sync_library_with_owners(apps, schema_editor):
    """Game.owners — источник правды: приводим UserLibrary в соответствие с ним."""
    Game = apps.get_model('mfs', 'Game')
    UserLibrary = apps.get_model('mfs', 'UserLibrary')

    owned = set(Game.owners.through.objects.values_list('user_id', 'game_id'))
    seen = set()

    for entry in UserLibrary.objects.order_by('pk'):
        key = (entry.user_id, entry.game_id)
        if key not in owned or key in seen:
            entry.delete()
        else:
            seen.add(key)

    UserLibrary.objects.bulk_create(
        UserLibrary(user_id=user_id, game_id=game_id)
        for user_id, game_id in owned - seen
    )


class Migration(migrations.Migration):

    dependencies = [
        ('mfs', '0024_alter_review_options_review_updated_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='profile_visibility',
            field=models.CharField(choices=[('everyone', 'Все'), ('friends', 'Только друзья'), ('private', 'Только я')], default='everyone', max_length=10),
        ),
        migrations.AddField(
            model_name='profile',
            name='show_library',
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(sync_library_with_owners, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='userlibrary',
            constraint=models.UniqueConstraint(fields=('user', 'game'), name='unique_library_entry'),
        ),
    ]
