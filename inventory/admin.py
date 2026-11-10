from django.contrib import admin

from .models import Product, Transaction, Warehouse

admin.site.register(Warehouse)
admin.site.register(Product)
admin.site.register(Transaction)
