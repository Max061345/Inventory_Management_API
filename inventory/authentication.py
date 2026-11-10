from rest_framework.authentication import SessionAuthentication


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """
    SessionAuthentication that disables CSRF enforcement for REST API clients (Postman, curl, SPA).
    """

    def enforce_csrf(self, request):
        return