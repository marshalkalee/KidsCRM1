from django.contrib import admin

from .models import Lead, LeadRejectionReason, LeadSource

admin.site.register(Lead)
admin.site.register(LeadSource)
admin.site.register(LeadRejectionReason)
