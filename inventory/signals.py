from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Product, Transaction, Warehouse
from .services import clear_report_cache


@receiver([post_save, post_delete], sender=Transaction)
@receiver([post_save, post_delete], sender=Product)
@receiver([post_save, post_delete], sender=Warehouse)
def invalidate_stock_cache(sender, **kwargs):
    clear_report_cache()