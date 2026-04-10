from django.db import migrations
from datetime import datetime


def preload_crops(apps, schema_editor):
    Crop = apps.get_model("masters", "Crop")
    crops = [
        ("Paddy", "நெல்"),
        ("Sugarcane", "கரும்பு"),
        ("Banana", "வாழை"),
        ("Blackgram", "உளுந்து"),
        ("Greengram", "பச்சைபயிறு"),
        ("Sesame", "எள்"),
        ("Maize", "மக்காச்சோளம்"),
        ("Groundnut", "மணிலா"),
        ("Cotton", "பருத்தி"),
        ("Bajra", "கம்பு"),
        ("Cowpea", "தட்டப்பயிறு"),
        ("Okra", "வெண்டை"),
        ("Brinjal", "கத்தரி"),
        ("Chilli", "மிளகாய்"),
        ("Watermelon", "தர்பூசணி"),
        ("Muskmelon", "முலாம்பழம்"),
        ("Bitter gourd", "பாகல்"),
        ("Ridge gourd", "பீர்க்கன்"),
        ("Snake gourd", "புடலை"),
        ("Bottle gourd", "சுரக்காய்"),
        ("Cucumber", "வெள்ளரி"),
        ("Tapioca", "மரவள்ளி"),
        ("Tinda", "திண்டா"),
        ("Tomato", "தக்காளி"),
        ("Mango", "மா"),
        ("Cashew", "முந்திரி"),
        ("Lemon", "எலுமிச்சை"),
        ("Coconut", "தென்னை"),
        ("Papaya", "பப்பாளி"),
        ("Guava", "கொய்யா"),
        ("Sapota", "சப்போட்டா"),
        ("Amla", "நெல்லி"),
        ("Jackfruit", "பலா"),
    ]
    for name_en, name_ta in crops:
        Crop.objects.get_or_create(
            name_en=name_en,
            name_ta=name_ta,
            defaults={"is_active": True, "created_at": datetime.now()},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0012_make_crop_names_nullable"),
    ]
    operations = [
        migrations.RunPython(preload_crops),
    ]
