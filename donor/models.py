from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

class Donor(models.Model):
    user=models.OneToOneField(User,on_delete=models.CASCADE)
    profile_pic= models.ImageField(upload_to='profile_pic/Donor/',null=True,blank=True)

    bloodgroup=models.CharField(max_length=10)
    address = models.CharField(max_length=255)
    mobile = models.CharField(max_length=20,null=False)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
        help_text="Decimal latitude between -90 and 90"
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
        help_text="Decimal longitude between -180 and 180"
    )
    location_verified = models.BooleanField(default=False)
    zipcode = models.CharField(max_length=12, blank=True)
    is_available = models.BooleanField(default=True)
    availability_updated_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)
   
    @property
    def get_name(self):
        return self.user.first_name+" "+self.user.last_name
    
    @property
    def get_instance(self):
        return self
    
    @property
    def has_profile_pic(self):
        return self.profile_pic and hasattr(self.profile_pic, 'url')
    
    def __str__(self):
        return self.user.first_name

    def mark_availability(self, available: bool):
        self.is_available = available
        self.availability_updated_at = timezone.now()
        self.save(update_fields=["is_available", "availability_updated_at"])

class BloodDonate(models.Model): 
    donor=models.ForeignKey(Donor,on_delete=models.CASCADE)   
    disease=models.CharField(max_length=100,default="Nothing")
    age=models.PositiveIntegerField()
    bloodgroup=models.CharField(max_length=10)
    unit=models.PositiveIntegerField(default=0)
    status=models.CharField(max_length=20,default="Pending")
    date=models.DateField(auto_now=True)
    
    def __str__(self):
        return f"{self.donor.get_name} - {self.bloodgroup} - {self.status}"
    
    class Meta:
        ordering = ['-date', '-id']  # Most recent first
        verbose_name = "Blood Donation"
        verbose_name_plural = "Blood Donations"