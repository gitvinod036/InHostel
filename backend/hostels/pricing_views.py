from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


class PricingViewSet(viewsets.ModelViewSet):
    """ViewSet for Pricing entries scoped to the authenticated owner via hostel ownership."""

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        from .models import Pricing
        return Pricing.objects.filter(hostel__owner=self.request.user).select_related('hostel').order_by('sharing_count')

    def get_serializer_class(self):
        from .serializers import PricingSerializer
        return PricingSerializer

    def perform_create(self, serializer):
        # serializer enforces hostel ownership in validate_hostel
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        # No resident allocations exist yet; safe to allow deletion
        return super().destroy(request, *args, **kwargs)
