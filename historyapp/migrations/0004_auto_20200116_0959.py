# Generated by Django 2.2.7 on 2020-01-16 09:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('historyapp', '0003_auto_20191129_0313'),
    ]

    operations = [
        migrations.AlterField(
            model_name='eosaction',
            name='id',
            field=models.BigIntegerField(primary_key=True, serialize=False),
        ),
    ]
