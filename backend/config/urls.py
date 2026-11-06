from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from hostels.views import PublicRegistrationView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('register/<str:token>/', PublicRegistrationView.as_view(), name='public-register-root'),
    path('api/v1/', include('health.urls')),
    path('api/v1/auth/', include('accounts.urls')),
    path('api/v1/', include('hostels.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
