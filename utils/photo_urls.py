"""Build absolute URLs for profile photo fields."""


def build_profile_photo_url(request, image_field) -> str | None:
    if not image_field:
        return None
    try:
        url = image_field.url
    except (ValueError, AttributeError):
        return None
    if request:
        return request.build_absolute_uri(url)
    return url
