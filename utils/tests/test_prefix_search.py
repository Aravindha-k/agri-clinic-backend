"""Unit tests for prefix search helpers."""

from django.core.exceptions import FieldError
from django.test import TestCase

from masters.models import District, Farmer
from utils.prefix_search import (
    filter_queryset_by_prefix_search,
    normalize_search_term,
    prefix_search_q,
)


class PrefixSearchHelperTests(TestCase):
    def test_normalize_search_term(self):
        self.assertEqual(normalize_search_term("  Ara  "), "Ara")
        self.assertEqual(normalize_search_term("   "), "")
        self.assertEqual(normalize_search_term(None), "")

    def test_prefix_search_q_builds_istartswith(self):
        q = prefix_search_q(["name", "phone"], "Ara")
        self.assertEqual(q.children, [("name__istartswith", "Ara"), ("phone__istartswith", "Ara")])
        self.assertEqual(q.connector, "OR")

    def test_filter_queryset_by_prefix_search(self):
        district = District.objects.create(name="Villupuram")
        match = Farmer.objects.create(name="Aravindh", phone="9626262922", district=district)
        Farmer.objects.create(name="Suresh", phone="9111111111", district=district)
        qs = filter_queryset_by_prefix_search(Farmer.objects.all(), "Ara", ["name"])
        self.assertEqual(list(qs), [match])
        qs = filter_queryset_by_prefix_search(Farmer.objects.all(), "rav", ["name"])
        self.assertEqual(qs.count(), 0)
