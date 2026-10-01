from rest_framework import serializers

from .models import Task


class TaskSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.CharField(
        source="assigned_to.full_name", read_only=True, default=None
    )
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default=None
    )
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    child_name = serializers.CharField(source="child.full_name", read_only=True, default=None)
    lead_name = serializers.CharField(source="lead.parent_name", read_only=True, default=None)
    contact_phone = serializers.SerializerMethodField()
    contact_whatsapp = serializers.SerializerMethodField()
    child_debt = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "type",
            "type_display",
            "status",
            "status_display",
            "source",
            "title",
            "description",
            "closing_comment",
            "due_at",
            "assigned_to",
            "assigned_to_name",
            "created_by",
            "created_by_name",
            "lead",
            "lead_name",
            "child",
            "child_name",
            "branch",
            "contact_phone",
            "contact_whatsapp",
            "child_debt",
            "created_at",
        ]
        read_only_fields = ["source", "created_by", "closing_comment"]

    def get_contact_phone(self, obj):
        contact = self._payer_contact(obj)
        if contact is None:
            return obj.lead.phone if obj.lead_id else None
        phone = contact.phones.first()
        return phone.number if phone else None

    def get_contact_whatsapp(self, obj):
        contact = self._payer_contact(obj)
        if contact and contact.whatsapp:
            return contact.whatsapp
        return self.get_contact_phone(obj)

    def get_child_debt(self, obj):
        if not obj.child_id:
            return None
        from domains.money.subscriptions.debt import debt_by_child

        return str(debt_by_child(obj.organization, [obj.child_id]).get(obj.child_id, 0))

    def _payer_contact(self, obj):
        if not obj.child_id:
            return None
        from domains.people.clients.models import ChildContact

        link = (
            ChildContact.objects.filter(child_id=obj.child_id, is_payer=True)
            .select_related("parent_contact")
            .first()
        )
        return link.parent_contact if link else None
