from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("leads", "0006_lead_sold_subscription")]

    operations = [
        migrations.AddField(
            model_name="leadstatuschange",
            name="is_automatic",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Переход выполнен системой по бизнес-событию, " "а не вручную в заявке."
                ),
            ),
        )
    ]
