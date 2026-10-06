from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("portal", "0006_parentlessonrequest_cancel_reason_and_more")]

    operations = [
        migrations.AddField(
            model_name="parentlessonrequest",
            name="rejection_reason",
            field=models.TextField(blank=True, default=""),
        ),
    ]
