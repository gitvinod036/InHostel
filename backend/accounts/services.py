import secrets
from abc import ABC, abstractmethod
from datetime import timedelta
from random import randint

from django.conf import settings
from django.utils import timezone

from .models import OwnerOTP, PasswordResetToken


class OTPProvider(ABC):
    @abstractmethod
    def send_code(self, owner, mobile_number):
        raise NotImplementedError


class MockOTPProvider(OTPProvider):
    def send_code(self, owner, mobile_number):
        return ''.join(str(randint(0, 9)) for _ in range(6))


def get_otp_provider():
    provider_name = (getattr(settings, 'OTP_PROVIDER', 'mock') or 'mock').lower()
    if provider_name == 'mock':
        return MockOTPProvider()
    return MockOTPProvider()


def generate_otp_code(length=6):
    return ''.join(str(randint(0, 9)) for _ in range(length))


def create_owner_otp(owner, mobile_number):
    code = generate_otp_code()
    expires_at = timezone.now() + timedelta(minutes=getattr(settings, 'OTP_EXPIRES_MINUTES', 5))
    otp_record = OwnerOTP.objects.create(
        owner=owner,
        mobile_number=mobile_number,
        code_hash=OwnerOTP.build_hash(code),
        expires_at=expires_at,
        max_attempts=getattr(settings, 'OTP_MAX_ATTEMPTS', 5),
    )
    return otp_record, code


def verify_owner_otp(owner, mobile_number, candidate_code):
    otp_record = OwnerOTP.objects.filter(owner=owner, mobile_number=mobile_number).order_by('-created_at').first()
    if not otp_record:
        raise ValueError('No OTP was requested for this mobile number.')
    if otp_record.is_used:
        raise ValueError('This OTP has already been used.')
    if otp_record.is_expired():
        raise ValueError('This OTP has expired. Please request a new one.')
    if otp_record.attempt_count >= otp_record.max_attempts:
        raise ValueError('Too many OTP attempts. Please request a new code.')
    if otp_record.code_hash != OwnerOTP.build_hash(candidate_code):
        otp_record.attempt_count += 1
        otp_record.save(update_fields=['attempt_count'])
        raise ValueError('Invalid OTP code.')

    otp_record.is_used = True
    otp_record.attempt_count += 1
    otp_record.save(update_fields=['is_used', 'attempt_count'])
    return True


def create_password_reset_token(owner):
    token = secrets.token_urlsafe(24)
    token_hash = PasswordResetToken.build_hash(token)
    expires_at = timezone.now() + timedelta(hours=1)
    token_obj, created = PasswordResetToken.objects.get_or_create(
        owner=owner,
        token_hash=token_hash,
        defaults={'expires_at': expires_at},
    )
    if not created:
        token_obj.expires_at = expires_at
        token_obj.save(update_fields=['expires_at'])
    return token


def consume_password_reset_token(token: str, new_password: str) -> None:
    """Validate a plain-text reset token, set the owner's new password, and mark the token used.

    Raises ValueError with a safe message on any validation failure.
    The raw token value is never stored or logged — only its SHA-256 hash is compared.
    """
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError

    token_hash = PasswordResetToken.build_hash(token)
    try:
        token_obj = PasswordResetToken.objects.select_related('owner').get(token_hash=token_hash)
    except PasswordResetToken.DoesNotExist:
        raise ValueError('This password reset link is invalid.')

    if token_obj.used_at is not None:
        raise ValueError('This password reset link has already been used.')

    if token_obj.is_expired():
        raise ValueError('This password reset link has expired. Please request a new one.')

    try:
        validate_password(new_password, user=token_obj.owner)
    except DjangoValidationError as exc:
        raise ValueError(' '.join(exc.messages)) from exc

    owner = token_obj.owner
    owner.set_password(new_password)
    owner.save(update_fields=['password', 'updated_at'])

    token_obj.used_at = timezone.now()
    token_obj.save(update_fields=['used_at'])
