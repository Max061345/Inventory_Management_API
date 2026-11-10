from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Product, Transaction, Warehouse
from .services import get_stock_for_warehouse, get_total_stock

User = get_user_model()


class InventoryAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='admin', email='admin@example.com', password='Password123!')
        self.client.force_authenticate(user=self.user)

        self.warehouse_a = Warehouse.objects.create(
            name='Main Warehouse',
            address='Lviv, Ukraine',
            admin_email='warehouse-admin@example.com',
        )
        self.warehouse_b = Warehouse.objects.create(
            name='Secondary Warehouse',
            address='Kyiv, Ukraine',
            admin_email='second-admin@example.com',
        )

        self.product = Product.objects.create(
            sku='SKU-1001',
            name='Laptop',
            description='Gaming laptop',
            base_price='1200.00',
            min_stock_level=5,
        )

    def test_register_login_and_logout_flow(self):
        client = APIClient()
        register_response = client.post(
            '/api/auth/register/',
            {'username': 'new_employee', 'email': 'new@example.com', 'password': 'StrongPass123!', 'password_confirm': 'StrongPass123!'},
            format='json',
        )
        self.assertEqual(register_response.status_code, 201)

        # Duplicate username rejection
        duplicate_response = client.post(
            '/api/auth/register/',
            {'username': 'new_employee', 'email': 'different@example.com', 'password': 'StrongPass123!', 'password_confirm': 'StrongPass123!'},
            format='json',
        )
        self.assertEqual(duplicate_response.status_code, 400)

        login_response = client.post(
            '/api/auth/login/',
            {'username': 'new_employee', 'password': 'StrongPass123!'},
            format='json',
        )
        self.assertEqual(login_response.status_code, 200)

        logout_response = client.post('/api/auth/logout/', format='json')
        self.assertEqual(logout_response.status_code, 200)

    def test_password_reset_flow(self):
        client = APIClient()
        reset_request = client.post(
            '/api/auth/password-reset/',
            {'email': 'admin@example.com'},
            format='json',
        )
        self.assertEqual(reset_request.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

        email_body = mail.outbox[0].body
        uid = None
        token = None
        for line in email_body.splitlines():
            if line.startswith('UID:'):
                uid = line.replace('UID:', '').strip()
            elif line.startswith('Token:'):
                token = line.replace('Token:', '').strip()

        self.assertIsNotNone(uid)
        self.assertIsNotNone(token)

        confirm_response = client.post(
            '/api/auth/password-reset/confirm/',
            {
                'uid': uid,
                'token': token,
                'password': 'NewSecurePassword123!',
                'password_confirm': 'NewSecurePassword123!',
            },
            format='json',
        )
        self.assertEqual(confirm_response.status_code, 200)

        login_after_reset = client.post(
            '/api/auth/login/',
            {'username': 'admin', 'password': 'NewSecurePassword123!'},
            format='json',
        )
        self.assertEqual(login_after_reset.status_code, 200)

    def test_warehouse_crud_and_stock_aggregation(self):
        create_resp = self.client.post(
            '/api/warehouses/',
            {'name': 'Dnipro Hub', 'address': 'Dnipro, Central Ave', 'admin_email': 'dnipro@example.com'},
            format='json',
        )
        self.assertEqual(create_resp.status_code, 201)
        warehouse_id = create_resp.data['id']

        detail_resp = self.client.get(f'/api/warehouses/{warehouse_id}/')
        self.assertEqual(detail_resp.status_code, 200)
        self.assertIn('inventory', detail_resp.data)

        update_resp = self.client.patch(
            f'/api/warehouses/{warehouse_id}/',
            {'name': 'Dnipro Central Hub'},
            format='json',
        )
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(update_resp.data['name'], 'Dnipro Central Hub')

        delete_resp = self.client.delete(f'/api/warehouses/{warehouse_id}/')
        self.assertEqual(delete_resp.status_code, 204)

    def test_product_soft_delete(self):
        response = self.client.delete(f'/api/products/{self.product.id}/')
        self.assertEqual(response.status_code, 204)

        self.product.refresh_from_db()
        self.assertTrue(self.product.is_deleted)

        list_response = self.client.get('/api/products/')
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data.get('results', list_response.data)), 0)

        # Soft-deleted product should not be accessible in detail view
        detail_response = self.client.get(f'/api/products/{self.product.id}/')
        self.assertEqual(detail_response.status_code, 404)

    def test_product_search_and_price_filtering(self):
        Product.objects.create(
            sku='SKU-KEY-99',
            name='Mechanical Keyboard',
            description='RGB Keyboard',
            base_price='150.00',
            min_stock_level=2,
        )

        search_response = self.client.get('/api/products/?search=Keyboard')
        self.assertEqual(search_response.status_code, 200)
        results = search_response.data.get('results', search_response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['sku'], 'SKU-KEY-99')

        price_filter = self.client.get('/api/products/?min_price=1000')
        self.assertEqual(price_filter.status_code, 200)
        filtered_results = price_filter.data.get('results', price_filter.data)
        self.assertEqual(len(filtered_results), 1)
        self.assertEqual(filtered_results[0]['sku'], 'SKU-1001')

    def test_transaction_in_out_and_transfer_flow(self):
        inbound = self.client.post(
            '/api/transactions/',
            {
                'product': self.product.id,
                'transaction_type': 'IN',
                'quantity': 20,
                'destination_warehouse': self.warehouse_a.id,
            },
            format='json',
        )
        self.assertEqual(inbound.status_code, 201)
        self.assertEqual(get_stock_for_warehouse(self.product, self.warehouse_a), 20)
        self.assertEqual(get_total_stock(self.product), 20)

        # Transfer from A to B
        transfer = self.client.post(
            '/api/transactions/',
            {
                'product': self.product.id,
                'transaction_type': 'TRANSFER',
                'quantity': 8,
                'source_warehouse': self.warehouse_a.id,
                'destination_warehouse': self.warehouse_b.id,
            },
            format='json',
        )
        self.assertEqual(transfer.status_code, 201)
        self.assertEqual(get_stock_for_warehouse(self.product, self.warehouse_a), 12)
        self.assertEqual(get_stock_for_warehouse(self.product, self.warehouse_b), 8)
        self.assertEqual(get_total_stock(self.product), 20)

        # Invalid transfer: exceeding stock
        invalid_transfer = self.client.post(
            '/api/transactions/',
            {
                'product': self.product.id,
                'transaction_type': 'TRANSFER',
                'quantity': 50,
                'source_warehouse': self.warehouse_a.id,
                'destination_warehouse': self.warehouse_b.id,
            },
            format='json',
        )
        self.assertEqual(invalid_transfer.status_code, 400)

        # Valid OUT
        valid_out = self.client.post(
            '/api/transactions/',
            {
                'product': self.product.id,
                'transaction_type': 'OUT',
                'quantity': 2,
                'source_warehouse': self.warehouse_a.id,
            },
            format='json',
        )
        self.assertEqual(valid_out.status_code, 201)
        self.assertEqual(get_stock_for_warehouse(self.product, self.warehouse_a), 10)
        self.assertEqual(get_total_stock(self.product), 18)

    def test_transaction_validation_errors(self):
        # IN with source warehouse provided should fail
        in_with_source = self.client.post(
            '/api/transactions/',
            {
                'product': self.product.id,
                'transaction_type': 'IN',
                'quantity': 5,
                'source_warehouse': self.warehouse_a.id,
                'destination_warehouse': self.warehouse_b.id,
            },
            format='json',
        )
        self.assertEqual(in_with_source.status_code, 400)

        # OUT with destination warehouse provided should fail
        out_with_dest = self.client.post(
            '/api/transactions/',
            {
                'product': self.product.id,
                'transaction_type': 'OUT',
                'quantity': 1,
                'source_warehouse': self.warehouse_a.id,
                'destination_warehouse': self.warehouse_b.id,
            },
            format='json',
        )
        self.assertEqual(out_with_dest.status_code, 400)

        # TRANSFER with same source and destination should fail
        transfer_same = self.client.post(
            '/api/transactions/',
            {
                'product': self.product.id,
                'transaction_type': 'TRANSFER',
                'quantity': 1,
                'source_warehouse': self.warehouse_a.id,
                'destination_warehouse': self.warehouse_a.id,
            },
            format='json',
        )
        self.assertEqual(transfer_same.status_code, 400)

    def test_transaction_filtering_by_warehouse_type_and_date(self):
        now = timezone.now()
        Transaction.objects.create(
            product=self.product,
            transaction_type='IN',
            quantity=10,
            destination_warehouse=self.warehouse_a,
            created_by=self.user,
            transaction_at=now,
        )
        Transaction.objects.create(
            product=self.product,
            transaction_type='OUT',
            quantity=2,
            source_warehouse=self.warehouse_a,
            created_by=self.user,
            transaction_at=now,
        )

        filter_by_type = self.client.get('/api/transactions/?type=IN')
        self.assertEqual(filter_by_type.status_code, 200)
        results = filter_by_type.data.get('results', filter_by_type.data)
        self.assertTrue(all(item['transaction_type'] == 'IN' for item in results))

        filter_by_wh = self.client.get(f'/api/transactions/?warehouse={self.warehouse_a.id}')
        self.assertEqual(filter_by_wh.status_code, 200)
        wh_results = filter_by_wh.data.get('results', filter_by_wh.data)
        self.assertEqual(len(wh_results), 2)

    def test_low_stock_alert_email(self):
        self.product.min_stock_level = 8
        self.product.save(update_fields=['min_stock_level'])

        self.client.post(
            '/api/transactions/',
            {
                'product': self.product.id,
                'transaction_type': 'IN',
                'quantity': 10,
                'destination_warehouse': self.warehouse_a.id,
            },
            format='json',
        )

        with patch('inventory.views.send_mail') as mocked_send_mail:
            response = self.client.post(
                '/api/transactions/',
                {
                    'product': self.product.id,
                    'transaction_type': 'OUT',
                    'quantity': 4,
                    'source_warehouse': self.warehouse_a.id,
                },
                format='json',
            )
            self.assertEqual(response.status_code, 201)
            mocked_send_mail.assert_called_once()

    def test_rate_limit_rejected(self):
        with patch('inventory.views.check_rate_limit', return_value=False):
            response = self.client.post(
                '/api/transactions/',
                {
                    'product': self.product.id,
                    'transaction_type': 'IN',
                    'quantity': 1,
                    'destination_warehouse': self.warehouse_b.id,
                },
                format='json',
            )
            self.assertEqual(response.status_code, 429)

    def test_stock_report_json_and_csv_and_cache_invalidation(self):
        self.client.post(
            '/api/transactions/',
            {
                'product': self.product.id,
                'transaction_type': 'IN',
                'quantity': 15,
                'destination_warehouse': self.warehouse_a.id,
            },
            format='json',
        )

        json_report = self.client.get('/api/reports/stock-summary/')
        self.assertEqual(json_report.status_code, 200)
        self.assertIn('summary', json_report.data)
        self.assertIn('total_company_value', json_report.data)
        self.assertIsNotNone(cache.get('stock_report_summary'))

        # Adding a new transaction must invalidate the cache
        self.client.post(
            '/api/transactions/',
            {
                'product': self.product.id,
                'transaction_type': 'IN',
                'quantity': 5,
                'destination_warehouse': self.warehouse_a.id,
            },
            format='json',
        )
        self.assertIsNone(cache.get('stock_report_summary'))

        csv_report = self.client.get('/api/reports/stock-summary/?format=csv')
        self.assertEqual(csv_report.status_code, 200)
        self.assertEqual(csv_report['Content-Type'], 'text/csv; charset=utf-8')
        content = csv_report.content.decode('utf-8')
        self.assertIn('warehouse_name,warehouse_id,product_id', content)
        self.assertIn('SKU-1001', content)

    def test_product_sorting_by_current_stock_and_price(self):
        cheap_product = Product.objects.create(
            sku='SKU-CHEAP',
            name='Mouse',
            description='Wireless mouse',
            base_price='20.00',
            min_stock_level=1,
        )

        self.client.post(
            '/api/transactions/',
            {
                'product': self.product.id,
                'transaction_type': 'IN',
                'quantity': 5,
                'destination_warehouse': self.warehouse_a.id,
            },
            format='json',
        )
        self.client.post(
            '/api/transactions/',
            {
                'product': cheap_product.id,
                'transaction_type': 'IN',
                'quantity': 50,
                'destination_warehouse': self.warehouse_a.id,
            },
            format='json',
        )

        # Sort by stock descending
        response = self.client.get('/api/products/?ordering=-current_stock')
        self.assertEqual(response.status_code, 200)
        results = response.data.get('results', response.data)
        self.assertEqual(results[0]['sku'], 'SKU-CHEAP')
        self.assertEqual(results[1]['sku'], 'SKU-1001')

        # Sort by price ascending
        price_response = self.client.get('/api/products/?ordering=price')
        self.assertEqual(price_response.status_code, 200)
        price_results = price_response.data.get('results', price_response.data)
        self.assertEqual(price_results[0]['sku'], 'SKU-CHEAP')
        self.assertEqual(price_results[1]['sku'], 'SKU-1001')