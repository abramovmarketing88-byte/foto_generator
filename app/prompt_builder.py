from __future__ import annotations

from app.models import PhotoAsset, ShootSettings, Profile

ANGLE_LABELS = {
    "DRONE_TOP": "top-down drone view",
    "LOW_FROM_BELOW": "low angle from below",
    "SIDE_PROFILE": "side profile",
    "DUTCH_ANGLE": "dutch angle",
    "PANORAMA_360": "360 panoramic perspective",
    "FOOT_LEVEL": "foot-level camera angle",
    "ARM_LENGTH_SELFIE": "arm-length selfie angle",
    "NON_SELFIE_PORTRAIT": "eye-level portrait angle",
    "AUTO": "natural camera angle (model's choice)",
}


def _profile_physical_desc(profile: Profile) -> str:
    """Build physical description from structured profile fields."""
    parts = []
    if profile.height_cm:
        parts.append(f"height {profile.height_cm} cm")
    if profile.weight_kg:
        parts.append(f"weight {profile.weight_kg} kg")
    if profile.hair_color:
        parts.append(f"hair {profile.hair_color}")
    if profile.eye_color:
        parts.append(f"eyes {profile.eye_color}")
    if profile.body_type:
        parts.append(f"body type {profile.body_type}")
    if profile.profile_text:
        parts.append(profile.profile_text)
    return ", ".join(parts) if parts else profile.profile_text or ""


def build_final_prompt(
    profile: Profile,
    scene_text: str,
    shoot_settings: ShootSettings,
    face_signature_text: str,
    photos: list[PhotoAsset],
) -> str:
    _ = photos
    physical = _profile_physical_desc(profile)
    lens = f'{shoot_settings.lens_mm}mm' if shoot_settings.lens_selected and shoot_settings.lens_mm else "natural lens"
    angle = ANGLE_LABELS.get(shoot_settings.angle_code, shoot_settings.angle_code.lower().replace("_", " "))
    framing = getattr(shoot_settings, "framing_code", None) or "half body"
    framing = framing.lower().replace("_", " ")

    lines = [
        "1) Subject: same person as reference photos",
        "2) Identity constraints: keep facial features consistent; no face swap; no drastic ethnicity/age change",
        f"3) Physical description: {physical} {face_signature_text}".strip(),
        f"4) Scene: {scene_text}",
        "5) Camera:",
        f'   - lens: "{lens}"',
        f"   - angle: {angle}",
        f"   - framing: {framing}",
        "6) Quality: cinematic, realistic skin texture, natural lighting, high detail, sharp focus",
        "7) Negative: artifacts, extra fingers, deformed face, blur, watermark, text",
    ]
    return "\n".join(lines)
