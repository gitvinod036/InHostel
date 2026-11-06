from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from django.utils import timezone
from datetime import timedelta

from .models import Owner, OwnerOTP, PasswordResetToken
from . import services


@override_settings(DEBUG=True)
class OwnerAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = Owner.objects.create_user(
            email='owner@example.com',
            mobile_number='9998887776',
            password='StrongPass123!',
            first_name='Test',
            last_name='Owner',
        )

    def test_register_and_duplicate(self):
        url = reverse('owner-register')
        payload = {
            'email': 'newowner@example.com',
            'mobile_number': '9876543210',
            'first_name': 'New',
            'last_name': 'Owner',
            'password': 'AnotherPass123!'
        }
        res = self.client.post(url, payload, format='json')
        self.assertEqual(res.status_code, 201)
        # Duplicate email
        payload['mobile_number'] = '9876543211'
        res2 = self.client.post(url, payload, format='json')
        self.assertEqual(res2.status_code, 400)

    def test_login_success_and_invalid_password(self):
        url = reverse('owner-login')
        res = self.client.post(url, {'email': 'owner@example.com', 'password': 'StrongPass123!'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertIn('access', res.data)
        self.assertIn('refresh', res.data)

        # invalid
        res2 = self.client.post(url, {'email': 'owner@example.com', 'password': 'badpass'}, format='json')
        self.assertEqual(res2.status_code, 400)

    def test_token_refresh_and_logout(self):
        login = self.client.post(reverse('owner-login'), {'email': 'owner@example.com', 'password': 'StrongPass123!'}, format='json')
        refresh = login.data['refresh']
        res = self.client.post(reverse('owner-refresh'), {'refresh': refresh}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertIn('access', res.data)

        # Logout
        res2 = self.client.post(reverse('owner-logout'), {'refresh': refresh}, format='json')
        self.assertEqual(res2.status_code, 200)

    def test_otp_request_verify_and_reuse(self):
        # create otp via service to get code
        otp_record, code = services.create_owner_otp(self.owner, self.owner.mobile_number)
        # verify via endpoint
        res = self.client.post(reverse('owner-otp-verify'), {'mobile_number': self.owner.mobile_number, 'otp': code}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertIn('access', res.data)

        # reuse should fail
        res2 = self.client.post(reverse('owner-otp-verify'), {'mobile_number': self.owner.mobile_number, 'otp': code}, format='json')
        self.assertEqual(res2.status_code, 400)

    def test_otp_expiration_and_attempt_limits(self):
        otp_record, code = services.create_owner_otp(self.owner, self.owner.mobile_number)
        # expire it
        otp_record.expires_at = timezone.now() - timedelta(minutes=1)
        otp_record.save()
        res = self.client.post(reverse('owner-otp-verify'), {'mobile_number': self.owner.mobile_number, 'otp': code}, format='json')
        self.assertEqual(res.status_code, 400)

        # attempt limits
        otp2, code2 = services.create_owner_otp(self.owner, self.owner.mobile_number)
        # wrong attempts
        for i in range(otp2.max_attempts):
            resw = self.client.post(reverse('owner-otp-verify'), {'mobile_number': self.owner.mobile_number, 'otp': '000000'}, format='json')
            # until last, should be 400
            self.assertEqual(resw.status_code, 400)
        # now even correct should fail
        resc = self.client.post(reverse('owner-otp-verify'), {'mobile_number': self.owner.mobile_number, 'otp': code2}, format='json')
        self.assertEqual(resc.status_code, 400)

    def test_authenticated_api_access_and_unauthorized(self):
        login = self.client.post(reverse('owner-login'), {'email': 'owner@example.com', 'password': 'StrongPass123!'}, format='json')
        access = login.data['access']
        # authenticated
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        res = self.client.get(reverse('owner-profile'))
        self.assertEqual(res.status_code, 200)
        # unauthorized
        self.client.credentials()  # clear
        res2 = self.client.get(reverse('owner-profile'))
        self.assertEqual(res2.status_code, 401)

    def test_forgot_password_creates_token(self):
        res = self.client.post(reverse('owner-forgot-password'), {'email': 'owner@example.com'}, format='json')
        self.assertEqual(res.status_code, 200)
        tokens = PasswordResetToken.objects.filter(owner=self.owner)
        self.assertTrue(tokens.exists())

    def test_google_auth_creates_or_uses_account(self):
        # monkeypatch id_token verifier by patching module function
        import google.oauth2.id_token as id_token_module
        original = id_token_module.verify_oauth2_token

        def fake_verify(token, request, client_id):
            return {'email': 'googleowner@example.com', 'given_name': 'Google', 'phone_number': '9991112223'}

        id_token_module.verify_oauth2_token = fake_verify
        try:
            res = self.client.post(reverse('owner-google-auth'), {'id_token': 'fake-token', 'mobile_number': '9991112223'}, format='json')
            self.assertEqual(res.status_code, 200)
            self.assertIn('access', res.data)
        finally:
            id_token_module.verify_oauth2_token = original

