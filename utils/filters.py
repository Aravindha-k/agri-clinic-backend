"""DRF filter backends with prefix search semantics."""

from django.db.models.constants import LOOKUP_SEP

from rest_framework.filters import SearchFilter


class PrefixSearchFilter(SearchFilter):
    """
    DRF SearchFilter that defaults to case-insensitive prefix matching.

    Explicit lookup prefixes (^, =, @, $) in search_fields are still honored.
    """

    def construct_search(self, field_name, queryset=None):
        lookup = self.lookup_prefixes.get(field_name[0])
        if lookup:
            field_name = field_name[1:]
        else:
            lookup = "istartswith"
        return LOOKUP_SEP.join([field_name, lookup])
