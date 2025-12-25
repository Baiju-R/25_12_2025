from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from donor.models import Donor
from blood.models import BloodRequest
from blood.services.donor_recommender import recommend_donors_for_request


class DonorRecommenderTests(TestCase):
    def test_recommender_filters_by_recovery(self):
        user = User.objects.create(username="d1")
        donor = Donor.objects.create(
            user=user,
            bloodgroup="O+",
            address="x",
            mobile="1",
            is_available=True,
            last_donated_at=timezone.now().date() - timedelta(days=10),
        )
        req = BloodRequest.objects.create(
            patient=None,
            request_by_donor=None,
            patient_name="p",
            patient_age=30,
            reason="r",
            bloodgroup="O+",
            unit=200,
            status="Pending",
        )

        recs = recommend_donors_for_request(req, require_eligible=True)
        self.assertEqual(len(recs), 0)

        donor.last_donated_at = timezone.now().date() - timedelta(days=120)
        donor.save(update_fields=["last_donated_at"])

        recs = recommend_donors_for_request(req, require_eligible=True)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].donor.id, donor.id)

    def test_recommender_requires_exact_bloodgroup(self):
        user = User.objects.create(username="d2")
        Donor.objects.create(
            user=user,
            bloodgroup="A+",
            address="x",
            mobile="1",
            is_available=True,
            last_donated_at=None,
        )
        req = BloodRequest.objects.create(
            patient=None,
            request_by_donor=None,
            patient_name="p",
            patient_age=30,
            reason="r",
            bloodgroup="O+",
            unit=200,
            status="Pending",
        )
        recs = recommend_donors_for_request(req, require_eligible=True)
        self.assertEqual(recs, [])
