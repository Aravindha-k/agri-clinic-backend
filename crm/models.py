from django.db import models


class Farmer(models.Model):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=15, unique=True)
    village = models.CharField(max_length=255)


class Visit(models.Model):
    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="visits")
    crop = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)


class VisitReview(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="reviews")
    notes = models.TextField()
    visit_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
