# Generated by Django 5.0 on 2023-12-19 23:39

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reviewblitz', '0007_auto_20221222_1808'),
    ]

    operations = [
        migrations.CreateModel(
            name='WeeklyTheme',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text="A name for this theme, such as 'One-Shot Week'.", max_length=50)),
                ('description', models.TextField(help_text='A basic description of this theme.')),
                ('notes', models.TextField(help_text='A more detailed explanation of what qualifies for this theme.')),
                ('claimable', models.CharField(choices=[('per_chapter', 'Per chapter'), ('per_review', 'Per review'), ('per_fic', 'Per fic'), ('per_author', 'Per author')], default='per_fic', max_length=11)),
                ('consecutive_chapter_bonus_applies', models.BooleanField(default=True, help_text='Whether or not the repeat bonus for consecutive chapters, if any, applies when this theme is active.')),
            ],
        ),
        migrations.AlterField(
            model_name='blitzreview',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='blitzuser',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='blitzuser',
            name='points_spent',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AlterField(
            model_name='reviewblitz',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='reviewblitzscoring',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='reviewchapterlink',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.CreateModel(
            name='ReviewBlitzTheme',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('week', models.PositiveIntegerField()),
                ('blitz', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='reviewblitz.reviewblitz')),
                ('theme', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='reviewblitz.weeklytheme')),
            ],
        ),
        migrations.AddField(
            model_name='reviewblitz',
            name='themes',
            field=models.ManyToManyField(through='reviewblitz.ReviewBlitzTheme', to='reviewblitz.weeklytheme'),
        ),
    ]