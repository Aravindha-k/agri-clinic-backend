from .dashboard import MobileDashboardAPI
from .work import MobileWorkStartAPI, MobileWorkStopAPI, MobileWorkStatusAPI
from .visit_stats import MobileVisitStatsAPI
from .tracking import MobileTrackingAPI
from .reports import MobileReportsAPI
from .visits import (
    MobileVisitListCreateAPI,
    MobileVisitDetailAPI,
    MobileVisitMediaUploadAPI,
)
from visits.attachment_views import (
    MobileVisitAttachmentListCreateAPI,
    MobileVisitAttachmentDeleteAPI,
)
from mobile_api.profile import MobileProfilePhotoAPI
from farmers.photo_views import MobileFarmerPhotoAPI
from .farmers import MobileFarmerListAPI, MobileFarmerDetailAPI
from .map import MobileVisitMapAPI
