from celery import shared_task


@shared_task
def geocode_branch_task(branch_id: str):
    """Координаты по адресу — фоном: внешний сервис не держит форму (TRU-178)."""
    from .geocoding import geocode_branch
    from .models import Branch

    branch = Branch.objects.filter(pk=branch_id).first()
    return bool(branch and geocode_branch(branch))
