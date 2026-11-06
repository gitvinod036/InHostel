import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from django.urls import reverse
from .models import Hostel, Floor, Room, Cot, Resident, Payment, Pricing
from django.contrib.auth import get_user_model
from django.db import connection
from unittest.mock import patch

User = get_user_model()


class HostelsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(email='owner1@example.com', mobile_number='9000000001', password='Pass1234!', first_name='Owner', last_name='One')
        self.other = User.objects.create_user(email='owner2@example.com', mobile_number='9000000002', password='Pass1234!', first_name='Owner', last_name='Two')

    def auth(self, user):
        res = self.client.post(reverse('owner-login'), {'email': user.email, 'password': 'Pass1234!'}, format='json')
        token = res.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_authenticated_owner_can_create_hostel(self):
        self.auth(self.owner)
        res = self.client.post('/api/v1/hostels/', {'hostel_name': 'H1', 'address': 'Addr1'}, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Hostel.objects.filter(owner=self.owner).count(), 1)

    def test_unauthenticated_cannot_create_hostel(self):
        res = self.client.post('/api/v1/hostels/', {'hostel_name': 'H1', 'address': 'Addr1'}, format='json')
        self.assertEqual(res.status_code, 401)

    def test_owner_max_two_hostels(self):
        self.auth(self.owner)
        self.client.post('/api/v1/hostels/', {'hostel_name': 'H1', 'address': 'A'}, format='json')
        self.client.post('/api/v1/hostels/', {'hostel_name': 'H2', 'address': 'B'}, format='json')
        res = self.client.post('/api/v1/hostels/', {'hostel_name': 'H3', 'address': 'C'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_owner_cannot_access_another_hostel(self):
        self.auth(self.owner)
        h = Hostel.objects.create(owner=self.other, hostel_name='OtherHostel', address='X')
        res = self.client.get(f'/api/v1/hostels/{h.id}/')
        self.assertEqual(res.status_code, 404)

    def test_create_floor_and_duplicate(self):
        self.auth(self.owner)
        h = Hostel.objects.create(owner=self.owner, hostel_name='H1', address='A')
        res = self.client.post('/api/v1/floors/', {'hostel': h.id, 'floor_number': '1'}, format='json')
        self.assertEqual(res.status_code, 201)
        res2 = self.client.post('/api/v1/floors/', {'hostel': h.id, 'floor_number': '1'}, format='json')
        self.assertEqual(res2.status_code, 400)

    def test_create_room_and_duplicate(self):
        self.auth(self.owner)
        h = Hostel.objects.create(owner=self.owner, hostel_name='H1', address='A')
        f = Floor.objects.create(hostel=h, floor_number='1')
        r = self.client.post('/api/v1/rooms/', {'floor': f.id, 'room_number': '101'}, format='json')
        self.assertEqual(r.status_code, 201)
        r2 = self.client.post('/api/v1/rooms/', {'floor': f.id, 'room_number': '101'}, format='json')
        self.assertEqual(r2.status_code, 400)

    def test_create_cot_and_duplicate_and_defaults(self):
        self.auth(self.owner)
        h = Hostel.objects.create(owner=self.owner, hostel_name='H1', address='A')
        f = Floor.objects.create(hostel=h, floor_number='1')
        r = Room.objects.create(floor=f, room_number='101')
        c = self.client.post('/api/v1/cots/', {'room': r.id, 'cot_number': 'C1'}, format='json')
        self.assertEqual(c.status_code, 201)
        data = c.data
        self.assertEqual(data['status'], Cot.STATUS_AVAILABLE)
        c2 = self.client.post('/api/v1/cots/', {'room': r.id, 'cot_number': 'C1'}, format='json')
        self.assertEqual(c2.status_code, 400)

    def test_cannot_delete_occupied_cot_and_room_hostel_rules(self):
        self.auth(self.owner)
        h = Hostel.objects.create(owner=self.owner, hostel_name='H1', address='A')
        f = Floor.objects.create(hostel=h, floor_number='1')
        r = Room.objects.create(floor=f, room_number='101')
        cot = Cot.objects.create(room=r, cot_number='C1', status=Cot.STATUS_OCCUPIED)
        # cannot delete cot
        res = self.client.delete(f'/api/v1/cots/{cot.id}/')
        self.assertEqual(res.status_code, 400)
        # cannot delete room
        res2 = self.client.delete(f'/api/v1/rooms/{r.id}/')
        self.assertEqual(res2.status_code, 400)
        # cannot delete hostel
        res3 = self.client.delete(f'/api/v1/hostels/{h.id}/')
        self.assertEqual(res3.status_code, 400)

    def test_nested_resources_cannot_cross_owners(self):
        self.auth(self.owner)
        other_h = Hostel.objects.create(owner=self.other, hostel_name='OH', address='X')
        # try create floor under other's hostel
        res = self.client.post('/api/v1/floors/', {'hostel': other_h.id, 'floor_number': '1'}, format='json')
        self.assertEqual(res.status_code, 400)

        # create hostel for owner, floor, room
        h = Hostel.objects.create(owner=self.owner, hostel_name='H1', address='A')
        f = Floor.objects.create(hostel=h, floor_number='1')
        # attempt to create room with floor id but different owner doesn't apply here as floor belongs to owner
        # ensure other owner cannot access it
        self.client.credentials()  # clear
        res2 = self.client.post('/api/v1/hostels/', {'hostel_name': 'X', 'address': 'Y'}, format='json')
        self.assertEqual(res2.status_code, 401)

    def test_owner_can_generate_registration_link_and_public_register(self):
        self.auth(self.owner)
        # generate link
        h = Hostel.objects.create(owner=self.owner, hostel_name='RegHost', address='R')
        res = self.client.get(f'/api/v1/hostels/{h.id}/registration_link/')
        self.assertEqual(res.status_code, 200)
        token = res.data['token']
        # public registration using token
        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {
            'full_name': 'Res One',
            'mobile_number': '9000000009',
            'joining_date': '2026-08-01',
            'address': 'Addr',
            'id_proof': SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            'photo': SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
        }
        client2 = APIClient()
        resp = client2.post(f'/api/v1/register/{token}/', data, format='multipart')
        self.assertEqual(resp.status_code, 201)
        # owner can list submissions
        self.auth(self.owner)
        list_res = self.client.get('/api/v1/residents/')
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(len(list_res.data), 1)

    def test_invalid_token_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {
            'full_name': 'Res Two',
            'mobile_number': '9000000012',
            'joining_date': '2026-08-01',
            'address': 'Addr',
            'id_proof': SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            'photo': SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
        }
        client2 = APIClient()
        resp = client2.post(f'/api/v1/register/invalidtoken123/', data, format='multipart')
        self.assertEqual(resp.status_code, 400)

    def test_owner_regenerate_registration_link_revokes_old_and_creates_new(self):
        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='RegenHostel', address='Addr')
        # 1. Initial GET creates and returns token 1
        res1 = self.client.get(f'/api/v1/hostels/{hostel.id}/registration_link/')
        self.assertEqual(res1.status_code, 200)
        token1 = res1.data['token']

        # 2. Subsequent GET returns the same active token
        res_same = self.client.get(f'/api/v1/hostels/{hostel.id}/registration_link/')
        self.assertEqual(res_same.status_code, 200)
        self.assertEqual(res_same.data['token'], token1)

        # 3. POST regenerates: revokes token 1 and creates token 2
        res2 = self.client.post(f'/api/v1/hostels/{hostel.id}/registration_link/')
        self.assertEqual(res2.status_code, 201)
        token2 = res2.data['token']
        self.assertNotEqual(token1, token2)

        # Verify in database
        from .models import RegistrationToken
        t1_obj = RegistrationToken.objects.get(token=token1)
        t2_obj = RegistrationToken.objects.get(token=token2)
        self.assertTrue(t1_obj.revoked)
        self.assertFalse(t2_obj.revoked)

        # 4. Subsequent GET returns token 2
        res3 = self.client.get(f'/api/v1/hostels/{hostel.id}/registration_link/')
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(res3.data['token'], token2)

    def test_revoked_token_cannot_be_used_for_public_registration(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='RevokeCheckHostel', address='Addr')
        res1 = self.client.get(f'/api/v1/hostels/{hostel.id}/registration_link/')
        token1 = res1.data['token']

        # Regenerate to revoke token1
        res2 = self.client.post(f'/api/v1/hostels/{hostel.id}/registration_link/')
        token2 = res2.data['token']

        client2 = APIClient()
        data_old = {
            'full_name': 'Old Link User',
            'mobile_number': '9000000021',
            'joining_date': '2026-08-01',
            'address': 'Addr',
            'id_proof': SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            'photo': SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
        }
        # Old token must fail
        resp_old = client2.post(f'/api/v1/register/{token1}/', data_old, format='multipart')
        self.assertEqual(resp_old.status_code, 400)
        self.assertIn('invalid or expired', resp_old.data.get('detail', '').lower())

        # New token must succeed
        data_new = {
            'full_name': 'New Link User',
            'mobile_number': '9000000022',
            'joining_date': '2026-08-01',
            'address': 'Addr',
            'id_proof': SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            'photo': SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
        }
        resp_new = client2.post(f'/api/v1/register/{token2}/', data_new, format='multipart')
        self.assertEqual(resp_new.status_code, 201)
        self.assertEqual(resp_new.data['status'], 'PENDING')
        self.assertEqual(resp_new.data['hostel'], hostel.id)

    def test_owner_cannot_access_other_owner_registration_token(self):
        self.auth(self.owner)
        other_hostel = Hostel.objects.create(owner=self.other, hostel_name='Other Host Link', address='Addr')

        # GET should return 404
        get_res = self.client.get(f'/api/v1/hostels/{other_hostel.id}/registration_link/')
        self.assertEqual(get_res.status_code, 404)

        # POST should return 404
        post_res = self.client.post(f'/api/v1/hostels/{other_hostel.id}/registration_link/')
        self.assertEqual(post_res.status_code, 404)

    def test_get_valid_registration_link_renders_html_form(self):
        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='HTML Form Hostel', address='123 Main Street')
        token = self.client.get(f'/api/v1/hostels/{hostel.id}/registration_link/').data['token']

        # Unauthenticated resident opens link in browser (Accept: text/html)
        client = APIClient()
        response = client.get(f'/register/{token}/', HTTP_ACCEPT='text/html,application/xhtml+xml')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('HTML Form Hostel', content)
        self.assertIn('123 Main Street', content)
        self.assertIn('Resident Registration', content)
        self.assertIn('name="full_name"', content)
        self.assertIn('name="mobile_number"', content)
        self.assertIn('name="id_proof"', content)
        self.assertIn('name="photo"', content)

    def test_get_invalid_registration_link_renders_error_page(self):
        client = APIClient()
        response = client.get('/register/completely-invalid-token/', HTTP_ACCEPT='text/html,application/xhtml+xml')
        self.assertEqual(response.status_code, 400)
        content = response.content.decode('utf-8')
        self.assertIn('Registration Link Invalid', content)

    def test_get_revoked_registration_link_renders_error_page(self):
        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='Revoked HTML Hostel', address='Addr')
        res1 = self.client.get(f'/api/v1/hostels/{hostel.id}/registration_link/')
        old_token = res1.data['token']
        # Regenerate to revoke old token
        self.client.post(f'/api/v1/hostels/{hostel.id}/registration_link/')

        client = APIClient()
        response = client.get(f'/register/{old_token}/', HTTP_ACCEPT='text/html,application/xhtml+xml')
        self.assertEqual(response.status_code, 400)
        content = response.content.decode('utf-8')
        self.assertIn('Registration Link Invalid', content)

    def test_post_valid_html_form_creates_pending_resident_and_renders_success_page(self):
        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='Web Submit Hostel', address='Addr')
        token = self.client.get(f'/api/v1/hostels/{hostel.id}/registration_link/').data['token']

        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {
            'full_name': 'Web Resident User',
            'mobile_number': '9000000088',
            'joining_date': '2026-08-01',
            'address': 'Resident Address',
            'id_proof': SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            'photo': SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
        }
        client = APIClient()
        response = client.post(f'/register/{token}/', data, format='multipart', HTTP_ACCEPT='text/html,application/xhtml+xml')
        self.assertEqual(response.status_code, 201)
        content = response.content.decode('utf-8')
        self.assertIn('Registration Submitted Successfully', content)
        self.assertIn('Web Resident User', content)
        self.assertIn('PENDING APPROVAL', content)

        # Verify resident in DB
        resident = Resident.objects.get(mobile_number='9000000088')
        self.assertEqual(resident.hostel_id, hostel.id)
        self.assertEqual(resident.status, Resident.STATUS_PENDING)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_successful_registration_sends_owner_email(self):
        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='RegHostEmail', address='R')
        token = self.client.get(f'/api/v1/hostels/{hostel.id}/registration_link/').data['token']
        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {
            'full_name': 'Res Email Success',
            'mobile_number': '9000000017',
            'joining_date': '2026-08-01',
            'address': 'Addr',
            'id_proof': SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            'photo': SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
        }
        response = APIClient().post(f'/api/v1/register/{token}/', data, format='multipart')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.owner.email, mail.outbox[0].to)
        self.assertIn(hostel.hostel_name, mail.outbox[0].subject)
        self.assertNotIn('password', mail.outbox[0].body.lower())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_failed_registration_does_not_send_email(self):
        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='RegHostFailedEmail', address='R')
        token = self.client.get(f'/api/v1/hostels/{hostel.id}/registration_link/').data['token']
        bad_data = {
            'mobile_number': '9000000018',
            'joining_date': '2026-08-01',
        }
        response = APIClient().post(f'/api/v1/register/{token}/', bad_data, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    @patch('hostels.services.EmailMultiAlternatives.send', side_effect=Exception('smtp down'))
    def test_email_failure_does_not_remove_resident(self, _mock_send):
        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='RegHostEmailFailure', address='R')
        token = self.client.get(f'/api/v1/hostels/{hostel.id}/registration_link/').data['token']
        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {
            'full_name': 'Res Email Failure',
            'mobile_number': '9000000019',
            'joining_date': '2026-08-01',
            'address': 'Addr',
            'id_proof': SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            'photo': SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
        }
        response = APIClient().post(f'/api/v1/register/{token}/', data, format='multipart')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Resident.objects.filter(id=response.data['id']).exists())

    def test_owner_can_confirm_registration_and_email_triggered(self):
        # generate token and register
        self.auth(self.owner)
        h = Hostel.objects.create(owner=self.owner, hostel_name='RegHost', address='R')
        res = self.client.get(f'/api/v1/hostels/{h.id}/registration_link/')
        token = res.data['token']
        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {
            'full_name': 'Res Three',
            'mobile_number': '9000000013',
            'joining_date': '2026-08-01',
            'address': 'Addr',
            'id_proof': SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            'photo': SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
        }
        client2 = APIClient()
        resp = client2.post(f'/api/v1/register/{token}/', data, format='multipart')
        self.assertEqual(resp.status_code, 201)
        pid = resp.data['id']
        # patch status to ACTIVE
        self.auth(self.owner)
        patch = self.client.patch(f'/api/v1/residents/{pid}/', {'status': 'ACTIVE'}, format='json')
        self.assertEqual(patch.status_code, 200)
        from .models import Resident
        r = Resident.objects.get(pk=pid)
        self.assertEqual(r.status, Resident.STATUS_ACTIVE)

    def test_owner_can_allocate_pending_resident_to_available_cot(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='AllocHost', address='Addr')
        floor = Floor.objects.create(hostel=hostel, floor_number='1')
        room = Room.objects.create(floor=floor, room_number='101')
        cot = Cot.objects.create(room=room, cot_number='A1', status=Cot.STATUS_AVAILABLE)
        resident = Resident.objects.create(
            hostel=hostel,
            full_name='Alloc Resident',
            mobile_number='9000000101',
            joining_date='2026-08-01',
            id_proof=SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            photo=SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
            address='Home',
            status=Resident.STATUS_PENDING,
        )

        res = self.client.post(f'/api/v1/residents/{resident.id}/allocate/', {'cot_id': cot.id}, format='json')
        self.assertEqual(res.status_code, 201)
        resident.refresh_from_db()
        cot.refresh_from_db()
        self.assertEqual(resident.assigned_cot_id, cot.id)
        self.assertEqual(resident.status, Resident.STATUS_ACTIVE)
        self.assertEqual(cot.status, Cot.STATUS_OCCUPIED)

    def test_occupied_cot_rejected_during_allocation(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='AllocHost2', address='Addr')
        floor = Floor.objects.create(hostel=hostel, floor_number='1')
        room = Room.objects.create(floor=floor, room_number='101')
        cot = Cot.objects.create(room=room, cot_number='A1', status=Cot.STATUS_OCCUPIED)
        resident = Resident.objects.create(
            hostel=hostel,
            full_name='Alloc Resident 2',
            mobile_number='9000000102',
            joining_date='2026-08-01',
            id_proof=SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            photo=SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
            address='Home',
            status=Resident.STATUS_PENDING,
        )

        res = self.client.post(f'/api/v1/residents/{resident.id}/allocate/', {'cot_id': cot.id}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIsNone(resident.assigned_cot_id)

    def test_duplicate_resident_allocation_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='AllocHost3', address='Addr')
        floor = Floor.objects.create(hostel=hostel, floor_number='1')
        room = Room.objects.create(floor=floor, room_number='101')
        cot = Cot.objects.create(room=room, cot_number='A1', status=Cot.STATUS_AVAILABLE)
        resident = Resident.objects.create(
            hostel=hostel,
            full_name='Alloc Resident 3',
            mobile_number='9000000103',
            joining_date='2026-08-01',
            id_proof=SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            photo=SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
            address='Home',
            status=Resident.STATUS_PENDING,
        )

        first = self.client.post(f'/api/v1/residents/{resident.id}/allocate/', {'cot_id': cot.id}, format='json')
        self.assertEqual(first.status_code, 201)
        second = self.client.post(f'/api/v1/residents/{resident.id}/allocate/', {'cot_id': cot.id}, format='json')
        self.assertEqual(second.status_code, 400)

    def test_cross_owner_cannot_access_other_owner_allocation(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.auth(self.owner)
        other_hostel = Hostel.objects.create(owner=self.other, hostel_name='Other Host', address='Addr')
        floor = Floor.objects.create(hostel=other_hostel, floor_number='1')
        room = Room.objects.create(floor=floor, room_number='101')
        cot = Cot.objects.create(room=room, cot_number='A1', status=Cot.STATUS_AVAILABLE)
        resident = Resident.objects.create(
            hostel=other_hostel,
            full_name='Other Owner Resident',
            mobile_number='9000000104',
            joining_date='2026-08-01',
            id_proof=SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            photo=SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
            address='Other',
            status=Resident.STATUS_PENDING,
        )

        res = self.client.get(f'/api/v1/residents/{resident.id}/allocation/')
        self.assertEqual(res.status_code, 404)

        alloc = self.client.post(f'/api/v1/residents/{resident.id}/allocate/', {'cot_id': cot.id}, format='json')
        self.assertEqual(alloc.status_code, 404)

    def test_concurrent_allocation_only_one_request_succeeds(self):
        if connection.vendor == 'sqlite':
            self.skipTest('SQLite does not reliably support row-level locking for concurrent allocation tests; production logic uses transaction.atomic + select_for_update for MySQL/Postgres.')

        from django.core.files.uploadedfile import SimpleUploadedFile

        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='AllocHost4', address='Addr')
        floor = Floor.objects.create(hostel=hostel, floor_number='1')
        room = Room.objects.create(floor=floor, room_number='101')
        cot = Cot.objects.create(room=room, cot_number='A1', status=Cot.STATUS_AVAILABLE)

        def create_resident(mobile):
            return Resident.objects.create(
                hostel=hostel,
                full_name=f'Resident {mobile}',
                mobile_number=mobile,
                joining_date='2026-08-01',
                id_proof=SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
                photo=SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
                address='Home',
                status=Resident.STATUS_PENDING,
            )

        resident_a = create_resident('9000000105')
        resident_b = create_resident('9000000106')
        barrier = threading.Barrier(2)

        def allocate(client, resident_id):
            barrier.wait()
            return client.post(f'/api/v1/residents/{resident_id}/allocate/', {'cot_id': cot.id}, format='json')

        client_a = APIClient()
        client_b = APIClient()
        owner_login = self.client.post(reverse('owner-login'), {'email': self.owner.email, 'password': 'Pass1234!'}, format='json')
        token = owner_login.data['access']
        client_a.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        client_b.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(allocate, client_a, resident_a.id), executor.submit(allocate, client_b, resident_b.id)]
            results = [future.result() for future in futures]

        success_count = sum(1 for result in results if result.status_code == 201)
        self.assertEqual(success_count, 1)
        self.assertEqual(Cot.objects.get(pk=cot.id).status, Cot.STATUS_OCCUPIED)


class DashboardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(email='owner-dashboard@example.com', mobile_number='9000000200', password='Pass1234!', first_name='Dash', last_name='Owner')
        self.other = User.objects.create_user(email='other-dashboard@example.com', mobile_number='9000000201', password='Pass1234!', first_name='Other', last_name='Owner')

    def auth(self, user):
        res = self.client.post(reverse('owner-login'), {'email': user.email, 'password': 'Pass1234!'}, format='json')
        token = res.data['access']
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)

    def test_dashboard_returns_owner_counts(self):
        self.auth(self.owner)
        hostel = Hostel.objects.create(owner=self.owner, hostel_name='Dashboard Hostel', address='Addr')
        floor = Floor.objects.create(hostel=hostel, floor_number='1')
        room = Room.objects.create(floor=floor, room_number='101')
        available_cot = Cot.objects.create(room=room, cot_number='A1', status=Cot.STATUS_AVAILABLE)
        occupied_cot = Cot.objects.create(room=room, cot_number='A2', status=Cot.STATUS_OCCUPIED)

        Resident.objects.create(hostel=hostel, full_name='Pending Resident', mobile_number='9000000202', joining_date='2026-08-01', id_proof='id.pdf', photo='photo.jpg', address='Addr', status=Resident.STATUS_PENDING)
        Resident.objects.create(hostel=hostel, full_name='Active Resident', mobile_number='9000000203', joining_date='2026-08-01', id_proof='id.pdf', photo='photo.jpg', address='Addr', status=Resident.STATUS_ACTIVE, assigned_cot=available_cot)
        Resident.objects.create(hostel=hostel, full_name='Vacated Resident', mobile_number='9000000204', joining_date='2026-08-01', id_proof='id.pdf', photo='photo.jpg', address='Addr', status=Resident.STATUS_VACATED, vacated_date='2026-08-07')

        res = self.client.get('/api/v1/hostels/dashboard/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data['hostels']), 1)
        summary = res.data['summary']
        self.assertEqual(summary['total_residents'], 3)
        self.assertEqual(summary['active_residents'], 1)
        self.assertEqual(summary['pending_residents'], 1)
        self.assertEqual(summary['vacated_residents'], 1)
        self.assertEqual(summary['available_cots'], 1)
        self.assertEqual(summary['occupied_cots'], 1)

    def test_dashboard_is_owner_scoped(self):
        self.auth(self.owner)
        owner_hostel = Hostel.objects.create(owner=self.owner, hostel_name='Owner Hostel', address='My Addr')
        Floor.objects.create(hostel=owner_hostel, floor_number='1')
        other_hostel = Hostel.objects.create(owner=self.other, hostel_name='Other Hostel', address='Other Addr')
        Floor.objects.create(hostel=other_hostel, floor_number='2')

        Resident.objects.create(hostel=owner_hostel, full_name='Owned Resident', mobile_number='9000000205', joining_date='2026-08-01', id_proof='id.pdf', photo='photo.jpg', address='Addr', status=Resident.STATUS_PENDING)
        Resident.objects.create(hostel=other_hostel, full_name='Other Resident', mobile_number='9000000206', joining_date='2026-08-01', id_proof='id.pdf', photo='photo.jpg', address='Addr', status=Resident.STATUS_ACTIVE)
        Cot.objects.create(room=Room.objects.create(floor=owner_hostel.floors.first(), room_number='101'), cot_number='A1', status=Cot.STATUS_AVAILABLE)
        Cot.objects.create(room=Room.objects.create(floor=other_hostel.floors.first(), room_number='201'), cot_number='B1', status=Cot.STATUS_OCCUPIED)

        res = self.client.get('/api/v1/hostels/dashboard/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data['hostels']), 1)
        self.assertEqual(res.data['hostels'][0]['hostel_name'], 'Owner Hostel')
        self.assertEqual(res.data['summary']['total_residents'], 1)
        self.assertEqual(res.data['summary']['available_cots'], 1)
        self.assertEqual(res.data['summary']['occupied_cots'], 0)

    def test_dashboard_requires_authentication(self):
        res = self.client.get('/api/v1/hostels/dashboard/')
        self.assertEqual(res.status_code, 401)


class PricingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(email='owner1@example.com', mobile_number='9000000010', password='Pass1234!', first_name='Owner', last_name='Pricer')
        self.other = User.objects.create_user(email='owner2@example.com', mobile_number='9000000011', password='Pass1234!', first_name='Owner', last_name='Two')
        self.h = Hostel.objects.create(owner=self.owner, hostel_name='HPrice', address='Addr')
        self.other_h = Hostel.objects.create(owner=self.other, hostel_name='OtherPrice', address='Addr2')

    def auth(self, user):
        res = self.client.post(reverse('owner-login'), {'email': user.email, 'password': 'Pass1234!'}, format='json')
        token = res.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_owner_can_create_pricing(self):
        self.auth(self.owner)
        res = self.client.post('/api/v1/pricing/', {'hostel': self.h.id, 'sharing_count': 1, 'monthly_amount': '12000.00'}, format='json')
        self.assertEqual(res.status_code, 201)
        from .models import Pricing
        self.assertEqual(Pricing.objects.filter(hostel=self.h, sharing_count=1).count(), 1)

    def test_unauthenticated_cannot_create_pricing(self):
        res = self.client.post('/api/v1/pricing/', {'hostel': self.h.id, 'sharing_count': 1, 'monthly_amount': '12000.00'}, format='json')
        self.assertEqual(res.status_code, 401)

    def test_invalid_sharing_count_rejected(self):
        self.auth(self.owner)
        res = self.client.post('/api/v1/pricing/', {'hostel': self.h.id, 'sharing_count': 0, 'monthly_amount': '5000.00'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_zero_or_negative_price_rejected(self):
        self.auth(self.owner)
        res = self.client.post('/api/v1/pricing/', {'hostel': self.h.id, 'sharing_count': 2, 'monthly_amount': '0.00'}, format='json')
        self.assertEqual(res.status_code, 400)
        res2 = self.client.post('/api/v1/pricing/', {'hostel': self.h.id, 'sharing_count': 2, 'monthly_amount': '-100.00'}, format='json')
        self.assertEqual(res2.status_code, 400)

    def test_duplicate_sharing_rejected(self):
        self.auth(self.owner)
        self.client.post('/api/v1/pricing/', {'hostel': self.h.id, 'sharing_count': 3, 'monthly_amount': '6500.00'}, format='json')
        res = self.client.post('/api/v1/pricing/', {'hostel': self.h.id, 'sharing_count': 3, 'monthly_amount': '7000.00'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_owner_cannot_create_for_other_hostel(self):
        self.auth(self.owner)
        res = self.client.post('/api/v1/pricing/', {'hostel': self.other_h.id, 'sharing_count': 1, 'monthly_amount': '12000.00'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_owner_can_update_and_delete_pricing(self):
        self.auth(self.owner)
        r = self.client.post('/api/v1/pricing/', {'hostel': self.h.id, 'sharing_count': 4, 'monthly_amount': '5500.00'}, format='json')
        self.assertEqual(r.status_code, 201)
        pid = r.data['id']
        patch = self.client.patch(f'/api/v1/pricing/{pid}/', {'monthly_amount': '6000.00'}, format='json')
        self.assertEqual(patch.status_code, 200)
        delete = self.client.delete(f'/api/v1/pricing/{pid}/')
        self.assertEqual(delete.status_code, 204)

    def test_monetary_precision(self):
        self.auth(self.owner)
        r = self.client.post('/api/v1/pricing/', {'hostel': self.h.id, 'sharing_count': 2, 'monthly_amount': '8000.50'}, format='json')
        self.assertEqual(r.status_code, 201)
        from decimal import Decimal
        from .models import Pricing
        p = Pricing.objects.get(pk=r.data['id'])
        self.assertIsInstance(p.monthly_amount, type(Decimal('1.0')))
        self.assertEqual(p.monthly_amount, Decimal('8000.50'))

    def test_owner_cannot_access_another_pricing(self):
        # create pricing by other owner
        self.auth(self.other)
        r = self.client.post('/api/v1/pricing/', {'hostel': self.other_h.id, 'sharing_count': 1, 'monthly_amount': '10000.00'}, format='json')
        self.assertEqual(r.status_code, 201)
        pid = r.data['id']
        # switch to owner and attempt access
        self.auth(self.owner)
        res = self.client.get(f'/api/v1/pricing/{pid}/')
        self.assertEqual(res.status_code, 404)


class PaymentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(email='owner-payment@example.com', mobile_number='9000000201', password='Pass1234!', first_name='Owner', last_name='Pay')
        self.other = User.objects.create_user(email='owner-payment-2@example.com', mobile_number='9000000202', password='Pass1234!', first_name='Other', last_name='Owner')
        self.hostel = Hostel.objects.create(owner=self.owner, hostel_name='Payment Hostel', address='Pay Addr')
        self.other_hostel = Hostel.objects.create(owner=self.other, hostel_name='Other Payment Hostel', address='Other Addr')
        self.pricing = Pricing.objects.create(hostel=self.hostel, sharing_count=1, monthly_amount=Decimal('2500.00'))

    def auth(self, user):
        res = self.client.post(reverse('owner-login'), {'email': user.email, 'password': 'Pass1234!'}, format='json')
        token = res.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def create_resident(self, hostel, full_name='Resident', mobile='9000000203', joining_date=None):
        if joining_date is None:
            joining_date = date(2026, 8, 12)
        from django.core.files.uploadedfile import SimpleUploadedFile
        return Resident.objects.create(
            hostel=hostel,
            full_name=full_name,
            mobile_number=mobile,
            joining_date=joining_date,
            id_proof=SimpleUploadedFile('id.pdf', b'PDFDATA', content_type='application/pdf'),
            photo=SimpleUploadedFile('photo.jpg', b'JPEGDATA', content_type='image/jpeg'),
            address='Main St',
            status=Resident.STATUS_ACTIVE,
        )

    def test_owner_can_record_payment(self):
        self.auth(self.owner)
        resident = self.create_resident(self.hostel, 'Pay Resident', '9000000203')
        response = self.client.post('/api/v1/payments/', {
            'resident': resident.id,
            'amount': '2500.00',
            'payment_date': '2026-08-20',
            'advance_amount': '0.00',
            'late_fee': '0.00',
            'payment_method': 'CASH',
            'reference': 'Receipt 1',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], Payment.STATUS_PAID)
        self.assertEqual(Payment.objects.filter(resident=resident).count(), 1)

    def test_unauthenticated_request_rejected(self):
        resident = self.create_resident(self.hostel, 'Unauth Resident', '9000000204')
        response = self.client.post('/api/v1/payments/', {
            'resident': resident.id,
            'amount': '2500.00',
            'payment_date': '2026-08-20',
            'advance_amount': '0.00',
            'late_fee': '0.00',
            'payment_method': 'UPI',
        }, format='json')
        self.assertEqual(response.status_code, 401)

    def test_cross_owner_payment_access_rejected(self):
        self.auth(self.owner)
        other_resident = self.create_resident(self.other_hostel, 'Other Resident', '9000000205')
        response = self.client.get(f'/api/v1/residents/{other_resident.id}/payments/')
        self.assertEqual(response.status_code, 404)
        response2 = self.client.post('/api/v1/payments/', {'resident': other_resident.id, 'amount': '2500.00', 'payment_date': '2026-08-20', 'advance_amount': '0.00', 'late_fee': '0.00', 'payment_method': 'BANK_TRANSFER'}, format='json')
        self.assertEqual(response2.status_code, 400)

    def test_negative_amount_rejected(self):
        self.auth(self.owner)
        resident = self.create_resident(self.hostel, 'Neg Resident', '9000000206')
        response = self.client.post('/api/v1/payments/', {
            'resident': resident.id,
            'amount': '-100.00',
            'payment_date': '2026-08-20',
            'advance_amount': '0.00',
            'late_fee': '0.00',
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_zero_amount_rejected(self):
        self.auth(self.owner)
        resident = self.create_resident(self.hostel, 'Zero Resident', '9000000207')
        response = self.client.post('/api/v1/payments/', {
            'resident': resident.id,
            'amount': '0.00',
            'payment_date': '2026-08-20',
            'advance_amount': '0.00',
            'late_fee': '0.00',
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_advance_and_late_fee_stored_correctly(self):
        self.auth(self.owner)
        resident = self.create_resident(self.hostel, 'Advance Resident', '9000000208')
        response = self.client.post('/api/v1/payments/', {
            'resident': resident.id,
            'amount': '2200.00',
            'payment_date': '2026-08-20',
            'advance_amount': '200.00',
            'late_fee': '50.00',
            'payment_method': 'UPI',
            'reference': 'ADV-1',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        payment = Payment.objects.get(pk=response.data['id'])
        self.assertEqual(payment.advance_amount, Decimal('200.00'))
        self.assertEqual(payment.late_fee, Decimal('50.00'))
        self.assertEqual(payment.status, Payment.STATUS_PARTIAL)

    def test_monthly_fee_comes_from_pricing(self):
        self.auth(self.owner)
        resident = self.create_resident(self.hostel, 'Pricing Resident', '9000000209')
        response = self.client.get(f'/api/v1/residents/{resident.id}/billing/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['monthly_fee'], '2500.00')

    def test_billing_period_uses_joining_date(self):
        self.auth(self.owner)
        resident = self.create_resident(self.hostel, 'Billing Resident', '9000000210', joining_date=date(2026, 8, 12))
        response = self.client.get(f'/api/v1/residents/{resident.id}/billing/?as_of=2026-09-15')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['billing_period_start'], '2026-09-12')
        self.assertEqual(response.data['billing_period_end'], '2026-10-11')
        self.assertEqual(response.data['next_due_date'], '2026-10-12')

    def test_payment_history_works(self):
        self.auth(self.owner)
        resident = self.create_resident(self.hostel, 'History Resident', '9000000211')
        self.client.post('/api/v1/payments/', {
            'resident': resident.id,
            'amount': '2500.00',
            'payment_date': '2026-08-20',
            'advance_amount': '0.00',
            'late_fee': '0.00',
            'payment_method': 'CASH',
        }, format='json')
        response = self.client.get(f'/api/v1/residents/{resident.id}/payments/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_paid_partial_status_works(self):
        self.auth(self.owner)
        resident = self.create_resident(self.hostel, 'Status Resident', '9000000212')
        paid = self.client.post('/api/v1/payments/', {
            'resident': resident.id,
            'amount': '2500.00',
            'payment_date': '2026-08-20',
            'advance_amount': '0.00',
            'late_fee': '0.00',
            'payment_method': 'CASH',
        }, format='json')
        partial = self.client.post('/api/v1/payments/', {
            'resident': resident.id,
            'amount': '1000.00',
            'payment_date': '2026-09-20',
            'advance_amount': '0.00',
            'late_fee': '0.00',
            'payment_method': 'UPI',
        }, format='json')
        self.assertEqual(paid.data['status'], Payment.STATUS_PAID)
        self.assertEqual(partial.data['status'], Payment.STATUS_PARTIAL)

    def test_month_end_billing_dates_work(self):
        self.auth(self.owner)
        resident = self.create_resident(self.hostel, 'Month End Resident', '9000000213', joining_date=date(2026, 1, 31))
        response = self.client.get(f'/api/v1/residents/{resident.id}/billing/?as_of=2026-02-28')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['billing_period_start'], '2026-02-28')
        self.assertEqual(response.data['billing_period_end'], '2026-03-27')
        self.assertEqual(response.data['next_due_date'], '2026-03-28')
