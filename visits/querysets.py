from visits.models import Visit
from visits.submitted import submitted_visits_qs
from visits.visit_response import VISIT_LIST_SELECT_RELATED


def visits_with_relations():
    return Visit.objects.select_related(*VISIT_LIST_SELECT_RELATED)


def submitted_visits_with_relations():
    return submitted_visits_qs(visits_with_relations())
