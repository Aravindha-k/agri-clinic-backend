from django.contrib import admin

# Register your models here.
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser
from django.utils.dateparse import parse_date

from tracking.models import LocationPing


class AdminLocationAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, user_id):
        date = request.GET.get("date")

        queryset = LocationPing.objects.filter(user_id=user_id)

        # ✅ Filter by Date if provided
        if date:
            d = parse_date(date)
            queryset = queryset.filter(recorded_at__date=d)

        points = queryset.order_by("recorded_at")

        data = [
            {
                "latitude": p.latitude,
                "longitude": p.longitude,
                "recorded_at": p.recorded_at,
                "is_visit": p.is_visit,
            }
            for p in points
        ]

        return Response(data)
