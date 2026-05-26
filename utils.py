import base64
import hashlib
import html
import re

import qrcode
from PIL import Image


def safe_html(value):
    return html.escape("" if value is None else str(value), quote=True)


def qr_file_path(item_code):
    item_code_text = str(item_code)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", item_code_text).strip("._")
    safe_name = safe_name or "item"
    digest = hashlib.sha256(item_code_text.encode("utf-8")).hexdigest()[:8]
    return f"qr_{safe_name}_{digest}.png"


def decode_qr_from_image(uploaded_image):
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None, "OpenCV is not installed. Run: pip install -r requirements.txt"

    image = Image.open(uploaded_image).convert("RGB")
    image_array = np.array(image)
    detector = cv2.QRCodeDetector()
    decoded_text, _, _ = detector.detectAndDecode(image_array)

    if decoded_text:
        return decoded_text.strip(), None

    if hasattr(cv2, "barcode_BarcodeDetector"):
        try:
            barcode_detector = cv2.barcode_BarcodeDetector()
            barcode_result = barcode_detector.detectAndDecode(image_array)

            if len(barcode_result) >= 2:
                decoded_info = barcode_result[1]

                if decoded_info is None:
                    return None, "No QR or barcode detected. Try a clearer image with the code centered."

                if isinstance(decoded_info, str) and decoded_info:
                    return decoded_info.strip(), None

                for decoded_value in decoded_info:
                    if decoded_value:
                        return decoded_value.strip(), None

        except cv2.error:
            pass

    return None, "No QR or barcode detected. Try a clearer image with the code centered."


def generate_qr(item_code):
    qr = qrcode.make(item_code)
    path = qr_file_path(item_code)
    qr.save(path)
    return path


def image_to_base64(path):
    with open(path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")
