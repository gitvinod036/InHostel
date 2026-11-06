from django.contrib.auth.base_user import BaseUserManager


class OwnerManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, mobile_number, password, **extra_fields):
        if not email:
            raise ValueError('The email field must be set.')
        if not mobile_number:
            raise ValueError('The mobile number field must be set.')

        email = self.normalize_email(email)
        user = self.model(email=email, mobile_number=mobile_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, mobile_number, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        if password is None:
            raise ValueError('Password must be set.')
        return self._create_user(email, mobile_number, password, **extra_fields)

    def create_superuser(self, email, mobile_number, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        if password is None:
            raise ValueError('Password must be set.')

        return self._create_user(email, mobile_number, password, **extra_fields)
