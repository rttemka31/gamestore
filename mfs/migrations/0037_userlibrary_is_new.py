from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mfs', '0036_gift'),
    ]

    operations = [
        # Игры, которые уже лежат в библиотеках, новыми не считаются: поле добавляется со значением False,
        # а True становится значением по умолчанию только для записей, созданных после миграции
        migrations.AddField(
            model_name='userlibrary',
            name='is_new',
            field=models.BooleanField(default=False, verbose_name='Новая игра'),
        ),
        migrations.AlterField(
            model_name='userlibrary',
            name='is_new',
            field=models.BooleanField(default=True, verbose_name='Новая игра'),
        ),
    ]
