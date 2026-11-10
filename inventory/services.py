import time
import uuid
from decimal import Decimal

import redis
from django.conf import settings
from django.core.cache import cache
from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce

from .models import Product, Transaction, Warehouse

_redis_pool = None


def get_redis_client():
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)
    return redis.Redis(connection_pool=_redis_pool, socket_connect_timeout=1)


def get_stock_for_warehouse(product, warehouse):
    incoming = (
        Transaction.objects.filter(
            product=product,
            destination_warehouse=warehouse,
            transaction_type__in=[Transaction.TYPE_IN, Transaction.TYPE_TRANSFER],
        ).aggregate(total=Sum('quantity'))['total']
        or 0
    )
    outgoing = (
        Transaction.objects.filter(
            product=product,
            source_warehouse=warehouse,
            transaction_type__in=[Transaction.TYPE_OUT, Transaction.TYPE_TRANSFER],
        ).aggregate(total=Sum('quantity'))['total']
        or 0
    )
    return int(incoming - outgoing)


def get_total_stock(product):
    incoming = (
        Transaction.objects.filter(
            product=product,
            transaction_type=Transaction.TYPE_IN,
        ).aggregate(total=Sum('quantity'))['total']
        or 0
    )
    outgoing = (
        Transaction.objects.filter(
            product=product,
            transaction_type=Transaction.TYPE_OUT,
        ).aggregate(total=Sum('quantity'))['total']
        or 0
    )
    return int(incoming - outgoing)


def get_total_value(product):
    return Decimal(get_total_stock(product)) * product.base_price


def get_product_queryset_with_stock():
    """
    Returns an active Product QuerySet annotated with total current_stock,
    total_value, and alias price calculated dynamically via Django ORM expressions.
    """
    return (
        Product.objects.filter(is_deleted=False)
        .annotate(
            current_stock=Coalesce(
                Sum(
                    Case(
                        When(transactions__transaction_type=Transaction.TYPE_IN, then=F('transactions__quantity')),
                        When(transactions__transaction_type=Transaction.TYPE_OUT, then=-F('transactions__quantity')),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                ),
                Value(0),
                output_field=IntegerField(),
            )
        )
        .annotate(
            total_stock=F('current_stock'),
            price=F('base_price'),
            total_value=Coalesce(
                ExpressionWrapper(
                    F('current_stock') * F('base_price'),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                ),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
    )


def get_warehouse_inventory_qs(warehouse):
    """
    Calculates current stock and stock value for every active product
    in a given warehouse using a single Django ORM aggregation query.
    """
    incoming = Coalesce(
        Sum(
            'transactions__quantity',
            filter=Q(
                transactions__destination_warehouse=warehouse,
                transactions__transaction_type__in=[Transaction.TYPE_IN, Transaction.TYPE_TRANSFER],
            ),
        ),
        Value(0),
        output_field=IntegerField(),
    )
    outgoing = Coalesce(
        Sum(
            'transactions__quantity',
            filter=Q(
                transactions__source_warehouse=warehouse,
                transactions__transaction_type__in=[Transaction.TYPE_OUT, Transaction.TYPE_TRANSFER],
            ),
        ),
        Value(0),
        output_field=IntegerField(),
    )

    return (
        Product.objects.filter(is_deleted=False)
        .annotate(stock=incoming - outgoing)
        .annotate(
            stock_value=Coalesce(
                ExpressionWrapper(
                    F('stock') * F('base_price'),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                ),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
    )


def get_warehouse_inventory(warehouse):
    products = get_warehouse_inventory_qs(warehouse)
    rows = []
    for product in products:
        rows.append(
            {
                'product_id': product.id,
                'sku': product.sku,
                'name': product.name,
                'current_stock': product.stock,
                'unit_price': product.base_price,
                'total_value': product.stock_value,
            }
        )
    return rows


def build_stock_summary():
    warehouses_data = []
    for warehouse in Warehouse.objects.all():
        products_qs = get_warehouse_inventory_qs(warehouse)
        products = []
        total_warehouse_value = Decimal('0.00')

        for p in products_qs:
            val = p.stock_value or Decimal('0.00')
            products.append(
                {
                    'product_id': p.id,
                    'sku': p.sku,
                    'name': p.name,
                    'current_stock': p.stock,
                    'unit_price': str(p.base_price),
                    'total_value': str(val),
                }
            )
            total_warehouse_value += val

        warehouses_data.append(
            {
                'warehouse_id': warehouse.id,
                'warehouse_name': warehouse.name,
                'admin_email': warehouse.admin_email,
                'products': products,
                'total_value': str(total_warehouse_value),
            }
        )
    return warehouses_data


def clear_report_cache():
    try:
        cache.delete('stock_report_summary')
    except Exception:
        pass


def check_rate_limit(user):
    try:
        client = get_redis_client()
        now = time.time()
        key = f'inventory:rate:{user.pk}'

        pipe = client.pipeline()
        pipe.zremrangebyscore(key, '-inf', now - 60)
        pipe.zcard(key)
        results = pipe.execute()
        current_count = results[1]

        if current_count >= 50:
            return False

        pipe = client.pipeline()
        pipe.zadd(key, {uuid.uuid4().hex: now})
        pipe.expire(key, 65)
        pipe.execute()
        return True
    except (redis.exceptions.RedisError, Exception):
        return True