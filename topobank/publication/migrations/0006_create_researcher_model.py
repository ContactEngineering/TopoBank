# Generated by Django 3.2.11 on 2022-02-03 14:39

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import sortedm2m.fields


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('publication', '0005_publication_container'),
    ]

    operations = [
        migrations.CreateModel(
            name='Affiliation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('ror_id', models.CharField(max_length=9,
                                            null=True,
                                            validators=[django.core.validators.RegexValidator('^0[^ilouILOU]{6}[0-9]{2}')])),
            ],
        ),
        migrations.CreateModel(
            name='Researcher',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_name', models.CharField(max_length=60)),
                ('last_name', models.CharField(max_length=60)),
                ('orcid_id', models.CharField(max_length=19,
                                              null=True,
                                              validators=[django.core.validators.RegexValidator('^[0-9]{4}-[0-9]{4}-[0-9]{4}')])),
                ('affiliations', sortedm2m.fields.SortedManyToManyField(help_text=None, to='publication.Affiliation')),
                ('user', models.ForeignKey(null=True,
                                           on_delete=django.db.models.deletion.SET_NULL,
                                           to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name='publication',
            name='authors_list',
            field=sortedm2m.fields.SortedManyToManyField(help_text=None, to='publication.Researcher'),
        ),
    ]
