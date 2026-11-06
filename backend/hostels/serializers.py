from rest_framework import serializers
from .models import Hostel, Floor, Room, Cot, Resident


class HostelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hostel
        fields = ['id', 'hostel_name', 'address', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        request = self.context.get('request')
        if request and request.method in ('POST',):
            owner = request.user
            existing = Hostel.objects.filter(owner=owner).count()
            max_hostels = 2
            if existing >= max_hostels:
                raise serializers.ValidationError({'non_field_errors': [f'You can manage up to {max_hostels} hostels.']})
        return attrs


class FloorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Floor
        fields = ['id', 'hostel', 'floor_number', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_hostel(self, value):
        request = self.context.get('request')
        if value.owner != request.user:
            raise serializers.ValidationError('Hostel does not belong to the authenticated owner.')
        return value

    def validate(self, attrs):
        hostel = attrs.get('hostel')
        floor_number = attrs.get('floor_number')
        if hostel and floor_number:
            if Floor.objects.filter(hostel=hostel, floor_number=floor_number).exists():
                raise serializers.ValidationError({'floor_number': 'A floor with this identifier already exists in the hostel.'})
        return attrs


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ['id', 'floor', 'room_number', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_floor(self, value):
        request = self.context.get('request')
        if value.hostel.owner != request.user:
            raise serializers.ValidationError('Floor does not belong to the authenticated owner.')
        return value

    def validate(self, attrs):
        floor = attrs.get('floor')
        room_number = attrs.get('room_number')
        if floor and room_number:
            if Room.objects.filter(floor=floor, room_number=room_number).exists():
                raise serializers.ValidationError({'room_number': 'A room with this identifier already exists on the floor.'})
        return attrs


class CotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cot
        fields = ['id', 'room', 'cot_number', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_room(self, value):
        request = self.context.get('request')
        if value.floor.hostel.owner != request.user:
            raise serializers.ValidationError('Room does not belong to the authenticated owner.')
        return value

    def validate(self, attrs):
        room = attrs.get('room')
        cot_number = attrs.get('cot_number')
        if room and cot_number:
            if Cot.objects.filter(room=room, cot_number=cot_number).exists():
                raise serializers.ValidationError({'cot_number': 'A cot with this identifier already exists in the room.'})
        return attrs


class PricingSerializer(serializers.ModelSerializer):
    class Meta:
        model = None  # set dynamically in __init__
        fields = ['id', 'hostel', 'sharing_count', 'monthly_amount', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def __init__(self, *args, **kwargs):
        from .models import Pricing
        super().__init__(*args, **kwargs)
        self.Meta.model = Pricing

    def validate_hostel(self, value):
        request = self.context.get('request')
        if value.owner != request.user:
            raise serializers.ValidationError('Hostel does not belong to the authenticated owner.')
        return value

    def validate_sharing_count(self, value):
        if not isinstance(value, int) or value < 1:
            raise serializers.ValidationError('Sharing count must be an integer >= 1.')
        return value

    def validate_monthly_amount(self, value):
        try:
            if value <= 0:
                raise serializers.ValidationError('Monthly amount must be greater than zero.')
        except TypeError:
            raise serializers.ValidationError('Invalid monetary value.')
        return value

    def validate(self, attrs):
        hostel = attrs.get('hostel')
        sharing_count = attrs.get('sharing_count')
        if hostel and sharing_count:
            from .models import Pricing
            qs = Pricing.objects.filter(hostel=hostel, sharing_count=sharing_count)
            instance = getattr(self, 'instance', None)
            if instance:
                qs = qs.exclude(pk=instance.pk)
            if qs.exists():
                raise serializers.ValidationError({'sharing_count': 'A pricing entry for this sharing count already exists for the hostel.'})
        return attrs


class AssignedCotSerializer(serializers.Serializer):
    """Read-only nested representation of a resident's assigned cot.

    Returned inside ResidentSerializer so the mobile client gets structured
    cot/room/floor info instead of a bare integer PK.
    """
    id = serializers.IntegerField(read_only=True)
    cot_number = serializers.CharField(read_only=True)
    room_number = serializers.SerializerMethodField()
    floor_number = serializers.SerializerMethodField()

    def get_room_number(self, obj):
        return obj.room.room_number if obj.room else None

    def get_floor_number(self, obj):
        return obj.room.floor.floor_number if obj.room and obj.room.floor else None


class ResidentSerializer(serializers.ModelSerializer):
    assigned_cot = AssignedCotSerializer(read_only=True, allow_null=True)

    class Meta:
        model = None
        fields = ['id', 'hostel', 'full_name', 'mobile_number', 'alternate_mobile_number', 'email', 'joining_date', 'address', 'id_proof', 'photo', 'status', 'assigned_cot', 'vacated_date', 'created_at', 'updated_at']
        read_only_fields = ['id', 'assigned_cot', 'vacated_date', 'created_at', 'updated_at']

    def __init__(self, *args, **kwargs):
        from .models import Resident
        super().__init__(*args, **kwargs)
        self.Meta.model = Resident

    def validate_hostel(self, value):
        request = self.context.get('request')
        if value.owner != request.user:
            raise serializers.ValidationError('Hostel does not belong to the authenticated owner.')
        return value


class PublicResidentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = None
        fields = ['full_name', 'mobile_number', 'alternate_mobile_number', 'email', 'joining_date', 'address', 'id_proof', 'photo']

    def __init__(self, *args, **kwargs):
        from .models import Resident
        super().__init__(*args, **kwargs)
        self.Meta.model = Resident

    def validate_mobile_number(self, value):
        if not value or not value.isdigit():
            raise serializers.ValidationError('Invalid mobile number.')
        return value

    def validate_joining_date(self, value):
        # Basic validation: joining date must be a date instance and not in the future
        from datetime import date
        if value > date.today():
            raise serializers.ValidationError('Joining date cannot be in the future.')
        return value

    def validate_id_proof(self, file):
        # validate file type and size (max 10MB)
        allowed = ['image/jpeg', 'image/png', 'application/pdf']
        content_type = getattr(file, 'content_type', None)
        if content_type not in allowed:
            raise serializers.ValidationError('ID proof must be JPG/PNG or PDF.')
        if file.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('ID proof must be <= 10MB.')
        return file

    def validate_photo(self, file):
        allowed = ['image/jpeg', 'image/png']
        content_type = getattr(file, 'content_type', None)
        if content_type not in allowed:
            raise serializers.ValidationError('Photo must be JPG/PNG.')
        if file.size > 5 * 1024 * 1024:
            raise serializers.ValidationError('Photo must be <= 5MB.')
        return file

    def validate(self, attrs):
        # basic duplicates check: same mobile + hostel via token context handled in view
        return attrs


class PaymentSerializer(serializers.ModelSerializer):
    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.all())

    class Meta:
        model = None
        fields = [
            'id', 'resident', 'amount', 'payment_date', 'advance_amount', 'late_fee',
            'payment_method', 'reference', 'billing_period_start', 'billing_period_end',
            'status', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'billing_period_start', 'billing_period_end', 'status', 'created_at', 'updated_at']

    def __init__(self, *args, **kwargs):
        from .models import Payment
        super().__init__(*args, **kwargs)
        self.Meta.model = Payment

    def validate_resident(self, value):
        request = self.context.get('request')
        if request and value.hostel.owner != request.user:
            raise serializers.ValidationError('Resident does not belong to the authenticated owner.')
        return value

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value

    def validate_advance_amount(self, value):
        if value < 0:
            raise serializers.ValidationError('Advance amount cannot be negative.')
        return value

    def validate_late_fee(self, value):
        if value < 0:
            raise serializers.ValidationError('Late fee cannot be negative.')
        return value

    def validate(self, attrs):
        resident = attrs.get('resident')
        amount = attrs.get('amount')
        payment_date = attrs.get('payment_date')
        advance_amount = attrs.get('advance_amount', 0)
        late_fee = attrs.get('late_fee', 0)

        if resident is None or amount is None or payment_date is None:
            return attrs

        if resident.hostel.owner != self.context.get('request').user:
            raise serializers.ValidationError({'resident': 'Resident does not belong to the authenticated owner.'})

        if amount <= 0:
            raise serializers.ValidationError({'amount': 'Amount must be greater than zero.'})
        if advance_amount < 0:
            raise serializers.ValidationError({'advance_amount': 'Advance amount cannot be negative.'})
        if late_fee < 0:
            raise serializers.ValidationError({'late_fee': 'Late fee cannot be negative.'})

        from .models import get_billing_cycle_for_date, get_resident_monthly_fee
        billing_start, billing_end, _ = get_billing_cycle_for_date(resident.joining_date, payment_date)
        attrs['billing_period_start'] = billing_start
        attrs['billing_period_end'] = billing_end

        due_amount = get_resident_monthly_fee(resident) + late_fee - advance_amount
        if due_amount < 0:
            due_amount = 0
        attrs['status'] = 'PAID' if amount >= due_amount else 'PARTIAL'
        return attrs

    def create(self, validated_data):
        from .models import get_billing_cycle_for_date, get_resident_monthly_fee
        resident = validated_data['resident']
        payment_date = validated_data['payment_date']
        advance_amount = validated_data.get('advance_amount', 0)
        late_fee = validated_data.get('late_fee', 0)
        billing_start, billing_end, _ = get_billing_cycle_for_date(resident.joining_date, payment_date)
        validated_data['billing_period_start'] = billing_start
        validated_data['billing_period_end'] = billing_end

        due_amount = get_resident_monthly_fee(resident) + late_fee - advance_amount
        if due_amount < 0:
            due_amount = 0
        validated_data['status'] = 'PAID' if validated_data['amount'] >= due_amount else 'PARTIAL'
        return super().create(validated_data)