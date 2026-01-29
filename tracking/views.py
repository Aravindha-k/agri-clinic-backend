from datetime import timedelta
import math

from django.utils import timezone
from django.utils.dateparse import parse_date

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status

from accounts.models import EmployeeProfile
from tracking.models import WorkDay, AvailabilityEvent, LocationLog


# ======================================================
# ✅ Utility: Distance Calculation
# ======================================================
def distance_km(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius km

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ======================================================
# ✅ START DAY
# ======================================================
class StartDayAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.is_staff:
            return Response(
                {"detail": "Admins cannot start workday"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ✅ Block inactive employees
        profile = EmployeeProfile.objects.filter(user=request.user).first()
        if profile and not profile.is_active_employee:
            return Response(
                {"error": "Inactive employee cannot start workday"},
                status=403,
            )

        workday = WorkDay.objects.create(
            user=request.user,
            date=timezone.now().date(),
            start_time=timezone.now(),
            is_active=True,
        )

        return Response(
            {"message": "Workday started", "date": workday.date},
            status=status.HTTP_201_CREATED,
        )


# ======================================================
# ✅ END DAY
# ======================================================
class EndDayAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        workday = WorkDay.objects.filter(user=request.user, is_active=True).first()

        if not workday:
            return Response({"detail": "No active workday"}, status=400)

        workday.end_time = timezone.now()
        workday.is_active = False
        workday.save()

        return Response({"message": "Workday ended"}, status=200)


# ======================================================
# ✅ HEARTBEAT
# ======================================================
class HeartbeatAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # ✅ Block inactive employees
        profile = EmployeeProfile.objects.filter(user=request.user).first()
        if profile and not profile.is_active_employee:
            return Response(
                {"error": "Inactive employee cannot send heartbeat"},
                status=403,
            )

        workday = WorkDay.objects.filter(user=request.user, is_active=True).first()

        if workday:
            workday.last_heartbeat = timezone.now()
            workday.save(update_fields=["last_heartbeat"])

        return Response({"message": "Heartbeat received"}, status=200)


# ======================================================
# ✅ PUSH LOCATION (GPS Logging)
# ======================================================
class PushLocationAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        # ✅ RULE 0: Block inactive employees
        profile = EmployeeProfile.objects.filter(user=user).first()
        if profile and not profile.is_active_employee:
            return Response(
                {"error": "Inactive employees cannot push GPS"},
                status=403,
            )

        lat = float(request.data.get("latitude"))
        lng = float(request.data.get("longitude"))
        accuracy = float(request.data.get("accuracy", 999))

        # ✅ RULE 1: Reject poor accuracy
        if accuracy > 50:
            return Response({"error": "Low GPS accuracy ignored"}, status=400)

        # ✅ RULE 2: Must have active workday
        workday = WorkDay.objects.filter(user=user, is_active=True).first()

        if not workday:
            return Response(
                {"error": "Workday not started. Cannot log location."},
                status=400,
            )

        # ✅ RULE 3: Ignore GPS jump > 5km
        last_point = (
            LocationLog.objects.filter(user=user, workday=workday)
            .order_by("-recorded_at")
            .first()
        )

        if last_point:
            jump = distance_km(
                float(last_point.latitude),
                float(last_point.longitude),
                lat,
                lng,
            )

            if jump > 5:
                return Response(
                    {
                        "error": "GPS jump detected, point ignored",
                        "jump_km": round(jump, 2),
                    },
                    status=400,
                )

        # ✅ SAVE POINT
        LocationLog.objects.create(
            user=user,
            workday=workday,
            latitude=lat,
            longitude=lng,
            accuracy=accuracy,
            recorded_at=timezone.now(),
        )

        return Response({"message": "Location saved successfully"}, status=201)


# ======================================================
# ✅ ADMIN: Tracking Status List
# ======================================================
class AdminTrackingStatusAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response({"detail": "Admin only"}, status=403)

        now = timezone.now()

        # ✅ FIX: Only Active Employees
        employees = EmployeeProfile.objects.select_related("user").filter(
            is_active_employee=True
        )

        data = []

        for emp in employees:
            user = emp.user

            work_status = "NOT_WORKING"
            connection = "OFFLINE"
            gps_status = "GPS_OFF"
            session_status = "N/A"

            workday = WorkDay.objects.filter(user=user, is_active=True).first()

            if workday:
                work_status = "WORKING"

                # ✅ Online check (heartbeat)
                if workday.last_heartbeat and workday.last_heartbeat > now - timedelta(
                    minutes=5
                ):
                    connection = "ONLINE"

                # ✅ GPS OFF event check
                gps_off = AvailabilityEvent.objects.filter(
                    user=user,
                    workday=workday,
                    event_type="GPS_OFF",
                    end_time__isnull=True,
                ).exists()

                gps_status = "GPS_OFF" if gps_off else "GPS_ON"
                session_status = "NORMAL"

            data.append(
                {
                    "employee_id": emp.employee_id,
                    "user_id": user.id,
                    "username": user.username,
                    "phone": emp.phone,
                    "work_status": work_status,
                    "connection": connection,
                    "gps_status": gps_status,
                    "session": session_status,
                }
            )

        return Response(data)


# ======================================================
# ✅ ADMIN: Employee Route Locations
# ======================================================
class AdminEmployeeLocationAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, user_id):
        # ✅ Block inactive employee map access
        profile = EmployeeProfile.objects.filter(user_id=user_id).first()

        if profile and not profile.is_active_employee:
            return Response(
                {"error": "Inactive employee route not accessible"},
                status=403,
            )

        date = request.GET.get("date")

        queryset = LocationLog.objects.filter(user_id=user_id)

        if date:
            d = parse_date(date)
            queryset = queryset.filter(recorded_at__date=d)

        points = queryset.order_by("recorded_at")

        data = [
            {
                "latitude": p.latitude,
                "longitude": p.longitude,
                "recorded_at": p.recorded_at,
            }
            for p in points
        ]

        return Response(data)
