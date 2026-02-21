from __future__ import annotations

from app.models import PhotoAsset, ShootSettings

ANGLE_LABELS = {
    "DRONE_TOP": "top-down drone view",
    "LOW_FROM_BELOW": "low angle from below",
    "SIDE_PROFILE": "side profile",
    "DUTCH_ANGLE": "dutch angle",
    "PANORAMA_360": "360 panoramic perspective",
    "FOOT_LEVEL": "foot-level camera angle",
    "ARM_LENGTH_SELFIE": "arm-length selfie angle",
    "NON_SELFIE_PORTRAIT": "eye-level portrait angle",
}


def build_final_prompt(
    profile_text: str,
    scene_text: str,
    shoot_settings: ShootSettings,
    face_signature_text: str,
    photos: list[PhotoAsset],
) -> str:
    _ = photos
    lens = f'{shoot_settings.lens_mm}mm' if shoot_settings.lens_selected and shoot_settings.lens_mm else "natural lens"
    angle = ANGLE_LABELS.get(shoot_settings.angle_code, shoot_settings.angle_code.lower().replace("_", " "))
    framing = shoot_settings.framing_code.lower().replace("_", " ")

    lines = [
        "1) Subject: same person as reference photos",
        "2) Identity constraints: keep facial features consistent; no face swap; no drastic ethnicity/age change",
        f"3) Physical description: {profile_text} {face_signature_text}".strip(),
        f"4) Scene: {scene_text}",
        "5) Camera:",
        f'   - lens: "{lens}"',
        f"   - angle: {angle}",
        f"   - framing: {framing}",
        "6) Quality: cinematic, realistic skin texture, natural lighting, high detail, sharp focus",
        "7) Negative: artifacts, extra fingers, deformed face, blur, watermark, text",
    ]
    return "\n".join(lines)
