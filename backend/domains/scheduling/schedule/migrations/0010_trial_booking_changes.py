import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0008_status_change_event_type"),
        ("schedule", "0009_trial_source_lead"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessonenrollment",
            name="cancel_reason",
            field=models.TextField(blank=True),
        ),
        migrations.RemoveConstraint(
            model_name="reschedulecalllog",
            name="unique_reschedule_call_per_contact",
        ),
        migrations.AlterField(
            model_name="reschedulecalllog",
            name="parent_contact",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="reschedule_call_logs",
                to="clients.parentcontact",
                verbose_name="Контакт",
            ),
        ),
        migrations.AddField(
            model_name="reschedulecalllog",
            name="source_lead",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="lesson_call_logs",
                to="leads.lead",
                verbose_name="Заявка на пробное",
            ),
        ),
        migrations.AddConstraint(
            model_name="reschedulecalllog",
            constraint=models.UniqueConstraint(
                condition=models.Q(("parent_contact__isnull", False)),
                fields=("lesson", "parent_contact"),
                name="unique_reschedule_call_per_contact",
            ),
        ),
        migrations.AddConstraint(
            model_name="reschedulecalllog",
            constraint=models.UniqueConstraint(
                condition=models.Q(("source_lead__isnull", False)),
                fields=("lesson", "source_lead"),
                name="unique_lesson_call_per_trial_lead",
            ),
        ),
        migrations.AddConstraint(
            model_name="reschedulecalllog",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("parent_contact__isnull", False), ("source_lead__isnull", True))
                    | models.Q(("parent_contact__isnull", True), ("source_lead__isnull", False))
                ),
                name="lesson_call_exactly_one_contact",
            ),
        ),
    ]
