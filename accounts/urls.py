from django.urls import path
from .views import (
    CreateEmployeeAPI,
    MeAPI,
    AdminResetPasswordAPI,
    EmployeeListAPI,
    ToggleEmployeeStatusAPI,
    AdminEmployeeUpdateDeleteAPI,
)

urlpatterns = [
    path("create-employee/", CreateEmployeeAPI.as_view()),
    path("me/", MeAPI.as_view()),
    path("reset-password/", AdminResetPasswordAPI.as_view()),
    path("employees/", EmployeeListAPI.as_view()),
    path("employees/<str:employee_id>/toggle/", ToggleEmployeeStatusAPI.as_view()),
    path("employees/<int:emp_id>/", AdminEmployeeUpdateDeleteAPI.as_view()),
]
