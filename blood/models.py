from django.db import models

from patient import models as pmodels
from donor import models as dmodels


def generate_confirmation_token() -> str:
    """Legacy helper kept so historic migrations keep importing cleanly."""

    return "legacy-token"

class Stock(models.Model):
    bloodgroup=models.CharField(max_length=10)
    unit=models.PositiveIntegerField(default=0)
    def __str__(self):
        return self.bloodgroup

class BloodRequest(models.Model):
    patient=models.ForeignKey(pmodels.Patient,null=True,blank=True,on_delete=models.CASCADE)
    request_by_donor=models.ForeignKey(dmodels.Donor,null=True,blank=True,on_delete=models.CASCADE)
    patient_name=models.CharField(max_length=30)
    patient_age=models.PositiveIntegerField()
    reason=models.CharField(max_length=500)
    bloodgroup=models.CharField(max_length=10)
    unit=models.PositiveIntegerField(default=0)
    status=models.CharField(max_length=20,default="Pending")
    date=models.DateField(auto_now=True)
    is_urgent = models.BooleanField(default=False)
    request_zipcode = models.CharField(max_length=12, blank=True)

    # Admin SMS diagnostics (last approval notification attempt)
    sms_last_approval_attempt_at = models.DateTimeField(null=True, blank=True)
    sms_last_approval_patient_to = models.CharField(max_length=32, blank=True)
    sms_last_approval_donor_to = models.CharField(max_length=32, blank=True)
    sms_last_approval_result = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=~(models.Q(patient__isnull=False) & models.Q(request_by_donor__isnull=False)),
                name="bloodrequest_not_both_patient_and_donor",
            ),
        ]

    def __str__(self):
        return f"{self.patient_name} - {self.bloodgroup}"


class Feedback(models.Model):
    AUTHOR_DONOR = "DONOR"
    AUTHOR_PATIENT = "PATIENT"
    AUTHOR_ANONYMOUS = "ANONYMOUS"

    FEEDBACK_DONATION = "DONATION"
    FEEDBACK_REQUEST = "REQUEST"
    FEEDBACK_GENERAL = "GENERAL"

    ADMIN_REACTIONS = [
        ("", "—"),
        ("👍", "👍"),
        ("❤️", "❤️"),
        ("🙏", "🙏"),
        ("👏", "👏"),
        ("😊", "😊"),
        ("🎉", "🎉"),
    ]

    author_type = models.CharField(
        max_length=16,
        choices=[
            (AUTHOR_DONOR, "Donor"),
            (AUTHOR_PATIENT, "Patient"),
            (AUTHOR_ANONYMOUS, "Anonymous"),
        ],
        default=AUTHOR_ANONYMOUS,
    )
    donor = models.ForeignKey(dmodels.Donor, null=True, blank=True, on_delete=models.SET_NULL)
    patient = models.ForeignKey(pmodels.Patient, null=True, blank=True, on_delete=models.SET_NULL)

    display_name = models.CharField(max_length=60, blank=True)

    # Internal flag used by demo seeding commands so we can safely refresh/cleanup
    # seeded records without touching real user feedback.
    is_seeded_demo = models.BooleanField(default=False, db_index=True)

    feedback_for = models.CharField(
        max_length=16,
        choices=[
            (FEEDBACK_DONATION, "Donation"),
            (FEEDBACK_REQUEST, "Request"),
            (FEEDBACK_GENERAL, "General"),
        ],
        default=FEEDBACK_GENERAL,
    )
    rating = models.PositiveSmallIntegerField(default=5)
    message = models.TextField(max_length=1200)

    image1 = models.ImageField(upload_to="feedback/%Y/%m/", null=True, blank=True)
    image2 = models.ImageField(upload_to="feedback/%Y/%m/", null=True, blank=True)
    image3 = models.ImageField(upload_to="feedback/%Y/%m/", null=True, blank=True)

    is_public = models.BooleanField(default=True)

    admin_reaction = models.CharField(max_length=8, blank=True, choices=ADMIN_REACTIONS)
    admin_reply = models.TextField(max_length=1200, blank=True)
    admin_updated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                check=~(models.Q(donor__isnull=False) & models.Q(patient__isnull=False)),
                name="feedback_not_both_donor_and_patient",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(author_type="ANONYMOUS", donor__isnull=True, patient__isnull=True)
                    | models.Q(author_type="DONOR", donor__isnull=False, patient__isnull=True)
                    | models.Q(author_type="PATIENT", donor__isnull=True, patient__isnull=False)
                ),
                name="feedback_author_matches_fk",
            ),
            models.CheckConstraint(
                check=models.Q(rating__gte=1) & models.Q(rating__lte=5),
                name="feedback_rating_1_to_5",
            ),
        ]

    @property
    def author_label(self) -> str:
        if self.author_type == self.AUTHOR_DONOR and self.donor_id:
            return self.donor.get_name
        if self.author_type == self.AUTHOR_PATIENT and self.patient_id:
            return self.patient.get_name
        return self.display_name.strip() or "Anonymous"

    def __str__(self):
        return f"{self.author_label} ({self.rating}★)"

