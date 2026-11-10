from django.conf import settings
from django.db import models
from django.utils import timezone


class Warehouse(models.Model):
    name = models.CharField(max_length=200)
    address = models.TextField()
    admin_email = models.EmailField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    sku = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    base_price = models.DecimalField(max_digits=12, decimal_places=2)
    min_stock_level = models.PositiveIntegerField(default=0)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.sku})'


class Transaction(models.Model):
    TYPE_IN = 'IN'
    TYPE_OUT = 'OUT'
    TYPE_TRANSFER = 'TRANSFER'
    TYPE_CHOICES = [
        (TYPE_IN, 'Inbound'),
        (TYPE_OUT, 'Outbound'),
        (TYPE_TRANSFER, 'Transfer'),
    ]

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='transactions')
    transaction_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    quantity = models.PositiveIntegerField()
    source_warehouse = models.ForeignKey(
        Warehouse,
        related_name='source_transactions',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    destination_warehouse = models.ForeignKey(
        Warehouse,
        related_name='destination_transactions',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    transaction_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='transactions')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-transaction_at']

    def __str__(self):
        return f'{self.product.sku} {self.transaction_type} {self.quantity}'
