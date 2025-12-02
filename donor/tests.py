from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from donor.forms import DonorForm
from donor import models as dmodels


class DonorFormGeoTests(TestCase):
	def setUp(self):
		self.base_data = {
			'bloodgroup': 'A+',
			'address': '221B Baker Street',
			'mobile': '1234567890',
		}

	def test_coordinates_optional_when_both_blank(self):
		form = DonorForm(data=self.base_data)
		self.assertTrue(form.is_valid(), form.errors)

	def test_rejects_partial_coordinate_submission(self):
		partial = {**self.base_data, 'latitude': '12.9716'}
		form = DonorForm(data=partial)
		self.assertFalse(form.is_valid())
		self.assertIn('Please provide both latitude and longitude or leave both blank.', form.errors['__all__'])

	def test_accepts_valid_coordinate_pair(self):
		data = {
			**self.base_data,
			'latitude': '12.971598',
			'longitude': '77.594566',
		}
		form = DonorForm(data=data)
		self.assertTrue(form.is_valid(), form.errors)


@override_settings(GEOCODER_ALLOW_REMOTE=False)
class AdminDonorMapViewTests(TestCase):
	def setUp(self):
		self.client = Client()
		self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pass1234')

		self.donor_with_coords_verified = self._create_donor(
			username='verified_user',
			first_name='Verified',
			latitude=Decimal('12.971598'),
			longitude=Decimal('77.594566'),
			location_verified=True,
		)

		self.donor_with_coords_pending = self._create_donor(
			username='pending_user',
			first_name='Pending',
			latitude=Decimal('28.613939'),
			longitude=Decimal('77.209023'),
			location_verified=False,
		)

		self.donor_without_coords = self._create_donor(
			username='no_coords',
			first_name='NoCoords',
			latitude=None,
			longitude=None,
			address='Unknown Address 12345',
		)

	def _create_donor(self, username, first_name, latitude, longitude, location_verified=False, address='Test Address'):
		user = User.objects.create_user(username=username, password='password', first_name=first_name, last_name='Donor')
		return dmodels.Donor.objects.create(
			user=user,
			bloodgroup='O+',
			address=address,
			mobile='9999999999',
			latitude=latitude,
			longitude=longitude,
			location_verified=location_verified,
		)

	def test_admin_donor_map_context_counts(self):
		self.client.force_login(self.admin)
		response = self.client.get(reverse('admin-donor-map'))

		self.assertEqual(response.status_code, 200)
		context = response.context

		self.assertEqual(context['total_donors'], 3)
		self.assertEqual(context['pin_ready'], 2)
		self.assertEqual(context['verified_count'], 1)
		self.assertEqual(context['pending_count'], 1)
		self.assertEqual(context['without_coordinates'], 1)

		listed_donors = context['donors']
		self.assertEqual(len(listed_donors), 2)  # only donors with coordinates appear
		self.assertTrue(all(d.latitude is not None and d.longitude is not None for d in listed_donors))

		markers = context['map_data']
		self.assertEqual(len(markers), 2)
		marker_ids = {marker['id'] for marker in markers}
		self.assertSetEqual(marker_ids, {self.donor_with_coords_verified.id, self.donor_with_coords_pending.id})

	def test_bulk_geocode_action_assigns_coordinates(self):
		self.client.force_login(self.admin)
		donor = self._create_donor(
			username='auto_geo',
			first_name='Auto',
			latitude=None,
			longitude=None,
		)
		donor.address = 'Test Address'
		donor.save(update_fields=['address'])

		response = self.client.post(reverse('admin-donor-map'), {'intent': 'bulk_geocode', 'limit': 5})
		self.assertEqual(response.status_code, 302)
		donor.refresh_from_db()
		self.assertIsNotNone(donor.latitude)
		self.assertIsNotNone(donor.longitude)
		self.assertFalse(donor.location_verified)


class DonorAutoGeocodeSignalTests(TestCase):
	def test_signal_assigns_coordinates_when_missing(self):
		user = User.objects.create_user('geo_user', password='password', first_name='Geo', last_name='Signal')
		donor = dmodels.Donor.objects.create(
			user=user,
			bloodgroup='B+',
			address='Test Address',
			mobile='1234567890',
		)
		self.assertIsNotNone(donor.latitude)
		self.assertIsNotNone(donor.longitude)
		self.assertEqual(str(donor.latitude), '12.971599')
		self.assertEqual(str(donor.longitude), '77.594566')
