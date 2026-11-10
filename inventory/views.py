import json
from decimal import Decimal

import pandas as pd
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction as db_transaction
from django.http import HttpResponse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    renderer_classes,
)
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.renderers import BaseRenderer, BrowsableAPIRenderer, JSONRenderer
from rest_framework.response import Response

from .filters import ProductFilter, TransactionFilter
from .models import Product, Transaction, Warehouse
from .serializers import (
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProductSerializer,
    RegisterSerializer,
    TransactionSerializer,
    UserSerializer,
    WarehouseSerializer,
)
from .services import (
    build_stock_summary,
    check_rate_limit,
    clear_report_cache,
    get_product_queryset_with_stock,
    get_stock_for_warehouse,
)

User = get_user_model()


class StockReportCSVRenderer(BaseRenderer):
    media_type = 'text/csv'
    format = 'csv'
    charset = 'utf-8'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b''
        if isinstance(data, bytes):
            return data
        if isinstance(data, str):
            return data.encode(self.charset)
        return json.dumps(data).encode(self.charset)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def register_user(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    return Response(
        {'detail': 'User registered successfully.', 'user': UserSerializer(user).data},
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def login_user(request):
    username = request.data.get('username')
    password = request.data.get('password')
    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({'detail': 'Invalid username or password.'}, status=status.HTTP_401_UNAUTHORIZED)
    login(request, user)
    return Response({'detail': 'Login successful.', 'user': UserSerializer(user).data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_user(request):
    logout(request)
    return Response({'detail': 'Logout successful.'})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def request_password_reset(request):
    serializer = PasswordResetRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    email = serializer.validated_data['email']
    users = User.objects.filter(email__iexact=email, is_active=True)

    for user in users:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        reset_url = f"{request.build_absolute_uri('/api/auth/password-reset/confirm/')}?uid={uid}&token={token}"
        send_mail(
            subject='Password Reset Request',
            message=(
                f"Hello {user.username},\n\n"
                f"You requested a password reset for your account.\n"
                f"UID: {uid}\n"
                f"Token: {token}\n"
                f"Reset URL: {reset_url}\n\n"
                f"If you did not request this, please ignore this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )

    return Response({'detail': 'Password reset email has been sent.'})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def confirm_password_reset(request):
    serializer = PasswordResetConfirmSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response({'detail': 'Password was reset successfully.'})


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ['sku', 'name']
    ordering_fields = ['base_price', 'price', 'name', 'current_stock', 'total_stock', 'total_value']
    ordering = ['name']

    def get_queryset(self):
        return get_product_queryset_with_stock()

    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save(update_fields=['is_deleted', 'updated_at'])
        clear_report_cache()

    def perform_create(self, serializer):
        super().perform_create(serializer)
        clear_report_cache()

    def perform_update(self, serializer):
        super().perform_update(serializer)
        clear_report_cache()


class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        super().perform_create(serializer)
        clear_report_cache()

    def perform_update(self, serializer):
        super().perform_update(serializer)
        clear_report_cache()

    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        clear_report_cache()


class TransactionViewSet(viewsets.ModelViewSet):
    queryset = Transaction.objects.select_related('product', 'source_warehouse', 'destination_warehouse', 'created_by')
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options']
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = TransactionFilter
    ordering_fields = ['transaction_at', 'quantity']
    ordering = ['-transaction_at']

    def create(self, request, *args, **kwargs):
        if not check_rate_limit(request.user):
            return Response(
                {'detail': 'You cannot create more than 50 transactions per minute.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        with db_transaction.atomic():
            product_instance = serializer.validated_data['product']
            Product.objects.select_for_update().get(pk=product_instance.pk)

            transaction_type = serializer.validated_data.get('transaction_type')
            source = serializer.validated_data.get('source_warehouse')
            quantity = serializer.validated_data.get('quantity')

            if transaction_type in [Transaction.TYPE_OUT, Transaction.TYPE_TRANSFER] and source:
                available_stock = get_stock_for_warehouse(product_instance, source)
                if available_stock < quantity:
                    raise ValidationError(
                        {'quantity': f'Not enough stock available at source warehouse. Available: {available_stock}, requested: {quantity}.'}
                    )

            transaction = serializer.save(created_by=self.request.user)

            if transaction.transaction_type in [Transaction.TYPE_OUT, Transaction.TYPE_TRANSFER] and transaction.source_warehouse:
                current_stock = get_stock_for_warehouse(transaction.product, transaction.source_warehouse)
                if current_stock < transaction.product.min_stock_level and transaction.source_warehouse.admin_email:
                    send_mail(
                        subject=f'Low stock alert: {transaction.product.name}',
                        message=(
                            f'Product {transaction.product.name} has fallen below the minimum stock level. '
                            f'Current stock: {current_stock}. Minimum allowed: {transaction.product.min_stock_level}.'
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[transaction.source_warehouse.admin_email],
                        fail_silently=True,
                    )
        clear_report_cache()

    def get_queryset(self):
        queryset = Transaction.objects.select_related('product', 'source_warehouse', 'destination_warehouse', 'created_by')
        if self.request.user.is_authenticated:
            return queryset
        return queryset.none()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@renderer_classes([JSONRenderer, BrowsableAPIRenderer, StockReportCSVRenderer])
def stock_report(request):
    report_format = request.query_params.get('format', 'json').lower()
    if getattr(request.accepted_renderer, 'format', None) == 'csv':
        report_format = 'csv'

    try:
        cached_report = cache.get('stock_report_summary')
    except Exception:
        cached_report = None

    if cached_report is None:
        cached_report = build_stock_summary()
        try:
            cache.set('stock_report_summary', cached_report, timeout=3600)
        except Exception:
            pass

    if report_format == 'csv':
        flat_data = []
        for warehouse in cached_report:
            for product in warehouse['products']:
                flat_data.append(
                    {
                        'warehouse_name': warehouse['warehouse_name'],
                        'warehouse_id': warehouse['warehouse_id'],
                        'product_id': product['product_id'],
                        'product_sku': product['sku'],
                        'product_name': product['name'],
                        'current_stock': product['current_stock'],
                        'unit_price': product['unit_price'],
                        'total_value': product['total_value'],
                    }
                )

        columns = [
            'warehouse_name',
            'warehouse_id',
            'product_id',
            'product_sku',
            'product_name',
            'current_stock',
            'unit_price',
            'total_value',
        ]
        df = pd.DataFrame(flat_data, columns=columns)
        csv_data = df.to_csv(index=False)
        response = HttpResponse(csv_data, content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="stock_report.csv"'
        return response

    total_company_value = sum(Decimal(str(item['total_value'])) for item in cached_report)
    return Response(
        {
            'summary': cached_report,
            'total_company_value': str(total_company_value),
            'generated_at': timezone.now().isoformat(),
        }
    )