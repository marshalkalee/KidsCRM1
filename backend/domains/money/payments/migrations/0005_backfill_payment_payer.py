from django.db import migrations


def backfill_payer(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")
    ChildContact = apps.get_model("clients", "ChildContact")

    for payment in Payment.objects.filter(payer__isnull=True).select_related("subscription"):
        link = ChildContact.objects.filter(
            child_id=payment.subscription.child_id, is_payer=True,
        ).first()
        if link:
            payment.payer_id = link.parent_contact_id
            payment.save(update_fields=["payer"])


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0004_payment_payer"),
    ]
    operations = [
        migrations.RunPython(backfill_payer, migrations.RunPython.noop),
    ]