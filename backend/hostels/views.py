from datetime import date

from django.db import transaction
from django.db.models import Sum
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Hostel, Floor, Room, Cot, Resident, Payment, get_billing_cycle_for_date, get_resident_monthly_fee
from .serializers import HostelSerializer, FloorSerializer, RoomSerializer, CotSerializer
from rest_framework.decorators import action
from .serializers import PricingSerializer, ResidentSerializer, PublicResidentCreateSerializer, PaymentSerializer
from .services import send_registration_email


class HostelViewSet(viewsets.ModelViewSet):
    serializer_class = HostelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Hostel.objects.filter(owner=self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=False, methods=['get'], url_path='dashboard')
    def dashboard(self, request):
        hostels = self.get_queryset().prefetch_related('residents', 'floors__rooms__cots')
        hostel_stats = []
        total_residents = 0
        total_active = 0
        total_pending = 0
        total_vacated = 0
        total_available_cots = 0
        total_occupied_cots = 0

        for hostel in hostels:
            residents = hostel.residents.all()
            hostel_total = residents.count()
            hostel_active = residents.filter(status=Resident.STATUS_ACTIVE).count()
            hostel_pending = residents.filter(status=Resident.STATUS_PENDING).count()
            hostel_vacated = residents.filter(status=Resident.STATUS_VACATED).count()
            available_cots = hostel.floors.filter(rooms__cots__status=Cot.STATUS_AVAILABLE).count()
            occupied_cots = hostel.floors.filter(rooms__cots__status=Cot.STATUS_OCCUPIED).count()

            total_residents += hostel_total
            total_active += hostel_active
            total_pending += hostel_pending
            total_vacated += hostel_vacated
            total_available_cots += available_cots
            total_occupied_cots += occupied_cots

            hostel_stats.append({
                'id': hostel.id,
                'hostel_name': hostel.hostel_name,
                'floor_count': hostel.floors.count(),
                'total_residents': hostel_total,
                'active_residents': hostel_active,
                'pending_residents': hostel_pending,
                'vacated_residents': hostel_vacated,
                'available_cots': available_cots,
                'occupied_cots': occupied_cots,
            })

        return Response({
            'hostels': hostel_stats,
            'summary': {
                'total_residents': total_residents,
                'active_residents': total_active,
                'pending_residents': total_pending,
                'vacated_residents': total_vacated,
                'available_cots': total_available_cots,
                'occupied_cots': total_occupied_cots,
            },
        })

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # prevent deletion if any occupied cot exists in hostel
        occupied = Cot.objects.filter(room__floor__hostel=instance, status=Cot.STATUS_OCCUPIED).exists()
        if occupied:
            return Response({'detail': 'Cannot delete hostel with occupied cots.'}, status=status.HTTP_400_BAD_REQUEST)
        # allow deletion (will cascade delete floors/rooms/cots)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['get', 'post'])
    def registration_link(self, request, pk=None):
        """GET: retrieve existing token or create one; POST: regenerate token (revoke old)
        Only the owner of the hostel may call this (get_queryset is owner-scoped).
        """
        instance = self.get_object()
        from .models import RegistrationToken
        if request.method == 'GET':
            token = RegistrationToken.objects.filter(hostel=instance, revoked=False).order_by('-created_at').first()
            if token:
                return Response({'token': token.token, 'created_at': token.created_at})
            # create one
            import secrets
            token_val = secrets.token_urlsafe(32)
            token = RegistrationToken.objects.create(hostel=instance, token=token_val)
            return Response({'token': token.token, 'created_at': token.created_at})
        else:
            # POST -> regenerate: revoke existing and create new
            RegistrationToken.objects.filter(hostel=instance, revoked=False).update(revoked=True)
            import secrets
            token_val = secrets.token_urlsafe(32)
            token = RegistrationToken.objects.create(hostel=instance, token=token_val)
            return Response({'token': token.token, 'created_at': token.created_at}, status=status.HTTP_201_CREATED)


class FloorViewSet(viewsets.ModelViewSet):
    serializer_class = FloorSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Floor.objects.filter(hostel__owner=self.request.user).select_related('hostel').order_by('floor_number')

    def perform_create(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # prevent deletion if room contains occupied cots
        occupied = Cot.objects.filter(room__floor=instance, status=Cot.STATUS_OCCUPIED).exists()
        if occupied:
            return Response({'detail': 'Cannot delete floor with occupied cots.'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


class RoomViewSet(viewsets.ModelViewSet):
    serializer_class = RoomSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Room.objects.filter(floor__hostel__owner=self.request.user).select_related('floor', 'floor__hostel').order_by('room_number')

    def perform_create(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        occupied = Cot.objects.filter(room=instance, status=Cot.STATUS_OCCUPIED).exists()
        if occupied:
            return Response({'detail': 'Cannot delete room with occupied cots.'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


class CotViewSet(viewsets.ModelViewSet):
    serializer_class = CotSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Cot.objects.filter(room__floor__hostel__owner=self.request.user).select_related('room', 'room__floor').order_by('cot_number')

    def perform_create(self, serializer):
        # default status should be handled by model default
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status == Cot.STATUS_OCCUPIED:
            return Response({'detail': 'Cannot delete an occupied cot.'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


class PricingViewSet(viewsets.ModelViewSet):
    serializer_class = None  # set dynamically
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        from .models import Pricing
        return Pricing.objects.filter(hostel__owner=self.request.user).select_related('hostel').order_by('sharing_count')

    def get_serializer_class(self):
        from .serializers import PricingSerializer
        return PricingSerializer

    def perform_create(self, serializer):
        # ensure hostel ownership is enforced in serializer.validate_hostel
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        # no resident allocation exists yet; safe to allow deletion
        instance = self.get_object()
        return super().destroy(request, *args, **kwargs)


class ResidentViewSet(viewsets.ModelViewSet):
    serializer_class = None
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        from .models import Resident
        return Resident.objects.filter(hostel__owner=self.request.user).select_related('hostel', 'assigned_cot', 'assigned_cot__room', 'assigned_cot__room__floor').order_by('-created_at')

    def get_serializer_class(self):
        from .serializers import ResidentSerializer
        return ResidentSerializer

    def perform_create(self, serializer):
        # owner-side creation (rare); owner must set hostel (validated)
        serializer.save()

    def partial_update(self, request, *args, **kwargs):
        # allow owner to update status to ACTIVE when confirming
        return super().partial_update(request, *args, **kwargs)

    @action(detail=True, methods=['get'], url_path='allocation')
    def available_cots(self, request, pk=None):
        resident = self.get_object()
        cots = (
            Cot.objects.filter(room__floor__hostel=resident.hostel, status=Cot.STATUS_AVAILABLE)
            .select_related('room', 'room__floor', 'room__floor__hostel')
            .order_by('room__floor__floor_number', 'room__room_number', 'cot_number')
        )
        payload = []
        for cot in cots:
            payload.append({
                'id': cot.id,
                'cot_number': cot.cot_number,
                'status': cot.status,
                'floor': {'id': cot.room.floor.id, 'floor_number': cot.room.floor.floor_number},
                'room': {'id': cot.room.id, 'room_number': cot.room.room_number},
            })
        return Response({'resident_id': resident.id, 'hostel_id': resident.hostel.id, 'available_cots': payload})

    @action(detail=True, methods=['post'], url_path='vacate')
    def vacate(self, request, pk=None):
        resident = self.get_object()
        if resident.hostel.owner != request.user:
            return Response({'detail': 'Resident does not belong to the authenticated owner.'}, status=status.HTTP_403_FORBIDDEN)
        if resident.status != Resident.STATUS_ACTIVE:
            return Response({'detail': 'Only active residents can be vacated.'}, status=status.HTTP_400_BAD_REQUEST)
        if resident.assigned_cot_id is None:
            return Response({'detail': 'Resident has no active cot assignment.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                resident = Resident.objects.select_for_update().get(pk=resident.pk)
                cot = resident.assigned_cot
                if cot is None:
                    raise ValueError('Resident has no active cot assignment.')
                cot = Cot.objects.select_for_update().get(pk=cot.pk)

                resident.assigned_cot = None
                resident.status = Resident.STATUS_VACATED
                resident.vacated_date = date.today()
                resident.save(update_fields=['assigned_cot', 'status', 'vacated_date', 'updated_at'])

                cot.status = Cot.STATUS_AVAILABLE
                cot.save(update_fields=['status', 'updated_at'])
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Cot.DoesNotExist:
            return Response({'detail': 'Assigned cot not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'detail': 'Resident vacated successfully.',
            'resident_id': resident.id,
            'status': resident.status,
            'vacated_date': resident.vacated_date.isoformat(),
            'cot_id': cot.id,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='allocate')
    def allocate(self, request, pk=None):
        resident = self.get_object()
        cot_id = request.data.get('cot_id') or request.data.get('cot')
        if cot_id in (None, ''):
            return Response({'detail': 'cot_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        if resident.assigned_cot_id is not None or resident.status == resident.STATUS_ACTIVE:
            return Response({'detail': 'Resident already has an active cot allocation.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                resident = Resident.objects.select_for_update().get(pk=resident.pk)
                cot = Cot.objects.select_for_update().get(pk=cot_id)

                if cot.room.floor.hostel.owner != request.user:
                    return Response({'detail': 'Cot does not belong to the authenticated owner.'}, status=status.HTTP_400_BAD_REQUEST)
                if resident.hostel_id != cot.room.floor.hostel_id:
                    return Response({'detail': 'Resident and cot must belong to the same hostel.'}, status=status.HTTP_400_BAD_REQUEST)
                if resident.assigned_cot_id is not None or resident.status == resident.STATUS_ACTIVE:
                    return Response({'detail': 'Resident already has an active cot allocation.'}, status=status.HTTP_400_BAD_REQUEST)
                if cot.status != Cot.STATUS_AVAILABLE:
                    return Response({'detail': 'Selected cot is not available.'}, status=status.HTTP_400_BAD_REQUEST)
                if Resident.objects.filter(assigned_cot=cot).exclude(pk=resident.pk).exists():
                    return Response({'detail': 'Selected cot is already allocated.'}, status=status.HTTP_400_BAD_REQUEST)

                resident.assigned_cot = cot
                resident.status = resident.STATUS_ACTIVE
                resident.save(update_fields=['assigned_cot', 'status', 'updated_at'])

                cot.status = Cot.STATUS_OCCUPIED
                cot.save(update_fields=['status', 'updated_at'])
        except Cot.DoesNotExist:
            return Response({'detail': 'Cot not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'detail': 'Resident allocated to cot successfully.',
            'resident_id': resident.id,
            'cot_id': cot.id,
            'status': resident.status,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='payments')
    def payment_history(self, request, pk=None):
        resident = self.get_object()
        payments = Payment.objects.filter(resident=resident).order_by('-payment_date', '-created_at')
        serializer = PaymentSerializer(payments, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='billing')
    def billing_info(self, request, pk=None):
        resident = self.get_object()
        as_of = request.GET.get('as_of')
        target_date = date.fromisoformat(as_of) if as_of else date.today()
        billing_start, billing_end, next_due_date = get_billing_cycle_for_date(resident.joining_date, target_date)
        total_paid = Payment.objects.filter(resident=resident).aggregate(total_paid=Sum('amount'))['total_paid'] or 0
        due_amount = get_resident_monthly_fee(resident)
        payload = {
            'resident_id': resident.id,
            'hostel_id': resident.hostel_id,
            'monthly_fee': str(get_resident_monthly_fee(resident)),
            'billing_period_start': billing_start.isoformat(),
            'billing_period_end': billing_end.isoformat(),
            'next_due_date': next_due_date.isoformat(),
            'total_paid': str(total_paid),
            'balance_due': str(due_amount - total_paid),
        }
        return Response(payload)


class PaymentViewSet(viewsets.ModelViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Payment.objects.filter(resident__hostel__owner=self.request.user).select_related('resident', 'resident__hostel').order_by('-payment_date', '-created_at')

    def perform_create(self, serializer):
        serializer.save()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()
        headers = self.get_success_headers(serializer.data)
        return Response(PaymentSerializer(payment, context={'request': request}).data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=False, methods=['get'], url_path='history')
    def payment_history(self, request):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


def _wants_html(request):
    accept = request.META.get('HTTP_ACCEPT', '')
    return 'text/html' in accept and 'application/json' not in accept


class PublicRegistrationView(APIView):
    """Endpoint for public resident registration using a secure token.

    URL: /register/<token>/ or /api/v1/register/<token>/
    GET  — renders the HTML registration form (register.html) for web browsers, or returns token status for JSON.
    POST — accepts multipart form data and creates a PENDING Resident (renders success HTML or returns JSON).
    """
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, token):
        from .models import RegistrationToken
        try:
            rt = RegistrationToken.objects.select_related('hostel').get(token=token, revoked=False)
        except RegistrationToken.DoesNotExist:
            if _wants_html(request):
                return render(request, 'hostels/invalid_token.html', {
                    'error_message': 'This registration link is invalid or has been revoked.',
                }, status=400)
            return Response({'detail': 'Invalid or expired registration link.'}, status=status.HTTP_400_BAD_REQUEST)

        if _wants_html(request):
            return render(request, 'hostels/register.html', {
                'hostel': rt.hostel,
                'token': token,
                'today_date': _date.today().isoformat(),
                'form_errors': {},
                'form_data': {},
            }, status=200)

        return Response({
            'valid': True,
            'hostel': {
                'id': rt.hostel.id,
                'hostel_name': rt.hostel.hostel_name,
                'address': rt.hostel.address,
            },
        }, status=status.HTTP_200_OK)

    def post(self, request, token):
        from .models import RegistrationToken, Resident
        from .serializers import PublicResidentCreateSerializer
        # validate token
        try:
            rt = RegistrationToken.objects.select_related('hostel').get(token=token, revoked=False)
        except RegistrationToken.DoesNotExist:
            if _wants_html(request):
                return render(request, 'hostels/invalid_token.html', {
                    'error_message': 'This registration link is invalid or has been revoked.',
                }, status=400)
            return Response({'detail': 'Invalid or expired registration link.'}, status=status.HTTP_400_BAD_REQUEST)

        hostel = rt.hostel
        serializer = PublicResidentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            if _wants_html(request):
                formatted_errors = {}
                for field, errs in serializer.errors.items():
                    formatted_errors[field] = errs[0] if isinstance(errs, list) and errs else str(errs)
                return render(request, 'hostels/register.html', {
                    'hostel': hostel,
                    'token': token,
                    'today_date': _date.today().isoformat(),
                    'form_errors': formatted_errors,
                    'form_data': request.data,
                }, status=400)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # save resident associated with hostel
        data = serializer.validated_data
        resident = Resident.objects.create(
            hostel=hostel,
            full_name=data.get('full_name'),
            mobile_number=data.get('mobile_number'),
            alternate_mobile_number=data.get('alternate_mobile_number'),
            email=data.get('email'),
            joining_date=data.get('joining_date'),
            address=data.get('address', ''),
            id_proof=data.get('id_proof'),
            photo=data.get('photo'),
            status=Resident.STATUS_PENDING,
        )
        # trigger email notification (do not fail on email errors)
        try:
            send_registration_email(resident)
        except Exception:
            pass

        if _wants_html(request):
            return render(request, 'hostels/registration_success.html', {
                'hostel': hostel,
                'resident': resident,
            }, status=201)

        from .serializers import ResidentSerializer
        out = ResidentSerializer(resident, context={'request': request})
        return Response(out.data, status=status.HTTP_201_CREATED)
