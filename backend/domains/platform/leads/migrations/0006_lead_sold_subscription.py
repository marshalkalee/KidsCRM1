from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0005_renewal_rejection_reasons"),
        ("subscriptions", "0006_subscription_branch"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="sold_subscription",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="source_leads",
                to="subscriptions.subscription",
            ),
        ),
    ]
