"""Mobile wrappers that always enforce EmployeeDeviceSession."""

from mobile_api.device_session import DeviceSessionRequiredMixin
from masters.problem_views import VisitFormOptionsAPI as BaseVisitFormOptionsAPI


class MobileVisitFormOptionsAPI(DeviceSessionRequiredMixin, BaseVisitFormOptionsAPI):
    """GET /api/v1/mobile/visit-form-options/ — requires X-Device-Session."""

    pass
