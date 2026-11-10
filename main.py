import os
import sys


if __name__ == "__main__":
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inventory_api.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise RuntimeError("Django is not installed or the virtual environment is not active.") from exc
    execute_from_command_line(sys.argv)
