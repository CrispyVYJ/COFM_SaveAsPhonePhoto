"""
Comfy OFM — shared node theme (single source of truth, Python side).

Everything a COFM node needs in order to look like a COFM node lives here:
the palette, the category namespace, the display-name marker, and the
DESCRIPTION formatter. A node subclasses :class:`CofmNodeMixin`, sets a few
plain-text attributes, and inherits the whole look with no styling code.

The matching visual layer is web/cofm_theme.js. That file carries its own
COFM config object (the canvas renderer cannot import Python), so the two
palettes are duplicated by design. If you change a colour here, change it
there too.
"""

# ---------------------------------------------------------------------------
# THE ONE DICT. Everything tunable on the Python side is in here.
# ---------------------------------------------------------------------------

COFM_THEME = {
    # Circuit-board palette, taken from the community logo.
    "palette": {
        "cyan":    "#4FD6F0",
        "mint":    "#6FE8B0",
        "lime":    "#A6F065",
        "violet":  "#8B7BF0",
        "magenta": "#E070C8",
        "bg":      "#0C121F",  # node body fill
        "bg_2":    "#131B2E",  # panel / widget fill
        "trace":   "#1E2C45",  # inner border + traces at rest
    },

    # Neon ring order. The JS header gradient and the trace pulses both walk
    # this list in order and wrap magenta -> cyan.
    "gradient": ["#4FD6F0", "#6FE8B0", "#A6F065", "#8B7BF0", "#E070C8"],

    # Category namespace. The web extension themes any node whose CATEGORY
    # starts with this string, so every COFM category must live beneath it —
    # that is why there is a trailing slash and why nothing sits at the bare
    # root. Touching this means touching cofm_theme.js's COFM.namespace.
    "namespace": "ComfyOFM",

    # Display-name marker. Node titles read "◈ COFM Save as Phone Photo".
    "marker": "◈",
    "display_prefix": "◈ COFM",

    # Node-ID prefix, so COFM node IDs never collide with other packs.
    "id_prefix": "COFM_",

    # DESCRIPTION formatting (the tooltip body ComfyUI shows on hover).
    "description": {
        "rule": "─" * 34,
        "params_heading": "Inputs",
        "note_heading": "Note",
        "footer": "Comfy OFM",
    },
}

PALETTE = COFM_THEME["palette"]
GRADIENT = COFM_THEME["gradient"]
NAMESPACE = COFM_THEME["namespace"]


# ---------------------------------------------------------------------------
# Helpers — use these instead of hand-writing strings, so a namespace or
# marker change stays a one-line edit in the dict above.
# ---------------------------------------------------------------------------

def cofm_category(*parts: str) -> str:
    """Build a themed CATEGORY.

    ``cofm_category("Image")`` -> ``"ComfyOFM/Image"``

    Always returns at least one path segment under the namespace, because the
    web extension matches on the ``"ComfyOFM/"`` prefix — a bare ``"ComfyOFM"``
    would silently render unthemed.
    """
    cleaned = [str(p).strip("/") for p in parts if str(p).strip("/")]
    if not cleaned:
        cleaned = ["General"]
    return "/".join([NAMESPACE, *cleaned])


def cofm_display(name: str) -> str:
    """Build a themed display name: ``"Save as Phone Photo"`` -> ``"◈ COFM Save as Phone Photo"``."""
    return f"{COFM_THEME['display_prefix']} {name.strip()}"


def cofm_node_id(name: str) -> str:
    """Build a collision-proof node ID: ``"SaveAsPhonePhoto"`` -> ``"COFM_SaveAsPhonePhoto"``."""
    name = name.strip()
    prefix = COFM_THEME["id_prefix"]
    return name if name.startswith(prefix) else f"{prefix}{name}"


def cofm_description(title, summary="", params=None, note="") -> str:
    """Render a DESCRIPTION block in the house format.

    Every COFM node's tooltip has the same shape, so the eye learns where to
    look once and then knows where to look on all of them::

        ◈ COFM Save as Phone Photo
        ──────────────────────────────────
        Saves images as phone-camera JPEGs.

        Inputs
          phone_model  — whose EXIF profile to use
          quality      — JPEG quality

        Note
          Files never overwrite.

        Comfy OFM

    ``params`` accepts a dict or a sequence of ``(name, blurb)`` pairs.
    """
    fmt = COFM_THEME["description"]
    lines = [cofm_display(title), fmt["rule"]]

    if summary:
        lines.append(str(summary).strip())

    if params:
        items = params.items() if isinstance(params, dict) else params
        items = [(str(k).strip(), str(v).strip()) for k, v in items]
        if items:
            width = max(len(k) for k, _ in items)
            lines.append("")
            lines.append(fmt["params_heading"])
            lines.extend(f"  {k.ljust(width)}  — {v}" for k, v in items)

    if note:
        lines.append("")
        lines.append(fmt["note_heading"])
        lines.extend(f"  {ln.strip()}" for ln in str(note).strip().splitlines())

    lines.append("")
    lines.append(fmt["footer"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The mixin. Inherit it and the node is themed.
# ---------------------------------------------------------------------------

class CofmNodeMixin:
    """Give a node the COFM category, tooltip format, and visual identity.

    Adding a node needs no styling code at all — the JS extension keys purely
    off CATEGORY, so simply landing under the namespace is enough. What this
    mixin adds on top is consistency: one category helper and one tooltip
    format shared by every COFM node.

    Declare intent with plain class attributes::

        class COFM_SaveAsPhonePhoto(CofmNodeMixin):
            COFM_SECTION = "Image"
            COFM_TITLE   = "Save as Phone Photo"
            COFM_SUMMARY = "Saves images as phone-camera JPEGs."
            COFM_PARAMS  = {"phone_model": "whose EXIF profile to use"}
            COFM_NOTE    = "Files never overwrite."

    ``CATEGORY`` and ``DESCRIPTION`` are then filled in automatically at class
    creation. Set either one explicitly and your value is left alone.
    """

    # Sensible defaults so a node that declares nothing still lands in-theme.
    COFM_SECTION = "General"
    COFM_TITLE = ""
    COFM_SUMMARY = ""
    COFM_PARAMS = None
    COFM_NOTE = ""

    CATEGORY = cofm_category("General")

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        # CATEGORY — derive from COFM_SECTION unless this class set its own.
        # `"CATEGORY" in cls.__dict__` (not getattr) so an inherited value from
        # the mixin counts as "not set" and still gets derived per-subclass.
        if "CATEGORY" not in cls.__dict__:
            cls.CATEGORY = cofm_category(cls.COFM_SECTION)

        # DESCRIPTION — build the house tooltip unless one was written by hand.
        if "DESCRIPTION" not in cls.__dict__:
            title = cls.COFM_TITLE or _title_from_classname(cls.__name__)
            cls.DESCRIPTION = cofm_description(
                title,
                summary=cls.COFM_SUMMARY,
                params=cls.COFM_PARAMS,
                note=cls.COFM_NOTE,
            )

    @classmethod
    def cofm_display_name(cls) -> str:
        """Display name for NODE_DISPLAY_NAME_MAPPINGS."""
        return cofm_display(cls.COFM_TITLE or _title_from_classname(cls.__name__))

    @classmethod
    def cofm_id(cls) -> str:
        """Node ID for NODE_CLASS_MAPPINGS."""
        return cofm_node_id(cls.__name__)


def _title_from_classname(name: str) -> str:
    """``COFM_SaveAsPhonePhoto`` -> ``Save As Phone Photo``. Only a fallback; prefer COFM_TITLE."""
    name = name[len(COFM_THEME["id_prefix"]):] if name.startswith(COFM_THEME["id_prefix"]) else name
    out, prev_lower = [], False
    for ch in name.replace("_", " "):
        if ch.isupper() and prev_lower:
            out.append(" ")
        out.append(ch)
        prev_lower = ch.islower() or ch.isdigit()
    return " ".join("".join(out).split())


# ---------------------------------------------------------------------------
# Registration helper.
# ---------------------------------------------------------------------------

def register(node_cls, class_mappings, display_mappings, node_id=None, display=None):
    """Register a COFM node into both mapping dicts.

    Derives the ``COFM_``-prefixed ID and the ``◈ COFM`` display name from the
    class unless they are passed explicitly.
    """
    nid = node_id or (
        node_cls.cofm_id() if hasattr(node_cls, "cofm_id") else cofm_node_id(node_cls.__name__)
    )
    label = display or (
        node_cls.cofm_display_name()
        if hasattr(node_cls, "cofm_display_name")
        else cofm_display(_title_from_classname(node_cls.__name__))
    )
    class_mappings[nid] = node_cls
    display_mappings[nid] = label
    return nid
