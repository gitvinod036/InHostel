import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models


def add_months_same_day(value_date, months):
    month_index = value_date.year * 12 + (value_date.month - 1) + months
    year = month_index // 12
    month = month_index % 12 + 1
    day = min(value_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def get_billing_cycle_for_date(joining_date, target_date):
    start = joining_date
    while add_months_same_day(start, 1) <= target_date:
        start = add_months_same_day(start, 1)
    end = add_months_same_day(start, 1) - timedelta(days=1)
    next_due_date = add_months_same_day(start, 1)
    return start, end, next_due_date


def get_resident_monthly_fee(resident):
    pricing = resident.hostel.pricings.order_by('sharing_count').first()
    if pricing is None:
        return Decimal('0.00')
    return pricing.monthly_amount


class Hostel(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hostels')
    hostel_name = models.CharField(max_length=255)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'hostels'
        indexes = [models.Index(fields=['owner']), models.Index(fields=['hostel_name'])]

    def __str__(self):
        return f"{self.hostel_name} ({self.owner})"


class Floor(models.Model):
    hostel = models.ForeignKey(Hostel, on_delete=models.CASCADE, related_name='floors')
    floor_number = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'floors'
        unique_together = (('hostel', 'floor_number'),)
        indexes = [models.Index(fields=['hostel', 'floor_number'])]

    def __str__(self):
        return f"{self.hostel} - Floor {self.floor_number}"


class Room(models.Model):
    floor = models.ForeignKey(Floor, on_delete=models.CASCADE, related_name='rooms')
    room_number = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rooms'
        unique_together = (('floor', 'room_number'),)
        indexes = [models.Index(fields=['floor', 'room_number'])]

    def __str__(self):
        return f"{self.floor} - Room {self.room_number}"


class Cot(models.Model):
    STATUS_AVAILABLE = 'AVAILABLE'
    STATUS_OCCUPIED = 'OCCUPIED'
    STATUS_CHOICES = [(STATUS_AVAILABLE, 'Available'), (STATUS_OCCUPIED, 'Occupied')]

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='cots')
    cot_number = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_AVAILABLE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'cots'
        unique_together = (('room', 'cot_number'),)
        indexes = [models.Index(fields=['room', 'cot_number']), models.Index(fields=['status'])]

    def __str__(self):
        return f"{self.room} - Cot {self.cot_number} ({self.status})"


class Pricing(models.Model):
    """Sharing pricing for a hostel.

    Pricing is owned by the hostel's owner via the hostel FK. Each (hostel, sharing_count)
    must be unique. Amount stored as Decimal to avoid floating-point issues.
    """
    hostel = models.ForeignKey(Hostel, on_delete=models.CASCADE, related_name='pricings')
    sharing_count = models.PositiveIntegerField()
    monthly_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pricing'
        unique_together = (('hostel', 'sharing_count'),)
        indexes = [models.Index(fields=['hostel', 'sharing_count'])]

    def __str__(self):
        return f"{self.hostel} - {self.sharing_count} sharing: {self.monthly_amount}"


class RegistrationToken(models.Model):
    """Secure registration token for public resident registration links.

    Each token is tied to a hostel and can be revoked. Token value is a URL-safe
    random string and should not expose any sequential IDs.
    """
    hostel = models.ForeignKey(Hostel, on_delete=models.CASCADE, related_name='registration_tokens')
    token = models.CharField(max_length=128, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked = models.BooleanField(default=False)

    class Meta:
        db_table = 'registration_tokens'

    def __str__(self):
        return f"Token for {self.hostel} ({'revoked' if self.revoked else 'active'})"


class Resident(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_VACATED = 'VACATED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_VACATED, 'Vacated'),
    ]

    hostel = models.ForeignKey(Hostel, on_delete=models.CASCADE, related_name='residents')
    full_name = models.CharField(max_length=255)
    mobile_number = models.CharField(max_length=30)
    alternate_mobile_number = models.CharField(max_length=30, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    joining_date = models.DateField()
    id_proof = models.FileField(upload_to='residents/id_proofs/')
    photo = models.FileField(upload_to='residents/photos/')
    address = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    assigned_cot = models.OneToOneField(
        'Cot',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_resident',
        db_index=True,
    )
    vacated_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'residents'
        indexes = [models.Index(fields=['hostel']), models.Index(fields=['mobile_number']), models.Index(fields=['status']), models.Index(fields=['assigned_cot'])]

    def __str__(self):
        return f"{self.full_name} @ {self.hostel} ({self.status})"


class Payment(models.Model):
    PAYMENT_METHOD_CASH = 'CASH'
    PAYMENT_METHOD_UPI = 'UPI'
    PAYMENT_METHOD_BANK_TRANSFER = 'BANK_TRANSFER'
    PAYMENT_METHOD_OTHER = 'OTHER'
    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_CASH, 'Cash'),
        (PAYMENT_METHOD_UPI, 'UPI'),
        (PAYMENT_METHOD_BANK_TRANSFER, 'Bank Transfer'),
        (PAYMENT_METHOD_OTHER, 'Other'),
    ]

    STATUS_PAID = 'PAID'
    STATUS_PARTIAL = 'PARTIAL'
    STATUS_CHOICES = [
        (STATUS_PAID, 'Paid'),
        (STATUS_PARTIAL, 'Partial'),
    ]

    resident = models.ForeignKey(Resident, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField()
    advance_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    late_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHOD_CHOICES)
    reference = models.CharField(max_length=255, blank=True, default='')
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PARTIAL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments'
        indexes = [
            models.Index(fields=['resident', 'payment_date']),
            models.Index(fields=['resident', 'status']),
            models.Index(fields=['payment_method']),
        ]

    def __str__(self):
        return f"Payment for {self.resident} - {self.amount} ({self.status})"