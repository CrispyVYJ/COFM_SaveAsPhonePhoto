"""
◈ COFM Save as Phone Photo — a single-node Comfy OFM pack.

Re-saves images as phone-camera JPEGs. The node is themed by web/cofm_theme.js,
which styles any node whose CATEGORY sits under "ComfyOFM/".
"""

from .cofm_theme import register
from .phone_photo import COFM_SaveAsPhonePhoto

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
register(COFM_SaveAsPhonePhoto, NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS)

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
