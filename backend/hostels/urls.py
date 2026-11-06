from rest_framework.routers import DefaultRouter
from .views import HostelViewSet, FloorViewSet, RoomViewSet, CotViewSet, PublicRegistrationView, ResidentViewSet, PaymentViewSet
from .pricing_views import PricingViewSet

router = DefaultRouter()
router.register(r'hostels', HostelViewSet, basename='hostel')
router.register(r'floors', FloorViewSet, basename='floor')
router.register(r'rooms', RoomViewSet, basename='room')
router.register(r'cots', CotViewSet, basename='cot')
router.register(r'pricing', PricingViewSet, basename='pricing')
router.register(r'residents', ResidentViewSet, basename='resident')
router.register(r'payments', PaymentViewSet, basename='payment')

from django.urls import path

urlpatterns = router.urls + [
    path('register/<str:token>/', PublicRegistrationView.as_view(), name='public-register'),
]
