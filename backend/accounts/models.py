import hashlib
import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from .managers import OwnerManager


class Owner(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    mobile_number = models.CharField(max_length=15, unique=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OwnerManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['mobile_number', 'first_name', 'last_name']

    class Meta:
        db_table = 'owners'
        indexes = [models.Index(fields=['email']), models.Index(fields=['mobile_number'])]

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()


class OwnerOTP(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='otps')
    mobile_number = models.CharField(max_length=15)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'owner_otps'
        indexes = [models.Index(fields=['owner', 'mobile_number', 'expires_at'])]

    @staticmethod
    def build_hash(code):
        return hashlib.sha256(code.strip().encode('utf-8')).hexdigest()

    @classmethod
    def create_code_for_owner(cls, owner, mobile_number, code_length=6):
        code = str(random.randint(10 ** (code_length - 1), (10 ** code_length) - 1))
        expires_at = timezone.now() + timedelta(minutes=5)
        otp = cls.objects.create(
            owner=owner,
            mobile_number=mobile_number,
            code_hash=cls.build_hash(code),
            expires_at=expires_at,
        )
        return otp, code

    def is_expired(self):
        return timezone.now() > self.expires_at

    def is_valid_code(self, code):
        return self.code_hash == self.build_hash(code) and not self.is_expired() and not self.is_used

    def __str__(self):
        return f'{self.owner.email} OTP'


class PasswordResetToken(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='password_reset_tokens')
    token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'password_reset_tokens'
        indexes = [models.Index(fields=['owner', 'expires_at'])]

    @staticmethod
    def build_hash(token):
        return hashlib.sha256(token.strip().encode('utf-8')).hexdigest()

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f'Reset token for {self.owner.email}'
