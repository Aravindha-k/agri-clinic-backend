from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from .permissions import IsEmployeeUser
from utils.response import success_response


class MobileVisitStatsAPI(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeUser]

    def get(self, request):
        # Dummy data for now, replace with real query
        data = {
            "today_visits": 0,
            "total_visits": 0,
            "completed": 0,
            "pending": 0,
        }
        return success_response(data=data, message="Visit stats fetched")


# Add other mobile endpoints here
