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
    patient=models.ForeignKey(pmodels.Patient,null=True,on_delete=models.CASCADE)
    request_by_donor=models.ForeignKey(dmodels.Donor,null=True,on_delete=models.CASCADE)
    patient_name=models.CharField(max_length=30)
    patient_age=models.PositiveIntegerField()
    reason=models.CharField(max_length=500)
    bloodgroup=models.CharField(max_length=10)
    unit=models.PositiveIntegerField(default=0)
    status=models.CharField(max_length=20,default="Pending")
    date=models.DateField(auto_now=True)
    is_urgent = models.BooleanField(default=False)
    request_zipcode = models.CharField(max_length=12, blank=True)
    def __str__(self):
        return f"{self.patient_name} - {self.bloodgroup}"

