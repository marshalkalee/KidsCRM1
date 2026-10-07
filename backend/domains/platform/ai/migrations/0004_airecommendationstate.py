import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0003_aigeneration"),
        ("tenants", "0003_direction"),
    ]

    operations = [
        migrations.CreateModel(
            name="AIRecommendationState",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("function", models.CharField(max_length=64)),
                ("candidate_key", models.CharField(max_length=64)),
                ("fingerprint", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("active", "Активна"), ("dismissed", "Отклонена")], default="active", max_length=16)),
                ("times_shown", models.PositiveSmallIntegerField(default=0)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.organization")),
            ],
        ),
        migrations.AddConstraint(
            model_name="airecommendationstate",
            constraint=models.UniqueConstraint(fields=("organization", "function", "fingerprint"), name="unique_ai_recommendation_fingerprint"),
        ),
        migrations.AddIndex(
            model_name="airecommendationstate",
            index=models.Index(fields=["organization", "function", "status"], name="ai_airecomm_organiz_535bbc_idx"),
        ),
    ]
