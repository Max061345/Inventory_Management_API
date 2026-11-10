# Inventory Management API

REST API for warehouse inventory management built with Django, Django REST Framework, PostgreSQL, Redis and Docker Compose.

## Features
- Employee registration, login/logout using Django session authentication
- Password reset via email
- CRUD for products and warehouses
- Soft delete for products
- Inventory movement transactions: IN, OUT, TRANSFER
- Dynamic stock calculation from transaction history without storing stock as a static field
- Redis-based rate limiting for transactions (50 per minute per employee)
- Cached company-wide stock summary report
- Search, filtering, sorting and pagination for products and transactions
- Export of stock report in JSON and CSV
- Low-stock email notification for warehouse admins

## Stack
- Django 6.x
- Django REST Framework
- PostgreSQL
- Redis
- Django Filter
- Pandas

## Local launch

1. Create and activate virtual environment
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   ```
2. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```
3. Apply migrations
   ```bash
   python main.py migrate
   ```
4. Start the server
   ```bash
   python main.py runserver 0.0.0.0:8000
   ```

## Docker Compose

Create a `.env` file in the project root (or copy `.env.example`) and set the
secret and database credentials before starting the services:

```bash
copy .env.example .env
docker compose up --build
```

Docker Compose reads `.env` for configuration. PostgreSQL's `POSTGRES_*`
variables are passed only to the `db` service; `web` receives a `DATABASE_URL`
connection string and does not receive those individual variables.

The API will be available at http://localhost:8000/api/.

## Main endpoints
- Auth: `/api/auth/register/`, `/api/auth/login/`, `/api/auth/logout/`
- Products: `/api/products/`
- Warehouses: `/api/warehouses/`
- Transactions: `/api/transactions/`
- Reports: `/api/reports/stock-summary/`

## Test run

```bash
python main.py test inventory
```
