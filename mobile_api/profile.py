"""Mobile profile photo upload."""

from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.profile_photos import MobileEmployeePhotoAPI

# Canonical mobile upload view (PATCH /api/v1/mobile/profile/photo/)
MobileProfilePhotoAPI = MobileEmployeePhotoAPI
