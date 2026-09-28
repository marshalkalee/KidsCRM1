# Generated for TRU-100.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0005_renewal_rejection_reasons"),
        ("schedule", "0008_lessonenrollment_source_attendance_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessonenrollment",
            name="source_lead",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="trial_enrollments",
                to="leads.lead",
            ),
        ),
        migrations.AddConstraint(
            model_name="lessonenrollment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("cancelled_at__isnull", True)),
                fields=("source_lead",),
                name="unique_active_trial_per_source_lead",
            ),
        ),
        migrations.AddConstraint(
            model_name="lessonenrollment",
            constraint=models.CheckConstraint(
                condition=models.Q(("source_lead__isnull", True), ("kind", "trial"), _connector="OR"),
                name="source_lead_only_for_trial",
            ),
        ),
    ]
