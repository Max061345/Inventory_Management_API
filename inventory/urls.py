from django.urls import path

from .views import (
    ProductViewSet,
    TransactionViewSet,
    WarehouseViewSet,
    confirm_password_reset,
    login_user,
    logout_user,
    register_user,
    request_password_reset,
    stock_report,
)

urlpatterns = [
    path('auth/register/', register_user, name='auth-register'),
    path('auth/login/', login_user, name='auth-login'),
    path('auth/logout/', logout_user, name='auth-logout'),
    path('auth/password-reset/', request_password_reset, name='auth-password-reset'),
    path('auth/password-reset/confirm/', confirm_password_reset, name='auth-password-reset-confirm'),
    path('products/', ProductViewSet.as_view({'get': 'list', 'post': 'create'}), name='products-list'),
    path('products/<int:pk>/', ProductViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='products-detail'),
    path('warehouses/', WarehouseViewSet.as_view({'get': 'list', 'post': 'create'}), name='warehouses-list'),
    path('warehouses/<int:pk>/', WarehouseViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='warehouses-detail'),
    path('transactions/', TransactionViewSet.as_view({'get': 'list', 'post': 'create'}), name='transactions-list'),
    path('transactions/<int:pk>/', TransactionViewSet.as_view({'get': 'retrieve'}), name='transactions-detail'),
    path('reports/stock-summary/', stock_report, name='stock-summary'),    
]
