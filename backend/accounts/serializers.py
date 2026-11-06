import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Owner, OwnerOTP, PasswordResetToken


class OwnerPublicSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Owner
        fields = ['id', 'email', 'mobile_number', 'full_name', 'created_at']

    def get_full_name(self, obj):
        return obj.full_name


class OwnerRegisterSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(max_length=50)
    last_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = Owner
        fields = ['email', 'mobile_number', 'first_name', 'last_name', 'password']

    def validate_email(self, value):
        cleaned = (value or '').strip().lower()
        if Owner.objects.filter(email__iexact=cleaned).exists():
            raise serializers.ValidationError('An owner account with this email already exists.')
        return cleaned

    def validate_mobile_number(self, value):
        normalized = re.sub(r'\D', '', value or '')
        if len(normalized) < 10:
            raise serializers.ValidationError('Enter a valid mobile number.')
        if Owner.objects.filter(mobile_number=normalized).exists():
            raise serializers.ValidationError('This mobile number is already linked to another owner account.')
        return normalized

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        return Owner.objects.create_user(password=password, **validated_data)


class OwnerLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = (attrs.get('email') or '').strip().lower()
        password = attrs.get('password')

        user = authenticate(request=self.context.get('request'), username=email, password=password)
        if user is None or not getattr(user, 'is_active', False):
            raise serializers.ValidationError('Invalid email or password.')

        attrs['user'] = user
        return attrs


class OwnerLogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate_refresh(self, value):
        try:
            token = RefreshToken(value)
            token.blacklist()
            return value
        except Exception as exc:
            raise serializers.ValidationError('The refresh token is invalid or expired.') from exc


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return (value or '').strip().lower()

    def save(self, **kwargs):
        email = self.validated_data['email']
        owner = Owner.objects.filter(email__iexact=email).first()
        if not owner:
            return None

        token = kwargs.get('token') or secrets.token_urlsafe(24)
        token_hash = PasswordResetToken.build_hash(token)
        expires_at = timezone.now() + timedelta(hours=1)
        token_obj, _ = PasswordResetToken.objects.get_or_create(
            owner=owner,
            token_hash=token_hash,
            defaults={'expires_at': expires_at},
        )
        if token_obj.expires_at < timezone.now():
            token_obj.expires_at = expires_at
            token_obj.save(update_fields=['expires_at'])
        return token


class ResetPasswordSerializer(serializers.Serializer):
    """Accepts a plain-text reset token and a new password.

    The token is never logged. Validation delegates all security checks
    (expiry, already-used, password strength) to consume_password_reset_token()
    in services.py so the logic lives in exactly one place.
    """
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        # Preliminary length check; full Django password validation happens in the service
        # so we have access to the owner instance there.
        if not value or not value.strip():
            raise serializers.ValidationError('New password must not be blank.')
        return value

    def save(self, **kwargs):
        from .services import consume_password_reset_token
        token = self.validated_data['token']
        new_password = self.validated_data['new_password']
        try:
            consume_password_reset_token(token, new_password)
        except ValueError as exc:
            raise serializers.ValidationError({'token': str(exc)}) from exc


class OTPRequestSerializer(serializers.Serializer):
    mobile_number = serializers.CharField(max_length=15)

    def validate_mobile_number(self, value):
        normalized = re.sub(r'\D', '', value or '')
        if len(normalized) < 10:
            raise serializers.ValidationError('Enter a valid mobile number.')
        return normalized


class OTPVerifySerializer(serializers.Serializer):
    mobile_number = serializers.CharField(max_length=15)
    otp = serializers.CharField(min_length=6, max_length=6)

    def validate(self, attrs):
        mobile_number = re.sub(r'\D', '', attrs.get('mobile_number') or '')
        otp = str(attrs.get('otp') or '')
        owner = Owner.objects.filter(mobile_number=mobile_number).first()
        if not owner:
            raise serializers.ValidationError('No owner account is associated with this mobile number.')

        otp_record = OwnerOTP.objects.filter(owner=owner, mobile_number=mobile_number).order_by('-created_at').first()
        if not otp_record:
            raise serializers.ValidationError('No OTP was requested for this mobile number.')
        if otp_record.is_expired():
            raise serializers.ValidationError('This OTP has expired. Please request a new one.')
        if otp_record.is_used:
            raise serializers.ValidationError('This OTP has already been used.')
        if otp_record.attempt_count >= otp_record.max_attempts:
            raise serializers.ValidationError('Too many OTP attempts. Please request a new code.')

        if otp_record.code_hash != OwnerOTP.build_hash(otp):
            otp_record.attempt_count += 1
            otp_record.save(update_fields=['attempt_count'])
            raise serializers.ValidationError('Invalid OTP code.')

        otp_record.is_used = True
        otp_record.attempt_count += 1
        otp_record.save(update_fields=['is_used', 'attempt_count'])
        attrs['owner'] = owner
        return attrs


class GoogleAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField(required=False, allow_blank=True)
    google_token = serializers.CharField(required=False, allow_blank=True)
    mobile_number = serializers.CharField(required=False, allow_blank=True, max_length=15)

    def validate(self, attrs):
        token = attrs.get('id_token') or attrs.get('google_token')
        if not token:
            raise serializers.ValidationError('Google token is missing.')

        client_id = settings.GOOGLE_CLIENT_ID
        if not client_id:
            raise serializers.ValidationError('Google Sign-In is not configured on the server.')

        try:
            payload = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
        except ValueError as exc:
            raise serializers.ValidationError('Google authentication failed. Please try again.') from exc

        email = payload.get('email')
        if not email:
            raise serializers.ValidationError('Google account email is required to continue.')

        owner = Owner.objects.filter(email__iexact=email).first()
        if owner is None:
            mobile_number = attrs.get('mobile_number') or payload.get('phone_number')
            if not mobile_number:
                raise serializers.ValidationError('A mobile number is required to create an owner account via Google Sign-In.')
            normalized = re.sub(r'\D', '', mobile_number)
            if len(normalized) < 10:
                raise serializers.ValidationError('Enter a valid mobile number.')
            if Owner.objects.filter(mobile_number=normalized).exists():
                raise serializers.ValidationError('This mobile number is already linked to another owner account.')
            owner = Owner.objects.create_user(
                email=email,
                mobile_number=normalized,
                password='GoogleSignInUser@' + str(abs(hash(email)))[:12],
                first_name=payload.get('given_name') or 'Owner',
                last_name=payload.get('family_name') or '',
            )

        attrs['owner'] = owner
        return attrs
