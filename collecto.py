# -*- coding: utf-8 -*-
"""
Django view to generate a Collecto Stop PDF **without** loading any DOCX template,
using ReportLab only.

Features
--------
- Queries Brussels Mobility WFS (Collecto_stops) and looks up the feature by `code_stop`.
- Builds a PDF that mirrors the intended layout:
    Title, map image (from local WMS GetPrint), names, address FR & NL, stop photo.
- Image fallbacks: if an image can't be downloaded, draws a grey placeholder box with a label.

Requirements:
    pip install reportlab requests

Add to urls.py (already mentioned by user):
    path('collecto/<str:stop>/', collecto.info)

"""
from __future__ import annotations

import io
from typing import Dict, Any, Optional, Tuple

import requests
from django.http import HttpResponse, HttpResponseNotFound, HttpResponseServerError
from django.views.decorators.http import require_GET

# ReportLab imports
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
    Table,
    TableStyle,
    KeepTogether,
)

# ---------------- Configuration ----------------

SERVER_URL = "http://localhost"

# Brussels Mobility WFS (Collecto stops)
WFS_URL = "https://data.mobility.brussels/geoserver/bm_public_transport/wfs"

# Local WMS GetPrint (QGIS / Lizmap print)
WMS_PRINT_URL = (
    "{SERVER_URL}:5555/"
    "?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetPrint"
    "&MAP=/data/collecto.qgz&TEMPLATE=stoplayout"
    "&FORMAT=png&CRS=EPSG:3812&DPI=50&ATLAS_PK={gid}"
)

# Default layout sizes (points)
LEFT_RIGHT_MARGIN = 2 * cm
TOP_BOTTOM_MARGIN = 1.6 * cm
TITLE_FONT_SIZE = 20
BODY_FONT_SIZE = 11

# Target widths for images relative to usable width
FIRST_IMAGE_WIDTH_RATIO = 1.0   # first image spans full text width
SECOND_IMAGE_WIDTH_RATIO = 0.66 # second image at ~2/3 of text width

# If an image is missing and we need a placeholder, use these heights (points)
FIRST_IMAGE_PLACEHOLDER_HEIGHT = 8 * cm
SECOND_IMAGE_PLACEHOLDER_HEIGHT = 6 * cm

# ------------------------------------------------


def _fetch_collecto_feature_by_code(stop_code: str) -> Optional[Dict[str, Any]]:
    """Return the first feature (GeoJSON dict) whose properties['code_stop'] == stop_code."""
    params = {
        "service": "wfs",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": "bm_public_transport:Collecto_stops",
        "outputFormat": "json",
        "srsName": "EPSG:3812",
    }
    r = requests.get(WFS_URL, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    for f in (data.get("features") or []):
        props = f.get("properties") or {}
        if str(props.get("code_stop", "")).strip() == str(stop_code).strip():
            return f
    return None


def _download_image(url: str, timeout: int = 20) -> Optional[bytes]:
    try:
        res = requests.get(url, timeout=timeout)
        res.raise_for_status()
        return res.content
    except Exception:
        return None


def _scaled_image_flowable(img_bytes: bytes, target_width_pts: float):
    """
    Scale image to target width preserving aspect. Return (Image flowable, w, h).

    IMPORTANT: pass BytesIO (or filename) to platypus.Image, NOT ImageReader.
    """
    # Use ImageReader to obtain intrinsic size (pixels)
    r = ImageReader(io.BytesIO(img_bytes))
    iw, ih = r.getSize()
    if not iw or not ih:
        raise ValueError("Invalid image dimensions (0 x 0)")

    # Compute scaled size
    w = target_width_pts if (target_width_pts and target_width_pts > 0) else float(iw)
    ratio = w / float(iw)
    h = ih * ratio

    # Build the flowable from a fresh BytesIO
    stream = io.BytesIO(img_bytes)
    return Image(stream, width=w, height=h), w, h


def _placeholder_box(width_pts: float, height_pts: float, label: str) -> Table:
    """Return a grey box with centered label as a placeholder for missing images."""
    tbl = Table(
        [[label]],
        colWidths=[width_pts],
        rowHeights=[height_pts],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.lightgrey),
            ("BOX", (0, 0), (-1, -1), 1, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.darkgray),
            ("FONTSIZE", (0, 0), (-1, -1), 11),
        ]),
    )
    return tbl


def _build_pdf(props: Dict[str, Any], img1_bytes: Optional[bytes], img2_bytes: Optional[bytes]) -> bytes:
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=LEFT_RIGHT_MARGIN,
        rightMargin=LEFT_RIGHT_MARGIN,
        topMargin=TOP_BOTTOM_MARGIN,
        bottomMargin=TOP_BOTTOM_MARGIN,
        title=f"Collecto {props.get('code_stop', '')}",
    )

    usable_width = A4[0] - doc.leftMargin - doc.rightMargin

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="TitleBig",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=TITLE_FONT_SIZE,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="H2",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Body",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=BODY_FONT_SIZE,
            leading=BODY_FONT_SIZE + 3,
        )
    )

    story = []

    # Title: "COLLECTO <code_stop>"
    code_stop = props.get("code_stop", "")
    story.append(Paragraph(f"COLLECTO {code_stop}", styles["TitleBig"]))
    story.append(Spacer(1, 6))

    # --- First image (map print) ---
    img1_target_w = usable_width * FIRST_IMAGE_WIDTH_RATIO
    if img1_bytes:
        try:
            img1_flow, w1, h1 = _scaled_image_flowable(img1_bytes, img1_target_w)
            story.append(img1_flow)
        except Exception:
            story.append(_placeholder_box(img1_target_w, FIRST_IMAGE_PLACEHOLDER_HEIGHT, "Map image unavailable"))
    else:
        story.append(_placeholder_box(img1_target_w, FIRST_IMAGE_PLACEHOLDER_HEIGHT, "Map image unavailable"))
    story.append(Spacer(1, 12))

    # Names line
    name_fr = props.get("name_fr", "")
    name_nl = props.get("name_nl", "")
    story.append(Paragraph(f"{name_fr} - {name_nl}", styles["H2"]))
    story.append(Spacer(1, 6))

    # Address FR and NL
    housenr = props.get("housenr", "")
    road_fr = props.get("road_fr", "")
    mu_fr = props.get("mu_fr", "")
    road_nl = props.get("road_nl", "")
    mu_nl = props.get("mu_nl", "")

    story.append(Paragraph(f"<b>Adresse :</b> {housenr}, {road_fr} - {mu_fr}", styles["Body"]))
    story.append(Spacer(1, 2))
    story.append(Paragraph(f"<b>Adres :</b> {road_nl} {housenr} - {mu_nl}", styles["Body"]))
    story.append(Spacer(1, 10))

    # --- Second image (stop photo) ---
    img2_target_w = usable_width * SECOND_IMAGE_WIDTH_RATIO
    if img2_bytes:
        try:
            img2_flow, w2, h2 = _scaled_image_flowable(img2_bytes, img2_target_w)
            story.append(KeepTogether([img2_flow]))
        except Exception:
            story.append(_placeholder_box(img2_target_w, SECOND_IMAGE_PLACEHOLDER_HEIGHT, "Stop photo unavailable"))
    else:
        story.append(_placeholder_box(img2_target_w, SECOND_IMAGE_PLACEHOLDER_HEIGHT, "Stop photo unavailable"))

    doc.build(story)
    return buffer.getvalue()


@require_GET
def info(request, stop: str):
    """Generate and return the Collecto PDF for /collecto/<stop>/ ."""
    # 1) Fetch feature by code_stop
    try:
        feature = _fetch_collecto_feature_by_code(stop)
    except requests.HTTPError as e:
        return HttpResponseServerError(f"WFS error: {e}")
    except Exception as e:
        return HttpResponseServerError(f"Could not query WFS: {e}")

    if not feature:
        return HttpResponseNotFound(
            f"Collecto stop with code_stop='{stop}' not found in the dataset."
        )

    props = feature.get("properties") or {}

    # 2) Resolve images
    gid = props.get("gid")
    image_stop = props.get("image_stop")

    img1_bytes = None
    if gid is not None:
        img1_bytes = _download_image(WMS_PRINT_URL.format(SERVER_URL=SERVER_URL, gid=gid))

    img2_bytes = None
    if image_stop:
        img2_bytes = _download_image(f"https://data.mobility.brussels/media/{image_stop}")

    # 3) Build PDF
    try:
        pdf_bytes = _build_pdf(props, img1_bytes, img2_bytes)
    except Exception as e:
        return HttpResponseServerError(f"Failed to generate PDF: {e}")

    filename = f"collecto_{props.get('code_stop', stop)}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
