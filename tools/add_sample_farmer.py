from masters.models import Farmer, District, Village
from django.contrib.auth import get_user_model

# Get or create related objects
User = get_user_model()
user = User.objects.filter(is_staff=True).first()  # Use any admin or staff user

district, _ = District.objects.get_or_create(name="Sample District")
village, _ = Village.objects.get_or_create(name="Sample Village", district=district)

# Create Farmer
farmer = Farmer.objects.create(
    name="Test Farmer",
    phone="9999999999",
    district=district,
    village=village,
    address="123 Test Lane",
    gps_location="12.3456,78.9012",
    total_land_area=2.5,
    irrigation_type="canal",
    soil_type="loamy",
    assigned_employee=user,
    is_active=True,
    created_by_employee=user,
)

print(f"Created Farmer: {farmer.id} - {farmer.name}")
