from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers

from .models import Product, Transaction, Warehouse
from .services import (
    get_stock_for_warehouse,
    get_total_stock,
    get_total_value,
    get_warehouse_inventory,
)

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('A user with that username already exists.')
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('A user with that email already exists.')
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match.'})
        validate_password(attrs['password'])
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        return User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
        )


class ProductSerializer(serializers.ModelSerializer):
    current_stock = serializers.SerializerMethodField()
    total_value = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id',
            'sku',
            'name',
            'description',
            'base_price',
            'min_stock_level',
            'current_stock',
            'total_value',
            'is_deleted',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'current_stock', 'total_value', 'is_deleted', 'created_at', 'updated_at']

    def get_current_stock(self, obj):
        if hasattr(obj, 'current_stock') and obj.current_stock is not None:
            return obj.current_stock
        return get_total_stock(obj)

    def get_total_value(self, obj):
        if hasattr(obj, 'total_value') and obj.total_value is not None:
            return Decimal(str(obj.total_value))
        return get_total_value(obj)


class WarehouseSerializer(serializers.ModelSerializer):
    inventory = serializers.SerializerMethodField()

    class Meta:
        model = Warehouse
        fields = ['id', 'name', 'address', 'admin_email', 'inventory', 'created_at', 'updated_at']
        read_only_fields = ['id', 'inventory', 'created_at', 'updated_at']

    def get_inventory(self, obj):
        return get_warehouse_inventory(obj)


class TransactionSerializer(serializers.ModelSerializer):
    product_name = serializers.SerializerMethodField(read_only=True)
    source_warehouse_name = serializers.SerializerMethodField(read_only=True)
    destination_warehouse_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Transaction
        fields = [
            'id',
            'product',
            'product_name',
            'transaction_type',
            'quantity',
            'source_warehouse',
            'source_warehouse_name',
            'destination_warehouse',
            'destination_warehouse_name',
            'transaction_at',
            'created_by',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'product_name',
            'source_warehouse_name',
            'destination_warehouse_name',
            'created_by',
            'created_at',
        ]

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError('Quantity must be greater than zero.')
        return value

    def validate(self, attrs):
        product = attrs.get('product')
        transaction_type = attrs.get('transaction_type')
        source = attrs.get('source_warehouse')
        destination = attrs.get('destination_warehouse')
        quantity = attrs.get('quantity')

        if product is None or product.is_deleted:
            raise serializers.ValidationError({'product': 'Product does not exist or is deleted.'})

        if transaction_type in [Transaction.TYPE_OUT, Transaction.TYPE_TRANSFER]:
            if source is None:
                raise serializers.ValidationError({'source_warehouse': 'Source warehouse is required for this transaction type.'})
            if transaction_type == Transaction.TYPE_TRANSFER and source == destination:
                raise serializers.ValidationError({'destination_warehouse': 'Source and destination warehouses must be different.'})
            available_stock = get_stock_for_warehouse(product, source)
            if available_stock < quantity:
                raise serializers.ValidationError(
                    {'quantity': f'Not enough stock available at source warehouse. Available: {available_stock}, requested: {quantity}.'}
                )

        if transaction_type in [Transaction.TYPE_IN, Transaction.TYPE_TRANSFER]:
            if destination is None:
                raise serializers.ValidationError({'destination_warehouse': 'Destination warehouse is required for this transaction type.'})

        if transaction_type == Transaction.TYPE_IN and source is not None:
            raise serializers.ValidationError({'source_warehouse': 'Source warehouse should be empty for inbound transactions.'})
        if transaction_type == Transaction.TYPE_OUT and destination is not None:
            raise serializers.ValidationError({'destination_warehouse': 'Destination warehouse should be empty for outbound transactions.'})

        return attrs

    def get_product_name(self, obj):
        return obj.product.name

    def get_source_warehouse_name(self, obj):
        return obj.source_warehouse.name if obj.source_warehouse else None

    def get_destination_warehouse_name(self, obj):
        return obj.destination_warehouse.name if obj.destination_warehouse else None


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match.'})
        try:
            user_id = urlsafe_base64_decode(attrs['uid']).decode()
            user = User.objects.get(pk=user_id)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({'uid': 'Invalid reset link.'})

        if not default_token_generator.check_token(user, attrs['token']):
            raise serializers.ValidationError({'token': 'Invalid or expired reset token.'})

        validate_password(attrs['password'], user=user)
        attrs['user'] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        user.set_password(self.validated_data['password'])
        user.save()
        return user