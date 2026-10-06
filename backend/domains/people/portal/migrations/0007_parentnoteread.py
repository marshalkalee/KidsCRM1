import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0004_parentnote_kind_parentnote_valid_until"),
        ("portal", "0006_parentlessonrequest_cancel_reason_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ParentNoteRead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("read_at", models.DateTimeField(auto_now_add=True)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="note_reads", to="portal.parentaccount")),
                ("note", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="parent_reads", to="attendance.parentnote")),
            ],
        ),
        migrations.AddConstraint(
            model_name="parentnoteread",
            constraint=models.UniqueConstraint(
                fields=("account", "note"), name="unique_parent_note_read"
            ),
        ),
    ]
