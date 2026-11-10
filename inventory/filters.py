import django_filters
from django.db.models import Q

from .models import Product, Transaction


class ProductFilter(django_filters.FilterSet):
    sku = django_filters.CharFilter(field_name='sku', lookup_expr='icontains')
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')
    min_price = django_filters.NumberFilter(field_name='base_price', lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name='base_price', lookup_expr='lte')

    class Meta:
        model = Product
        fields = ['sku', 'name', 'min_price', 'max_price']


class TransactionFilter(django_filters.FilterSet):
    transaction_type = django_filters.CharFilter(field_name='transaction_type', lookup_expr='iexact')
    type = django_filters.CharFilter(field_name='transaction_type', lookup_expr='iexact')
    warehouse = django_filters.NumberFilter(method='filter_warehouse')
    warehouse_id = django_filters.NumberFilter(method='filter_warehouse')
    product = django_filters.NumberFilter(field_name='product_id')
    product_id = django_filters.NumberFilter(field_name='product_id')
    date_from = django_filters.DateTimeFilter(field_name='transaction_at', lookup_expr='gte')
    start_date = django_filters.DateTimeFilter(field_name='transaction_at', lookup_expr='gte')
    date_to = django_filters.DateTimeFilter(field_name='transaction_at', lookup_expr='lte')
    end_date = django_filters.DateTimeFilter(field_name='transaction_at', lookup_expr='lte')

    class Meta:
        model = Transaction
        fields = [
            'transaction_type',
            'type',
            'warehouse',
            'warehouse_id',
            'product',
            'product_id',
            'date_from',
            'start_date',
            'date_to',
            'end_date',
        ]

    def filter_warehouse(self, queryset, name, value):
        return queryset.filter(Q(source_warehouse_id=value) | Q(destination_warehouse_id=value))